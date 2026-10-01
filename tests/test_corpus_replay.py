"""Checks for the offline corpus harness and opt-in frozen corpus receipts."""

import hashlib
import json
import os
from pathlib import Path

import pytest

from tests.corpus_compare import contextual_rows, period_rows
from tests.corpus_replay import numbers, subsequence, tokens


def test_coverage_is_ordered_not_just_token_counts():
    assert subsequence(["alpha", "beta"], ["prefix", "alpha", "beta"])["ok"]
    assert not subsequence(["alpha", "beta"], ["beta", "alpha"])["ok"]
    assert not subsequence(["100", "100"], ["100"])["ok"]
    assert tokens("Heading\n---PAGE---\nCash 123") == ["Heading", "Cash", "123"]
    assert numbers("Cash $1,234.50 and 20%") == ["1,234.50", "20%"]


def test_relational_audit_detects_missing_period_not_just_preserved_header():
    head = "| Summary | Value |\n| --- | --- |"
    period = "| Years | 2025 / 2024 |"
    row = "| Income | 1,200 / 1,100 |"
    text = head + "\n" + period + "\n" + row
    fragmented = [
        {"content": {"value": head + "\n" + period}},
        {"content": {"value": head + "\n" + row}},
    ]
    assert period_rows(text, fragmented) == {(row, period): False}
    assert period_rows(text, [{"content": {"value": text}}]) == {(row, period): True}


def test_relational_audit_detects_units_and_linked_footnote():
    table = "| Metric | 2025 |\n| --- | --- |\n| Income (a) | 1,200 |"
    text = "In millions\n\n" + table + "\n\n(a) Includes adjustments."
    fragmented = [{"content": {"value": table}}]
    assert set(contextual_rows(text, fragmented).values()) == {False}
    assert set(contextual_rows(text, [{"content": {"value": text}}]).values()) == {True}


@pytest.mark.skipif(
    not os.environ.get("SEC_CORPUS_EVIDENCE"),
    reason="Set SEC_CORPUS_EVIDENCE to the private corpus artifact directory",
)
def test_frozen_corpus_receipts_and_source_hashes():
    root = Path(os.environ["SEC_CORPUS_EVIDENCE"])
    manifest = json.loads((root / "manifest-v6-final.json").read_bytes())
    comparison = json.loads((root / "comparison-v6-refined.json").read_bytes())
    assert len(manifest["documents"]) == len(comparison) == 20
    results = {result["id"]: result for result in comparison}
    for entry in manifest["documents"]:
        assert hashlib.sha256(Path(entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
        result = results[entry["id"]]
        assert result["lexical_equal"] and result["numeric_equal"]
        assert result["emitted_lexical_coverage"]["ok"] and result["emitted_numeric_coverage"]["ok"]
        assert not result["candidate_row_failures"]
        assert not result["candidate_section_mixing"]
        assert result["non_list_table_changes"] == 0
        assert not result["new_context_misses"]
        assert not result["new_period_misses"]
        assert result["max_chars"] <= manifest["chunking"]["max_size"]
        assert result["max_request_bytes"] <= manifest["chunking"]["max_item_bytes"]
        raw_date = entry["filing"].get("report_period_end")
        if entry["filing"]["form"].removesuffix("/A") in {"10-K", "10-Q"} and raw_date:
            assert result["candidate_report_period"] == [raw_date[:10] + "T00:00:00Z"]
        else:
            assert result["candidate_report_period"] == [""]
