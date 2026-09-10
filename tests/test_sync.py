"""Desired-state synchronization and guarded deletion regression tests."""

import aiosqlite
import aiohttp
import pytest

from sec_connector.models import FilingState
from sec_connector.pipeline import IngestionPipeline
from .test_recovery import config, filing, clients


async def test_shrinking_document_replaces_then_deletes_obsolete_ids(config, clients):
    _, graph, documents, paths = clients
    paths[documents[0].filename].write_text("<p>" + "Financial fact. " * 2000 + "</p>", encoding="utf-8")
    pipeline = IngestionPipeline(config)
    first = await pipeline.ingest(["AAPL"])
    assert first["errors"] == 0
    original_ids = {call.args[0] for call in graph.upload_payload.await_args_list}
    events = []

    async def upload(item_id, payload):
        events.append(("put", item_id))

    async def delete(item_id):
        events.append(("delete", item_id))

    graph.upload_payload.side_effect = upload
    graph.delete_item.side_effect = delete
    paths[documents[0].filename].write_text("<p>" + "Updated financial fact. " * 20 + "</p>", encoding="utf-8")
    second = await pipeline.ingest(["AAPL"])
    assert second["errors"] == 0
    assert second["chunks_deleted"] > 0
    assert events[0][0] == "put"
    assert all(event[0] == "delete" for event in events[1:])
    async with pipeline._state() as state:
        record = (await state.get_filings_by_state(FilingState.COMPLETED))[0]
        desired = {chunk.chunk_id for chunk in await state.get_chunks(record.id)}
        assert set(call.args[0] for call in graph.delete_item.await_args_list) == original_ids - desired
        assert (await state.get_stats())["acknowledged_items"] == len(desired)


async def test_removed_exhibit_deletes_only_exhibit_items(config, clients):
    sec, graph, documents, _ = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    exhibit_id = graph.upload_payload.await_args_list[1].args[0]
    graph.upload_payload.reset_mock()
    sec.get_filing_documents.return_value = documents[:1]
    result = await pipeline.ingest(["AAPL"])
    assert result["chunks_deleted"] == 1
    assert result["errors"] == 0
    graph.delete_item.assert_awaited_once_with(exhibit_id)
    graph.upload_payload.assert_not_awaited()


async def test_failed_inventory_never_deletes_previous_generation(config, clients):
    sec, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    before = (await pipeline.status())["acknowledged_items"]
    sec.get_filing_documents.side_effect = OSError("inventory unavailable")
    result = await pipeline.ingest(["AAPL"])
    assert result["errors"] == 1
    graph.delete_item.assert_not_awaited()
    assert (await pipeline.status())["acknowledged_items"] == before


async def test_delete_failure_resumes_without_reupload(config, clients):
    sec, graph, documents, _ = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    sec.get_filing_documents.return_value = documents[:1]
    graph.delete_item.side_effect = RuntimeError("Graph unavailable")
    result = await pipeline.ingest(["AAPL"])
    assert result["errors"] == 1
    graph.upload_payload.reset_mock()
    graph.delete_item.side_effect = None
    sec.download_document.side_effect = AssertionError("Prepared generation must not download again")
    result = await pipeline.resume()
    assert result["errors"] == 0
    assert result["chunks_deleted"] == result["filings_completed"] == 1
    graph.upload_payload.assert_not_awaited()


async def test_missing_recent_filings_are_retained_without_explicit_prune(config, clients):
    sec, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    sec.get_filings.return_value = []
    await pipeline.ingest(["AAPL"])
    graph.delete_item.assert_not_awaited()
    assert (await pipeline.status())["total_filings"] == 1


async def test_explicit_complete_historical_prune_retires_missing_filing(config, clients):
    sec, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    sec.get_filings.return_value = []
    config.sync.prune_missing_filings = True
    result = await pipeline.ingest(["AAPL"])
    assert result["errors"] == 0
    assert result["filings_retired"] == 1
    assert graph.delete_item.await_count == 2
    assert (await pipeline.status())["total_filings"] == 0


async def test_retirement_failure_resumes_as_retirement(config, clients):
    sec, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    sec.get_filings.return_value = []
    config.sync.prune_missing_filings = True
    graph.delete_item.side_effect = RuntimeError("offline")
    assert (await pipeline.ingest(["AAPL"]))["errors"] > 0
    async with pipeline._state() as state:
        assert (await state.get_resume_candidates())[0].state == FilingState.RETIRING
    graph.delete_item.side_effect = None
    assert (await pipeline.resume())["filings_retired"] == 1


@pytest.mark.parametrize("limits", [{"max_filings": 1}, {"max_pages": 1}])
async def test_sampled_crawl_cannot_prune(config, clients, limits):
    config.sync.prune_missing_filings = True
    with pytest.raises(ValueError, match="unlimited"):
        await IngestionPipeline(config).ingest(["AAPL"], **limits)


async def test_metadata_change_reindexes_unchanged_source(config, clients, filing):
    sec, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    sec.get_filings.return_value = [filing.model_copy(update={"company_name": "Updated issuer name"})]
    graph.upload_payload.reset_mock()
    result = await pipeline.ingest(["AAPL"])
    assert result["errors"] == 0
    assert result["chunks_uploaded"] == 2
    assert all(call.args[1]["properties"]["Company"] == "Updated issuer name"
               for call in graph.upload_payload.await_args_list)


async def test_run_observability_records_scope_and_outcome(config, clients):
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    status = await pipeline.status()
    assert status["last_run"]["status"] == "completed"
    assert '"AAPL"' in status["last_run"]["scope"]
    assert status["acknowledged_items"] == 2


@pytest.mark.parametrize("failure", ["parse", "upload"])
async def test_failed_replacement_never_deletes_old_exhibit(config, clients, monkeypatch, failure):
    sec, graph, documents, paths = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    sec.get_filing_documents.return_value = documents[:1]
    paths[documents[0].filename].write_text("<p>Changed financial fact.</p>", encoding="utf-8")
    if failure == "parse":
        monkeypatch.setattr("sec_connector.pipeline.parse_document", lambda *args, **kwargs: None)
    else:
        graph.upload_payload.side_effect = RuntimeError("offline")
    assert (await pipeline.ingest(["AAPL"]))["errors"] > 0
    graph.delete_item.assert_not_awaited()
    assert (await pipeline.status())["acknowledged_items"] == 2


async def test_sample_cannot_downgrade_completed_filing(config, clients):
    _, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    graph.upload_payload.reset_mock()
    result = await pipeline.ingest(["AAPL"], max_pages=1)
    assert result["filings_skipped"] == 1
    graph.upload_payload.assert_not_awaited()
    graph.delete_item.assert_not_awaited()
    assert (await pipeline.status())["filings"] == {"completed": 1}


async def test_icon_configuration_invalidates_payload_cache(config, clients):
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    config.azure.icon_url = "https://www.sec.gov/new-icon.ico"
    result = await pipeline.ingest(["AAPL"])
    assert result["chunks_uploaded"] == 2
    assert result["documents_cached"] == 0


async def test_v1_migration_preserves_acknowledged_items(config, clients):
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    async with aiosqlite.connect(pipeline.db_path) as db:
        await db.executescript("""
            DROP TABLE delivered_items;
            DROP TABLE document_cache;
            DROP TABLE runs;
            UPDATE destination SET version = 1;
        """)
    assert (await pipeline.status())["acknowledged_items"] == 2
    assert (await pipeline.ingest(["AAPL"]))["chunks_uploaded"] == 0


async def test_confirmed_missing_item_is_successful_deletion(config, clients):
    sec, graph, documents, _ = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    sec.get_filing_documents.return_value = documents[:1]
    graph.delete_item.side_effect = aiohttp.ClientResponseError(
        request_info=None, history=(), status=404, message="Not found",
    )
    result = await pipeline.ingest(["AAPL"])
    assert result["errors"] == 0
    assert result["chunks_deleted"] == 1


async def test_filing_returning_during_retirement_is_reingested(config, clients, filing):
    sec, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    config.sync.prune_missing_filings = True
    sec.get_filings.return_value = []
    graph.delete_item.side_effect = RuntimeError("offline")
    await pipeline.ingest(["AAPL"])
    sec.get_filings.return_value = [filing]
    graph.delete_item.side_effect = None
    result = await pipeline.ingest(["AAPL"])
    assert result["errors"] == 0
    assert result["filings_retired"] == 1
    assert result["chunks_uploaded"] == 2
    assert (await pipeline.status())["filings"] == {"completed": 1}
