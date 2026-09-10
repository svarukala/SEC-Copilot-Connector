"""Resumable ingestion backed by destination-scoped document and payload manifests."""

import asyncio
import json
import hashlib
from pathlib import Path
from typing import Optional

import aiohttp

from .chunker import chunk_with_limit
from .config import AppConfig, ChunkingConfig, ensure_directories
from .graph_client import GraphClient
from .models import ChunkState, FilingMetadata, FilingState
from .parser import parse_document
from .sec_client import SECClient
from .state_manager import StateManager, scoped_database_path
from .utils import console, get_logger

logger = get_logger("pipeline")
PROCESSING_VERSION = 4


class IngestionPipeline:
    """Persist discovery before processing, and persist payloads before delivery."""

    def __init__(self, config: AppConfig, test_mode: bool = False, save_payloads: bool = False):
        self.config = config
        self.test_mode = test_mode
        self.save_payloads = save_payloads
        self.download_dir = Path(config.paths.downloads)
        self.legacy_db_path = Path(config.paths.database)
        self.db_path = scoped_database_path(
            self.legacy_db_path, config.azure.tenant_id, config.azure.connection_id
        )
        self.payload_dir = Path(config.paths.payloads) / self.db_path.stem

    def _state(self) -> StateManager:
        if self.legacy_db_path.exists():
            raise RuntimeError(
                f"Legacy unscoped state exists at {self.legacy_db_path}. Remove or relocate it explicitly "
                "and reingest into a new connection; it cannot safely be adopted or reset."
            )
        return StateManager(
            self.db_path, self.config.azure.tenant_id, self.config.azure.connection_id
        )

    async def setup(self) -> None:
        async with self._state() as state, GraphClient(self.config) as graph:
            desired = graph.load_schema()
            has_local_filings = (await state.get_stats())["total_filings"] > 0
            try:
                await graph.get_connection()
            except aiohttp.ClientResponseError as exc:
                if exc.status != 404:
                    raise
                if has_local_filings:
                    raise RuntimeError(
                        "The connection is missing but local delivery state exists. "
                        "Run reset for this destination before setup to invalidate old acknowledgments."
                    ) from exc
                await graph.create_connection()
            try:
                actual = await graph.get_schema_status()
            except aiohttp.ClientResponseError as exc:
                if exc.status != 404:
                    raise
            else:
                if graph.schema_matches(actual, desired):
                    console.print("[green]Connection schema matches the requested schema.[/]")
                    return
            if has_local_filings:
                raise RuntimeError(
                    "Schema changes on a populated destination require reingestion. "
                    "Use a new connection ID for the schema change in this release."
                )
            await graph.register_schema()
            if not await graph.wait_for_schema(timeout=900):
                raise RuntimeError("Schema provisioning failed or timed out")
            if not graph.schema_matches(await graph.get_schema_status(), desired):
                raise RuntimeError("Provisioning completed but the remote schema does not match the request")
            console.print("[green]Setup complete. Schema provisioning succeeded.[/]")

    @staticmethod
    def _stats() -> dict:
        return {
            "tickers_processed": 0, "filings_discovered": 0, "filings_downloaded": 0,
            "filings_parsed": 0, "filings_completed": 0, "filings_sampled": 0,
            "filings_skipped": 0, "chunks_created": 0, "chunks_uploaded": 0, "errors": 0,
            "chunks_unchanged": 0, "chunks_deleted": 0, "documents_cached": 0,
            "filings_retired": 0,
            "filings_outside_window": 0,
        }

    def _processing_options(self) -> dict:
        return {
            "chunking": self.config.chunking.model_dump(),
            "ocr_images": self.config.processing.ocr_images,
            "filings": self.config.filings.model_dump(mode="json"),
            "refresh_downloads": self.config.sync.refresh_downloads,
            "icon_url": self.config.azure.icon_url,
            "schema_hash": hashlib.sha256(
                json.dumps(GraphClient.load_schema(), sort_keys=True).encode("utf-8")
            ).hexdigest(),
            "processing_version": PROCESSING_VERSION,
        }

    async def ingest(
        self, tickers: list[str], max_filings: Optional[int] = None,
        max_pages: Optional[int] = None, reprocess: bool = False,
    ) -> dict:
        if not tickers or any(not ticker.strip() for ticker in tickers):
            raise ValueError("At least one nonempty ticker is required")
        if (max_filings is not None and max_filings <= 0) or (max_pages is not None and max_pages <= 0):
            raise ValueError("Filing and page limits must be positive")
        ensure_directories(self.config)
        if self.test_mode:
            tickers = tickers[:1]
            max_filings = max_filings or self.config.test_mode.max_filings
            max_pages = max_pages or self.config.test_mode.max_pages
        if self.config.sync.prune_missing_filings and (
            self.test_mode or max_filings is not None or max_pages is not None
            or not self.config.filings.include_history
            or self.config.filings.start_date is not None or self.config.filings.end_date is not None
        ):
            raise ValueError("Pruning missing filings requires an unlimited, complete historical crawl")

        stats = self._stats()
        options = self._processing_options()
        async with (
            self._state() as state,
            SECClient(self.config) as sec,
            GraphClient(self.config) as graph,
        ):
            run_id = await state.start_run(
                {"tickers": tickers, "max_filings": max_filings, "max_pages": max_pages,
                 "prune": self.config.sync.prune_missing_filings, "reprocess": reprocess,
                 "start_date": options["filings"].get("start_date"),
                 "end_date": options["filings"].get("end_date")}
            )
            try:
                await sec.load_ticker_mapping()
            except Exception:
                stats["errors"] += 1
                await state.finish_run(run_id, stats)
                raise
            for ticker in dict.fromkeys(t.strip().upper() for t in tickers):
                try:
                    if not sec.get_cik(ticker):
                        raise ValueError(f"Unknown ticker: {ticker}")
                    filings = await sec.get_filings(
                        ticker, forms=self.config.filings.forms, max_filings=max_filings
                    )
                    stats["filings_discovered"] += len(filings)
                    # Checkpoint all discovered filings before the first download.
                    filing_ids = [
                        await state.add_filing(
                            filing, sample_limit=max_pages,
                            processing_options=options,
                        ) for filing in filings
                    ]
                    ticker_errors = stats["errors"]
                    for filing_id, filing in zip(filing_ids, filings):
                        record = await state.get_filing(filing_id)
                        if record.state == FilingState.RETIRING:
                            await self._retire_filing(filing_id, state, graph, stats)
                            if await state.get_filing_id(filing.cik, filing.accession_number) is not None:
                                continue
                            filing_id = await state.add_filing(filing, sample_limit=max_pages, processing_options=options)
                            record = await state.get_filing(filing_id)
                        if record.state == FilingState.COMPLETED and max_pages is not None:
                            logger.warning("Skipping sampled downgrade of completed filing %s", filing.accession_number)
                            stats["filings_skipped"] += 1
                            continue
                        if record.state in (FilingState.COMPLETED, FilingState.SAMPLED):
                            await state.begin_refresh(filing_id, filing, options, max_pages)
                        elif reprocess:
                            logger.info(
                                "Rebuilding selected in-flight filing %s with processing version %s; "
                                "retaining previous IDs until replacement delivery succeeds",
                                filing.accession_number, PROCESSING_VERSION,
                            )
                            await state.begin_refresh(
                                filing_id, filing, options, max_pages, allow_inflight=True
                            )
                        await self._process_filing(filing_id, sec, state, graph, stats)
                        if max_pages is None and (await state.get_filing(filing_id)).state == FilingState.SAMPLED:
                            await state.begin_refresh(filing_id, filing, options, None)
                            await self._process_filing(filing_id, sec, state, graph, stats)
                    if self.config.sync.prune_missing_filings and stats["errors"] == ticker_errors:
                        for missing in await state.missing_filings(
                            ticker, {filing.accession_number for filing in filings}
                        ):
                            await self._retire_filing(missing.id, state, graph, stats)
                    stats["tickers_processed"] += 1
                except Exception:
                    logger.exception("Failed to discover/process ticker %s", ticker)
                    stats["errors"] += 1
            await state.finish_run(run_id, stats)
        return stats

    async def _prepare_filing(
        self, filing_id: int, sec: SECClient, state: StateManager, graph: GraphClient, stats: dict,
    ) -> None:
        record = await state.get_filing(filing_id)
        if record.payloads_ready:
            return
        filing = FilingMetadata.model_validate(record.model_dump())
        if record.processing_options.get("processing_version", PROCESSING_VERSION) != PROCESSING_VERSION:
            raise RuntimeError(
                "Pending filing uses a different processing version; finish it with its original version "
                "or use ingest --reprocess with the intended ticker/date scope to rebuild it"
            )
        current_schema_hash = self._processing_options()["schema_hash"]
        if record.processing_options.get("schema_hash", current_schema_hash) != current_schema_hash:
            raise RuntimeError("Restore the pending filing's captured schema before preparing more documents")
        chunking = ChunkingConfig.model_validate(record.processing_options["chunking"])
        ocr_images = record.processing_options["ocr_images"]
        if chunking != self.config.chunking or ocr_images != self.config.processing.ocr_images:
            logger.warning(
                "Filing %s resumes with captured chunking/OCR settings, not the current configuration",
                filing.accession_number,
            )
        if not record.inventory_complete:
            selection = record.processing_options.get("filings")
            if selection is not None:
                # Dates select filings, not documents within an already selected filing.
                captured_selection = {key: value for key, value in selection.items()
                                      if key not in ("start_date", "end_date")}
                current_selection = {key: value for key, value in self.config.filings.model_dump(mode="json").items()
                                     if key not in ("start_date", "end_date")}
                if captured_selection != current_selection:
                    raise ValueError("Restore the pending filing's captured selection settings before resuming discovery")
            await state.set_inventory(filing_id, await sec.get_filing_documents(filing))
        existing = await state.get_chunks(filing_id)
        remaining = None if record.sample_limit is None else max(0, record.sample_limit - len(existing))
        for entry in await state.get_documents(filing_id):
            document = entry["document"]
            if entry["state"] in ("parsed", "sampled_out"):
                continue
            if remaining == 0:
                await state.update_document(filing_id, document.filename, "sampled_out")
                continue
            try:
                path = await sec.download_document(
                    filing, document, self.download_dir,
                    refresh=record.processing_options.get("refresh_downloads", True),
                )
                await state.update_document(filing_id, document.filename, "downloaded")
                digest = hashlib.sha256(await asyncio.to_thread(path.read_bytes)).hexdigest()
                fingerprint = hashlib.sha256(json.dumps({
                    "source": digest, "filing": filing.model_dump(mode="json"),
                    "document": document.model_dump(mode="json"), "options": record.processing_options,
                    "remaining": remaining,
                }, sort_keys=True).encode("utf-8")).hexdigest()
                payloads = await state.cached_payloads(filing_id, document.filename, fingerprint)
                if payloads is None:
                    parsed = await asyncio.to_thread(
                        parse_document, path, filing, document, ocr_images=ocr_images,
                    )
                    if parsed is None:
                        raise ValueError(f"Document did not produce usable content: {document.filename}")
                    chunks = chunk_with_limit(parsed, chunking, max_chunks=remaining)
                    payloads = [
                        graph.build_payload(chunk, icon_url=record.processing_options.get("icon_url"))
                        for chunk in chunks
                    ]
                else:
                    stats["documents_cached"] += 1
                await state.save_document_payloads(filing_id, document, payloads, fingerprint)
                stats["chunks_created"] += len(payloads)
                if remaining is not None:
                    remaining -= len(payloads)
            except Exception as exc:
                await state.update_document(filing_id, document.filename, "failed", str(exc))
                raise
        await state.mark_payloads_ready(filing_id)
        stats["filings_downloaded"] += 1
        stats["filings_parsed"] += 1

    async def _deliver_filing(self, filing_id: int, state: StateManager, graph: GraphClient, stats: dict) -> None:
        pending = await state.get_pending_chunks(filing_id)
        stats["chunks_unchanged"] += len(await state.get_chunks(filing_id)) - len(pending)
        if self.save_payloads:
            record = await state.get_filing(filing_id)
            directory = self.payload_dir / record.ticker / record.accession_number.replace("-", "")
            directory.mkdir(parents=True, exist_ok=True)
            for chunk in await state.get_chunks(filing_id):
                (directory / f"{chunk.chunk_id}.json").write_text(
                    json.dumps(chunk.payload, indent=2, ensure_ascii=False), encoding="utf-8"
                )

        async def deliver(chunk) -> Optional[str]:
            try:
                if chunk.payload is None:
                    raise ValueError(f"Missing persisted payload: {chunk.chunk_id}")
                await graph.upload_payload(chunk.chunk_id, chunk.payload)
            except Exception as exc:
                logger.error("Upload failed for %s: %s", chunk.chunk_id, exc)
                return str(exc)
            return None

        # Retain bounded PUT concurrency; each acknowledgment checkpoints its own item.
        batch_size = min(self.config.processing.batch_size, 5)
        for start in range(0, len(pending), batch_size):
            batch = pending[start:start + batch_size]
            errors = await asyncio.gather(*(deliver(chunk) for chunk in batch))
            for chunk, error in zip(batch, errors):
                if error is not None:
                    await state.update_chunk_state(chunk.chunk_id, ChunkState.FAILED, error)
                    stats["errors"] += 1
                else:
                    await state.update_chunk_state(chunk.chunk_id, ChunkState.UPLOADED)
                    stats["chunks_uploaded"] += 1
        if await state.check_all_chunks_uploaded(filing_id):
            record = await state.get_filing(filing_id)
            sampled = record.sample_limit is not None
            if not sampled:
                if not await self._delete_items(
                    await state.stale_item_ids(filing_id), state, graph, stats
                ):
                    await state.update_filing_state(
                        filing_id, FilingState.FAILED, "Obsolete items remain; resume to retry deletions"
                    )
                    return
            await state.update_filing_state(
                filing_id, FilingState.SAMPLED if sampled else FilingState.COMPLETED
            )
            stats["filings_sampled" if sampled else "filings_completed"] += 1
        else:
            await state.update_filing_state(filing_id, FilingState.FAILED, "Pending or failed uploads")

    async def _delete_items(self, item_ids: list[str], state: StateManager, graph: GraphClient, stats: dict) -> bool:
        success = True
        for item_id in item_ids:
            try:
                try:
                    await graph.delete_item(item_id)
                except aiohttp.ClientResponseError as exc:
                    if exc.status != 404:
                        raise
                await state.acknowledge_delete(item_id)
                stats["chunks_deleted"] += 1
            except Exception:
                logger.exception("Failed to delete obsolete item %s", item_id)
                stats["errors"] += 1
                success = False
        return success

    async def _retire_filing(self, filing_id: int, state: StateManager, graph: GraphClient, stats: dict) -> None:
        await state.update_filing_state(filing_id, FilingState.RETIRING)
        if await self._delete_items(await state.stale_item_ids(filing_id, retire=True), state, graph, stats):
            await state.finish_retirement(filing_id)
            stats["filings_retired"] += 1

    async def _process_filing(
        self, filing_id: int, sec: SECClient, state: StateManager, graph: GraphClient, stats: dict,
    ) -> None:
        try:
            await self._prepare_filing(filing_id, sec, state, graph, stats)
            await self._deliver_filing(filing_id, state, graph, stats)
        except Exception as exc:
            logger.exception("Failed processing filing %s", filing_id)
            await state.update_filing_state(filing_id, FilingState.FAILED, str(exc))
            stats["errors"] += 1

    async def resume(self) -> dict:
        ensure_directories(self.config)
        stats = self._stats()
        stats["filings_resumed"] = 0
        async with (
            self._state() as state,
            SECClient(self.config) as sec,
            GraphClient(self.config) as graph,
        ):
            start_date = self.config.filings.start_date
            end_date = self.config.filings.end_date
            run_id = await state.start_run({
                "resume": True,
                "start_date": start_date.isoformat() if start_date else None,
                "end_date": end_date.isoformat() if end_date else None,
            })
            for record in await state.get_resume_candidates():
                if ((start_date and record.filing_date.date() < start_date)
                    or (end_date and record.filing_date.date() > end_date)):
                    stats["filings_outside_window"] += 1
                    continue
                if record.state == FilingState.RETIRING:
                    await self._retire_filing(record.id, state, graph, stats)
                else:
                    await self._process_filing(record.id, sec, state, graph, stats)
                stats["filings_resumed"] += 1
            if stats["filings_outside_window"]:
                logger.info("Left %s queued filings outside the configured date window untouched",
                            stats["filings_outside_window"])
            await state.finish_run(run_id, stats)
        return stats

    async def status(self) -> dict:
        async with self._state() as state:
            return await state.get_stats()

    async def reset(self) -> None:
        # Hold the destination lock across remote deletion and local cleanup.
        async with self._state() as state, GraphClient(self.config) as graph:
            try:
                await graph.delete_connection()
            except aiohttp.ClientResponseError as exc:
                if exc.status != 404:
                    raise
            await state.clear()
        console.print("[green]Connection reset acknowledged; scoped state cleared. Run setup next.[/]")
