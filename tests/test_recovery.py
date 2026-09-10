"""Offline regression tests for scoped state, completeness, and restart recovery."""

from contextlib import asynccontextmanager
from datetime import date, datetime
from unittest.mock import AsyncMock

import aiohttp
import pytest

from sec_connector.config import AppConfig
from sec_connector.graph_client import GraphClient
from sec_connector.models import DocumentInfo, FilingMetadata, FilingState
from sec_connector.pipeline import IngestionPipeline
from sec_connector.sec_client import SECClient
from sec_connector.state_manager import StateManager


@pytest.fixture
def config(tmp_path):
    return AppConfig(
        azure={"tenant_id": "tenant-a", "connection_id": "connection-a"},
        paths={
            "database": str(tmp_path / "state.db"), "downloads": str(tmp_path / "downloads"),
            "payloads": str(tmp_path / "payloads"), "logs": str(tmp_path / "logs"),
        },
    )


@pytest.fixture
def filing():
    return FilingMetadata(
        cik="0000320193", accession_number="0000320193-23-000077", ticker="AAPL",
        company_name="Apple", form="10-K", filing_date=datetime(2023, 11, 3),
        primary_document="primary.htm",
    )


@pytest.fixture
def clients(config, filing, tmp_path, monkeypatch):
    documents = [
        DocumentInfo(sequence=1, filename="primary.htm", document_type="10-K"),
        DocumentInfo(sequence=2, filename="exhibit.htm", document_type="EX-99"),
    ]
    paths = {}
    for document in documents:
        path = tmp_path / document.filename
        path.write_text("<p>" + ("Financial facts " * 100) + "</p>", encoding="utf-8")
        paths[document.filename] = path
    sec = SECClient(config)
    sec._ticker_to_cik = {"AAPL": filing.cik}
    sec.load_ticker_mapping = AsyncMock()
    sec.get_filings = AsyncMock(return_value=[filing])
    sec.get_filing_documents = AsyncMock(return_value=documents)

    async def download(_filing, document, _directory, refresh=False):
        return paths[document.filename]

    sec.download_document = AsyncMock(side_effect=download)
    graph = object.__new__(GraphClient)
    graph.config = config
    graph.upload_payload = AsyncMock()
    graph.delete_connection = AsyncMock()
    graph.delete_item = AsyncMock()

    @asynccontextmanager
    async def sec_context(_config):
        yield sec

    @asynccontextmanager
    async def graph_context(_config):
        yield graph
    graph_context.load_schema = GraphClient.load_schema

    monkeypatch.setattr("sec_connector.pipeline.SECClient", sec_context)
    monkeypatch.setattr("sec_connector.pipeline.GraphClient", graph_context)
    return sec, graph, documents, paths


def test_state_paths_are_destination_scoped(config):
    a = IngestionPipeline(config)
    config.azure.connection_id = "connection-b"
    b = IngestionPipeline(config)
    config.azure.tenant_id = "tenant-b"
    c = IngestionPipeline(config)
    assert len({a.db_path, b.db_path, c.db_path}) == 3


@pytest.mark.parametrize("bound,outside_date", [
    ("start_date", datetime(2018, 1, 1)),
    ("end_date", datetime(2024, 1, 1)),
])
async def test_resume_applies_inclusive_date_window_to_existing_queue(config, clients, filing, bound, outside_date):
    sec, graph, _, _ = clients
    outside = filing.model_copy(update={
        "accession_number": "0000320193-18-000001", "filing_date": outside_date,
    })
    sec.get_filings.return_value = [filing, outside]
    sec.get_filing_documents.side_effect = RuntimeError("temporary discovery failure")
    pipeline = IngestionPipeline(config)
    assert (await pipeline.ingest(["AAPL"]))["errors"] == 2

    setattr(config.filings, bound, filing.filing_date.date())
    sec.get_filing_documents.side_effect = None
    sec.get_filing_documents.reset_mock()
    result = await pipeline.resume()
    assert result["errors"] == 0
    assert result["filings_resumed"] == result["filings_completed"] == 1
    assert result["filings_outside_window"] == 1
    assert graph.upload_payload.await_count == 2
    sec.get_filing_documents.assert_awaited_once()
    assert sec.get_filing_documents.await_args.args[0].accession_number == filing.accession_number
    async with pipeline._state() as state:
        excluded_id = await state.get_filing_id(outside.cik, outside.accession_number)
        assert (await state.get_filing(excluded_id)).state == FilingState.FAILED
        run = (await state.get_stats())["last_run"]
        assert f'"{bound}": "2023-11-03"' in run["scope"]


async def test_date_change_does_not_allow_document_policy_change(config, clients):
    sec, graph, _, _ = clients
    sec.get_filing_documents.side_effect = RuntimeError("temporary discovery failure")
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    config.filings.start_date = date(2019, 9, 9)
    config.filings.include_exhibits = False
    sec.get_filing_documents.side_effect = None
    result = await pipeline.resume()
    assert result["errors"] == 1
    graph.upload_payload.assert_not_awaited()


async def test_legacy_state_is_not_adopted_or_deleted(config):
    pipeline = IngestionPipeline(config)
    pipeline.legacy_db_path.write_bytes(b"legacy state")
    with pytest.raises(RuntimeError, match="Legacy unscoped"):
        await pipeline.status()
    assert pipeline.legacy_db_path.read_bytes() == b"legacy state"
    assert not pipeline.db_path.exists()


async def test_binding_rejects_wrong_destination(config):
    path = IngestionPipeline(config).db_path
    async with StateManager(path, "tenant-a", "connection-a"):
        pass
    with pytest.raises(RuntimeError, match="destination or format"):
        async with StateManager(path, "tenant-a", "connection-b"):
            pass
    async with StateManager(path, "tenant-a", "connection-a"):
        pass


async def test_concurrent_run_is_rejected_and_lock_released(config):
    pipeline = IngestionPipeline(config)
    async with pipeline._state():
        with pytest.raises(RuntimeError, match="Another process"):
            async with pipeline._state():
                pass
    async with pipeline._state():
        pass


async def test_zero_chunks_cannot_complete_and_early_failure_resumes(config, filing):
    pipeline = IngestionPipeline(config)
    async with pipeline._state() as state:
        filing_id = await state.add_filing(filing)
        await state.update_filing_state(filing_id, FilingState.FAILED, "download failed")
        assert not await state.check_all_chunks_uploaded(filing_id)
        with pytest.raises(ValueError, match="Cannot complete"):
            await state.update_filing_state(filing_id, FilingState.COMPLETED)
        candidates = await state.get_resume_candidates()
        assert len(candidates) == 1
        assert candidates[0].primary_document == filing.primary_document


async def test_empty_inventory_is_failure(config, clients):
    sec, graph, _, _ = clients
    sec.get_filing_documents.return_value = []
    pipeline = IngestionPipeline(config)
    stats = await pipeline.ingest(["AAPL"])
    assert stats["errors"] == 1
    assert stats["filings_completed"] == stats["chunks_uploaded"] == 0
    assert graph.upload_payload.await_count == 0
    async with pipeline._state() as state:
        assert len(await state.get_resume_candidates()) == 1


async def test_failed_document_is_recorded_and_resume_only_prepares_missing(config, clients):
    sec, graph, documents, paths = clients
    original = sec.download_document.side_effect

    async def partial(filing, document, directory, refresh=False):
        if document.sequence == 2:
            raise OSError("download interrupted")
        return await original(filing, document, directory)

    sec.download_document.side_effect = partial
    pipeline = IngestionPipeline(config)
    assert (await pipeline.ingest(["AAPL"]))["errors"] == 1
    assert graph.upload_payload.await_count == 0
    async with pipeline._state() as state:
        record = (await state.get_resume_candidates())[0]
        inventory = await state.get_documents(record.id)
        assert [entry["state"] for entry in inventory] == ["parsed", "failed"]
        saved = (await state.get_chunks(record.id))[0].payload
    # Already parsed documents must not be re-read after a restart.
    paths[documents[0].filename].unlink()
    sec.download_document.reset_mock()
    sec.download_document.side_effect = original
    stats = await IngestionPipeline(config).resume()
    assert stats["errors"] == 0
    assert stats["filings_completed"] == 1
    assert sec.download_document.await_count == 1
    assert graph.upload_payload.await_args_list[0].args[1] == saved


async def test_parse_none_is_not_silently_excluded(config, clients, monkeypatch):
    _, graph, documents, paths = clients
    monkeypatch.setattr("sec_connector.pipeline.parse_document", lambda *args, **kwargs: None)
    pipeline = IngestionPipeline(config)
    stats = await pipeline.ingest(["AAPL"])
    assert stats["errors"] == 1
    assert stats["filings_completed"] == 0
    assert not graph.upload_payload.called


async def test_resume_replays_only_failed_immutable_payload(config, clients):
    sec, graph, _, _ = clients

    async def upload(item_id, payload):
        if payload["properties"]["Sequence"] == 2:
            raise RuntimeError("temporary Graph error")

    graph.upload_payload.side_effect = upload
    pipeline = IngestionPipeline(config)
    stats = await pipeline.ingest(["AAPL"])
    assert stats["errors"] == 1
    async with pipeline._state() as state:
        record = (await state.get_resume_candidates())[0]
        original = (await state.get_pending_chunks(record.id))[0].payload
    config.chunking.target_size = 40
    config.chunking.max_size = 80
    sec.get_filing_documents.side_effect = AssertionError("Must not rediscover")
    sec.download_document.side_effect = AssertionError("Must not reparse")
    graph.upload_payload.reset_mock()
    graph.upload_payload.side_effect = None
    stats = await IngestionPipeline(config).resume()
    assert stats["errors"] == 0
    assert stats["filings_completed"] == 1
    graph.upload_payload.assert_awaited_once_with(original["id"], original)


async def test_post_upload_pre_completion_crash_recovers_without_put(config, clients, monkeypatch):
    _, graph, _, _ = clients
    original = StateManager.update_filing_state

    async def interrupt(self, filing_id, state, error_message=None):
        if state == FilingState.COMPLETED:
            raise KeyboardInterrupt("simulated process crash")
        await original(self, filing_id, state, error_message)

    monkeypatch.setattr(StateManager, "update_filing_state", interrupt)
    with pytest.raises(KeyboardInterrupt):
        await IngestionPipeline(config).ingest(["AAPL"])
    monkeypatch.setattr(StateManager, "update_filing_state", original)
    graph.upload_payload.reset_mock()
    stats = await IngestionPipeline(config).resume()
    assert stats["filings_completed"] == 1
    graph.upload_payload.assert_not_awaited()


async def test_sample_budget_is_per_filing_and_can_expand(config, clients):
    _, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    stats = await pipeline.ingest(["AAPL"], max_pages=1)
    assert stats["chunks_uploaded"] == stats["filings_sampled"] == 1
    assert stats["filings_completed"] == 0
    graph.upload_payload.reset_mock()
    stats = await pipeline.ingest(["AAPL"])
    assert stats["filings_completed"] == 1
    assert stats["chunks_uploaded"] == 1
    assert stats["chunks_unchanged"] == 1


async def test_repeated_complete_run_skips_acknowledged_filing(config, clients):
    _, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    assert (await pipeline.ingest(["AAPL"]))["filings_completed"] == 1
    graph.upload_payload.reset_mock()
    stats = await pipeline.ingest(["AAPL"])
    assert stats["documents_cached"] == 2
    assert stats["chunks_unchanged"] == 2
    graph.upload_payload.assert_not_awaited()


async def test_reset_failure_preserves_state(config, clients):
    _, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    before = await pipeline.status()
    graph.delete_connection.side_effect = RuntimeError("Graph unavailable")
    with pytest.raises(RuntimeError, match="Graph unavailable"):
        await pipeline.reset()
    assert await pipeline.status() == before


@pytest.mark.parametrize("not_found", [False, True])
async def test_reset_clears_only_its_destination(config, clients, not_found):
    _, graph, _, _ = clients
    first = IngestionPipeline(config)
    await first.ingest(["AAPL"])
    other_config = config.model_copy(deep=True)
    other_config.azure.connection_id = "connection-b"
    second = IngestionPipeline(other_config)
    await second.ingest(["AAPL"])
    if not_found:
        graph.delete_connection.side_effect = aiohttp.ClientResponseError(
            request_info=None, history=(), status=404, message="not found"
        )
    await first.reset()
    assert (await first.status())["total_filings"] == 0
    assert (await second.status())["total_filings"] == 1


async def test_all_discovery_is_persisted_before_download(config, clients, filing):
    sec, _, _, _ = clients
    second = filing.model_copy(update={"accession_number": "0000320193-23-000078"})
    sec.get_filings.return_value = [filing, second]
    sec.download_document.side_effect = KeyboardInterrupt("crash")
    pipeline = IngestionPipeline(config)
    with pytest.raises(KeyboardInterrupt):
        await pipeline.ingest(["AAPL"])
    async with pipeline._state() as state:
        assert len(await state.get_resume_candidates()) == 2


async def test_document_manifest_is_atomic_on_id_collision(config, filing):
    pipeline = IngestionPipeline(config)
    document = DocumentInfo(sequence=1, filename="primary.htm", document_type="10-K")
    payload = {"id": "same-id", "properties": {"Page": 1}, "content": {"value": "test"}}
    async with pipeline._state() as state:
        filing_id = await state.add_filing(filing)
        await state.set_inventory(filing_id, [document])
        import aiosqlite
        with pytest.raises(aiosqlite.IntegrityError):
            await state.save_document_payloads(filing_id, document, [payload, payload])
        assert await state.get_chunks(filing_id) == []
        assert (await state.get_documents(filing_id))[0]["state"] == "pending"
        assert not (await state.get_filing(filing_id)).payloads_ready


async def test_resume_uses_captured_settings_before_first_payload(config, clients):
    sec, _, _, _ = clients
    original = sec.download_document.side_effect
    sec.download_document.side_effect = OSError("interrupted first download")
    pipeline = IngestionPipeline(config)
    assert (await pipeline.ingest(["AAPL"]))["errors"] == 1
    # A valid but different configuration must not change a pending generation.
    config.chunking.target_size = 400
    config.chunking.max_size = 800
    sec.download_document.side_effect = original
    result = await IngestionPipeline(config).resume()
    assert result["errors"] == 0
    assert result["chunks_uploaded"] == 2


async def test_setup_does_not_recreate_missing_connection_over_old_acknowledgments(config, clients):
    _, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    graph.load_schema = lambda: {"properties": []}
    graph.get_connection = AsyncMock(side_effect=aiohttp.ClientResponseError(
        request_info=None, history=(), status=404, message="missing"
    ))
    graph.create_connection = AsyncMock()
    with pytest.raises(RuntimeError, match="local delivery state exists"):
        await pipeline.setup()
    graph.create_connection.assert_not_awaited()
    assert (await pipeline.status())["total_filings"] == 1


async def test_setup_auth_error_is_not_mistaken_for_absence(config, clients):
    _, graph, _, _ = clients
    graph.load_schema = lambda: {"properties": []}
    graph.get_connection = AsyncMock(side_effect=aiohttp.ClientResponseError(
        request_info=None, history=(), status=403, message="forbidden"
    ))
    graph.create_connection = AsyncMock()
    with pytest.raises(aiohttp.ClientResponseError) as error:
        await IngestionPipeline(config).setup()
    assert error.value.status == 403
    graph.create_connection.assert_not_awaited()


@pytest.mark.parametrize("matches_after_provisioning", [False, True])
async def test_setup_checks_provisioned_schema(config, clients, matches_after_provisioning):
    _, graph, _, _ = clients
    desired = {"baseType": "microsoft.graph.externalItem", "properties": [
        {"name": "Title", "type": "String", "isRetrievable": True, "labels": ["title"]}
    ]}
    graph.load_schema = lambda: desired
    graph.get_connection = AsyncMock(return_value={"id": "connection-a"})
    missing = aiohttp.ClientResponseError(request_info=None, history=(), status=404, message="missing")
    graph.get_schema_status = AsyncMock(side_effect=[
        missing, desired if matches_after_provisioning else {"properties": []}
    ])
    graph.register_schema = AsyncMock()
    graph.wait_for_schema = AsyncMock(return_value=True)
    pipeline = IngestionPipeline(config)
    if matches_after_provisioning:
        await pipeline.setup()
    else:
        with pytest.raises(RuntimeError, match="does not match"):
            await pipeline.setup()
    graph.register_schema.assert_awaited_once()
    graph.wait_for_schema.assert_awaited_once_with(timeout=900)
