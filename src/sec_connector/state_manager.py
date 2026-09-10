"""Destination-scoped SQLite checkpoints and durable upload manifests."""

import hashlib
import json
import os
from pathlib import Path
from typing import BinaryIO, Optional

import aiosqlite

from .models import ChunkRecord, ChunkState, DocumentInfo, FilingMetadata, FilingRecord, FilingState
from .payloads import payload_hash


def scoped_database_path(base: Path, tenant_id: str, connection_id: str) -> Path:
    """Keep different Graph destinations physically separate."""
    if not tenant_id.strip() or not connection_id.strip():
        raise ValueError("tenant_id and connection_id are required for scoped state")
    identity = json.dumps([tenant_id.lower(), connection_id]).encode("utf-8")
    suffix = hashlib.sha256(identity).hexdigest()[:20]
    return base.with_name(f"{base.stem}.{suffix}{base.suffix or '.db'}")


class StateManager:
    """Own one destination's state and an OS-released exclusive run lock."""

    def __init__(self, db_path: Path, tenant_id: str, connection_id: str):
        if not tenant_id.strip() or not connection_id.strip():
            raise ValueError("A state destination requires both tenant_id and connection_id")
        self.db_path = db_path
        self.identity = (tenant_id.lower(), connection_id)
        self._db: Optional[aiosqlite.Connection] = None
        self._lock: Optional[BinaryIO] = None

    def _acquire_lock(self) -> None:
        lock = self.db_path.with_suffix(self.db_path.suffix + ".lock").open("a+b")
        if lock.seek(0, os.SEEK_END) == 0:
            lock.write(b"\0")
            lock.flush()
        lock.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            lock.close()
            raise RuntimeError(f"Another process is using connector state: {self.db_path}") from exc
        self._lock = lock

    async def __aenter__(self) -> "StateManager":
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_lock()
        try:
            self._db = await aiosqlite.connect(self.db_path)
            self._db.row_factory = aiosqlite.Row
            await self._db.execute("PRAGMA foreign_keys = ON")
            await self._init_schema()
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        try:
            if self._db:
                await self._db.close()
                self._db = None
        finally:
            if self._lock:
                self._lock.close()
                self._lock = None

    async def _init_schema(self) -> None:
        cursor = await self._db.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        )
        tables = {row["name"] for row in await cursor.fetchall()}
        if tables and "destination" not in tables:
            raise RuntimeError(
                f"Unscoped legacy state at {self.db_path}; archive it and use a new "
                "connection for reingestion. Automatic destination adoption is unsafe."
            )
        version = 3
        if "destination" in tables:
            cursor = await self._db.execute("SELECT tenant_id, connection_id, version FROM destination")
            row = await cursor.fetchone()
            if not row or (row["tenant_id"], row["connection_id"]) != self.identity or row["version"] not in (1, 2, 3):
                raise RuntimeError("State destination or format does not match this connector")
            version = row["version"]

        await self._db.executescript("""
            CREATE TABLE IF NOT EXISTS destination (
                tenant_id TEXT NOT NULL,
                connection_id TEXT NOT NULL,
                version INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS filings (
                id INTEGER PRIMARY KEY,
                cik TEXT NOT NULL,
                accession_number TEXT NOT NULL,
                metadata TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                inventory_complete INTEGER NOT NULL DEFAULT 0,
                payloads_ready INTEGER NOT NULL DEFAULT 0,
                sample_limit INTEGER,
                processing_options TEXT NOT NULL,
                error_message TEXT,
                UNIQUE(cik, accession_number)
            );
            CREATE TABLE IF NOT EXISTS documents (
                filing_id INTEGER NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                metadata TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT,
                PRIMARY KEY(filing_id, filename)
            );
            CREATE TABLE IF NOT EXISTS chunks (
                chunk_id TEXT PRIMARY KEY,
                filing_id INTEGER NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                page_number INTEGER NOT NULL,
                sequence INTEGER NOT NULL,
                payload TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending',
                error_message TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_filings_state ON filings(state);
            CREATE INDEX IF NOT EXISTS idx_chunks_filing ON chunks(filing_id);
            CREATE TABLE IF NOT EXISTS delivered_items (
                chunk_id TEXT PRIMARY KEY,
                filing_id INTEGER NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
                payload_hash TEXT NOT NULL,
                error_message TEXT
            );
            CREATE TABLE IF NOT EXISTS reconciliation_candidates (
                chunk_id TEXT PRIMARY KEY,
                filing_id INTEGER NOT NULL REFERENCES filings(id) ON DELETE CASCADE
            );
            CREATE INDEX IF NOT EXISTS idx_reconciliation_filing
                ON reconciliation_candidates(filing_id);
            CREATE TABLE IF NOT EXISTS document_cache (
                filing_id INTEGER NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
                filename TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                payloads TEXT NOT NULL,
                PRIMARY KEY(filing_id, filename)
            );
            CREATE TABLE IF NOT EXISTS runs (
                id INTEGER PRIMARY KEY,
                started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                completed_at TEXT,
                status TEXT NOT NULL DEFAULT 'running',
                scope TEXT NOT NULL,
                stats TEXT
            );
        """)
        if "destination" not in tables:
            await self._db.execute("INSERT INTO destination VALUES (?, ?, 3)", self.identity)
        elif version == 1:
            cursor = await self._db.execute("SELECT * FROM chunks WHERE state = 'uploaded'")
            for chunk in await cursor.fetchall():
                await self._db.execute(
                    "INSERT OR REPLACE INTO delivered_items VALUES (?, ?, ?, NULL)",
                    (chunk["chunk_id"], chunk["filing_id"], payload_hash(json.loads(chunk["payload"]))),
                )
        if version < 3:
            await self._db.execute("UPDATE destination SET version = 3")
        await self._db.commit()

    @staticmethod
    def _filing_record(row) -> FilingRecord:
        return FilingRecord(
            **json.loads(row["metadata"]), id=row["id"], state=FilingState(row["state"]),
            inventory_complete=bool(row["inventory_complete"]),
            payloads_ready=bool(row["payloads_ready"]), sample_limit=row["sample_limit"],
            processing_options=json.loads(row["processing_options"]),
            error_message=row["error_message"],
        )

    async def add_filing(
        self, filing: FilingMetadata, sample_limit: Optional[int] = None,
        processing_options: Optional[dict] = None,
    ) -> int:
        # Preserve the original metadata and manifest for in-flight retries.
        await self._db.execute(
            """INSERT INTO filings(cik, accession_number, metadata, sample_limit, processing_options)
               VALUES (?, ?, ?, ?, ?) ON CONFLICT(cik, accession_number) DO NOTHING""",
            (filing.cik, filing.accession_number, filing.model_dump_json(), sample_limit,
             json.dumps(processing_options or {})),
        )
        await self._db.commit()
        return await self.get_filing_id(filing.cik, filing.accession_number)

    async def get_filing_id(self, cik: str, accession_number: str) -> Optional[int]:
        cursor = await self._db.execute(
            "SELECT id FROM filings WHERE cik = ? AND accession_number = ?", (cik, accession_number)
        )
        row = await cursor.fetchone()
        return row["id"] if row else None

    async def get_filing(self, filing_id: int) -> FilingRecord:
        cursor = await self._db.execute("SELECT * FROM filings WHERE id = ?", (filing_id,))
        row = await cursor.fetchone()
        if row is None:
            raise ValueError(f"Unknown filing: {filing_id}")
        return self._filing_record(row)

    async def get_filings_by_state(self, state: FilingState) -> list[FilingRecord]:
        cursor = await self._db.execute("SELECT * FROM filings WHERE state = ?", (state.value,))
        return [self._filing_record(row) for row in await cursor.fetchall()]

    async def update_filing_state(
        self, filing_id: int, state: FilingState, error_message: Optional[str] = None,
    ) -> None:
        if state in (FilingState.COMPLETED, FilingState.SAMPLED):
            if not await self.check_all_chunks_uploaded(filing_id):
                raise ValueError("Cannot complete a filing with incomplete inventory or delivery")
            if state == FilingState.COMPLETED and await self.stale_item_ids(filing_id):
                raise ValueError("Cannot complete a filing with obsolete remote items")
            await self._db.execute(
                """DELETE FROM reconciliation_candidates WHERE filing_id = ? AND chunk_id IN
                   (SELECT chunk_id FROM chunks WHERE filing_id = ? AND state = 'uploaded')""",
                (filing_id, filing_id),
            )
        await self._db.execute(
            "UPDATE filings SET state = ?, error_message = ? WHERE id = ?",
            (state.value, error_message, filing_id),
        )
        await self._db.commit()

    async def set_inventory(self, filing_id: int, documents: list[DocumentInfo]) -> None:
        if not documents:
            raise ValueError("Filing inventory contains no processable documents")
        if len({doc.filename for doc in documents}) != len(documents):
            raise ValueError("Filing inventory contains duplicate filenames")
        try:
            await self._db.executemany(
                "INSERT INTO documents(filing_id, filename, metadata) VALUES (?, ?, ?)",
                [(filing_id, doc.filename, doc.model_dump_json()) for doc in documents],
            )
            await self._db.execute(
                "UPDATE filings SET inventory_complete = 1 WHERE id = ?", (filing_id,)
            )
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise

    async def get_documents(self, filing_id: int) -> list[dict]:
        cursor = await self._db.execute(
            "SELECT metadata, state, error_message FROM documents WHERE filing_id = ? ORDER BY rowid",
            (filing_id,),
        )
        return [
            {"document": DocumentInfo.model_validate_json(row["metadata"]),
             "state": row["state"], "error_message": row["error_message"]}
            for row in await cursor.fetchall()
        ]

    async def update_document(
        self, filing_id: int, filename: str, state: str, error_message: Optional[str] = None,
    ) -> None:
        await self._db.execute(
            "UPDATE documents SET state = ?, error_message = ? WHERE filing_id = ? AND filename = ?",
            (state, error_message, filing_id, filename),
        )
        await self._db.commit()

    async def save_document_payloads(
        self, filing_id: int, document: DocumentInfo, payloads: list[dict],
        fingerprint: Optional[str] = None,
    ) -> None:
        if not payloads:
            raise ValueError(f"No content generated for {document.filename}")
        try:
            for p in payloads:
                cursor = await self._db.execute(
                    """SELECT payload_hash FROM delivered_items WHERE chunk_id = ?
                       AND chunk_id NOT IN (SELECT chunk_id FROM reconciliation_candidates)""",
                    (p["id"],)
                )
                previous = await cursor.fetchone()
                unchanged = previous is not None and previous["payload_hash"] == payload_hash(p)
                await self._db.execute(
                    """INSERT INTO chunks(chunk_id, filing_id, filename, page_number, sequence, payload, state)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (p["id"], filing_id, document.filename, p["properties"]["Page"],
                     document.sequence, json.dumps(p, ensure_ascii=False), "uploaded" if unchanged else "pending"),
                )
            if fingerprint is not None:
                await self._db.execute(
                    """INSERT INTO document_cache VALUES (?, ?, ?, ?)
                       ON CONFLICT(filing_id, filename) DO UPDATE SET
                       fingerprint = excluded.fingerprint, payloads = excluded.payloads""",
                    (filing_id, document.filename, fingerprint, json.dumps(payloads, ensure_ascii=False)),
                )
            await self._db.execute(
                """UPDATE documents SET state = 'parsed', error_message = NULL
                   WHERE filing_id = ? AND filename = ?""",
                (filing_id, document.filename),
            )
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise

    async def mark_payloads_ready(self, filing_id: int) -> None:
        cursor = await self._db.execute(
            """SELECT COUNT(*) AS total,
               SUM(CASE WHEN state NOT IN ('parsed', 'sampled_out') THEN 1 ELSE 0 END) AS pending
               FROM documents WHERE filing_id = ?""", (filing_id,)
        )
        row = await cursor.fetchone()
        if not row["total"] or row["pending"]:
            raise ValueError("Cannot publish an incomplete document manifest")
        await self._db.execute(
            "UPDATE filings SET payloads_ready = 1, state = 'parsed', error_message = NULL WHERE id = ?",
            (filing_id,),
        )
        await self._db.commit()

    async def get_chunks(self, filing_id: int, pending_only: bool = False) -> list[ChunkRecord]:
        query = "SELECT * FROM chunks WHERE filing_id = ?"
        if pending_only:
            query += " AND state != 'uploaded'"
        cursor = await self._db.execute(query + " ORDER BY rowid", (filing_id,))
        return [
            ChunkRecord(
                filing_id=row["filing_id"], chunk_id=row["chunk_id"],
                page_number=row["page_number"], sequence=row["sequence"],
                state=ChunkState(row["state"]), error_message=row["error_message"],
                payload=json.loads(row["payload"]),
            )
            for row in await cursor.fetchall()
        ]

    async def get_pending_chunks(self, filing_id: int) -> list[ChunkRecord]:
        return await self.get_chunks(filing_id, pending_only=True)

    async def update_chunk_state(
        self, chunk_id: str, state: ChunkState, error_message: Optional[str] = None,
    ) -> None:
        await self._db.execute(
            "UPDATE chunks SET state = ?, error_message = ? WHERE chunk_id = ?",
            (state.value, error_message, chunk_id),
        )
        if state == ChunkState.UPLOADED:
            cursor = await self._db.execute("SELECT filing_id, payload FROM chunks WHERE chunk_id = ?", (chunk_id,))
            row = await cursor.fetchone()
            if row is None:
                raise ValueError(f"Unknown chunk: {chunk_id}")
            await self._db.execute(
                "INSERT OR REPLACE INTO delivered_items VALUES (?, ?, ?, NULL)",
                (chunk_id, row["filing_id"], payload_hash(json.loads(row["payload"]))),
            )
        await self._db.commit()

    async def get_resume_candidates(self) -> list[FilingRecord]:
        cursor = await self._db.execute(
            "SELECT * FROM filings WHERE state NOT IN ('completed', 'sampled') ORDER BY id"
        )
        return [self._filing_record(row) for row in await cursor.fetchall()]

    async def check_all_chunks_uploaded(self, filing_id: int) -> bool:
        filing = await self.get_filing(filing_id)
        cursor = await self._db.execute(
            """SELECT COUNT(*) AS total,
               SUM(CASE WHEN state != 'uploaded' THEN 1 ELSE 0 END) AS pending
               FROM chunks WHERE filing_id = ?""", (filing_id,)
        )
        row = await cursor.fetchone()
        return bool(filing.inventory_complete and filing.payloads_ready and row["total"] and not row["pending"])

    async def expand_sample(self, filing_id: int) -> None:
        """Rebuild the sample with its captured settings; remote PUTs remain idempotent."""
        await self._db.execute("DELETE FROM chunks WHERE filing_id = ?", (filing_id,))
        await self._db.execute("DELETE FROM documents WHERE filing_id = ?", (filing_id,))
        await self._db.execute(
            """UPDATE filings SET state = 'pending', inventory_complete = 0, payloads_ready = 0,
               sample_limit = NULL, error_message = NULL WHERE id = ?""", (filing_id,)
        )
        await self._db.commit()

    async def begin_refresh(
        self, filing_id: int, filing: FilingMetadata, processing_options: dict, sample_limit: Optional[int],
        *, allow_inflight: bool = False,
    ) -> None:
        """Replace desired payloads, retaining uncertain PUTs separately from acknowledgments."""
        record = await self.get_filing(filing_id)
        if record.state == FilingState.RETIRING:
            raise ValueError("Finish retirement before rebuilding a filing")
        if record.state not in (FilingState.COMPLETED, FilingState.SAMPLED) and not allow_inflight:
            raise ValueError("Rebuilding an in-flight filing requires explicit allow_inflight=True")
        if record.state == FilingState.COMPLETED and sample_limit is not None:
            raise ValueError("Cannot sample-downgrade a completed filing")
        try:
            # A successful PUT may not have reached its local acknowledgment.
            await self._db.execute(
                """INSERT OR IGNORE INTO reconciliation_candidates(chunk_id, filing_id)
                   SELECT chunk_id, filing_id FROM chunks
                   WHERE filing_id = ? AND state != 'uploaded'""",
                (filing_id,),
            )
            await self._db.execute("DELETE FROM chunks WHERE filing_id = ?", (filing_id,))
            await self._db.execute("DELETE FROM documents WHERE filing_id = ?", (filing_id,))
            await self._db.execute(
                """UPDATE filings SET metadata = ?, processing_options = ?, sample_limit = ?,
                   state = 'pending', inventory_complete = 0, payloads_ready = 0, error_message = NULL
                   WHERE id = ?""",
                (filing.model_dump_json(), json.dumps(processing_options), sample_limit, filing_id),
            )
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise

    async def cached_payloads(self, filing_id: int, filename: str, fingerprint: str) -> Optional[list[dict]]:
        cursor = await self._db.execute(
            "SELECT payloads FROM document_cache WHERE filing_id = ? AND filename = ? AND fingerprint = ?",
            (filing_id, filename, fingerprint),
        )
        row = await cursor.fetchone()
        return json.loads(row["payloads"]) if row else None

    async def stale_item_ids(self, filing_id: int, retire: bool = False) -> list[str]:
        if retire:
            query = """SELECT chunk_id FROM delivered_items WHERE filing_id = ?
                       UNION SELECT chunk_id FROM chunks WHERE filing_id = ?
                       UNION SELECT chunk_id FROM reconciliation_candidates WHERE filing_id = ?"""
            params = (filing_id, filing_id, filing_id)
        else:
            record = await self.get_filing(filing_id)
            if record.sample_limit is not None or not await self.check_all_chunks_uploaded(filing_id):
                raise ValueError("Deleting stale items requires a complete unsampled upload manifest")
            query = """SELECT d.chunk_id FROM (
                           SELECT chunk_id FROM delivered_items WHERE filing_id = ?
                           UNION SELECT chunk_id FROM reconciliation_candidates WHERE filing_id = ?
                       ) d
                       LEFT JOIN chunks c ON c.chunk_id = d.chunk_id
                       WHERE c.chunk_id IS NULL"""
            params = (filing_id, filing_id)
        cursor = await self._db.execute(query, params)
        return [row["chunk_id"] for row in await cursor.fetchall()]

    async def acknowledge_delete(self, chunk_id: str) -> None:
        try:
            await self._db.execute("DELETE FROM delivered_items WHERE chunk_id = ?", (chunk_id,))
            await self._db.execute("DELETE FROM chunks WHERE chunk_id = ?", (chunk_id,))
            await self._db.execute("DELETE FROM reconciliation_candidates WHERE chunk_id = ?", (chunk_id,))
            await self._db.commit()
        except BaseException:
            await self._db.rollback()
            raise

    async def finish_retirement(self, filing_id: int) -> None:
        if await self.stale_item_ids(filing_id, retire=True):
            raise ValueError("Cannot retire a filing with unacknowledged remote deletions")
        await self._db.execute("DELETE FROM filings WHERE id = ?", (filing_id,))
        await self._db.commit()

    async def missing_filings(self, ticker: str, present: set[str]) -> list[FilingRecord]:
        cursor = await self._db.execute("SELECT * FROM filings ORDER BY id")
        records = [self._filing_record(row) for row in await cursor.fetchall()]
        return [r for r in records if r.ticker == ticker and r.accession_number not in present]

    async def start_run(self, scope: dict) -> int:
        # The destination OS lock proves any previous running record was interrupted.
        await self._db.execute("UPDATE runs SET status = 'interrupted' WHERE status = 'running'")
        cursor = await self._db.execute("INSERT INTO runs(scope) VALUES (?)", (json.dumps(scope),))
        await self._db.commit()
        return cursor.lastrowid

    async def finish_run(self, run_id: int, stats: dict) -> None:
        await self._db.execute(
            "UPDATE runs SET status = ?, completed_at = CURRENT_TIMESTAMP, stats = ? WHERE id = ?",
            ("failed" if stats["errors"] else "completed", json.dumps(stats), run_id),
        )
        await self._db.commit()

    async def get_stats(self) -> dict:
        stats = {}
        for table in ("filings", "chunks"):
            cursor = await self._db.execute(f"SELECT state, COUNT(*) AS count FROM {table} GROUP BY state")
            counts = {row["state"]: row["count"] for row in await cursor.fetchall()}
            stats[table] = counts
            stats[f"total_{table}"] = sum(counts.values())
        cursor = await self._db.execute("SELECT * FROM runs ORDER BY id DESC LIMIT 1")
        row = await cursor.fetchone()
        stats["last_run"] = dict(row) if row else None
        cursor = await self._db.execute("SELECT COUNT(*) AS count FROM delivered_items")
        stats["acknowledged_items"] = (await cursor.fetchone())["count"]
        return stats

    async def clear(self) -> None:
        """Retain destination identity and the lock while clearing its acknowledged reset."""
        await self._db.execute("DELETE FROM filings")
        await self._db.commit()
