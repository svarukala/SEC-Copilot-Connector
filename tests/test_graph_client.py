"""Graph transport and provisioning regressions; no network or credentials."""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import aiohttp
import pytest

from sec_connector import graph_client
from sec_connector.config import GRAPH_MAX_ITEM_BYTES, AppConfig
from sec_connector.graph_client import GRAPH_BASE_URL, GraphClient
from sec_connector.models import ContentChunk, DocumentInfo, FilingMetadata


OPERATION = f"{GRAPH_BASE_URL}/external/connections/test/operations/schema-op"


def test_constructing_client_for_offline_payloads_does_not_authenticate(monkeypatch):
    factory = Mock(side_effect=AssertionError("Offline payload building must not authenticate"))
    monkeypatch.setattr(graph_client, "ConfidentialClientApplication", factory)
    GraphClient(AppConfig())
    factory.assert_not_called()


async def test_concurrent_requests_share_one_token_acquisition(monkeypatch):
    app = Mock()
    app.acquire_token_for_client.return_value = {"access_token": "unit-test-token", "expires_in": 3600}
    factory = Mock(return_value=app)
    monkeypatch.setattr(graph_client, "ConfidentialClientApplication", factory)
    client = GraphClient(AppConfig())
    assert await asyncio.gather(*(client._get_token() for _ in range(5))) == ["unit-test-token"] * 5
    factory.assert_called_once()
    app.acquire_token_for_client.assert_called_once()


class Response:
    def __init__(self, status=200, data=None, headers=None):
        self.status = status
        self.headers = headers or {}
        self.body = json.dumps(data).encode("utf-8") if data is not None else b""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return None

    async def read(self):
        return self.body

    def raise_for_status(self):
        if self.status >= 400:
            raise aiohttp.ClientResponseError(
                SimpleNamespace(real_url=OPERATION), (), status=self.status, message="test error"
            )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(graph_client, "ConfidentialClientApplication", Mock())
    config = SimpleNamespace(
        azure=SimpleNamespace(
            tenant_id="unused", client_id="unused", client_secret="unused",
            connection_id="test", connection_name="Test", connection_description="Test",
            icon_url="https://www.sec.gov/favicon.ico",
        ),
        chunking=SimpleNamespace(max_item_bytes=GRAPH_MAX_ITEM_BYTES),
    )
    result = GraphClient(config)
    result._get_token = AsyncMock(return_value="test-token")
    result._session = SimpleNamespace(request=Mock())
    return result


@pytest.fixture
def clock(monkeypatch):
    now = [0.0]
    monkeypatch.setattr(graph_client, "time", SimpleNamespace(monotonic=lambda: now[0], time=lambda: 0))

    async def sleep(delay):
        now[0] += delay

    sleeper = AsyncMock(side_effect=sleep)
    monkeypatch.setattr(graph_client.asyncio, "sleep", sleeper)
    return now, sleeper


async def test_empty_202_patches_once_and_follows_location(client, clock):
    client._session.request.side_effect = [
        Response(202, headers={"Location": OPERATION}),
        Response(data={"status": "inprogress"}, headers={"Retry-After": "7"}),
        Response(data={"status": "completed"}),
    ]
    assert await client.register_schema() == {}
    assert await client.wait_for_schema()
    calls = client._session.request.call_args_list
    assert [call.args[0] for call in calls] == ["PATCH", "GET", "GET"]
    assert calls[0].args[1] == f"{GRAPH_BASE_URL}/external/connections/test/schema"
    assert calls[0].kwargs["json"] == client.load_desired_schema()
    assert calls[0].kwargs["headers"]["Prefer"] == "include-unknown-enum-members"
    assert calls[1].args[1] == calls[2].args[1] == OPERATION
    clock[1].assert_awaited_once_with(7)


async def test_relative_operation_location(client):
    client._session.request.side_effect = [
        Response(202, headers={"Location": "/v1.0/external/connections/test/operations/schema-op"}),
        Response(data={"status": "completed"}),
    ]
    await client.register_schema()
    assert await client.wait_for_schema()
    assert client._session.request.call_args.args[1] == OPERATION


async def test_accepted_schema_requires_location(client):
    client._session.request.return_value = Response(202)
    with pytest.raises(RuntimeError, match="without an operation Location"):
        await client.register_schema()
    assert client._session.request.call_count == 1


async def test_failed_operation_reports_error(client):
    client._schema_operation_url = OPERATION
    client._session.request.return_value = Response(
        data={"status": "failed", "error": {"code": "InvalidSchema", "message": "bad property"}}
    )
    with pytest.raises(RuntimeError, match="InvalidSchema"):
        await client.wait_for_schema()


async def test_schema_properties_do_not_mean_operation_success(client, clock):
    client._schema_operation_url = OPERATION
    client._session.request.return_value = Response(data={"properties": [{"name": "Title"}]})
    assert not await client.wait_for_schema(timeout=12)
    assert clock[0][0] == 12
    assert [call.args[0] for call in clock[1].await_args_list] == [10, 2]
    assert client._session.request.call_count == 2


async def test_default_schema_deadline_is_fifteen_minutes(client, clock):
    client._schema_operation_url = OPERATION
    client._session.request.return_value = Response(
        data={"status": "inprogress"}, headers={"Retry-After": "901"}
    )
    assert not await client.wait_for_schema()
    assert clock[0][0] == 900


async def test_poll_request_itself_is_bounded_by_deadline(client):
    client._schema_operation_url = OPERATION

    async def blocked(*args, **kwargs):
        await asyncio.Event().wait()

    client._request_result = blocked
    assert not await client.wait_for_schema(timeout=0.001)


async def test_wait_requires_operation_not_existing_schema(client):
    with pytest.raises(RuntimeError, match="No schema operation"):
        await client.wait_for_schema()
    client._session.request.assert_not_called()


async def test_non_graph_success_status_does_not_complete_operation(client, clock):
    client._schema_operation_url = OPERATION
    client._session.request.return_value = Response(data={"status": "succeeded"})
    assert not await client.wait_for_schema(timeout=1)


@pytest.mark.parametrize("change", ["type", "flag", "label", "missing", "baseType"])
def test_existing_differing_schema_is_not_compatible(client, change):
    desired = client.load_desired_schema()
    remote = deepcopy(desired)
    if change == "type":
        remote["properties"][0]["type"] = "Int64"
    elif change == "flag":
        remote["properties"][0]["isQueryable"] = False
    elif change == "label":
        remote["properties"][0]["labels"] = []
    elif change == "missing":
        remote["properties"].pop()
    else:
        remote["baseType"] = "different"
    assert not client.schemas_compatible(remote, desired)


def test_compatible_schema_ignores_order_metadata_and_extra_properties(client):
    desired = client.load_desired_schema()
    remote = deepcopy(desired)
    remote["@odata.context"] = "ignored"
    remote["properties"].reverse()
    for prop in remote["properties"]:
        prop["type"] = prop["type"].lower()
        prop.setdefault("isRefinable", False)
    remote["properties"].append({"name": "Additional", "type": "string"})
    assert client.schemas_compatible(remote, desired)


def test_setup_helper_interfaces(client):
    assert client.load_schema() == client.load_desired_schema()
    assert client.schema_matches(client.load_schema(), client.load_schema())


@pytest.mark.parametrize("status", [400, 401, 403, 404, 409])
async def test_permanent_errors_do_not_retry(client, clock, status):
    client._session.request.return_value = Response(status)
    with pytest.raises(aiohttp.ClientResponseError) as error:
        await client.get_schema_status()
    assert error.value.status == status
    assert client._session.request.call_count == 1
    clock[1].assert_not_awaited()


async def test_registration_conflict_is_not_swallowed(client, clock):
    client._session.request.return_value = Response(409)
    with pytest.raises(aiohttp.ClientResponseError):
        await client.register_schema()
    assert client._session.request.call_count == 1
    clock[1].assert_not_awaited()


@pytest.mark.parametrize("status", [429, 500, 503])
async def test_retry_after_sleeps_once_without_extra_backoff(client, clock, status):
    client._session.request.side_effect = [
        Response(status, headers={"Retry-After": "3"}), Response(data={"id": "test"}),
    ]
    assert await client.get_connection() == {"id": "test"}
    clock[1].assert_awaited_once_with(3)
    assert client._session.request.call_count == 2


async def test_retry_after_http_date(client, clock):
    client._session.request.side_effect = [
        Response(429, headers={"Retry-After": "Thu, 01 Jan 1970 00:00:08 GMT"}),
        Response(data={}),
    ]
    await client.get_connection()
    clock[1].assert_awaited_once_with(8)


@pytest.mark.parametrize("error", [aiohttp.ClientConnectionError("reset"), asyncio.TimeoutError()])
async def test_transport_errors_retry(client, clock, error):
    client._session.request.side_effect = [error, Response(data={"id": "test"})]
    assert await client.get_connection() == {"id": "test"}
    clock[1].assert_awaited_once_with(4)


async def test_transient_retries_are_bounded(client, clock):
    client._session.request.return_value = Response(503, headers={"Retry-After": "1"})
    with pytest.raises(aiohttp.ClientResponseError):
        await client.get_connection()
    assert client._session.request.call_count == 5
    assert clock[1].await_count == 4


async def test_configured_body_limit_checked_before_transport(client):
    client.config.chunking.max_item_bytes = 40
    with pytest.raises(ValueError, match="request body"):
        await client.upload_payload("item", {"properties": {"Title": "x" * 40}, "content": {}})
    client._session.request.assert_not_called()
    client._get_token.assert_not_awaited()


async def test_absolute_service_body_limit_cannot_be_overridden(client):
    client.config.chunking.max_item_bytes = GRAPH_MAX_ITEM_BYTES * 2
    with pytest.raises(ValueError, match=f"limit is {GRAPH_MAX_ITEM_BYTES} bytes"):
        await client.upload_payload("item", {"content": {"value": "x" * GRAPH_MAX_ITEM_BYTES}})
    client._session.request.assert_not_called()


async def test_measured_utf8_bytes_are_sent_and_replay_id_is_stripped(client):
    payload = {"id": "old-id", "properties": {"Title": 'é中"\\\n'}, "content": {"value": "🙂"}, "acl": []}
    expected = json.dumps(
        {key: value for key, value in payload.items() if key != "id"},
        ensure_ascii=False, separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    client.config.chunking.max_item_bytes = len(expected)
    client._session.request.return_value = Response(204)
    assert await client.upload_payload("replay-id", payload) == {}
    call = client._session.request.call_args
    assert call.args == ("PUT", f"{GRAPH_BASE_URL}/external/connections/test/items/replay-id")
    assert call.kwargs["data"] == expected
    assert "json" not in call.kwargs
    assert "id" not in json.loads(call.kwargs["data"])
    assert payload["id"] == "old-id"
    client.config.chunking.max_item_bytes -= 1
    with pytest.raises(ValueError):
        await client.upload_payload("replay-id", payload)
    assert client._session.request.call_count == 1


async def test_upload_item_delegates_to_replay(client):
    chunk = SimpleNamespace(graph_item_id="chunk-id")
    client.build_payload = Mock(return_value={"id": "chunk-id", "content": {}})
    client.upload_payload = AsyncMock(return_value={"id": "chunk-id"})
    assert await client.upload_item(chunk) == {"id": "chunk-id"}
    client.upload_payload.assert_awaited_once_with("chunk-id", client.build_payload.return_value)


@pytest.mark.parametrize("filing_date", [
    datetime(2025, 1, 1),
    datetime(2025, 1, 1, 2, tzinfo=timezone(timedelta(hours=2))),
])
def test_filing_date_serializes_as_utc(client, filing_date):
    filing = FilingMetadata(
        filing_date=filing_date, company_name="Example", ticker="EX", form="10-K",
        cik="123", accession_number="123-25-1", primary_document="primary.htm",
    )
    chunk = ContentChunk(
        filing=filing, title="Title",
        document=DocumentInfo(sequence=1, filename="primary.htm", document_type="10-K"),
        page_number=1, content="Text", chunk_id="chunk-id",
    )
    assert client.build_payload(chunk)["properties"]["FilingDate"] == "2025-01-01T00:00:00Z"


def test_updated_schema_and_document_metadata_align(client):
    filing = FilingMetadata(
        cik="123", accession_number="0000000123-25-000001", ticker="EX", company_name="Example",
        form="10-K/A", filing_date=datetime(2025, 1, 1), primary_document="primary.htm",
        report_period_end=datetime(2024, 12, 31),
        acceptance_datetime=datetime(2025, 1, 1, 12, tzinfo=timezone.utc),
    )
    chunk = ContentChunk(
        filing=filing, document=DocumentInfo(sequence=2, filename="exhibit.htm", document_type="EX-99"),
        page_number=1, chunk_ordinal=3, section_title="Results", content="facts",
        title="Example report", chunk_id="test",
    )
    properties = client.build_payload(chunk)["properties"]
    schema = client.load_schema()["properties"]
    assert properties.keys() <= {prop["name"] for prop in schema}
    assert properties["Url"].endswith("/exhibit.htm")
    assert properties["FilingUrl"].endswith("-index.html")
    assert properties["IsAmendment"] is True
    assert properties["ChunkOrdinal"] == 3
    labels = {label for prop in schema for label in prop.get("labels", [])}
    assert {"title", "url", "iconUrl", "fileName", "fileExtension"} <= labels
    assert not any(prop.get("isSearchable") and prop.get("isRefinable") for prop in schema)


async def test_operation_location_cannot_send_token_to_another_host(client):
    client._schema_operation_url = "https://example.invalid/operation"
    with pytest.raises(ValueError, match="Microsoft Graph HTTPS origin"):
        await client.wait_for_schema()
    client._session.request.assert_not_called()
