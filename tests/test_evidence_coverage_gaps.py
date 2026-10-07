"""Synthetic non-bank/legacy/amendment controls; not real issuer coverage."""

from datetime import datetime

import pytest

from sec_connector.chunker import chunk_document
from sec_connector.config import AppConfig, ChunkingConfig
from sec_connector.graph_client import GraphClient
from sec_connector.models import DocumentInfo, FilingMetadata
from sec_connector.parser import parse_document
from sec_connector.payloads import serialize_item
from tests.corpus_replay import subsequence, tokens


def process(tmp_path, source, *, form="10-K", accession="0000000001-25-000001", extension="htm"):
    path = tmp_path / f"synthetic.{extension}"
    path.write_text(source, encoding="utf-8")
    parsed = parse_document(
        path,
        FilingMetadata(
            cik="0000000001", accession_number=accession, company_name="Synthetic Manufacturer",
            ticker="SYN", form=form, filing_date=datetime(2025, 3, 1),
            report_period_end=datetime(2024, 12, 31),
        ),
        DocumentInfo(sequence=1, filename=path.name, document_type=form),
    )
    assert parsed is not None
    config = ChunkingConfig(target_size=350, max_size=800, overlap=0)
    chunks = chunk_document(parsed, config)
    assert subsequence(tokens(parsed.content), tokens("\n".join(c.content for c in chunks)))["ok"]
    graph = GraphClient(AppConfig())
    payloads = [graph.build_payload(c) for c in chunks]
    assert len({p["id"] for p in payloads}) == len(payloads)
    assert all(len(p["content"]["value"]) <= config.max_size for p in payloads)
    assert all(len(serialize_item(p)) <= config.max_item_bytes for p in payloads)
    return parsed, chunks, payloads


@pytest.mark.parametrize("form", ["10-K/A", "10-Q/A", "8-K/A", "DEF 14A/A"])
def test_amendment_keeps_distinct_evidence_and_fiscal_metadata(tmp_path, form):
    original_form = form.removesuffix("/A")
    original = process(tmp_path, "<h2>Inventory</h2><p>Inventory was 120 million.</p>", form=original_form)[2]
    amended = process(
        tmp_path, "<h2>Amendment</h2><p>Restated inventory was 115 million, not 120 million.</p>",
        form=form, accession="0000000001-25-000002",
    )[2]
    assert {p["id"] for p in original}.isdisjoint(p["id"] for p in amended)
    assert all(p["properties"]["IsAmendment"] for p in amended)
    assert not any(p["properties"]["IsAmendment"] for p in original)
    assert all(("ReportPeriodEnd" in p["properties"]) == (original_form in {"10-K", "10-Q"}) for p in amended)
    assert "115" not in original[0]["content"]["value"]
    assert "115" in amended[0]["content"]["value"]


def test_legacy_text_pages_preserve_non_bank_units_and_negative_values(tmp_path):
    _, chunks, _ = process(
        tmp_path,
        "MANUFACTURING OPERATIONS\nUnits in thousands\nWidgets shipped: 120\n"
        "<PAGE>\nINVENTORY\nObsolete inventory adjustment: (15)\n",
        extension="txt",
    )
    assert len(chunks) == 2
    assert "Units in thousands" in chunks[0].content
    assert "(15)" in chunks[1].content


def test_non_bank_multi_level_headers_keep_equal_values_in_independent_columns(tmp_path):
    source = (
        "<h2>Manufacturing segments</h2><table>"
        "<tr><th rowspan='2'>Units in thousands</th><th colspan='2'>2024</th>"
        "<th colspan='2'>2023</th></tr><tr><th>Domestic</th><th>Export</th>"
        "<th>Domestic</th><th>Export</th></tr>"
        + "".join(f"<tr><td>Product {i}</td><td>120</td><td>120</td><td>90</td><td>(15)</td></tr>" for i in range(20))
        + "</table>"
    )
    _, chunks, _ = process(tmp_path, source)
    assert len(chunks) > 1
    for chunk in (c for c in chunks if "| Product " in c.content):
        assert "2024 / Domestic" in chunk.content and "2023 / Export" in chunk.content
    assert sum("| 120 | 120 | 90 | (15) |" in line for c in chunks for line in c.content.splitlines()) == 20


def note_source(kind):
    marker = "*" if kind == "symbol" else "(a)"
    separator = "<PAGE>" if kind == "cross-page" else (
        "<p>A separate narrative intervenes.</p>" if kind == "separated" else ""
    )
    return (
        "<h2>Inventory</h2><table><tr><th>Metric</th><th>2024</th></tr>"
        + "".join(f"<tr><td>Product {i} {marker}</td><td>120</td></tr>" for i in range(28))
        + f"</table>{separator}<p>{marker} Net of obsolete inventory.</p>"
    )


@pytest.mark.parametrize("kind", ["symbol", "cross-page", "separated"])
def test_gap_sources_retain_rows_and_note_in_document_order(tmp_path, kind):
    parsed, chunks, _ = process(tmp_path, note_source(kind))
    assert "Net of obsolete inventory." in parsed.content
    assert sum(f"| Product {i} " in c.content for c in chunks for i in range(28)) == 28
    assert any("Net of obsolete inventory." in c.content for c in chunks)


@pytest.mark.parametrize("kind", ["symbol", "cross-page", "separated"])
def test_desired_marked_rows_are_self_contained(tmp_path, kind):
    _, chunks, _ = process(tmp_path, note_source(kind))
    assert all("Net of obsolete inventory." in c.content for c in chunks if "| Product " in c.content)
