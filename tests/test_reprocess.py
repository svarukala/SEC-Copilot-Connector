"""Offline coverage for explicitly rebuilding interrupted desired generations."""

import json
from datetime import date, datetime

import aiohttp
import aiosqlite
from click.testing import CliRunner
import pytest

from sec_connector.cli import main
from sec_connector.models import ChunkState, FilingState
from sec_connector.pipeline import IngestionPipeline, PROCESSING_VERSION
from sec_connector.state_manager import StateManager
from .test_cli import cli_pipeline
from .test_recovery import config, filing, clients


async def candidates(state, filing_id):
    cursor = await state._db.execute(
        "SELECT chunk_id FROM reconciliation_candidates WHERE filing_id = ?", (filing_id,)
    )
    return {row["chunk_id"] for row in await cursor.fetchall()}


async def prepare_old(pipeline, clients, filing, monkeypatch):
    sec, graph, _, _ = clients
    with monkeypatch.context() as old:
        old.setattr("sec_connector.pipeline.PROCESSING_VERSION", 3)
        async with pipeline._state() as state:
            filing_id = await state.add_filing(filing, processing_options=pipeline._processing_options())
            await pipeline._prepare_filing(filing_id, sec, state, graph, pipeline._stats())
            chunks = await state.get_chunks(filing_id)
    return filing_id, chunks


async def test_reprocess_upgrades_early_pending_and_preserves_unselected_queue(
    config, clients, filing,
):
    pipeline = IngestionPipeline(config)
    options = {**pipeline._processing_options(), "processing_version": 3}
    excluded = [
        filing.model_copy(update={"ticker": "PNC", "cik": "0000713676"}),
        filing.model_copy(update={
            "accession_number": "0000320193-18-000001", "filing_date": datetime(2018, 1, 1),
        }),
    ]
    async with pipeline._state() as state:
        selected_id = await state.add_filing(filing, processing_options=options)
        excluded_ids = [await state.add_filing(item, processing_options=options) for item in excluded]
        before = [await state.get_filing(item_id) for item_id in excluded_ids]
    config.filings.start_date = date(2021, 9, 9)
    assert (await pipeline.ingest(["AAPL"]))["errors"] == 1
    result = await pipeline.ingest(["AAPL"], reprocess=True)
    assert result["errors"] == 0
    assert result["filings_completed"] == 1
    async with pipeline._state() as state:
        selected = await state.get_filing(selected_id)
        assert selected.processing_options["processing_version"] == PROCESSING_VERSION == 4
        assert [await state.get_filing(item_id) for item_id in excluded_ids] == before
        scope = json.loads((await state.get_stats())["last_run"]["scope"])
        assert scope["reprocess"] is True
        assert scope["start_date"] == "2021-09-09"
        assert scope["tickers"] == ["AAPL"]


async def test_unacknowledged_put_is_deleted_only_after_replacement(
    config, clients, filing, monkeypatch,
):
    sec, graph, documents, _ = clients
    pipeline = IngestionPipeline(config)
    filing_id, old = await prepare_old(pipeline, clients, filing, monkeypatch)
    # Simulate a successful PUT whose acknowledgment was lost at process exit.
    await graph.upload_payload(old[1].chunk_id, old[1].payload)
    graph.upload_payload.reset_mock()
    sec.get_filing_documents.return_value = documents[:1]
    events = []

    async def upload(item_id, payload):
        events.append(("put", item_id))

    async def delete(item_id):
        events.append(("delete", item_id))

    graph.upload_payload.side_effect = upload
    graph.delete_item.side_effect = delete
    result = await pipeline.ingest(["AAPL"], reprocess=True)
    assert result["errors"] == 0
    assert events == [("put", old[0].chunk_id), ("delete", old[1].chunk_id)]
    async with pipeline._state() as state:
        assert not await candidates(state, filing_id)
        assert (await state.get_stats())["acknowledged_items"] == 1
        assert (await state.get_filing(filing_id)).state == FilingState.COMPLETED


@pytest.mark.parametrize("failure", ["inventory", "parse", "upload"])
async def test_failed_reprocess_never_deletes_uncertain_old_items(
    config, clients, filing, monkeypatch, failure,
):
    sec, graph, documents, _ = clients
    pipeline = IngestionPipeline(config)
    filing_id, old = await prepare_old(pipeline, clients, filing, monkeypatch)
    sec.get_filing_documents.return_value = documents[:1]
    if failure == "inventory":
        sec.get_filing_documents.side_effect = OSError("offline")
    elif failure == "parse":
        monkeypatch.setattr("sec_connector.pipeline.parse_document", lambda *args, **kwargs: None)
    else:
        graph.upload_payload.side_effect = RuntimeError("offline")
    assert (await pipeline.ingest(["AAPL"], reprocess=True))["errors"] > 0
    graph.delete_item.assert_not_awaited()
    async with pipeline._state() as state:
        assert await candidates(state, filing_id) == {chunk.chunk_id for chunk in old}
        assert (await state.get_stats())["acknowledged_items"] == 0
        with pytest.raises(ValueError, match="complete unsampled"):
            await state.stale_item_ids(filing_id)
        with pytest.raises(ValueError, match="Cannot complete"):
            await state.update_filing_state(filing_id, FilingState.COMPLETED)


async def test_same_id_uncertainty_forces_put_even_when_old_ack_hash_matches(
    config, clients, filing, monkeypatch,
):
    _, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    filing_id, old = await prepare_old(pipeline, clients, filing, monkeypatch)
    async with pipeline._state() as state:
        for chunk in old:
            await state.update_chunk_state(chunk.chunk_id, ChunkState.UPLOADED)
        # A later attempted overwrite could have changed Graph, but not the saved ack hash.
        await state.update_chunk_state(old[0].chunk_id, ChunkState.FAILED, "lost overwrite acknowledgment")
    result = await pipeline.ingest(["AAPL"], reprocess=True)
    assert result["errors"] == 0
    assert result["chunks_uploaded"] == 1
    assert result["chunks_unchanged"] == 1
    graph.upload_payload.assert_awaited_once_with(old[0].chunk_id, old[0].payload)
    graph.delete_item.assert_not_awaited()
    async with pipeline._state() as state:
        assert not await candidates(state, filing_id)
        assert (await state.get_stats())["acknowledged_items"] == 2


async def test_delete_crash_resumes_and_accepts_404(config, clients, filing, monkeypatch):
    sec, graph, documents, _ = clients
    pipeline = IngestionPipeline(config)
    filing_id, old = await prepare_old(pipeline, clients, filing, monkeypatch)
    sec.get_filing_documents.return_value = documents[:1]

    async def crash_ack(self, chunk_id):
        raise KeyboardInterrupt("Delete succeeded before local acknowledgment")

    with monkeypatch.context() as interrupted:
        interrupted.setattr(StateManager, "acknowledge_delete", crash_ack)
        with pytest.raises(KeyboardInterrupt):
            await pipeline.ingest(["AAPL"], reprocess=True)
    async with pipeline._state() as state:
        assert old[1].chunk_id in await candidates(state, filing_id)
        with pytest.raises(ValueError, match="obsolete remote"):
            await state.update_filing_state(filing_id, FilingState.COMPLETED)
    graph.upload_payload.reset_mock()
    graph.delete_item.reset_mock()
    graph.delete_item.side_effect = aiohttp.ClientResponseError(
        request_info=None, history=(), status=404, message="Not found",
    )
    sec.download_document.side_effect = AssertionError("Resume must replay, not rebuild")
    result = await pipeline.resume()
    assert result["errors"] == 0
    assert result["chunks_deleted"] == result["filings_completed"] == 1
    graph.upload_payload.assert_not_awaited()
    graph.delete_item.assert_awaited_once_with(old[1].chunk_id)
    async with pipeline._state() as state:
        assert not await candidates(state, filing_id)


async def test_repeated_reprocess_preserves_all_generations(config, clients, filing, monkeypatch):
    _, graph, documents, _ = clients
    pipeline = IngestionPipeline(config)
    filing_id, old = await prepare_old(pipeline, clients, filing, monkeypatch)
    async with pipeline._state() as state:
        for generation in ("orphan-second", "orphan-third"):
            await state.begin_refresh(
                filing_id, filing, pipeline._processing_options(), None, allow_inflight=True
            )
            await state.set_inventory(filing_id, documents[:1])
            payload = {**old[0].payload, "id": generation}
            await state.save_document_payloads(filing_id, documents[0], [payload])
            await state.mark_payloads_ready(filing_id)
        assert (await state.get_stats())["acknowledged_items"] == 0
        assert await candidates(state, filing_id) == {
            *(chunk.chunk_id for chunk in old), "orphan-second",
        }
    result = await pipeline.ingest(["AAPL"], reprocess=True)
    assert result["errors"] == 0
    assert {call.args[0] for call in graph.delete_item.await_args_list} == {
        "orphan-second", "orphan-third",
    }
    async with pipeline._state() as state:
        assert not await candidates(state, filing_id)
        assert (await state.get_stats())["acknowledged_items"] == 2


@pytest.mark.parametrize("mode", ["resume", "ingest"])
async def test_default_replay_keeps_old_prepared_payloads(config, clients, filing, monkeypatch, mode):
    sec, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    filing_id, old = await prepare_old(pipeline, clients, filing, monkeypatch)
    config.chunking.target_size = 40
    config.chunking.max_size = 80
    sec.get_filing_documents.side_effect = AssertionError("Must not rebuild inventory")
    sec.download_document.side_effect = AssertionError("Must not reparse")
    result = await pipeline.resume() if mode == "resume" else await pipeline.ingest(["AAPL"])
    assert result["errors"] == 0
    assert [call.args[1] for call in graph.upload_payload.await_args_list] == [c.payload for c in old]
    async with pipeline._state() as state:
        assert (await state.get_filing(filing_id)).processing_options["processing_version"] == 3
        assert not await candidates(state, filing_id)


async def test_explicit_reprocess_cannot_sample_downgrade_completed(config, clients):
    _, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    await pipeline.ingest(["AAPL"])
    graph.upload_payload.reset_mock()
    result = await pipeline.ingest(["AAPL"], max_pages=1, reprocess=True)
    assert result["filings_skipped"] == 1
    assert (await pipeline.status())["filings"] == {"completed": 1}
    graph.upload_payload.assert_not_awaited()
    graph.delete_item.assert_not_awaited()


async def test_sampled_reprocess_retains_obsolete_candidates_until_full_run(
    config, clients, filing, monkeypatch,
):
    _, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    filing_id, old = await prepare_old(pipeline, clients, filing, monkeypatch)
    result = await pipeline.ingest(["AAPL"], max_pages=1, reprocess=True)
    assert result["filings_sampled"] == 1
    graph.delete_item.assert_not_awaited()
    async with pipeline._state() as state:
        assert await candidates(state, filing_id) == {old[1].chunk_id}
    result = await pipeline.ingest(["AAPL"])
    assert result["filings_completed"] == 1
    graph.delete_item.assert_not_awaited()
    async with pipeline._state() as state:
        assert not await candidates(state, filing_id)


async def test_refresh_guard_and_transaction_rollback(config, clients, filing, monkeypatch):
    pipeline = IngestionPipeline(config)
    filing_id, old = await prepare_old(pipeline, clients, filing, monkeypatch)
    async with pipeline._state() as state:
        with pytest.raises(ValueError, match="allow_inflight"):
            await state.begin_refresh(filing_id, filing, pipeline._processing_options(), None)
        before = await state.get_filing(filing_id)
        await state._db.executescript("""
            CREATE TRIGGER fail_refresh BEFORE UPDATE ON filings
            BEGIN SELECT RAISE(ABORT, 'simulated failure'); END;
        """)
        with pytest.raises(aiosqlite.IntegrityError, match="simulated failure"):
            await state.begin_refresh(
                filing_id, filing, pipeline._processing_options(), None, allow_inflight=True
            )
        assert await state.get_filing(filing_id) == before
        assert await state.get_chunks(filing_id) == old
        assert len(await state.get_documents(filing_id)) == 2
        assert not await candidates(state, filing_id)


async def test_retirement_includes_orphan_candidates(config, clients, filing, monkeypatch):
    _, graph, _, _ = clients
    pipeline = IngestionPipeline(config)
    filing_id, old = await prepare_old(pipeline, clients, filing, monkeypatch)
    async with pipeline._state() as state:
        await state.begin_refresh(
            filing_id, filing, pipeline._processing_options(), None, allow_inflight=True
        )
        assert not await state.get_chunks(filing_id)
        with pytest.raises(ValueError, match="unacknowledged remote"):
            await state.finish_retirement(filing_id)
        await pipeline._retire_filing(filing_id, state, graph, pipeline._stats())
        assert (await state.get_stats())["total_filings"] == 0
        assert not await candidates(state, filing_id)
    assert {call.args[0] for call in graph.delete_item.await_args_list} == {c.chunk_id for c in old}


async def test_v2_migration_preserves_manifest_cache_and_acknowledgments(
    config, clients, filing, monkeypatch,
):
    pipeline = IngestionPipeline(config)
    filing_id, old = await prepare_old(pipeline, clients, filing, monkeypatch)
    async with pipeline._state() as state:
        await state.update_chunk_state(old[0].chunk_id, ChunkState.UPLOADED)
        before = await state.get_chunks(filing_id)
        await state.start_run({"reprocess": False})
    async with aiosqlite.connect(pipeline.db_path) as db:
        await db.executescript("""
            DROP TABLE reconciliation_candidates;
            UPDATE destination SET version = 2;
        """)
    async with pipeline._state() as state:
        cursor = await state._db.execute("SELECT version FROM destination")
        assert (await cursor.fetchone())["version"] == 3
        assert await state.get_chunks(filing_id) == before
        stats = await state.get_stats()
        assert stats["acknowledged_items"] == 1
        assert json.loads(stats["last_run"]["scope"]) == {"reprocess": False}
        cursor = await state._db.execute("SELECT COUNT(*) AS count FROM document_cache")
        assert (await cursor.fetchone())["count"] == 2
        assert not await candidates(state, filing_id)
    assert (await pipeline.ingest(["AAPL"], reprocess=True))["errors"] == 0


@pytest.mark.parametrize("flag", [[], ["--reprocess"]])
def test_cli_passes_explicit_reprocess_flag(cli_pipeline, flag):
    _, pipeline, _ = cli_pipeline
    pipeline.ingest.return_value = {"errors": 0}
    result = CliRunner().invoke(main, ["ingest", "-t", "WFC,JPM,BAC,USB", *flag])
    assert result.exit_code == 0, result.output
    pipeline.ingest.assert_awaited_once_with(
        tickers=["WFC", "JPM", "BAC", "USB"], max_filings=None, max_pages=None,
        reprocess=bool(flag),
    )
