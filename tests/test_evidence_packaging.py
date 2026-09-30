"""Synthetic evidence packaging regression; no issuer text or live services."""

from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import socket

import pytest

from sec_connector.chunker import chunk_document
from sec_connector.config import AppConfig, ChunkingConfig
from sec_connector.graph_client import GraphClient
from sec_connector.models import DocumentInfo, FilingMetadata, ParsedDocument
from sec_connector.parser import html_to_markdown, parse_document
from sec_connector.payloads import serialize_item


def _filing(form="DEF 14A"):
    return FilingMetadata(
        cik="0000000123", accession_number="0000000123-25-000001",
        company_name="Synthetic Example Co.", ticker="SYN", form=form,
        filing_date=datetime(2025, 3, 1), report_period_end=datetime(2025, 4, 20),
    )


def test_pay_disclosure_keeps_source_year_values_ratio_and_section_together():
    def bullet(text):
        return (
            "<table><tr><td>&#8718;</td><td>&nbsp;</td>"
            f"<td><p>{text}</p></td></tr></table>"
        )

    source = (
        "<h2>Equity awards</h2><p>Neighboring equity disclosure.</p><PAGE>"
        '<p><span style="color:orange"><span style="font-weight:bold">'
        "Executive pay ratio</span></span></p>"
        "<p>For the year ended December 31, 2024:</p>"
        + bullet("Annual CEO compensation was $13,500,000.")
        + bullet("Annual median employee compensation was $90,000.")
        + bullet("The reported ratio was 150 to 1.")
        + "<p>Methodology uses the same employee population.</p>"
        "<table><tr><td>[1]</td><td>Excluded employees are described here.</td></tr></table>"
        "<PAGE><h2>Audit fees</h2><p>Unrelated audit disclosure.</p>"
    )
    config = ChunkingConfig()
    parsed = ParsedDocument(
        filing=_filing(), document=DocumentInfo(sequence=1, filename="proxy.htm", document_type="DEF 14A"),
        content=html_to_markdown(source),
    )
    chunks = chunk_document(parsed, config)
    assert [c.section_title for c in chunks] == ["Equity awards", "Executive pay ratio", "Audit fees"]
    target = chunks[1]
    for fact in ("December 31, 2024", "$13,500,000", "$90,000", "150 to 1", "Methodology", "Excluded"):
        assert fact in target.content
    assert "Equity awards" not in target.content
    assert "Audit fees" not in target.content
    assert "Report period" not in target.content
    graph = GraphClient(AppConfig())
    for chunk in chunks:
        payload = graph.build_payload(chunk)
        assert "ReportPeriodEnd" not in payload["properties"]
        assert payload["properties"]["FilingDate"] == "2025-03-01T00:00:00Z"
        assert len(chunk.content) <= config.max_size
        assert len(serialize_item(payload)) <= config.max_item_bytes


@pytest.mark.parametrize("form, fiscal", [
    ("DEF 14A", False), ("DEF 14A/A", False), ("PRE 14A", False),
    ("8-K", False), ("8-K/A", False), ("10-K", True), ("10-Q", True),
    ("10-K/A", True), ("10-Q/A", True),
])
def test_raw_sec_date_is_not_implicitly_a_fiscal_period(form, fiscal):
    filing = _filing(form)
    # Applies to metadata restored from historical manifests as well as discovery.
    filing = FilingMetadata.model_validate_json(filing.model_dump_json())
    assert filing.report_period_end == datetime(2025, 4, 20)
    expected = filing.report_period_end if fiscal else None
    assert filing.fiscal_report_period_end == expected
    parsed = ParsedDocument(
        filing=filing, document=DocumentInfo(sequence=1, filename="document.htm", document_type=form),
        content="Source text states its own reporting year: 2024.",
    )
    chunk = chunk_document(parsed, ChunkingConfig())[0]
    assert ("Report period: 2025-04-20" in chunk.content) == fiscal
    payload = GraphClient(AppConfig()).build_payload(chunk)
    assert ("ReportPeriodEnd" in payload["properties"]) == fiscal
    assert "2024" in payload["content"]["value"]


@pytest.mark.skipif(
    not os.environ.get("SEC_EVIDENCE_PILOT_SOURCE"),
    reason="Exact cached source is private/local; set SEC_EVIDENCE_PILOT_SOURCE for offline replay",
)
def test_exact_cached_pilot_source_offline(monkeypatch):
    def no_network(*args, **kwargs):
        raise AssertionError("Pilot regression must remain offline")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    source = Path(os.environ["SEC_EVIDENCE_PILOT_SOURCE"])
    assert source.name == "d62941ddef14a.htm"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == (
        "6b370b9316b08382d62d88c7b8286d9bee1ea4dd89633237a74d211f501b4931"
    )
    filing = FilingMetadata(
        cik="0000713676", accession_number="0001193125-26-102189",
        company_name="PNC FINANCIAL SERVICES GROUP, INC.", ticker="PNC",
        form="DEF 14A", filing_date=datetime(2026, 3, 11),
        primary_document=source.name, report_period_end=datetime(2026, 4, 22),
    )
    document = DocumentInfo(sequence=1, filename=source.name, document_type="DEF 14A")
    parsed = parse_document(source, filing, document)
    assert parsed is not None
    config = ChunkingConfig()
    chunks = chunk_document(parsed, config)
    evidence = [chunk for chunk in chunks if "226 to 1" in chunk.content]
    assert len(evidence) == 1
    target = evidence[0]
    assert target.section_title == "CEO pay ratio"
    text = " ".join(target.content.split())
    for fact in (
        "### CEO pay ratio", "year ended December 31, 2025",
        "$29,530,103", "$130,900", "226 to 1", "methodology", "| 110 |",
        "health care premium contributions", "56,088", "178",
    ):
        assert fact in text
    assert "MNPI" not in text and "Report period" not in text
    assert target.page_number == 119  # Source segment, NOT the printed page label.
    assert len(chunks) == len({chunk.graph_item_id for chunk in chunks})
    graph = GraphClient(AppConfig())
    for chunk in chunks:
        payload = graph.build_payload(chunk)
        assert "ReportPeriodEnd" not in payload["properties"]
        assert len(chunk.content) <= config.max_size
        assert len(serialize_item(payload)) <= config.max_item_bytes

    # Every lexical source token survives in order; context/header repetition
    # may add tokens but cannot substitute for omitted source text.
    source_tokens = re.findall(r"\w+", parsed.content.replace("---PAGE---", ""))
    delivered = iter(re.findall(r"\w+", "\n".join(chunk.content for chunk in chunks)))
    assert all(any(candidate == token for candidate in delivered) for token in source_tokens)

    baseline = os.environ.get("SEC_EVIDENCE_PILOT_BASELINE")
    if baseline:
        old = Path(baseline)
        metadata = json.loads((old / "summary.json").read_text(encoding="utf-8"))
        assert metadata["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
        assert re.findall(r"\w+", (old / "parsed.md").read_text(encoding="utf-8")) == (
            re.findall(r"\w+", parsed.content)
        )
