"""Minimized source-geometry controls derived from financial header layouts."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re

import pytest
from bs4 import BeautifulSoup

from sec_connector.chunker import _split_content, _table_header_count, chunk_document
from sec_connector.config import AppConfig, ChunkingConfig
from sec_connector.graph_client import GraphClient
from sec_connector.models import DocumentInfo, FilingMetadata, ParsedDocument
from sec_connector.parser import _source_header_end, html_to_markdown, parse_document
from sec_connector.payloads import serialize_item
from tests.corpus_replay import subsequence, tokens
from tests.table_context_audit import data_row_counts
from tests.source_header_audit import audit, digest


def cell(text, span=3, align="center", extra=""):
    return f'<td colspan="{span}" style="vertical-align:bottom;text-align:{align}" {extra}>{text}</td>'


def source(rows=35, label="Transfers into Level 3"):
    return (
        "<table><tr>" + cell("Fair value measurements using significant unobservable inputs", 9)
        + "</tr><tr>" + cell("Year ended December 31, 2025 (in millions)", align="left", extra='rowspan="2"')
        + cell(label) + cell("Fair value at December 31, 2025")
        + "</tr><tr>" + cell("Purchases (a)") + cell("Transfers out of Level 3")
        + "</tr><tr>" + cell("Assets", align="left") + cell("", 6) + "</tr>"
        + "".join(f"<tr>{cell('Financial instrument ' + str(i), align='left')}"
                  f"<td>$</td><td>1,200</td><td></td><td>$</td><td>1,200</td><td></td></tr>"
                  for i in range(rows))
        + "</table><p>(a) Net of settlements.</p>"
    )


def convert(html):
    headers = {}
    text = html_to_markdown(html, table_header_rows=headers)
    # Collection is a sidecar; neither rendering nor native content changes.
    assert text == html_to_markdown(html)
    return text, headers


def test_source_band_keeps_exact_columns_and_repeats_only_headers():
    text, headers = convert(source())
    table = re.search(r"^\|[^\n]*(?:\n\|[^\n]*)*", text, re.M).group()
    count = headers[hashlib.sha256(table.encode()).hexdigest()]
    assert count > _table_header_count(table.splitlines())
    assert count == 4
    chunks = _split_content(text, 1400, 2100, 0, 10000, headers)
    band = "\n".join(table.splitlines()[:count])
    for chunk in chunks:
        if "| Financial instrument" in chunk:
            assert band in chunk
            assert "(a) Net of settlements." in chunk
            assert len(chunk) <= 2100
    assert sum(line.startswith("| Assets") for c in chunks for line in c.splitlines()) == 1
    rows = [line for line in text.splitlines() if line.startswith("| Financial instrument")]
    assert [line for c in chunks for line in c.splitlines() if line.startswith("| Financial instrument")] == rows
    assert all(line.count("1,200") == 2 for line in rows)
    assert subsequence(tokens(text), tokens("\n".join(chunks)))["ok"]
    assert not data_row_counts(text, [{"content": {"value": c}} for c in chunks])["missing_occurrences"]


@pytest.mark.parametrize("value", ["(1,200)", "-1200", "1200", "$1,200", "3.5%", "2025", "2025-12-31"])
def test_bold_first_value_or_date_row_is_not_structural_header(value):
    html = (
        "<table><tr>" + cell("In millions", align="left") + cell("Fair value")
        + "</tr><tr>" + cell("Total", align="left") + cell(f"<b>{value}</b>")
        + "</tr><tr>" + cell("Subsequent data", align="left") + cell("1,200")
        + "</tr></table>"
    )
    text, headers = convert(html)
    table = re.search(r"^\|[^\n]*(?:\n\|[^\n]*)*", text, re.M).group()
    assert all(count == 2 for count in headers.values())
    soup = BeautifulSoup(html, "lxml")
    assert _source_header_end([r.find_all("td", recursive=False) for r in soup.find_all("tr")]) == 1
    assert "Total" in table


def test_domain_label_not_enough_without_structural_evidence():
    html = "<table><tr><td>In millions</td><td>Level 3 instruments</td></tr>"
    html += "<tr><td>Actual observation</td><td>1,234</td></tr></table>"
    _, headers = convert(html)
    assert all(count == 2 for count in headers.values())


def test_long_source_caption_with_geometry_not_arbitrary_first_data_row():
    label = "Unrealized gains and losses on instruments held at the end of the reporting period " * 2
    text, headers = convert(source(label=label))
    table = re.search(r"^\|[^\n]*(?:\n\|[^\n]*)*", text, re.M).group()
    assert headers[hashlib.sha256(table.encode()).hexdigest()] == 4
    assert " ".join(label.split()) in table
    assert "Financial instrument 0" not in "\n".join(table.splitlines()[:4])


def test_native_headers_and_unrelated_table_sidecars_do_not_leak(tmp_path):
    html = source(20) + "<PAGE><h2>Other section</h2><table><thead><tr><th>Metric</th>"
    html += "<th>Period</th></tr></thead><tbody><tr><th scope='row'>Maturity</th><td>2027</td></tr></tbody></table>"
    path = tmp_path / "annual.htm"
    path.write_text(html, encoding="utf-8")
    parsed = parse_document(
        path, FilingMetadata(cik="0000000001", ticker="SYN", accession_number="0000000001-26-000001",
                             form="10-K", filing_date=datetime(2026, 1, 1), company_name="Synthetic"),
        DocumentInfo(sequence=1, filename="annual.htm", document_type="10-K"),
    )
    assert parsed.table_header_rows
    restored = ParsedDocument.model_validate_json(parsed.model_dump_json())
    chunks = chunk_document(restored, ChunkingConfig(target_size=1400, max_size=2100))
    assert all("Fair value measurements" not in c.content for c in chunks if c.page_number == 2)
    graph = GraphClient(AppConfig())
    for c in chunks:
        body = serialize_item(graph.build_payload(c))
        assert b"table_header_rows" not in body
        assert all(key.encode() not in body for key in parsed.table_header_rows)
    assert [c.model_dump() for c in chunks] == [c.model_dump() for c in chunk_document(restored, ChunkingConfig(target_size=1400, max_size=2100))]


def test_header_bundle_too_large_keeps_source_with_explicit_warning(caplog):
    text, headers = convert(source(label="Long financial caption " * 100))
    chunks = _split_content(text, 300, 500, 0, 800, headers)
    assert "header/context exceeds" in caplog.text
    assert all(len(c) <= 500 and len(c.encode()) <= 800 for c in chunks)
    assert subsequence(tokens(text), tokens("".join(chunks)))["ok"]


def test_stale_sidecar_hash_cannot_apply_to_changed_table():
    text, headers = convert(source())
    changed = text.replace("Level 3", "Level 2")
    assert _split_content(changed, 1400, 2100, 0, 10000, headers) == (
        _split_content(changed, 1400, 2100, 0, 10000)
    )


@pytest.mark.parametrize("vintage", [False, True])
def test_caption_and_vintage_source_bands_stop_before_financial_data(vintage):
    if vintage:
        top = cell("Credit quality by vintage", 15, "left")
        grouped = ("<tr>" + cell("Term loans by origination year", 9) + cell("Revolving loans", 6)
                   + "</tr>")
        header = (cell("Dollars in millions", align="left") + cell("2025") + cell("2024")
                  + cell("Prior") + cell("Total credit card"))
    else:
        top = cell("Table 1", 3, "left") + cell("Top countries exposure", 48, "left")
        grouped = ""
        header = (cell("Dollars in millions", align="left") + cell("Country exposure at December 31 2025")
                  + cell("Change from December 31 2024"))
    html = "<table><tr>" + top + "</tr><tr><td></td></tr>" + grouped + "<tr>" + header + "</tr>"
    html += "<tr>" + cell("Assets", 15) + "</tr>"
    html += "".join("<tr>" + cell(f"Loan {i}", align="left") + cell("<b>(1,200)</b>")
                    + cell("1,200") + "</tr>" for i in range(25)) + "</table>"
    soup = BeautifulSoup(html, "lxml")
    assert _source_header_end([r.find_all("td", recursive=False) for r in soup.find_all("tr")]) == (4 if vintage else 3)
    text, headers = convert(html)
    table = re.search(r"^\|[^\n]*(?:\n\|[^\n]*)*", text, re.M).group()
    count = headers[hashlib.sha256(table.encode()).hexdigest()]
    band = "\n".join(table.splitlines()[:count])
    assert "Assets" not in band and "Loan 0" not in band
    chunks = _split_content(text, 1800, 2500, 0, 10000, headers)
    assert all(band in chunk for chunk in chunks if "| Loan" in chunk)
    assert [r for c in chunks for r in c.splitlines() if r.startswith("| Loan")] == [
        r for r in text.splitlines() if r.startswith("| Loan")
    ]


def test_conflicting_identical_markdown_does_not_borrow_source_interpretation():
    html = source()
    unstyled = re.sub(r' style="[^"]*"', "", html)
    text, headers = convert(html)
    repeated, combined = convert(html + "<PAGE>" + unstyled)
    table = re.search(r"^\|[^\n]*(?:\n\|[^\n]*)*", text, re.M).group()
    key = hashlib.sha256(table.encode()).hexdigest()
    assert headers[key] == 4
    assert combined[key] == 2
    assert repeated.count(table) == 2


def test_row_scope_and_inline_xbrl_facts_override_native_header_tags():
    for cell_html in ("<th scope='row'>Total</th><th>2025</th>",
                      "<th>Assets</th><th><ix:nonfraction>1200</ix:nonfraction></th>"):
        soup = BeautifulSoup("<table><thead><tr>" + cell_html + "</tr></thead></table>", "lxml")
        assert _source_header_end([soup.tr.find_all("th", recursive=False)]) == 0


def test_reviewed_bounds_reject_data_promotion_and_unexplained_repetition():
    table = "| Caption | Context |\n| --- | --- |\n| In millions | Level 3 |\n| Asset | 1,200 |\n| Total | 1,200 |"
    key = digest(table)
    capture = {
        "index": 0, "converted": table, "source_header_end": 2,
        "source_structure": [], "source_cells": [["Caption", "Context"]],
    }
    annotation = {"table_sha256": key, "source_header_rows": 3,
                  "band": "\n".join(table.splitlines()[:3])}
    payloads = [{"content": {"value": table}}]
    assert not audit(table, payloads, payloads, [annotation], {key: 3}, [capture])["unapproved_extra_rows"]
    with pytest.raises(AssertionError, match="reviewed bound"):
        audit(table, payloads, payloads, [dict(annotation, source_header_rows=4)], {key: 3}, [capture])
    duplicated = [{"content": {"value": table + "\n| Asset | 1,200 |"}}]
    assert audit(table, payloads, duplicated, [annotation], {key: 3}, [capture])["unapproved_extra_rows"]
    missing = [{"content": {"value": table.replace("| Total | 1,200 |", "")}}]
    assert audit(table, payloads, missing, [annotation], {key: 3}, [capture])["missing_occurrences"]


@pytest.mark.skipif(not os.environ.get("SEC_SOURCE_HEADER_EVIDENCE"), reason="Private v8 corpus not configured")
def test_frozen_source_structure_corpus_receipts():
    root = Path(os.environ["SEC_SOURCE_HEADER_EVIDENCE"])
    manifest = json.loads((root / "manifest-v8-final.json").read_bytes())
    assert manifest["processing_version"] == 8 and len(manifest["documents"]) == 20
    for entry in manifest["documents"]:
        assert hashlib.sha256(Path(entry["path"]).read_bytes()).hexdigest() == entry["sha256"]
    comparisons = json.loads((root / "comparison-v8-final.json").read_bytes())
    assert len(comparisons) == 20
    assert sum(r["baseline_period_misses"] for r in comparisons) == 169
    assert all(r["period_misses"] == 0 and not r["new_period_misses"] for r in comparisons)
    assert all(not r["table_changes"] and r["lexical_equal"] and r["numeric_equal"] for r in comparisons)
    assert all(not r["added_headings"] and not r["removed_headings"] for r in comparisons)
    results = json.loads((root / "structure-audit-v8-reviewed.json").read_bytes())
    assert len(results) == 20
    assert all(not r["after_missing"] and not r["new_missing"]
               and not r["missing_occurrences"] and not r["unapproved_extra_rows"]
               and not r["unique_occurrence_misses"] for r in results)
    inventory = json.loads((root / "complex-header-source-inventory-all.json").read_bytes())
    assert len(inventory) == 20 and sum(t["misses"] for t in inventory) == 169
    assert all(all(score == 1 for score in t["match_scores"]) for t in inventory)
