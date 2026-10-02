"""Offline-first evidence diagnostics; executable directly without installing the connector."""

import argparse
from contextlib import closing
from datetime import datetime, timezone
import hashlib
import http.client
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


REPORT_VERSION = 1
SCOPES = (
    "0000713676:0001193125-25-052937:d889589ddef14a.htm",
    "0000713676:0000713676-24-000028:pnc-20231231.htm",
)
PROBES = {
    "market_capitalization": (r"76\.4", r"market\s+capitalization", r"\bPNC\b"),
    "annual_metrics": (r"13,499", r"13,916", r"2024\s+results", r"2023\s+results"),
    "stock_growth": (r"9\.64", r"5.year\s+compound\s+growth", r"158\.41"),
    "charity": (r"charitable\s+contributions",),
}
LIMITS = [
    "Hashes and evidence-token matches are not semantic success or correct table associations.",
    "App-only GETs do not prove user visibility, indexing, agent binding, or retrieval traces.",
    "Selected items only; no whole-connection audit, SEC downloads, repairs, or database writes.",
    "Stop writers first. Local snapshots and later remote receipts are not an atomic snapshot.",
    "Dependency versions describe this interpreter, not historical ingestion or the selected code root.",
    "Reports contain identifiers and hashes; review privately before sharing.",
]
REQUIRED_COLUMNS = {
    "destination": {"tenant_id", "connection_id", "version"},
    "filings": {"id", "cik", "accession_number", "metadata", "processing_options", "state",
                "inventory_complete", "payloads_ready", "sample_limit"},
    "documents": {"filing_id", "filename", "metadata", "state"},
    "chunks": {"chunk_id", "filing_id", "filename", "payload", "state"},
    "delivered_items": {"chunk_id", "filing_id", "payload_hash"},
    "document_cache": {"filing_id", "filename", "fingerprint", "payloads"},
    "reconciliation_candidates": {"filing_id", "chunk_id"},
}
STATES = {"pending", "failed", "downloaded", "parsed", "uploaded", "completed", "sampled",
          "retiring", "retired", "skipped"}
TERMINAL_PHASES = {"completed", "rolled_back"}
PHASES = TERMINAL_PHASES | {"forward", "verified", "rolling_back"}
MAX_ITEMS = 40
MAX_RESPONSE_BYTES = 32 * 1024 * 1024


class DiagnosticError(Exception):
    """Only fixed, non-sensitive error codes belong in this exception."""


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def digest(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def payload_digest(payload):
    # Deliberately mirrors payloads.serialize_item without importing the runtime.
    return digest({k: v for k, v in payload.items() if k != "id"})


def file_digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def parse_scope(value):
    if not re.fullmatch(r"\d{10}:\d{10}-\d{2}-\d{6}:[A-Za-z0-9][A-Za-z0-9_.-]*\.(?:htm|txt)", value):
        raise DiagnosticError("invalid_exact_scope")
    return tuple(value.split(":"))


def safe_state(value, allowed=STATES):
    return value if value in allowed else "unknown"


def evidence(payload):
    text = payload["content"]["value"]
    output = {}
    for name, patterns in PROBES.items():
        found = [bool(re.search(pattern, text, re.I)) for pattern in patterns]
        output[name] = {"matched_terms": sum(found), "all_terms": all(found)}
    output["rotated_text_markers"] = text.count("[rotated text]")
    output["missing_image_markers"] = len(re.findall(r"!\[[^\]]*\]\([^)]*\)", text))
    return output


def validate_payload(payload, item_id=None):
    if (not isinstance(payload, dict) or not isinstance(payload.get("content"), dict)
            or payload["content"].get("type") not in ("text", "html")
            or not isinstance(payload["content"].get("value"), str)
            or not isinstance(payload.get("properties"), dict)
            or not isinstance(payload.get("acl"), list)
            or any(not isinstance(entry, dict) for entry in payload["acl"])
            or not isinstance(payload.get("id"), str)
            or (item_id is not None and payload["id"] != item_id)):
        raise DiagnosticError("invalid_stored_payload")


def normalize_schema(schema):
    if (not isinstance(schema, dict) or not isinstance(schema.get("baseType"), str)
            or not isinstance(schema.get("properties"), list) or not schema["properties"]):
        raise DiagnosticError("invalid_schema")
    properties = {}
    flags = ("isSearchable", "isQueryable", "isRetrievable", "isRefinable", "isExactMatchRequired")
    for prop in schema["properties"]:
        if (not isinstance(prop, dict) or not isinstance(prop.get("name"), str)
                or not isinstance(prop.get("type"), str) or prop["name"] in properties):
            raise DiagnosticError("invalid_schema_properties")
        normalized = {"type": prop["type"].lower()}
        for flag in flags:
            if type(prop.get(flag, False)) is not bool:
                raise DiagnosticError("invalid_schema_flag")
            normalized[flag] = prop.get(flag, False)
        for field in ("labels", "aliases"):
            values = prop.get(field)
            if values is None:
                values = []
            if not isinstance(values, list) or any(not isinstance(v, str) for v in values):
                raise DiagnosticError("invalid_schema_labels")
            normalized[field] = sorted(set(values))
        # Unknown definition fields must not silently disappear from the comparison.
        normalized["other"] = {k: v for k, v in prop.items()
                               if k not in ("name", "type", "labels", "aliases", *flags)
                               and not k.startswith("@odata.")}
        properties[prop["name"]] = normalized
    return {"baseType": schema["baseType"].lower(), "properties": properties}


def runtime_info(root, schema):
    files = {}
    for name in ("parser.py", "chunker.py", "models.py", "graph_client.py", "payloads.py",
                 "pipeline.py", "config.py", "utils.py", "ocr_engine.py", "maintenance.py",
                 "maintenance_ocr.py", "state_manager.py", "sec_client.py", "cli.py",
                 "sample_upload.py", "pilot_upload.py"):
        path = root / name
        files[name] = file_digest(path) if path.is_file() else None
    if not files["pipeline.py"]:
        raise DiagnosticError("invalid_code_root")
    match = re.search(r"^PROCESSING_VERSION\s*=\s*(\d+)\s*$",
                      (root / "pipeline.py").read_text(encoding="utf-8"), re.M)
    packages = {}
    for name in ("sec-connector", "beautifulsoup4", "markdownify", "lxml", "pydantic",
                 "aiohttp", "msal", "PyYAML", "Pillow", "pytesseract"):
        try:
            distribution = importlib.metadata.distribution(name)
            # direct_url.json can contain private paths, credentials, or repository URLs.
            provenance = distribution.read_text("direct_url.json")
            packages[name] = {
                "version": distribution.version,
                "direct_url_sha256": digest(json.loads(provenance)) if provenance else None,
            }
        except importlib.metadata.PackageNotFoundError:
            packages[name] = {"version": None, "direct_url_sha256": None}
    return {
        "python": platform.python_version(), "packages": packages, "code_sha256": files,
        "processing_version": int(match[1]) if match else None,
        "schema_stored_format_sha256": hashlib.sha256(
            json.dumps(schema, sort_keys=True).encode("utf-8")).hexdigest(),
        "schema_normalized_sha256": digest(normalize_schema(schema)),
        "provenance": "operator_selected_code_root_and_current_interpreter_not_historical_runtime",
        "ocr_engine": "not_invoked_or_version_verified",
    }


def check_no_journal(path):
    # Even mode=ro SQLite may create WAL shared-memory files. Immutable reads avoid
    # those writes, but are only valid for a quiescent, journal-free main database.
    if any(Path(str(path) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise DiagnosticError("journal_present_stop_writer_and_use_operator_managed_snapshot")


def check_schema(db):
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table, required in REQUIRED_COLUMNS.items():
        if table not in tables or not required <= {
            row[1] for row in db.execute(f"PRAGMA table_info({table})")
        }:
            raise DiagnosticError("unsupported_database_schema_no_migration")
    rows = db.execute("SELECT tenant_id, connection_id, version FROM destination").fetchall()
    if len(rows) != 1 or rows[0]["version"] not in (3, 4):
        raise DiagnosticError("unsupported_destination_or_state_version")
    if rows[0]["version"] == 4 and "maintenance_operations" not in tables:
        raise DiagnosticError("missing_maintenance_schema")
    phases = []
    if "maintenance_operations" in tables:
        columns = {row[1] for row in db.execute("PRAGMA table_info(maintenance_operations)")}
        if "phase" not in columns:
            raise DiagnosticError("unsupported_maintenance_schema")
        phases = sorted(safe_state(row[0], PHASES) for row in db.execute(
            "SELECT phase FROM maintenance_operations") if row[0] not in TERMINAL_PHASES)
    return rows[0], phases


def inspect_document(db, args, scope, runtime):
    cik, accession, filename = parse_scope(scope)
    report = {"scope": scope, "issues": [], "items": []}
    rows = db.execute("SELECT * FROM filings WHERE cik=? AND accession_number=?",
                      (cik, accession)).fetchall()
    if len(rows) > 1:
        raise DiagnosticError("duplicate_filing_identity")
    if not rows:
        report["issues"].append("filing_not_found")
        return report, {}
    row = rows[0]
    options = json.loads(row["processing_options"])
    if not isinstance(options, dict):
        raise DiagnosticError("invalid_processing_options")
    report.update({
        "filing_state": safe_state(row["state"]), "inventory_complete": row["inventory_complete"] == 1,
        "payloads_ready": row["payloads_ready"] == 1, "sampled": row["sample_limit"] is not None,
        "filing_metadata_sha256": digest(json.loads(row["metadata"])),
        "options_sha256": digest(options),
        "option_hashes": {key: digest(options.get(key)) for key in (
            "processing_version", "chunking", "ocr_images", "filings", "refresh_downloads", "icon_url",
            "schema_hash")},
        "stored_processing_version": options.get("processing_version")
        if type(options.get("processing_version")) is int else None,
        "stored_version_matches_runtime": options.get("processing_version") == runtime["processing_version"]
        if options.get("processing_version") is not None and runtime["processing_version"] is not None else None,
        "stored_schema_matches_runtime": options.get("schema_hash") == runtime["schema_stored_format_sha256"]
        if options.get("schema_hash") else None,
    })
    inventory = db.execute(
        "SELECT filename,metadata,state FROM documents WHERE filing_id=? ORDER BY filename", (row["id"],)
    ).fetchall()
    report["inventory"] = [{"filename_sha256": digest(d["filename"]), "state": safe_state(d["state"])}
                           for d in inventory]
    document = [d for d in inventory if d["filename"] == filename]
    if len(document) > 1:
        raise DiagnosticError("duplicate_document_identity")
    if not document:
        report["issues"].append("document_not_found")
    report["document_metadata_sha256"] = digest(json.loads(document[0]["metadata"])) if document else None
    if any(d["state"] != "parsed" for d in inventory):
        report["issues"].append("document_inventory_not_fully_parsed")
    source = (args.downloads / cik / accession.replace("-", "") / filename).resolve()
    if not source.is_relative_to(args.downloads.resolve()):
        raise DiagnosticError("source_outside_downloads")
    report["source_sha256"] = file_digest(source) if source.is_file() else None
    if report["source_sha256"] is None:
        report["issues"].append("source_missing")
    selected = {}
    rows_chunks = db.execute(
        "SELECT c.chunk_id,c.payload,c.state,d.payload_hash,d.filing_id AS delivered_filing "
        "FROM chunks c LEFT JOIN delivered_items d ON d.chunk_id=c.chunk_id "
        "WHERE c.filing_id=? AND c.filename=? ORDER BY c.chunk_id", (row["id"], filename)
    ).fetchall()
    seen = set()
    for chunk in rows_chunks:
        if chunk["chunk_id"] in seen:
            raise DiagnosticError("duplicate_chunk_identity")
        seen.add(chunk["chunk_id"])
        payload = json.loads(chunk["payload"])
        validate_payload(payload, chunk["chunk_id"])
        phash, hits = payload_digest(payload), evidence(payload)
        item = {
            "id": chunk["chunk_id"], "state": safe_state(chunk["state"]),
            "payload_sha256": phash, "content_sha256": digest(payload["content"]),
            "properties_sha256": digest(payload["properties"]),
            "acl_sha256": digest(sorted(payload["acl"], key=digest)),
            "delivered_sha256": chunk["payload_hash"] if isinstance(chunk["payload_hash"], str)
            and re.fullmatch(r"[0-9a-f]{64}", chunk["payload_hash"]) else None,
            "delivered_hash_matches": chunk["payload_hash"] == phash and chunk["delivered_filing"] == row["id"],
            "evidence": hits,
        }
        report["items"].append(item)
        if any(hits[name]["all_terms"] for name in PROBES):
            selected[chunk["chunk_id"]] = payload
        if chunk["state"] != "uploaded" or not item["delivered_hash_matches"]:
            report["issues"].append("delivery_not_acknowledged_or_hash_mismatch")
        if hits["rotated_text_markers"] or hits["missing_image_markers"]:
            report["issues"].append("unresolved_image_markers")
    if not report["items"]:
        report["issues"].append("no_prepared_items")
    report["candidate_count"] = len(selected)
    report["manifest_sha256"] = digest([[item["id"], item["payload_sha256"]] for item in report["items"]])
    cache = db.execute("SELECT fingerprint,payloads FROM document_cache WHERE filing_id=? AND filename=?",
                       (row["id"], filename)).fetchall()
    report["cache_payloads_match"] = None
    report["source_fingerprint_matches"] = None
    if len(cache) == 1:
        payloads = json.loads(cache[0]["payloads"])
        if not isinstance(payloads, list):
            raise DiagnosticError("invalid_cached_payloads")
        for payload in payloads:
            validate_payload(payload)
        cached = sorted([[p["id"], payload_digest(p)] for p in payloads])
        report["cache_payloads_match"] = digest(cached) == report["manifest_sha256"]
        if document and report["source_sha256"] and row["sample_limit"] is None:
            expected = hashlib.sha256(json.dumps({
                "source": report["source_sha256"], "filing": json.loads(row["metadata"]),
                "document": json.loads(document[0]["metadata"]), "options": options, "remaining": None,
            }, sort_keys=True).encode("utf-8")).hexdigest()
            report["source_fingerprint_matches"] = cache[0]["fingerprint"] == expected
    if report["cache_payloads_match"] is not True:
        report["issues"].append("cache_payloads_missing_or_mismatched")
    if report["source_fingerprint_matches"] is not True:
        report["issues"].append("source_fingerprint_mismatch_or_unverifiable")
    report["reconciliation_candidates"] = db.execute(
        "SELECT count(*) FROM reconciliation_candidates WHERE filing_id=?", (row["id"],)).fetchone()[0]
    report["stale_delivered_count"] = db.execute(
        "SELECT count(*) FROM delivered_items d WHERE d.filing_id=? AND NOT EXISTS "
        "(SELECT 1 FROM chunks c WHERE c.chunk_id=d.chunk_id AND c.filing_id=d.filing_id)",
        (row["id"],)).fetchone()[0]
    if (row["state"] != "completed" or not report["inventory_complete"] or not report["payloads_ready"]
            or report["sampled"] or report["reconciliation_candidates"] or report["stale_delivered_count"]):
        report["issues"].append("filing_not_fully_reconciled")
    if report["stored_version_matches_runtime"] is not True or report["stored_schema_matches_runtime"] is not True:
        report["issues"].append("stored_runtime_drift_or_unknown")
    report["issues"] = sorted(set(report["issues"]))
    return report, selected


def read_local(args, runtime):
    path = args.db.resolve(strict=True)
    check_no_journal(path)
    before = (path.stat().st_size, path.stat().st_mtime_ns, path.stat().st_ino)
    selected, documents = {}, []
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        db.execute("BEGIN")
        destination, phases = check_schema(db)
        tenant, connection = destination["tenant_id"], destination["connection_id"]
        if not isinstance(tenant, str) or not tenant or connection != args.connection_id:
            raise DiagnosticError("database_destination_mismatch_no_authentication")
        for scope in args.scope:
            document, candidates = inspect_document(db, args, scope, runtime)
            if set(selected) & set(candidates):
                raise DiagnosticError("duplicate_scope_item")
            selected.update(candidates)
            documents.append(document)
        report = {
            "connection_id": connection, "tenant_sha256": digest(tenant.lower()),
            "database_format": destination["version"], "nonterminal_maintenance_phases": phases,
            "documents": documents,
        }
    check_no_journal(path)
    if before != (path.stat().st_size, path.stat().st_mtime_ns, path.stat().st_ino):
        raise DiagnosticError("database_changed_during_diagnostic")
    return report, selected, tenant


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def graph_get(path, token):
    if not path.startswith("/external/connections/") or "?" in path or "#" in path:
        raise DiagnosticError("invalid_graph_resource")
    request = urllib.request.Request("https://graph.microsoft.com/v1.0" + path, method="GET",
                                     headers={"Authorization": "Bearer " + token,
                                              "Prefer": "include-unknown-enum-members"})
    opener = urllib.request.build_opener(NoRedirect)
    for attempt in range(3):
        status = None
        try:
            with opener.open(request, timeout=45) as response:
                status = response.status
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    return {"status": response.status, "error": "response_too_large"}
                data = json.loads(raw)
                if not isinstance(data, dict):
                    return {"status": response.status, "error": "invalid_response_shape"}
                return {"status": response.status, "data": data}
        except urllib.error.HTTPError as exc:
            status, retry = exc.code, exc.headers.get("Retry-After", "5")
            exc.close()
            if status in (429, 500, 502, 503, 504) and attempt < 2:
                if not retry.isdigit() or int(retry) > 60:
                    return {"status": status, "error": "retry_deferred"}
                time.sleep(int(retry))
                continue
            return {"status": status, "error": "http_error"}
        except (urllib.error.URLError, OSError, http.client.HTTPException):
            return {"status": None, "error": "transport_error"}
        except (ValueError, UnicodeError, RecursionError):
            return {"status": status, "error": "invalid_response_json"}
    raise DiagnosticError("unreachable_retry_state")


def graph_credentials(config_path, tenant, connection):
    if config_path is None:
        raise DiagnosticError("graph_requires_config")
    import yaml

    try:
        config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError:
        raise DiagnosticError("invalid_graph_configuration") from None
    if not isinstance(config, dict) or not isinstance(config.get("azure"), dict):
        raise DiagnosticError("invalid_graph_configuration")
    values = {}
    for key in ("tenant_id", "connection_id", "client_id", "client_secret"):
        value = config["azure"].get(key)
        if not isinstance(value, str):
            raise DiagnosticError("missing_graph_configuration")
        values[key] = re.sub(r"\$\{([^}]+)\}", lambda m: os.environ.get(m[1], ""), value)
        if not values[key] or "${" in values[key]:
            raise DiagnosticError("missing_graph_environment")
    if values["tenant_id"].lower() != tenant.lower() or values["connection_id"] != connection:
        raise DiagnosticError("config_destination_mismatch_no_authentication")
    try:
        if any(str(uuid.UUID(values[key])) != values[key].lower() for key in ("tenant_id", "client_id")):
            raise ValueError
    except ValueError:
        raise DiagnosticError("invalid_azure_identity") from None
    return values


def authenticate(values):
    import msal
    from requests.exceptions import RequestException

    try:
        app = msal.ConfidentialClientApplication(
            values["client_id"], authority="https://login.microsoftonline.com/" + values["tenant_id"],
            client_credential=values["client_secret"],
        )
        result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    except (ValueError, RequestException):
        raise DiagnosticError("authentication_failed") from None
    if (not isinstance(result, dict) or not isinstance(result.get("access_token"), str)
            or not result["access_token"]):
        raise DiagnosticError("authentication_failed")
    return result["access_token"]


def compare_remote(expected, actual):
    props, acl = actual.get("properties"), actual.get("acl")
    if not isinstance(props, dict) or not isinstance(acl, list) or any(not isinstance(a, dict) for a in acl):
        raise DiagnosticError("invalid_remote_item")
    return {
        "id_matches": canonical(actual.get("id")) == canonical(expected["id"]),
        "content_matches": canonical(actual.get("content")) == canonical(expected["content"]),
        "expected_properties_match": all(
            k in props and canonical(props[k]) == canonical(v) for k, v in expected["properties"].items()),
        "acl_matches": canonical(sorted(acl, key=digest)) == canonical(sorted(expected["acl"], key=digest)),
        "extra_property_names": sorted(set(props) - set(expected["properties"])),
        "extra_top_level_names": sorted(set(actual) - {"id", "content", "properties", "acl"}
                                       - {key for key in actual if key.startswith("@odata.")}),
        "remote_content_sha256": digest(actual.get("content")),
        "remote_properties_sha256": digest(props),
        "remote_acl_sha256": digest(sorted(acl, key=digest)),
    }


def remote_report(args, selected, tenant, schema):
    values = graph_credentials(args.config, tenant, args.connection_id)
    token = authenticate(values)
    base = "/external/connections/" + urllib.parse.quote(args.connection_id, safe="")
    ids = sorted(selected)[:MAX_ITEMS]
    output = {"status": "complete", "candidate_count": len(selected), "selected_count": len(ids),
              "truncated": len(selected) > MAX_ITEMS, "items": [],
              "selection": "lexical_ids_matching_fixed_topic_tokens", "issues": []}
    if not ids or output["truncated"]:
        output["status"] = "incomplete"
        output["issues"].append("empty_or_truncated_evidence_sample")
    for label, suffix in (("connection", ""), ("schema", "/schema")):
        receipt = graph_get(base + suffix, token)
        data = receipt.pop("data", None)
        output[label] = receipt
        if receipt["status"] != 200 or data is None:
            output["status"] = "incomplete"
            return output
        if label == "connection":
            receipt["id_matches"] = data.get("id") == args.connection_id
            receipt["ready"] = data.get("state") == "ready"
            if not receipt["id_matches"] or not receipt["ready"]:
                output["issues"].append("connection_not_ready_or_mismatched")
                output["status"] = "incomplete"
                return output
        else:
            try:
                actual, desired = normalize_schema(data), normalize_schema(schema)
            except DiagnosticError:
                receipt["error"] = "invalid_remote_schema"
                output["status"] = "incomplete"
                return output
            receipt["normalized_sha256"] = digest(actual)
            receipt["matches_selected_schema"] = canonical(actual) == canonical(desired)
            receipt["extra_property_names"] = sorted(set(actual["properties"]) - set(desired["properties"]))
            if not receipt["matches_selected_schema"]:
                output["issues"].append("remote_schema_drift")
    for item_id in ids:
        receipt = graph_get(base + "/items/" + urllib.parse.quote(item_id, safe=""), token)
        actual = receipt.pop("data", None)
        receipt["id"] = item_id
        if receipt["status"] == 200 and actual is not None:
            try:
                receipt.update(compare_remote(selected[item_id], actual))
            except DiagnosticError:
                receipt["error"] = "invalid_remote_item"
            else:
                if (not all(receipt[key] for key in ("id_matches", "content_matches", "expected_properties_match", "acl_matches"))
                        or receipt["extra_property_names"] or receipt["extra_top_level_names"]):
                    output["issues"].append("remote_item_drift")
        if receipt["status"] != 200 or "error" in receipt:
            output["status"] = "incomplete"
        output["items"].append(receipt)
    output["issues"] = sorted(set(output["issues"]))
    return output


def collect(args, report):
    schema = load_json(args.schema)
    report["runtime"] = runtime_info(args.code_root, schema)
    local, selected, tenant = read_local(args, report["runtime"])
    report["local"] = local
    report["graph"] = remote_report(args, selected, tenant, schema) if args.graph else {"status": "not_requested"}
    graph = report["graph"]
    if args.graph:
        graph["candidate_counts_by_scope"] = {doc["scope"]: doc.get("candidate_count", 0)
                                              for doc in local["documents"]}
        if any(count == 0 for count in graph["candidate_counts_by_scope"].values()):
            graph["status"] = "incomplete"
            graph["issues"].append("scope_without_evidence_candidates")
    report["status"] = "incomplete" if graph["status"] == "incomplete" else "complete"
    report["findings"] = bool(local["nonterminal_maintenance_phases"] or
                              any(doc["issues"] for doc in local["documents"]) or graph.get("issues"))
    return report


def report_projections(report):
    if (not isinstance(report, dict) or report.get("report_version") != REPORT_VERSION
            or report.get("kind") != "collection" or not isinstance(report.get("local"), dict)
            or not isinstance(report.get("runtime"), dict) or not isinstance(report.get("graph"), dict)
            or type(report.get("findings")) is not bool
            or not {"code_sha256", "packages", "schema_normalized_sha256"} <= report["runtime"].keys()):
        raise DiagnosticError("incompatible_or_incomplete_report")
    documents = report["local"]["documents"]
    if not isinstance(documents, list) or any(not isinstance(doc, dict) for doc in documents):
        raise DiagnosticError("invalid_report_documents")
    scopes = [doc["scope"] for doc in documents]
    if not documents or len(scopes) != len(set(scopes)):
        raise DiagnosticError("invalid_report_scopes")
    output = {"input": {}, "settings": {}, "payload": {}, "delivery": {}, "runtime": report["runtime"]}
    for doc in documents:
        scope = doc["scope"]
        items = doc["items"]
        if len({item["id"] for item in items}) != len(items):
            raise DiagnosticError("duplicate_report_items")
        output["input"][scope] = {key: doc.get(key) for key in (
            "source_sha256", "filing_metadata_sha256", "document_metadata_sha256")}
        output["settings"][scope] = doc.get("options_sha256")
        output["payload"][scope] = {item["id"]: {key: item[key] for key in (
            "payload_sha256", "content_sha256", "properties_sha256", "acl_sha256", "evidence")} for item in items}
        output["delivery"][scope] = {
            "filing_state": doc.get("filing_state"), "inventory_complete": doc.get("inventory_complete"),
            "payloads_ready": doc.get("payloads_ready"), "sampled": doc.get("sampled"),
            "reconciliation_candidates": doc.get("reconciliation_candidates"),
            "stale_delivered_count": doc.get("stale_delivered_count"),
            "inventory": sorted(doc.get("inventory", []), key=digest),
            "issues": sorted(doc["issues"]),
            "cache_payloads_match": doc.get("cache_payloads_match"),
            "source_fingerprint_matches": doc.get("source_fingerprint_matches"),
            "items": {item["id"]: {key: item[key] for key in (
                "state", "delivered_sha256", "delivered_hash_matches")} for item in items},
        }
    output["destination"] = {key: report["local"][key] for key in (
        "connection_id", "tenant_sha256", "database_format")}
    output["maintenance"] = sorted(report["local"]["nonterminal_maintenance_phases"])
    graph = dict(report["graph"])
    if "items" in graph:
        if len({item["id"] for item in graph["items"]}) != len(graph["items"]):
            raise DiagnosticError("duplicate_graph_receipts")
        graph["items"] = {item["id"]: item for item in graph["items"]}
    if "issues" in graph:
        graph["issues"] = sorted(graph["issues"])
    output["graph"] = graph
    return output


def complete_report(report):
    if report.get("status") != "complete" or "error" in report:
        return False
    graph = report["graph"]
    if graph.get("status") == "not_requested":
        return set(graph) == {"status"}
    if graph.get("status") != "complete" or graph.get("truncated") is not False:
        return False
    items = graph.get("items", [])
    candidates = graph.get("candidate_counts_by_scope", {})
    if (not items or graph.get("candidate_count") != len(items) or graph.get("selected_count") != len(items)
            or set(candidates) != {doc["scope"] for doc in report["local"]["documents"]}
            or any(type(count) is not int or count <= 0 for count in candidates.values())
            or sum(candidates.values()) != len(items)):
        return False
    receipts = [graph.get("connection", {}), graph.get("schema", {}), *items]
    if any(receipt.get("status") != 200 or "error" in receipt for receipt in receipts):
        return False
    if not all(graph["connection"].get(key) is True for key in ("id_matches", "ready")):
        return False
    return ("normalized_sha256" in graph["schema"] and "matches_selected_schema" in graph["schema"]
            and all(all(key in item for key in ("id_matches", "content_matches", "expected_properties_match",
                                                "acl_matches", "remote_content_sha256",
                                                "remote_properties_sha256", "remote_acl_sha256")) for item in items))


def compare_reports(before, after):
    left, right = report_projections(before), report_projections(after)
    categories = {name: {"changed": canonical(left[name]) != canonical(right[name]),
                         "before_sha256": digest(left[name]), "after_sha256": digest(right[name])}
                  for name in left}
    incomplete = not all(complete_report(report) for report in (before, after))
    return {"status": "incomplete" if incomplete else "complete", "categories": categories,
            "differences": any(value["changed"] for value in categories.values()),
            "input_findings": [before.get("findings"), after.get("findings")],
            "interpretation": "Equivalent observations are not a semantic or retrieval pass."}


def reserve_output(args):
    out = args.out
    if out.suffix.lower() != ".json" or not out.parent.is_dir() or out.is_symlink() or out.exists():
        raise DiagnosticError("output_requires_new_json_in_existing_private_directory")
    resolved = out.resolve()
    for name in ("db", "config", "schema", "before", "after"):
        value = getattr(args, name, None)
        if value and resolved == value.resolve():
            raise DiagnosticError("output_conflicts_with_input")
    for name in ("code_root", "downloads"):
        value = getattr(args, name, None)
        if value and resolved.is_relative_to(value.resolve()):
            raise DiagnosticError("output_inside_source_directory")
    if getattr(args, "db", None) and resolved.parent == args.db.resolve().parent:
        raise DiagnosticError("output_inside_database_directory")
    # O_EXCL also refuses dangling links and races; POSIX gets 0600. Windows
    # inherits directory ACLs, so an operator-protected output directory is required.
    return os.fdopen(os.open(out, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w", encoding="utf-8")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    diagnostic = commands.add_parser("collect", help="Collect exact local evidence; Graph is opt-in")
    for flag in ("db", "downloads", "code-root", "schema"):
        diagnostic.add_argument("--" + flag, type=Path, required=True)
    diagnostic.add_argument("--connection-id", required=True)
    diagnostic.add_argument("--scope", action="append", help="Exact CIK:accession:filename; repeat up to eight times")
    diagnostic.add_argument("--graph", action="store_true")
    diagnostic.add_argument("--config", type=Path)
    comparison = commands.add_parser("compare", help="Offline comparison of two versioned reports")
    comparison.add_argument("--before", type=Path, required=True)
    comparison.add_argument("--after", type=Path, required=True)
    for command in (diagnostic, comparison):
        command.add_argument("--out", type=Path, required=True, help="New JSON in an existing private directory")
    args = parser.parse_args(argv)
    report = {"report_version": REPORT_VERSION, "kind": "collection" if args.command == "collect" else "comparison",
              "created_at": datetime.now(timezone.utc).isoformat(), "limits": LIMITS}
    try:
        if args.command == "collect":
            args.scope = sorted(args.scope or SCOPES)
            if len(args.scope) > 8 or len(set(args.scope)) != len(args.scope):
                raise DiagnosticError("invalid_scope_count_or_duplicates")
            for scope in args.scope:
                parse_scope(scope)
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", args.connection_id):
                raise DiagnosticError("invalid_connection_id")
            if args.config and not args.graph:
                raise DiagnosticError("config_only_allowed_with_explicit_graph")
        stream = reserve_output(args)
    except (DiagnosticError, OSError, ValueError):
        print("Diagnostic not started: invalid scope/options or unsafe/unavailable output.", file=sys.stderr)
        return 2
    try:
        with stream:
            try:
                report.update(collect(args, report) if args.command == "collect" else
                              compare_reports(load_json(args.before), load_json(args.after)))
            except DiagnosticError as exc:
                report.update(status="incomplete", error=str(exc))
            except (OSError, ValueError, KeyError, TypeError, AttributeError, sqlite3.Error, ImportError, RecursionError):
                report.update(status="incomplete", error="invalid_input_dependency_or_io_error_details_redacted")
            except KeyboardInterrupt:
                report.update(status="incomplete", error="interrupted")
            json.dump(report, stream, indent=2, ensure_ascii=True, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
    except (OSError, ValueError):
        print("Report write failed; reserved output is incomplete.", file=sys.stderr)
        return 2
    status = 2 if report["status"] == "incomplete" else int(bool(
        report.get("findings") or report.get("differences") or any(report.get("input_findings", []))))
    print(("Requested checks collected", "Findings or differences recorded", "Diagnostic incomplete")[status]
          + "; review the private report. No semantic-success claim.")
    return status


if __name__ == "__main__":
    sys.exit(main())
