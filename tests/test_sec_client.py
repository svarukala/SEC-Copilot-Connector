"""Download cache integrity and failure propagation."""

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import pytest

from sec_connector.config import AppConfig
from sec_connector.models import DocumentInfo, FilingMetadata
from sec_connector.sec_client import SECClient


@pytest.fixture
def filing():
    return FilingMetadata(cik="123", accession_number="123-24-1", ticker="TEST",
                          company_name="Test", form="10-K", filing_date=datetime(2024, 1, 1))


async def test_failed_download_is_not_reported_as_partial_success(tmp_path, filing):
    client = SECClient(AppConfig())
    client.get_filing_documents = AsyncMock(return_value=[
        DocumentInfo(sequence=1, filename="filing.htm", document_type="10-K")
    ])
    client.download_document = AsyncMock(side_effect=OSError("offline"))
    with pytest.raises(OSError, match="offline"):
        await client.download_filing(filing, tmp_path)


async def test_download_validates_size_and_keeps_cache_atomic(tmp_path, filing):
    client = SECClient(AppConfig())
    doc = DocumentInfo(sequence=1, filename="filing.htm", document_type="10-K", size=5)
    directory = tmp_path / filing.cik / filing.accession_no_dashes
    directory.mkdir(parents=True)
    cached = directory / doc.filename
    cached.write_bytes(b"")
    client._get = AsyncMock(return_value=b"bad")
    with pytest.raises(ValueError, match="size"):
        await client.download_document(filing, doc, tmp_path)
    assert cached.read_bytes() == b""
    client._get.return_value = b"valid"
    assert await client.download_document(filing, doc, tmp_path) == cached
    assert cached.read_bytes() == b"valid"
    assert not list(directory.glob("*.part"))
    client._get.reset_mock()
    await client.download_document(filing, doc, tmp_path)
    client._get.assert_not_awaited()


async def test_refresh_retrieves_source_even_for_valid_cache(tmp_path, filing):
    client = SECClient(AppConfig())
    doc = DocumentInfo(sequence=1, filename="main.htm", document_type="10-K", size=5)
    client._get = AsyncMock(return_value=b"first")
    path = await client.download_document(filing, doc, tmp_path)
    client._get.return_value = b"fresh"
    assert await client.download_document(filing, doc, tmp_path, refresh=True) == path
    assert path.read_bytes() == b"fresh"
    assert client._get.await_count == 2
    client._get.return_value = b"bad"
    with pytest.raises(ValueError, match="size"):
        await client.download_document(filing, doc, tmp_path, refresh=True)
    assert path.read_bytes() == b"fresh"


@pytest.mark.parametrize("filename", [
    "../outside.htm", r"..\outside.htm", "/absolute.htm", r"C:\outside.htm",
    "file.htm:stream", "%2e%2e%2fsecret.htm", "CON.htm", "file.htm.", " file.htm",
])
async def test_unsafe_source_filenames_never_hit_network(tmp_path, filing, filename):
    client = SECClient(AppConfig())
    client._get = AsyncMock()
    with pytest.raises(ValueError, match="Unsafe"):
        await client.download_document(
            filing, DocumentInfo(sequence=1, filename=filename, document_type="10-K"), tmp_path)
    client._get.assert_not_awaited()


async def test_unsafe_filing_path_never_hits_network(tmp_path, filing):
    client = SECClient(AppConfig())
    client._get = AsyncMock()
    filing.cik = "../outside"
    with pytest.raises(ValueError, match="Unsafe"):
        await client.download_document(
            filing, DocumentInfo(sequence=1, filename="main.htm", document_type="10-K"), tmp_path)
    client._get.assert_not_awaited()


async def test_download_concurrency_is_bounded_and_failure_is_propagated(tmp_path, filing):
    client = SECClient(AppConfig(processing={"concurrent_downloads": 2}))
    docs = [DocumentInfo(sequence=i, filename=f"doc{i}.htm", document_type="EX-99") for i in range(1, 6)]
    client.get_filing_documents = AsyncMock(return_value=docs)
    active = 0
    high_water = 0

    async def download(filing, doc, directory):
        nonlocal active, high_water
        active += 1
        high_water = max(high_water, active)
        try:
            await asyncio.sleep(0)
            if doc.sequence == 3:
                raise OSError("one document failed")
            return directory / doc.filename
        finally:
            active -= 1

    client.download_document = download
    with pytest.raises(OSError, match="one document failed"):
        await client.download_filing(filing, tmp_path)
    assert high_water == 2
    assert active == 0


def response(status=200, headers=None):
    result = MagicMock()
    result.headers = headers or {}
    result.__aenter__ = AsyncMock(return_value=result)
    result.__aexit__ = AsyncMock(return_value=False)
    result.read = AsyncMock(return_value=b"payload")
    if status >= 400:
        result.raise_for_status.side_effect = aiohttp.ClientResponseError(
            MagicMock(real_url="https://www.sec.gov/mock"), (), status=status)
    return result


def network_client():
    client = SECClient(AppConfig(sec={"user_agent": "ResearchConnector contact@research.invalid"}))
    client._session = MagicMock()
    client.rate_limiter.acquire = AsyncMock()
    return client


@pytest.mark.parametrize("agent", ["", "   ", "Connector", "Connector your-email@example.com", "${SEC_USER_AGENT}"])
async def test_invalid_user_agent_rejected_before_network(agent):
    client = SECClient(AppConfig(sec={"user_agent": agent}))
    client._session = MagicMock()
    with pytest.raises(ValueError, match="SEC_USER_AGENT"):
        await client._get("https://www.sec.gov/mock")
    client._session.get.assert_not_called()


@pytest.mark.parametrize("status", [403, 404])
async def test_permanent_errors_are_not_retried(status, monkeypatch):
    client = network_client()
    client._session.get.return_value = response(status)
    sleep = AsyncMock()
    monkeypatch.setattr("sec_connector.sec_client.asyncio.sleep", sleep)
    with pytest.raises(aiohttp.ClientResponseError):
        await client._get("https://www.sec.gov/mock")
    assert client._session.get.call_count == 1
    sleep.assert_not_awaited()


async def test_transient_attempts_each_acquire_token_and_honor_retry_after(monkeypatch):
    client = network_client()
    client._session.get.side_effect = [
        response(429, {"Retry-After": "12"}), response(503), response()]
    sleep = AsyncMock()
    monkeypatch.setattr("sec_connector.sec_client.asyncio.sleep", sleep)
    assert await client._get("https://www.sec.gov/mock") == b"payload"
    assert client.rate_limiter.acquire.await_count == 3
    assert [call.args[0] for call in sleep.await_args_list] == [12, 8]
    assert isinstance(client._session.get.call_args.kwargs["timeout"], aiohttp.ClientTimeout)


async def test_http_date_retry_after_is_honored(monkeypatch):
    client = network_client()
    later = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=30))
    client._session.get.side_effect = [response(429, {"Retry-After": later}), response()]
    sleep = AsyncMock()
    monkeypatch.setattr("sec_connector.sec_client.asyncio.sleep", sleep)
    await client._get("https://www.sec.gov/mock")
    assert 28 <= sleep.await_args.args[0] <= 30


@pytest.mark.parametrize("error", [aiohttp.ClientConnectionError(), asyncio.TimeoutError()])
async def test_connections_and_timeouts_retry_with_pacing(error, monkeypatch):
    client = network_client()
    client._session.get.side_effect = [error, response()]
    monkeypatch.setattr("sec_connector.sec_client.asyncio.sleep", AsyncMock())
    assert await client._get("https://www.sec.gov/mock") == b"payload"
    assert client.rate_limiter.acquire.await_count == 2


async def test_transient_errors_stop_after_five_attempts(monkeypatch):
    client = network_client()
    client._session.get.return_value = response(500)
    sleep = AsyncMock()
    monkeypatch.setattr("sec_connector.sec_client.asyncio.sleep", sleep)
    with pytest.raises(aiohttp.ClientResponseError):
        await client._get("https://www.sec.gov/mock")
    assert client.rate_limiter.acquire.await_count == 5
    assert sleep.await_count == 4
