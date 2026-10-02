"""Offline source/payload diagnostics are independent of human answer scoring."""

from copy import deepcopy
from datetime import datetime
import json
import socket

import pytest

from sec_connector.config import ChunkingConfig
from tests.corpus_replay import replay, sha
from tests.evidence_evaluate import MANIFEST, availability, evaluate, main, offline, validate_runs


def manifest():
    return json.loads(MANIFEST.read_bytes())


def run_record():
    case = manifest()["cases"][0]
    source = manifest()["sources"][0]
    return {
        "id": "run-1", "kind": "invocation", "case_id": case["id"],
        "conversation_id": "synthetic-chat-1", "response_id": "synthetic-response-1",
        "timestamp": "2026-10-02T16:00:00-04:00", "actual_model_setting": "Synthetic model selection",
        "fresh_chat": True, "selected_connection": "syntheticconnection",
        "instructions_version": "test-v1", "instructions_sha256": "a" * 64,
        "payload_manifest_sha256": "b" * 64, "skills": [], "skills_observed": True,
        "other_sources": [], "other_sources_observed": True, "index_visibility": "verified",
        "prompt": case["prompt"], "response": "Synthetic recorded response; not an actual agent run.",
        "reviewer": "synthetic reviewer", "adjudication_notes": "Validator fixture, not evidence of accuracy.",
        "components": dict.fromkeys(case["required"], "full"), "source_grounding": "full",
        "citations": [{
            "source": source["id"], "url": source["url"], "locator": "table 376",
            "verified": True, "components": list(case["required"]),
        }],
    }


def test_manifest_public_scope_and_evaluator_only():
    data = manifest()
    assert len(data["sources"]) == 4 and len(data["cases"]) == 7
    sources = {s["id"] for s in data["sources"]}
    evidence = {e["id"] for e in data["evidence"]}
    assert len(sources) == len(data["sources"])
    assert len(evidence) == len(data["evidence"])
    assert all(e["source"] in sources for e in data["evidence"])
    assert all(set(c["evidence"]) <= evidence and c["required"] for c in data["cases"])
    assert len({c["id"] for c in data["cases"]}) == len(data["cases"])
    assert all("path" not in s and s["url"].startswith("https://www.sec.gov/Archives/") for s in data["sources"])
    assert next(e for e in data["evidence"] if e["id"] == "charity")["unverified"]
    assert len(next(e for e in data["evidence"] if e["id"] == "hr-2025")["rows"]) == 13
    assert len(next(e for e in data["evidence"] if e["id"] == "hr-2024")["rows"]) == 14
    visual = next(e for e in data["evidence"] if e["id"] == "charity")["visual_reference"]
    assert [header["column"] for header in visual["marked_headers"]] == visual["marked_columns"]
    assert visual["marked_columns"] == [2, 5, 6, 7, 8, 13]
    assert round((23.7 - 18.7) / 18.7 * 100, 1) == 26.7


def test_frozen_public_receipt_matches_manifest_and_does_not_claim_live_results():
    data = manifest()
    report = json.loads((MANIFEST.parents[2] / "docs" / "evidence-evaluation-results.json").read_bytes())
    assert report["manifest_sha256"] == sha(json.dumps(data, sort_keys=True).encode())
    assert {s["id"]: s["sha256"] for s in report["sources"]} == {
        s["id"]: s["sha256"] for s in data["sources"]
    }
    assert len(report["evidence"]) == len(data["evidence"]) == 9
    assert sum(len(e.get("rows", [])) for e in data["evidence"]) == 34
    assert report["agent_evaluation"] == "not_run"
    assert all(e["payload"] == {"status": "not_run"} for e in report["evidence"])
    assert all(all(e["parsed"]["rows_present"]) for e in report["evidence"])
    assert next(e for e in report["evidence"] if e["id"] == "charity")["image_header_recovery"] == "not_evaluated"


def test_rows_need_labels_order_and_values_not_document_wide_number_presence():
    rows = [["Revenue", "120", "110"]]
    good = "| Metric | 2024 | 2023 |\n| Revenue | 120 | 110 |\n(a) Net of returns."
    assert availability(rows, ["2024", "2023"], ["(a) Net of returns."], [good])["row_headers_together"] == [True]
    for wrong in ("| Revenue | 110 | 120 |", "| Cost | 120 | 110 |", "Revenue 120 110"):
        assert availability(rows, [], [], [wrong])["rows_present"] == [False]
    split = availability(rows, ["2024"], ["(a) Net of returns."], [
        "| Metric | 2024 | 2023 |", "| Revenue | 120 | 110 |", "(a) Net of returns.",
    ])
    assert split["rows_present"] == [True] and split["context_present"] == [True]
    assert split["row_headers_together"] == split["row_context_together"] == [False]


@pytest.mark.parametrize("symbol", ["*", "**"])
def test_escaped_symbols_are_preserved_not_discarded_for_a_passing_score(symbol):
    rows = [[f"EPS{symbol} (1)", "10", "9"]]
    escaped = symbol.replace("*", "\\*")
    assert availability(rows, [], [], [f"| EPS{escaped}(1) | 10 | 9 |"])["rows_present"] == [True]
    assert availability(rows, [], [], ["| EPS (1) | 10 | 9 |"])["rows_present"] == [False]


def test_source_and_existing_corpus_payload_checks(tmp_path):
    path = tmp_path / "synthetic.htm"
    path.write_text("<table><tr><th>Metric</th><th>2024</th><th>2023</th></tr>"
                    "<tr><td>Revenue</td><td>120</td><td>110</td></tr></table>", encoding="utf-8")
    source = {
        "id": "synthetic", "cik": "0000000001", "accession": "0000000001-25-000001",
        "filename": path.name, "sha256": sha(path.read_bytes()),
        "url": "https://www.sec.gov/Archives/edgar/data/0000000001/000000000125000001/synthetic.htm",
    }
    data = {"sources": [source], "evidence": [{
        "id": "revenue", "source": "synthetic", "table_index": 0,
        "headers": ["2024", "2023"], "rows": [["Revenue", "120", "110"]],
    }]}
    entry = {
        "id": "synthetic", "path": str(path), "sha256": source["sha256"],
        "filing": {
            "cik": source["cik"], "accession_number": source["accession"], "ticker": "SYN",
            "company_name": "Synthetic Manufacturer", "form": "10-K/A",
            "filing_date": datetime(2025, 3, 1), "report_period_end": datetime(2024, 12, 31),
        },
        "document": {"sequence": 1, "filename": path.name, "document_type": "10-K/A"},
    }
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    with offline():
        replay(entry, corpus / source["id"], ChunkingConfig())
    report = evaluate(data, {"synthetic": str(path)}, corpus)
    assert report["evidence"][0]["source"]["rows_present"] == [True]
    assert report["evidence"][0]["payload"]["row_headers_together"] == [True]
    assert evaluate(data, {"synthetic": str(path)})["evidence"][0]["payload"] == {"status": "not_run"}
    payload_path = corpus / "synthetic" / "payloads.json"
    payloads = json.loads(payload_path.read_bytes())
    payloads[0]["properties"]["AccessionNumber"] = "0000000001-24-000001"
    payload_path.write_text(json.dumps(payloads), encoding="utf-8")
    with pytest.raises(ValueError, match="payload hash"):
        evaluate(data, {"synthetic": str(path)}, corpus)
    receipt_path = corpus / "synthetic" / "result.json"
    receipt = json.loads(receipt_path.read_bytes())
    receipt["payload_sha256"] = sha(json.dumps(payloads, sort_keys=True).encode())
    receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
    with pytest.raises(ValueError, match="identity"):
        evaluate(data, {"synthetic": str(path)}, corpus)
    path.write_text("<p>Changed source</p>", encoding="utf-8")
    with pytest.raises(ValueError, match="source hash"):
        evaluate(data, {"synthetic": str(path)})


def test_network_connections_are_blocked_and_restored():
    connect = socket.socket.connect
    with offline(), socket.socket() as sock:
        with pytest.raises(RuntimeError, match="offline"):
            sock.connect(("127.0.0.1", 1))
        with pytest.raises(RuntimeError, match="offline"):
            sock.connect_ex(("127.0.0.1", 1))
    assert socket.socket.connect is connect


def test_actual_invocations_copies_and_unquantified_history_are_separate():
    record = run_record()
    failed = deepcopy(record)
    failed.update(id="failed-run", conversation_id="synthetic-chat-2", response_id="synthetic-response-2")
    failed["components"]["award"] = "fail"
    historical = {
        "id": "historical", "kind": "historical_observation",
        "note": "A user reported baseline failures; exact run count and model are unobserved.",
        "source_reference": "docs/evidence-packaging-pilot.md",
    }
    summary = validate_runs([record, failed, historical, {
        "id": "worksheet-copy", "kind": "copy", "original_id": record["id"],
    }], manifest())
    assert [r["grade"] for r in summary["invocations"]] == ["full", "fail"]
    assert summary["copies"] == ["worksheet-copy"]
    assert summary["historical_observations"] == ["historical"]
    copied = deepcopy(record)
    copied["id"] = "disguised-copy"
    with pytest.raises(ValueError, match="duplicate native"):
        validate_runs([record, copied], manifest())


@pytest.mark.parametrize("key,value", [
    ("timestamp", "2026-10-02T16:00:00"),
    ("fresh_chat", "yes"),
    ("instructions_sha256", "not-a-hash"),
    ("prompt", "Modified question"),
    ("components", {"target": "full"}),
    ("citations", []),
    ("skills", [{"name": "unknown", "version": "v1", "sha256": "unknown"}]),
])
def test_incomplete_or_invalid_invocation_is_not_certified(key, value):
    record = run_record()
    record[key] = value
    with pytest.raises(ValueError):
        validate_runs([record], manifest())


def test_unobserved_settings_and_partial_grounding_do_not_become_controlled_full_passes():
    record = run_record()
    record.update(actual_model_setting="unobserved", fresh_chat=None, skills_observed=False,
                  source_grounding="unobserved", citations=[])
    result = validate_runs([record], manifest())["invocations"][0]
    assert result["grade"] == "partial" and not result["controlled"]


def test_cli_preserves_failure_receipt_and_refuses_overwrite(tmp_path, monkeypatch):
    sources = tmp_path / "sources.json"
    sources.write_text("{}", encoding="utf-8")
    output = tmp_path / "result.json"
    monkeypatch.setattr("tests.evidence_evaluate.evaluate", lambda *args: {
        "evidence": [{"id": "negative-control", "source": {"rows_present": [False]}}],
    })
    monkeypatch.setattr("sys.argv", ["evidence_evaluate", "--sources", str(sources), "--output", str(output)])
    with pytest.raises(SystemExit, match="mismatch"):
        main()
    previous = output.read_bytes()
    with pytest.raises(FileExistsError, match="preserve"):
        main()
    assert output.read_bytes() == previous


def test_blank_template_cannot_be_counted_as_a_run():
    template = json.loads((MANIFEST.parent / "run-template.json").read_bytes())
    with pytest.raises(ValueError, match="record ID"):
        validate_runs(template, manifest())
