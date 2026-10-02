"""Frozen single-document maintenance. No SEC discovery or schema mutations."""

from contextlib import closing
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import re
import sqlite3

import aiohttp

from .chunker import chunk_with_limit
from .graph_client import GRAPH_BASE_URL, GraphClient, HTTPResult
from .models import DocumentInfo, FilingMetadata
from .parser import parse_document
from .payloads import payload_hash, serialize_item
from .pilot_upload import SERVICE_METADATA_KEYS, validate_service_metadata, validate_token_identity
from .pipeline import IngestionPipeline, document_fingerprint
from .state_manager import StateManager, check_state_access


SCOPED_TABLES = ("documents", "chunks", "delivered_items",
                 "reconciliation_candidates", "document_cache")
TERMINAL = ("completed", "rolled_back")


class MaintenanceGraphClient(GraphClient):
    """One mutation dispatch per durable intent; recovery rechecks before retry."""

    async def _request_result(self, method, url, json_data=None, use_beta=False, body=None):
        if method == "GET":
            return await super()._request_result(method, url, json_data, use_beta, body)
        prefix = f"/external/connections/{self.config.azure.connection_id}/items/"
        if (method not in {"PUT", "DELETE"} or not url.startswith(prefix)
                or not re.fullmatch(r"[A-Za-z0-9-]+", url[len(prefix):])
                or use_beta or json_data is not None or self._session is None):
            raise ValueError("Maintenance transport forbids unscoped mutations")
        token = await self._get_token()
        validate_token_identity(token, self.config.azure.tenant_id, self.config.azure.client_id)
        async with self._session.request(
            method, GRAPH_BASE_URL + url, data=body, allow_redirects=False,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "Prefer": "include-unknown-enum-members"},
        ) as response:
            response.raise_for_status()
            if not 200 <= response.status < 300:
                raise RuntimeError("Unexpected maintenance mutation response")
            raw = await response.read()
            return HTTPResult(response.status, dict(response.headers), json.loads(raw) if raw else {})


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def sha(value) -> str:
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def same_payload(actual, expected) -> bool:
    # Python equality treats False == 0 and True == 1; Graph property types matter.
    return canonical(actual) == canonical(expected)


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def write_new(path: Path, value) -> None:
    """Never replace a reviewed plan or recovery artifact."""
    with path.open("x", encoding="utf-8") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def read_only(path: Path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def snapshot(db, filing_id: int) -> dict:
    row = db.execute("SELECT * FROM filings WHERE id = ?", (filing_id,)).fetchone()
    if row is None:
        raise ValueError("Selected filing is missing")
    result = {"filing": dict(row)}
    for table in SCOPED_TABLES:
        result[table] = [dict(r) for r in db.execute(
            f"SELECT * FROM {table} WHERE filing_id = ? ORDER BY rowid", (filing_id,),
        )]
    return result


async def async_snapshot(db, filing_id):
    row = await (await db.execute("SELECT * FROM filings WHERE id = ?", (filing_id,))).fetchone()
    if row is None:
        raise ValueError("Selected filing is missing")
    result = {"filing": dict(row)}
    for table in SCOPED_TABLES:
        rows = await (await db.execute(
            f"SELECT * FROM {table} WHERE filing_id = ? ORDER BY rowid", (filing_id,),
        )).fetchall()
        result[table] = [dict(r) for r in rows]
    return result


def ownership(db, item_ids, filing_id):
    for table in ("chunks", "delivered_items", "reconciliation_candidates"):
        for row in db.execute(f"SELECT chunk_id, filing_id FROM {table}"):
            if row["chunk_id"] in item_ids and row["filing_id"] != filing_id:
                raise ValueError(f"Cross-filing ID collision: {row['chunk_id']}")


def provenance(config) -> dict:
    options = IngestionPipeline(config)._processing_options()
    if options["ocr_images"]:
        raise ValueError("Maintenance v1 does not support OCR/multiple source assets")
    modules = ("parser", "chunker", "models", "payloads", "pipeline", "graph_client",
               "config", "state_manager", "maintenance")
    return {
        "options": options,
        "modules": {name: file_hash(Path(__file__).with_name(name + ".py")) for name in modules},
        "dependencies": {name: version(name) for name in ("beautifulsoup4", "lxml", "markdownify", "pydantic")},
    }


def scope_for(filing, document):
    if (not re.fullmatch(r"\d{10}", filing.cik)
            or not re.fullmatch(r"\d{10}-\d{2}-\d{6}", filing.accession_number)
            or not re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:htm|txt)", document.filename)
            or document.sequence < 1):
        raise ValueError("Invalid exact document scope")
    url = filing.document_url(document.filename)
    return {
        "CIK": filing.cik, "AccessionNumber": filing.accession_number,
        "DocumentName": document.filename, "Sequence": document.sequence,
        "DocumentId": hashlib.sha256(url.encode()).hexdigest(), "Url": url,
    }


def validate_payloads(payloads, scope, limit):
    ids = set()
    prefix = f"{scope['CIK']}-{scope['AccessionNumber'].replace('-', '')}-{scope['Sequence']}-"
    for p in payloads:
        item_id = p["id"]
        if (item_id in ids
                or not re.fullmatch(re.escape(prefix) + r"[1-9]\d*(?:-[1-9]\d*)?", item_id)):
            raise ValueError("Duplicate or out-of-scope item ID")
        if set(p) != {"id", "properties", "content", "acl"}:
            raise ValueError("Unexpected replay payload fields")
        if any(not same_payload(p["properties"].get(k), v) for k, v in scope.items()):
            raise ValueError(f"Payload escapes exact document scope: {item_id}")
        if p["acl"] != [{"type": "everyone", "value": "everyone", "accessType": "grant"}]:
            raise ValueError("ACL differs from supported connector policy")
        if (p["content"].get("type") != "text" or not p["content"].get("value")
                or not isinstance(p["content"]["value"], str) or len(serialize_item(p)) > limit):
            raise ValueError("Invalid or oversized replay payload")
        ids.add(item_id)
    if not ids:
        raise ValueError("Empty payload set")


def normalized(raw, schema):
    """Strip OData annotations and only the complete, typed service metadata band."""
    def clean(obj):
        return {k: v for k, v in obj.items() if not (k.startswith("@odata.") or "@odata." in k)}
    props = clean(raw["properties"])
    extras = set(props) & SERVICE_METADATA_KEYS
    metadata = {}
    if extras:
        if extras & {p["name"] for p in schema["properties"]}:
            raise ValueError("Service metadata collides with schema")
        metadata = {k: props[k] for k in extras}
        validate_service_metadata(metadata)
        props = {k: v for k, v in props.items() if k not in extras}
    return {
        "id": raw["id"], "properties": props, "content": clean(raw["content"]),
        "acl": [clean(a) for a in raw["acl"]],
    }, metadata


async def get_item(graph, item_id):
    try:
        return await graph._request(
            "GET", f"/external/connections/{graph.config.azure.connection_id}/items/{item_id}",
        )
    except aiohttp.ClientResponseError as exc:
        if exc.status == 404:
            return None
        raise


async def environment(graph, plan=None):
    config = graph.config
    if plan is not None and plan["identity"] != [
        config.azure.tenant_id.lower(), config.azure.connection_id, config.azure.client_id.lower(),
    ]:
        raise ValueError("Graph client identity differs from the plan")
    validate_token_identity(await graph._get_token(), config.azure.tenant_id, config.azure.client_id)
    connection = await graph.get_connection()
    if connection.get("id") != config.azure.connection_id or connection.get("state") != "ready":
        raise ValueError("Destination is not the expected ready connection")
    schema = await graph.get_schema_status()
    if not graph.schemas_compatible(schema, graph.load_schema()):
        raise ValueError("Incompatible remote schema")
    if plan is not None and sha(schema) != plan["schema_hash"]:
        raise ValueError("Remote schema drift")
    return schema


def load_plan(path, expected_digest):
    plan = json.loads(path.read_bytes())
    if sha(plan) != expected_digest or plan.get("format") != 1:
        raise ValueError("Reviewed plan digest or format mismatch")
    return plan


def check_binding(plan, config, *, forward=True):
    pipeline = IngestionPipeline(config)
    expected = [config.azure.tenant_id.lower(), config.azure.connection_id, config.azure.client_id.lower()]
    if plan["identity"] != expected or plan["database"] != str(pipeline.db_path.resolve()):
        raise ValueError("Plan destination/app/database mismatch")
    if forward:
        if plan["provenance"] != provenance(config):
            raise ValueError("Processing code/config drift")
        if file_hash(Path(plan["source"])) != plan["source_hash"]:
            raise ValueError("Source drift")
    for name in ("old", "desired"):
        validate_payloads(list(plan[name].values()), plan["scope"], config.chunking.max_item_bytes)
        if any(k != p["id"] for k, p in plan[name].items()):
            raise ValueError("Plan item key mismatch")
        if plan[name + "_hashes"] != {k: payload_hash(p) for k, p in plan[name].items()}:
            raise ValueError("Plan payload hash mismatch")
    old, desired = set(plan["old"]), set(plan["desired"])
    if plan["new"] != sorted(desired - old) or plan["stale"] != sorted(old - desired):
        raise ValueError("Plan difference mismatch")
    order = plan["desired_order"]
    if len(order) != len(desired) or set(order) != desired:
        raise ValueError("Incomplete or duplicate desired ordering")
    if [plan["desired"][i]["properties"].get("ChunkOrdinal") for i in order] != list(range(1, len(order) + 1)):
        raise ValueError("Desired ordinals are incomplete")


async def prepare(config, graph, *, cik, accession, filename, sequence, source: Path, output: Path):
    """Read-only database and Graph observations; write only a new plan artifact."""
    pipeline = IngestionPipeline(config)
    identity = (config.azure.tenant_id.lower(), config.azure.connection_id)
    check_state_access(pipeline.db_path, identity, maintenance=True)
    frozen = provenance(config)
    with closing(read_only(pipeline.db_path)) as db:
        db.execute("BEGIN")
        if db.execute("SELECT version FROM destination").fetchone()[0] == 4:
            if db.execute("SELECT 1 FROM maintenance_operations WHERE phase NOT IN ('completed','rolled_back')").fetchone():
                raise ValueError("Unfinished maintenance exists")
        row = db.execute(
            "SELECT id FROM filings WHERE cik = ? AND accession_number = ?", (cik, accession),
        ).fetchone()
        if row is None:
            raise ValueError("Exact persisted filing not found")
        old_local = snapshot(db, row["id"])
        if db.execute("SELECT 1 FROM runs WHERE status = 'running'").fetchone():
            raise ValueError("Running/interrupted ingestion must be resolved before maintenance")
    record = old_local["filing"]
    if (record["state"] != "completed" or record["sample_limit"] is not None
            or record["inventory_complete"] != 1 or record["payloads_ready"] != 1
            or record["error_message"] or len(old_local["documents"]) != 1
            or old_local["reconciliation_candidates"]):
        raise ValueError("Requires a completed unsampled sole-document inventory without pending recovery")
    doc_row = old_local["documents"][0]
    document = DocumentInfo.model_validate_json(doc_row["metadata"])
    filing = FilingMetadata.model_validate_json(record["metadata"])
    if ((filing.cik, filing.accession_number) != (cik, accession)
            or (document.filename, document.sequence) != (filename, sequence)
            or doc_row["filename"] != filename or doc_row["state"] != "parsed"
            or doc_row["error_message"]):
        raise ValueError("Exact persisted document does not match requested scope")
    scope = scope_for(filing, document)
    source = source.resolve()
    if source.name != filename:
        raise ValueError("Source filename must match the selected document")
    source_hash = file_hash(source)
    old_options = json.loads(record["processing_options"])
    if old_options.get("ocr_images") is not False:
        raise ValueError("Old OCR provenance is unsupported or missing")
    cache = old_local["document_cache"]
    if (len(cache) != 1 or cache[0]["filename"] != filename
            or cache[0]["fingerprint"] != document_fingerprint(source_hash, filing, document, old_options)):
        raise ValueError("Source does not match the persisted document cache provenance")
    old_payloads = [json.loads(c["payload"]) for c in old_local["chunks"]]
    if (any(c["state"] != "uploaded" or c["filename"] != filename or c["sequence"] != sequence
            or c["chunk_id"] != json.loads(c["payload"])["id"]
            or c["page_number"] != json.loads(c["payload"])["properties"]["Page"]
            or c["error_message"] for c in old_local["chunks"])
            or json.loads(cache[0]["payloads"]) != old_payloads):
        raise ValueError("Old manifest/cache is not fully acknowledged and consistent")
    validate_payloads(old_payloads, scope, config.chunking.max_item_bytes)
    old = {p["id"]: p for p in old_payloads}
    if {r["chunk_id"]: r["payload_hash"] for r in old_local["delivered_items"]} != {
        k: payload_hash(p) for k, p in old.items()
    } or any(r["error_message"] for r in old_local["delivered_items"]):
        raise ValueError("Delivered state differs from old manifest")
    parsed = parse_document(source, filing, document, ocr_images=False)
    if parsed is None:
        raise ValueError("Source produced no usable content")
    payloads = [graph.build_payload(c, icon_url=frozen["options"]["icon_url"])
                for c in chunk_with_limit(parsed, config.chunking)]
    validate_payloads(payloads, scope, config.chunking.max_item_bytes)
    desired = {p["id"]: p for p in payloads}
    schema = await environment(graph)
    remote = {}
    for item_id, payload in old.items():
        raw = await get_item(graph, item_id)
        if raw is None or not same_payload(normalized(raw, schema)[0], payload):
            raise ValueError(f"Old remote mismatch or missing item: {item_id}")
        remote[item_id] = {"raw": raw, "observed_at": now()}
    new_absent = {}
    for item_id in sorted(set(desired) - set(old)):
        if await get_item(graph, item_id) is not None:
            raise ValueError(f"New ID already occupied: {item_id}")
        new_absent[item_id] = now()
    with closing(read_only(pipeline.db_path)) as db:
        db.execute("BEGIN")
        if snapshot(db, record["id"]) != old_local:
            raise ValueError("Local scope changed during preparation")
        ownership(db, set(old) | set(desired), record["id"])
    if source_hash != file_hash(source):
        raise ValueError("Source changed during preparation")
    plan = {
        "format": 1, "prepared_at": now(), "identity": [*identity, config.azure.client_id.lower()],
        "database": str(pipeline.db_path.resolve()), "source": str(source), "source_hash": source_hash,
        "scope": scope, "provenance": frozen, "schema": schema, "schema_hash": sha(schema),
        "old_local": old_local, "old": old, "desired": desired,
        "old_hashes": {k: payload_hash(p) for k, p in old.items()},
        "desired_hashes": {k: payload_hash(p) for k, p in desired.items()},
        "new": sorted(set(desired) - set(old)), "stale": sorted(set(old) - set(desired)),
        "remote": remote, "new_absent": new_absent, "desired_order": list(desired),
        "fingerprint": document_fingerprint(source_hash, filing, document, frozen["options"]),
    }
    write_new(output, plan)
    return sha(plan)


async def insert_rows(db, table, rows):
    for row in rows:
        columns = list(row)
        await db.execute(
            f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
            tuple(row[c] for c in columns),
        )


async def save_operation(db, digest, phase, data):
    await db.execute(
        "UPDATE maintenance_operations SET phase = ?, data = ? WHERE digest = ?",
        (phase, canonical(data), digest),
    )


async def checkpoint(db, digest, phase, data):
    await save_operation(db, digest, phase, data)
    await db.commit()


def verify_backup(data, plan, digest):
    directory = Path(data["recovery"])
    if (file_hash(directory / "state.db") != data["backup_hash"]
            or file_hash(directory / "recovery.json") != data["recovery_hash"]):
        raise ValueError("Recovery evidence missing or changed; maintenance remains guarded")
    evidence = json.loads((directory / "recovery.json").read_bytes())
    if evidence["digest"] != digest or evidence["plan"] != plan:
        raise ValueError("Recovery evidence binding mismatch")


async def activate(state, graph, plan, digest, recovery):
    """Backup first; format, guard and desired generation commit together."""
    db = state._db
    filing_id = plan["old_local"]["filing"]["id"]
    with closing(read_only(state.db_path)) as reader:
        reader.execute("BEGIN")
        if snapshot(reader, filing_id) != plan["old_local"]:
            raise ValueError("Local scope drift before activation")
        ownership(reader, set(plan["old"]) | set(plan["desired"]), filing_id)
        if reader.execute("SELECT 1 FROM runs WHERE status = 'running'").fetchone():
            raise ValueError("Running ingestion blocks maintenance")
    refreshed = {}
    for item_id, payload in plan["old"].items():
        raw = await get_item(graph, item_id)
        if raw is None or not same_payload(normalized(raw, plan["schema"])[0], payload):
            raise ValueError(f"Old remote drift before activation: {item_id}")
        refreshed[item_id] = {"raw": raw, "observed_at": now()}
    absent = {}
    for item_id in plan["new"]:
        if await get_item(graph, item_id) is not None:
            raise ValueError(f"New ID collision before activation: {item_id}")
        absent[item_id] = now()
    check_binding(plan, graph.config)
    await environment(graph, plan)
    recovery = recovery.resolve()
    recovery.mkdir(parents=True, exist_ok=False)
    with closing(sqlite3.connect(recovery / "state.db")) as target:
        await db.backup(target)
        if target.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite backup integrity check failed")
    write_new(recovery / "recovery.json", {
        "digest": digest, "plan": plan, "refreshed_remote": refreshed, "refreshed_absent": absent,
    })
    data = {
        "recovery": str(recovery), "backup_hash": file_hash(recovery / "state.db"),
        "recovery_hash": file_hash(recovery / "recovery.json"),
        "put": {}, "delete": {}, "restore": {}, "remove_new": {},
    }
    verify_backup(data, plan, digest)
    check_binding(plan, graph.config)
    try:
        await db.execute("BEGIN IMMEDIATE")
        if await async_snapshot(db, filing_id) != plan["old_local"]:
            raise ValueError("Local scope drift during recovery capture")
        await db.execute("""CREATE TABLE IF NOT EXISTS maintenance_operations (
            digest TEXT PRIMARY KEY, phase TEXT NOT NULL, data TEXT NOT NULL)""")
        if await (await db.execute(
            "SELECT 1 FROM maintenance_operations WHERE phase NOT IN ('completed','rolled_back')"
        )).fetchone():
            raise ValueError("Another maintenance operation is unfinished")
        await db.execute("INSERT INTO maintenance_operations VALUES (?, 'forward', ?)", (digest, canonical(data)))
        await db.execute("UPDATE destination SET version = 4")
        await db.execute("DELETE FROM chunks WHERE filing_id = ?", (filing_id,))
        for item_id in plan["desired_order"]:
            p = plan["desired"][item_id]
            await db.execute(
                """INSERT INTO chunks(chunk_id,filing_id,filename,page_number,sequence,payload,state)
                   VALUES (?,?,?,?,?,?,'pending')""",
                (item_id, filing_id, plan["scope"]["DocumentName"], p["properties"]["Page"],
                 plan["scope"]["Sequence"], canonical(p)),
            )
        for item_id in sorted(set(plan["old"]) | set(plan["desired"])):
            await db.execute("INSERT INTO reconciliation_candidates VALUES (?,?)", (item_id, filing_id))
        await db.execute(
            "UPDATE filings SET state = 'parsed', processing_options = ?, error_message = NULL WHERE id = ?",
            (canonical(plan["provenance"]["options"]), filing_id),
        )
        await db.execute(
            "UPDATE document_cache SET fingerprint = ?, payloads = ? WHERE filing_id = ?",
            (plan["fingerprint"], canonical([plan["desired"][i] for i in plan["desired_order"]]), filing_id),
        )
        data["local_hash"] = sha(await async_snapshot(db, filing_id))
        await save_operation(db, digest, "forward", data)
        await db.commit()
    except BaseException:
        await db.rollback()
        raise
    return "forward", data


async def exact_get(graph, payload, schema):
    raw = await get_item(graph, payload["id"])
    if raw is None or not same_payload(normalized(raw, schema)[0], payload):
        raise ValueError(f"Exact GET verification failed: {payload['id']}")
    return normalized(raw, schema)[1]


async def put_verified(state, graph, plan, digest, phase, data, item_id, *, rollback=False):
    target = plan["old"] if rollback else plan["desired"]
    journal = data["restore" if rollback else "put"]
    payload = target[item_id]
    raw = await get_item(graph, item_id)
    current = normalized(raw, plan["schema"])[0] if raw is not None else None
    allowed = [plan["old"].get(item_id)]
    if item_id in data["put"]:
        allowed.append(plan["desired"].get(item_id))
    if rollback and item_id in data["delete"]:
        allowed.append(None)
    if not any(same_payload(current, candidate) for candidate in allowed):
        raise ValueError(f"Remote drift before {'restore' if rollback else 'PUT'}: {item_id}")
    entry = journal.setdefault(item_id, {})
    if not entry.get("ack"):
        entry["intent"] = now()
        await checkpoint(state._db, digest, phase, data)
        await graph.upload_payload(item_id, payload)
        entry["ack"] = now()
        await checkpoint(state._db, digest, phase, data)
    entry["service_metadata"] = await exact_get(graph, payload, plan["schema"])
    entry["verified"] = now()
    await checkpoint(state._db, digest, phase, data)


async def delete_verified(state, graph, plan, digest, phase, data, item_id, *, rollback=False):
    journal = data["remove_new" if rollback else "delete"]
    payload = (plan["desired"] if rollback else plan["old"])[item_id]
    raw = await get_item(graph, item_id)
    entry = journal.setdefault(item_id, {})
    if raw is not None:
        if not same_payload(normalized(raw, plan["schema"])[0], payload):
            raise ValueError(f"Stale/new item drift; refusing DELETE: {item_id}")
        entry["intent"] = now()
        await checkpoint(state._db, digest, phase, data)
        try:
            await graph.delete_item(item_id)
        except aiohttp.ClientResponseError as exc:
            if exc.status != 404:
                raise
        entry["ack"] = now()
    else:
        entry["observed_absent"] = now()
    if await get_item(graph, item_id) is not None:
        raise ValueError(f"DELETE absence not confirmed: {item_id}")
    entry["verified_absent"] = now()
    await checkpoint(state._db, digest, phase, data)


async def finish(state, plan, digest, data, *, rollback=False):
    db = state._db
    filing_id = plan["old_local"]["filing"]["id"]
    try:
        await db.execute("BEGIN IMMEDIATE")
        if sha(await async_snapshot(db, filing_id)) != data["local_hash"]:
            raise ValueError("Local maintenance scope drift; refusing final transition")
        if rollback:
            for table in SCOPED_TABLES:
                await db.execute(f"DELETE FROM {table} WHERE filing_id = ?", (filing_id,))
            row = plan["old_local"]["filing"]
            columns = [k for k in row if k != "id"]
            await db.execute(
                f"UPDATE filings SET {','.join(k + ' = ?' for k in columns)} WHERE id = ?",
                tuple(row[k] for k in columns) + (filing_id,),
            )
            for table in SCOPED_TABLES:
                await insert_rows(db, table, plan["old_local"][table])
        else:
            await db.execute("DELETE FROM delivered_items WHERE filing_id = ?", (filing_id,))
            await db.executemany("INSERT INTO delivered_items VALUES (?,?,?,NULL)", [
                (item_id, filing_id, payload_hash(p)) for item_id, p in plan["desired"].items()
            ])
            await db.execute("DELETE FROM reconciliation_candidates WHERE filing_id = ?", (filing_id,))
            await db.execute("UPDATE chunks SET state = 'uploaded', error_message = NULL WHERE filing_id = ?", (filing_id,))
            await db.execute("UPDATE filings SET state = 'completed' WHERE id = ?", (filing_id,))
        data["local_hash"] = sha(await async_snapshot(db, filing_id))
        await save_operation(db, digest, "rolled_back" if rollback else "completed", data)
        await db.commit()
    except BaseException:
        await db.rollback()
        raise


async def execute(config, graph, plan, digest, action, *, acknowledged, recovery=None):
    if action not in {"apply", "resume", "rollback"} or plan.get("format") != 1 or sha(plan) != digest:
        raise ValueError("Invalid action or reviewed plan digest")
    if not acknowledged:
        raise ValueError("Acknowledge quiescing all local, scheduled and other-machine writers")
    check_binding(plan, config, forward=action != "rollback")
    path = IngestionPipeline(config).db_path
    async with StateManager(path, config.azure.tenant_id, config.azure.connection_id, maintenance=True) as state:
        check_binding(plan, config, forward=action != "rollback")
        await environment(graph, plan)
        tables = await (await state._db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )).fetchall()
        operation = None
        if "maintenance_operations" in {r["name"] for r in tables}:
            other = await (await state._db.execute(
                "SELECT digest FROM maintenance_operations WHERE phase NOT IN ('completed','rolled_back') AND digest != ?",
                (digest,),
            )).fetchone()
            if other:
                raise ValueError("A different maintenance operation is unfinished")
            operation = await (await state._db.execute(
                "SELECT phase, data FROM maintenance_operations WHERE digest = ?", (digest,),
            )).fetchone()
        if operation is None:
            if action != "apply" or recovery is None:
                raise ValueError("No operation to resume/rollback; use apply with a new recovery directory")
            phase, data = await activate(state, graph, plan, digest, recovery)
        else:
            phase, data = operation["phase"], json.loads(operation["data"])
            if action == "apply":
                raise ValueError("Operation already exists; use maintenance resume/rollback")
        verify_backup(data, plan, digest)
        check_binding(plan, config, forward=action != "rollback")
        if sha(await async_snapshot(state._db, plan["old_local"]["filing"]["id"])) != data["local_hash"]:
            raise ValueError("Local maintenance scope drift")
        with closing(read_only(path)) as reader:
            ownership(reader, set(plan["old"]) | set(plan["desired"]), plan["old_local"]["filing"]["id"])
        if phase == "rolled_back" or (phase == "completed" and action != "rollback"):
            raise ValueError(f"Operation already {phase}; inspect retained evidence")
        if phase == "rolling_back" and action != "rollback":
            raise ValueError("Rollback has started; repeat maintenance rollback")
        if action == "rollback":
            phase = "rolling_back"
            await checkpoint(state._db, digest, phase, data)
            for item_id in plan["old"]:
                await put_verified(state, graph, plan, digest, phase, data, item_id, rollback=True)
            for payload in plan["old"].values():
                await exact_get(graph, payload, plan["schema"])
            data["old_set_verified"] = now()
            await checkpoint(state._db, digest, phase, data)
            for item_id in plan["new"]:
                if item_id in data["put"]:
                    await delete_verified(state, graph, plan, digest, phase, data, item_id, rollback=True)
                elif await get_item(graph, item_id) is not None:
                    raise ValueError(f"Originally absent unowned ID occupied: {item_id}")
            for payload in plan["old"].values():
                await exact_get(graph, payload, plan["schema"])
            for item_id in plan["new"]:
                if await get_item(graph, item_id) is not None:
                    raise ValueError(f"New ID is no longer absent: {item_id}")
            await finish(state, plan, digest, data, rollback=True)
            return "rolled_back"
        # Check a property-removing shared overwrite before the rest of the set.
        order = sorted(plan["desired_order"], key=lambda i: not (
            i in plan["old"] and set(plan["old"][i]["properties"]) - set(plan["desired"][i]["properties"])
        ))
        for item_id in order:
            await put_verified(state, graph, plan, digest, phase, data, item_id)
        # Reverify the whole set on every continuation, never trust an old GET gate.
        for payload in plan["desired"].values():
            await exact_get(graph, payload, plan["schema"])
        phase = "verified"
        data["desired_set_verified"] = now()
        await checkpoint(state._db, digest, phase, data)
        for item_id in plan["stale"]:
            await delete_verified(state, graph, plan, digest, phase, data, item_id)
        for payload in plan["desired"].values():
            await exact_get(graph, payload, plan["schema"])
        for item_id in plan["stale"]:
            if await get_item(graph, item_id) is not None:
                raise ValueError(f"Stale ID is no longer absent: {item_id}")
        await finish(state, plan, digest, data)
        return "completed"


def inspect(plan, digest):
    result = {
        "digest": digest, "identity": plan["identity"], "scope": plan["scope"],
        "old": len(plan["old"]), "desired": len(plan["desired"]),
        "new": len(plan["new"]), "stale": len(plan["stale"]),
        "processing_version": plan["provenance"]["options"]["processing_version"],
        "phase": "prepared",
    }
    with closing(read_only(Path(plan["database"]))) as db:
        row = db.execute("SELECT version FROM destination").fetchone()
        if row[0] == 4:
            operation = db.execute(
                "SELECT phase,data FROM maintenance_operations WHERE digest = ?", (digest,),
            ).fetchone()
            if operation:
                result["phase"] = operation["phase"]
                result["checkpoints"] = json.loads(operation["data"])
    return result
