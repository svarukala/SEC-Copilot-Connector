"""Offline coverage of SEC submissions and authoritative document inventories."""

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from sec_connector.config import AppConfig
from sec_connector.models import FilingMetadata
from sec_connector.sec_client import SECClient


def batch(*rows):
    keys = ("accessionNumber", "form", "filingDate", "primaryDocument")
    return {key: [row[i] for row in rows] for i, key in enumerate(keys)}


def client_with_batches(recent, history=None, **options):
    client = SECClient(AppConfig(filings=options))
    client._ticker_to_cik = {"TEST": "0000000123"}
    inventory = {"recent": recent, "files": [{"name": "CIK123-history.json"}] if history else []}
    client._get_json = AsyncMock(side_effect=[{"name": "Test Company", "filings": inventory}, history])
    return client


async def test_history_date_coverage_amendments_dedupe_and_sorted_limit():
    recent = batch(
        ("123-24-3", "10-K", "2024-03-01", "main.htm"),
        ("123-24-2", "10-K/A", "2024-02-01", "amended.htm"),
    )
    history = batch(
        ("123-24-2", "10-K/A", "2024-02-01", "amended.htm"),
        ("123-24-4", "10-K", "2024-04-01", "main.htm"),
        ("123-23-1", "10-K", "2023-01-01", "main.htm"),
        ("123-24-1", "8-K", "2024-01-01", "main.htm"),
    )
    client = client_with_batches(recent, history, start_date=date(2024, 1, 1),
                                 end_date=date(2024, 3, 1))
    filings = await client.get_filings("test", forms=["10-K"], max_filings=10)
    assert [f.accession_number for f in filings] == ["123-24-3", "123-24-2"]
    assert filings[1].is_amendment
    assert client._get_json.await_args_list[1].args[0].endswith("/submissions/CIK123-history.json")
    client = client_with_batches(recent, history)
    assert [f.accession_number for f in await client.get_filings("TEST", max_filings=1)] == ["123-24-4"]


async def test_history_and_amendments_can_be_disabled():
    recent = batch(("123-24-2", "10-K/A", "2024-02-01", "a.htm"),
                   ("123-24-1", "10-K", "2024-01-01", "main.htm"))
    client = client_with_batches(recent, {"unused": []}, include_history=False, include_amendments=False)
    filings = await client.get_filings("TEST", forms=["10-K/A"])
    assert [f.form for f in filings] == ["10-K"]
    assert client._get_json.await_count == 1


async def test_zero_limit_and_empty_forms_are_bounded():
    client = client_with_batches(batch(("123-24-1", "10-K", "2024-01-01", "main.htm")))
    assert await client.get_filings("TEST", max_filings=0) == []
    client._get_json.assert_not_awaited()
    with pytest.raises(ValueError, match="negative"):
        await client.get_filings("TEST", max_filings=-1)
    assert await client.get_filings("TEST", forms=[]) == []


@pytest.mark.parametrize("column,value", [
    ("form", []), ("primaryDocument", None), ("acceptanceDateTime", []),
])
async def test_malformed_arrays_fail_instead_of_silent_truncation(column, value):
    recent = batch(("123-24-1", "10-K", "2024-01-01", "main.htm"))
    recent[column] = value
    with pytest.raises(ValueError, match="arrays"):
        await client_with_batches(recent).get_filings("TEST")


async def test_historical_malformed_arrays_are_not_hidden_by_max_limit():
    recent = batch(("123-24-1", "10-K", "2024-01-01", "main.htm"))
    with pytest.raises(ValueError, match="arrays"):
        await client_with_batches(recent, {"accessionNumber": ["123-23-1"]}).get_filings("TEST", max_filings=1)


@pytest.mark.parametrize("accepted,offset", [
    ("2024-01-01T16:10:00", timedelta(hours=-5)),
    ("2024-07-01T16:10:00", timedelta(hours=-4)),
    ("2024-07-01T20:10:00Z", timedelta(0)),
    ("2024-07-01T16:10:00-04:00", timedelta(hours=-4)),
])
async def test_report_period_and_acceptance_timezone(accepted, offset):
    recent = batch(("123-24-1", "10-K", "2024-01-01", "main.htm"))
    recent.update(reportDate=["2023-12-31"], acceptanceDateTime=[accepted], fileNumber=["001-123"])
    filing = (await client_with_batches(recent).get_filings("TEST"))[0]
    assert filing.report_period_end == datetime(2023, 12, 31)
    assert filing.acceptance_datetime.utcoffset() == offset
    assert filing.file_number == "001-123"


@pytest.fixture
def filing():
    return FilingMetadata(cik="0000000123", accession_number="123-24-1", ticker="TEST",
                          company_name="Test", form="10-K", filing_date=datetime(2024, 1, 1),
                          primary_document="main.htm")


def document_row(sequence, filename, doc_type, href=None):
    return (
        f'<tr><td>{sequence}</td><td>{doc_type} description</td>'
        f'<td><a href="{href or filename}">{filename}</a></td><td>{doc_type}</td><td>5</td></tr>'
    )


def detail(*rows):
    return ('<table summary="Document Format Files"><tr><th>Seq</th><th>Description</th>'
            '<th>Document</th><th>Type</th><th>Size</th></tr>' + "".join(rows) + "</table>").encode()


async def test_authoritative_primary_exhibits_sequences_and_duplicate_exclusion(filing, caplog):
    client = SECClient(AppConfig())
    primary = document_row(7, "main.htm", "10-K", "/ix?doc=/Archives/edgar/data/123/123241/main.htm")
    client._get = AsyncMock(return_value=detail(
        document_row("", "123-24-1.txt", ""), primary, primary,
        document_row(8, "press.htm", "EX-99.1"), document_row(9, "agreement.txt", "EX-10.2"),
        document_row(10, "logo.jpg", "GRAPHIC"), document_row(11, "exhibit.pdf", "EX-99.2"),
        document_row(12, "index.htm", ""), document_row(13, "other.htm", "EX-101"),
        document_row(14, "navigation.htm", "", "https://www.sec.gov/"),
        document_row(15, "123-24-1.txt", "EX-99"),
    ) + b'<table summary="Data Files">' + document_row(30, "data.htm", "EX-99").encode() + b"</table>")
    documents = await client.get_filing_documents(filing)
    assert [(d.sequence, d.filename, d.document_type) for d in documents] == [
        (7, "main.htm", "10-K"), (8, "press.htm", "EX-99.1"), (9, "agreement.txt", "EX-10.2")]
    assert documents[0].size == 5
    assert "unsupported binary" in caplog.text
    assert client._get.await_args.args[0].endswith("/123241/123-24-1-index.html")


async def test_exhibits_can_be_disabled(filing):
    client = SECClient(AppConfig(filings={"include_exhibits": False}))
    client._get = AsyncMock(return_value=detail(
        document_row(3, "main.htm", "10-K"), document_row(4, "press.htm", "EX-99.1")))
    assert [d.filename for d in await client.get_filing_documents(filing)] == ["main.htm"]


async def test_explicit_exhibit_allowlist_does_not_match_other_families(filing):
    client = SECClient(AppConfig(filings={"exhibit_types": ["EX-21"]}))
    client._get = AsyncMock(return_value=detail(
        document_row(1, "main.htm", "10-K"), document_row(2, "subs.htm", "EX-21.1"),
        document_row(3, "press.htm", "EX-99.1"), document_row(4, "wrong.htm", "EX-210")))
    assert [d.filename for d in await client.get_filing_documents(filing)] == ["main.htm", "subs.htm"]


async def test_conflicting_real_sequences_fail_inventory(filing):
    client = SECClient(AppConfig())
    client._get = AsyncMock(return_value=detail(
        document_row(1, "main.htm", "10-K"), document_row(1, "press.htm", "EX-99")))
    with pytest.raises(ValueError, match="Duplicate SEC document sequence"):
        await client.get_filing_documents(filing)


async def test_empty_required_arrays_are_valid_but_missing_arrays_are_not():
    assert await client_with_batches(batch()).get_filings("TEST") == []
    with pytest.raises(ValueError, match="required columns missing"):
        await client_with_batches({}).get_filings("TEST")


async def test_missing_primary_is_not_fabricated(filing):
    client = SECClient(AppConfig())
    client._get = AsyncMock(return_value=detail(document_row(3, "press.htm", "EX-99.1")))
    with pytest.raises(ValueError, match="primary document missing"):
        await client.get_filing_documents(filing)


@pytest.mark.parametrize("href", [
    "../main.htm", "https://evil.invalid/main.htm",
    "/Archives/edgar/data/999/123241/main.htm",
    "/Archives/edgar/data/123/123241/%2e%2e%5coutside.htm",
])
async def test_document_links_cannot_escape_the_filing(filing, href):
    client = SECClient(AppConfig())
    client._get = AsyncMock(return_value=detail(document_row(1, "main.htm", "10-K", href)))
    with pytest.raises(ValueError):
        await client.get_filing_documents(filing)
