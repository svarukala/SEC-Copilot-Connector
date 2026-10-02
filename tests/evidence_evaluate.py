"""Offline evaluator-only source checks and manually adjudicated run receipts."""

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from importlib.metadata import version
import json
from pathlib import Path
import re
import socket
from unittest.mock import patch

from bs4 import BeautifulSoup

from sec_connector import chunker, parser
from tests.corpus_replay import sha


MANIFEST = Path(__file__).resolve().parents[1] / "samples" / "evaluation" / "pnc-evidence-v1.json"


def normalize(text):
    return " ".join(text.split())


def row_text(text):
    # Ignore Markdown emphasis and visual empty columns, not numbers or ordering.
    text = re.sub(r"(?<!\\)\*\*([^*\n|]+)(?<!\\)\*\*", r"\1", text)
    text = text.replace("\\*", "*").replace("|", " ")
    return re.sub(r"\s+(?=\([a-z0-9]+\))", "", normalize(text))


@contextmanager
def offline():
    def denied(*args, **kwargs):
        raise RuntimeError("Evidence evaluation must remain offline")

    with patch.object(socket.socket, "connect", denied), patch.object(socket.socket, "connect_ex", denied):
        yield


def availability(rows, headers, context, contents):
    """Presence and co-location only, never answer correctness or retrieval."""
    normalized = [row_text(content) for content in contents]
    row_matches = [
        [i for i, content in enumerate(contents)
         if any(row_text(" ".join(row)) == row_text(line)
                for line in content.splitlines() if line.startswith("|"))]
        for row in rows
    ]
    return {
        "rows_present": [bool(matches) for matches in row_matches],
        "row_headers_together": [
            any(all(row_text(header) in normalized[i] for header in headers) for i in matches)
            for matches in row_matches
        ],
        "context_present": [
            any(row_text(item) in content for content in normalized) for item in context
        ],
        "row_context_together": [
            any(all(row_text(item) in normalized[i] for item in context) for i in matches)
            for matches in row_matches
        ],
        "matching_content_indexes": row_matches,
    }


def load_payloads(root, source):
    directory = root / source["id"]
    receipt = json.loads((directory / "result.json").read_bytes())
    payloads = json.loads((directory / "payloads.json").read_bytes())
    if receipt["source_sha256"] != source["sha256"]:
        raise ValueError("Corpus source hash mismatch")
    if receipt["payload_sha256"] != sha(json.dumps(payloads, sort_keys=True).encode()):
        raise ValueError("Corpus payload hash mismatch")
    if not payloads or len({p["id"] for p in payloads}) != len(payloads):
        raise ValueError("Empty or duplicate corpus payloads")
    for payload in payloads:
        props = payload["properties"]
        if any(props[key] != source[field] for key, field in (
            ("CIK", "cik"), ("AccessionNumber", "accession"),
            ("DocumentName", "filename"), ("Url", "url"),
        )):
            raise ValueError("Corpus document identity mismatch")
    return payloads


def evaluate(manifest, source_paths, corpus=None):
    sources = {source["id"]: source for source in manifest["sources"]}
    if set(source_paths) != set(sources):
        raise ValueError("Source map must name exactly the manifest sources")
    result = {
        "kind": "offline_evidence_availability",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "manifest_sha256": sha(json.dumps(manifest, sort_keys=True).encode()),
        "code_sha256": {
            name: sha(Path(module.__file__).read_bytes())
            for name, module in (("parser", parser), ("chunker", chunker))
        },
        "runner_sha256": sha(Path(__file__).read_bytes()),
        "dependencies": {name: version(name) for name in ("beautifulsoup4", "lxml", "markdownify")},
        "ocr": False,
        "agent_evaluation": "not_run",
        "content_probe": {"target_size": 4000, "max_size": 8000, "overlap": 200, "max_bytes": 31457280},
        "content_probe_limit": "No filing metadata prefix or page/section orchestration; not an ingestion/payload replay.",
        "sources": [],
        "evidence": [],
    }
    with offline():
        for source_id, source in sources.items():
            raw = Path(source_paths[source_id]).read_bytes()
            if sha(raw) != source["sha256"]:
                raise ValueError(f"Frozen source hash mismatch: {source_id}")
            soup = BeautifulSoup(raw, "lxml")
            source_text = normalize(soup.get_text(" ", strip=True))
            tables = soup.find_all("table")
            headers = {}
            parsed = parser.html_to_markdown(raw.decode("utf-8"), table_header_rows=headers)
            chunks = chunker._split_content(parsed, 4000, 8000, 200, 31457280, headers)
            payloads = load_payloads(corpus, source) if corpus is not None else None
            result["sources"].append({
                "id": source_id, "sha256": sha(raw), "bytes": len(raw),
                "content_probe_chunks": len(chunks),
                "payloads": len(payloads) if payloads is not None else None,
            })
            for evidence in manifest["evidence"]:
                if evidence["source"] != source_id:
                    continue
                expected = evidence.get("rows", [])
                rendered_rows = [evidence.get("rendered_row_prefix", []) + row for row in expected]
                context = evidence.get("context", [])
                required_headers = evidence.get("headers", [])
                source_check = {"context_present": [normalize(text) in source_text for text in context]}
                if "table_index" in evidence:
                    table = tables[evidence["table_index"]]
                    actual_rows = [
                        [value for cell in row.find_all(["td", "th"], recursive=False)
                         if (value := normalize(cell.get_text(" ", strip=True)))]
                        for row in table.find_all("tr")
                    ]
                    table_text = normalize(table.get_text(" ", strip=True))
                    source_check.update({
                        "rows_present": [row in actual_rows for row in expected],
                        "headers_present": [normalize(h) in table_text for h in required_headers],
                    })
                    if "image_count" in evidence:
                        source_check["image_count_matches"] = (
                            len(table.find_all("img")) == evidence["image_count"]
                        )
                    if "visual_reference" in evidence:
                        images = table.find_all("img")
                        source_check["referenced_asset_order"] = [
                            images[header["column"] - 1].get("src") == header["filename"]
                            for header in evidence["visual_reference"]["marked_headers"]
                        ]
                result["evidence"].append({
                    "id": evidence["id"],
                    "source": source_check,
                    "parsed": availability(rendered_rows, required_headers, context, [parsed]),
                    "content_probe": availability(rendered_rows, required_headers, context, chunks),
                    "payload": availability(
                        rendered_rows, required_headers, context,
                        [p["content"]["value"] for p in payloads],
                    ) if payloads is not None else {"status": "not_run"},
                    "unverified": evidence.get("unverified", []),
                    "image_header_recovery": "not_evaluated" if "visual_reference" in evidence else "not_applicable",
                })
    return result


def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def validate_runs(records, manifest):
    """Validate human grading/provenance; never grade free text by keyword."""
    cases = {case["id"]: case for case in manifest["cases"]}
    sources = {source["id"]: source for source in manifest["sources"]}
    evidence_sources = {item["id"]: item["source"] for item in manifest["evidence"]}
    ids, invocations = set(), set()
    summary = {"invocations": [], "historical_observations": [], "copies": []}
    for record in records:
        run_id = record["id"]
        if not nonempty(run_id) or run_id in ids:
            raise ValueError("Missing or duplicate record ID")
        ids.add(run_id)
        kind = record["kind"]
        if kind == "copy":
            if record["original_id"] not in ids or record["original_id"] == run_id:
                raise ValueError("Copy must reference an earlier original record")
            summary["copies"].append(run_id)
            continue
        if kind == "historical_observation":
            if not nonempty(record["note"]) or not nonempty(record["source_reference"]):
                raise ValueError("Historical observation needs its original provenance and limitations")
            summary["historical_observations"].append(run_id)
            continue
        if kind != "invocation":
            raise ValueError("Unknown record kind")
        case = cases[record["case_id"]]
        identity = (record["conversation_id"], record["response_id"])
        if not all(nonempty(v) for v in identity) or identity in invocations:
            raise ValueError("Missing or duplicate native conversation/response identity")
        invocations.add(identity)
        timestamp = datetime.fromisoformat(record["timestamp"].replace("Z", "+00:00"))
        if timestamp.utcoffset() is None:
            raise ValueError("Timestamp must include timezone")
        for key in ("actual_model_setting", "selected_connection", "instructions_version",
                    "response", "reviewer", "adjudication_notes"):
            if not nonempty(record[key]):
                raise ValueError(f"Missing {key}; record unobserved rather than infer settings")
        for key in ("instructions_sha256", "payload_manifest_sha256"):
            if record[key] != "unobserved" and not digest(record[key]):
                raise ValueError(f"Invalid {key}")
        if record["fresh_chat"] is not None and type(record["fresh_chat"]) is not bool:
            raise ValueError("fresh_chat must be true, false or null (unobserved)")
        if record["prompt"] != case["prompt"]:
            raise ValueError("Changed prompt requires a separately versioned case")
        if record["index_visibility"] not in {"verified", "unobserved", "unavailable"}:
            raise ValueError("Invalid index visibility")
        if not isinstance(record["other_sources"], list) or not isinstance(record["skills"], list):
            raise ValueError("Explicit sources and skills lists are required")
        for key in ("skills_observed", "other_sources_observed"):
            if type(record[key]) is not bool:
                raise ValueError(f"{key} must distinguish absent from unobserved")
        for skill in record["skills"]:
            if not all(nonempty(skill[key]) for key in ("name", "version")) or not digest(skill["sha256"]):
                raise ValueError("Installed skills need exact versions and hashes")
        grades = record["components"]
        if set(grades) != set(case["required"]) or any(g not in {"full", "partial", "fail"} for g in grades.values()):
            raise ValueError("Grade every required component full/partial/fail")
        grounding = record["source_grounding"]
        if grounding not in {"full", "partial", "fail", "unobserved"}:
            raise ValueError("Invalid grounding grade")
        supported = set()
        allowed_sources = {evidence_sources[e] for e in case["evidence"]}
        for citation in record["citations"]:
            if citation["source"] not in allowed_sources:
                raise ValueError("Citation refers to a source outside this case")
            if citation["url"].split("#", 1)[0] != sources[citation["source"]]["url"]:
                raise ValueError("Citation URL does not identify the declared source")
            if not nonempty(citation["locator"]) or type(citation["verified"]) is not bool:
                raise ValueError("Citation requires a locator and explicit verification")
            if not set(citation["components"]) <= set(grades):
                raise ValueError("Citation references an unknown component")
            if citation["verified"]:
                supported.update(citation["components"])
        if grounding == "full" and supported != set(grades):
            raise ValueError("Full grounding requires verified citations for every component")
        grade = "fail" if "fail" in grades.values() or grounding == "fail" else (
            "full" if set(grades.values()) == {"full"} and grounding == "full" else "partial"
        )
        controlled = (
            record["fresh_chat"] is True and record["index_visibility"] == "verified"
            and not record["other_sources"] and record["other_sources_observed"]
            and record["skills_observed"]
            and all(record[key] != "unobserved" for key in (
                "actual_model_setting", "selected_connection", "instructions_version",
                "instructions_sha256", "payload_manifest_sha256",
            ))
        )
        summary["invocations"].append({
            "id": run_id, "case_id": case["id"], "grade": grade,
            "source_grounding": grounding, "controlled": controlled,
        })
    return summary


def main():
    args = argparse.ArgumentParser(description=__doc__)
    args.add_argument("--manifest", type=Path, default=MANIFEST)
    inputs = args.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--sources", type=Path, help="Private JSON map: source ID -> exact cached HTML path")
    inputs.add_argument("--runs", type=Path, help="Private JSON array of manually adjudicated receipts")
    args.add_argument("--corpus", type=Path, help="Existing tests.corpus_replay output; requires --sources")
    args.add_argument("--output", type=Path, required=True)
    options = args.parse_args()
    if options.corpus and not options.sources:
        args.error("--corpus requires --sources")
    manifest = json.loads(options.manifest.read_bytes())
    if options.output.exists():
        raise FileExistsError("Use a new output path; preserve historical receipts")
    if options.sources:
        result = evaluate(manifest, json.loads(options.sources.read_bytes()), options.corpus)
    else:
        raw = options.runs.read_bytes()
        result = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "runs_sha256": sha(raw), "manifest_sha256": sha(json.dumps(manifest, sort_keys=True).encode()),
            "runner_sha256": sha(Path(__file__).read_bytes()),
            **validate_runs(json.loads(raw), manifest),
        }
    with options.output.open("x", encoding="utf-8") as stream:
        json.dump(result, stream, indent=2)
    if options.sources:
        for item in result["evidence"]:
            for checks in item["source"].values():
                if checks is False or isinstance(checks, list) and not all(checks):
                    raise SystemExit("Source expectation mismatch; diagnostic receipt preserved")


if __name__ == "__main__":
    main()
