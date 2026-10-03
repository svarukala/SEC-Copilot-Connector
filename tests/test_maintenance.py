"""Customer/CI runnable maintenance safety tests; no credentials, SEC or Graph."""

import base64
from contextlib import closing
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import subprocess

import aiohttp
from click.testing import CliRunner
import pytest

from sec_connector import maintenance as m
from sec_connector.chunker import chunk_with_limit
from sec_connector.cli import main
from sec_connector.config import AppConfig
from sec_connector.graph_client import GraphClient
from sec_connector.models import ChunkState, DocumentInfo, FilingMetadata, FilingState
from sec_connector.parser import parse_document
from sec_connector.pipeline import IngestionPipeline, document_fingerprint
from sec_connector.state_manager import StateManager


class FakeGraph(GraphClient):
    def __init__(self, config):
        super().__init__(config)
        self.items = {}
        self.events = []
        self.fail = None
        self.schema = self.load_schema()
        self.keep_removed_property = False

    async def _get_token(self):
        claims = {"tid": self.config.azure.tenant_id, "appid": self.config.azure.client_id,
                  "aud": "https://graph.microsoft.com",
                  "roles": ["ExternalConnection.ReadWrite.All", "ExternalItem.ReadWrite.All"]}
        return "x." + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=") + ".x"

    async def get_connection(self):
        return {"id": self.config.azure.connection_id, "state": "ready"}

    async def get_schema_status(self):
        return deepcopy(self.schema)

    def failure(self, stage, item_id):
        if self.fail == (stage, item_id):
            self.fail = None
            raise RuntimeError(stage)

    async def _request(self, method, url, **kwargs):
        assert method == "GET"
        item_id = url.rsplit("/", 1)[1]
        self.events.append(("get", item_id))
        self.failure("get", item_id)
        if item_id not in self.items:
            raise aiohttp.ClientResponseError(None, (), status=404)
        return deepcopy(self.items[item_id])

    async def upload_payload(self, item_id, payload):
        self.events.append(("put", item_id))
        self.failure("before_put", item_id)
        previous = self.items.get(item_id, {})
        self.items[item_id] = deepcopy(payload)
        if self.keep_removed_property and "ReportPeriodEnd" in previous.get("properties", {}):
            self.items[item_id]["properties"]["ReportPeriodEnd"] = previous["properties"]["ReportPeriodEnd"]
        self.failure("after_put", item_id)

    async def delete_item(self, item_id):
        self.events.append(("delete", item_id))
        self.failure("before_delete", item_id)
        self.items.pop(item_id, None)
        self.failure("after_delete", item_id)


@pytest.fixture
async def prepared(tmp_path):
    config = AppConfig(
        azure={"tenant_id": "tenant", "client_id": "app", "connection_id": "testconnection"},
        chunking={"target_size": 100, "max_size": 180, "overlap": 10},
        paths={"database": str(tmp_path / "state.db"), "downloads": str(tmp_path / "downloads"),
               "payloads": str(tmp_path / "payloads"), "logs": str(tmp_path / "logs")},
    )
    filing = FilingMetadata(cik="0000000001", accession_number="0000000001-26-000001",
                            form="DEF 14A", filing_date=datetime(2026, 4, 1),
                            company_name="Synthetic Company", ticker="SYN",
                            primary_document="proxy.htm", report_period_end=datetime(2026, 4, 22))
    document = DocumentInfo(sequence=1, filename="proxy.htm", document_type="DEF 14A")
    source = tmp_path / document.filename
    source.write_text("<html><body><h1>Compensation</h1><p>" +
                      "Synthetic compensation disclosure for 2025. " * 20 + "</p></body></html>")
    graph = FakeGraph(config)
    desired = [graph.build_payload(c, icon_url=config.azure.icon_url)
               for c in chunk_with_limit(parse_document(source, filing, document), config.chunking)]
    assert len(desired) > 2
    old = [deepcopy(desired[0]), deepcopy(desired[0])]
    old[0]["content"]["value"] = "Old common content"
    old[1]["id"] = "0000000001-000000000126000001-1-9999"
    old[1]["properties"]["Page"] = 9999
    old[1]["properties"]["ChunkOrdinal"] = 2
    old[1]["content"]["value"] = "Old stale content"
    for p in old:
        p["properties"]["ReportPeriodEnd"] = "2026-04-22T00:00:00Z"
    pipeline = IngestionPipeline(config)
    options = {**pipeline._processing_options(), "processing_version": 3}
    async with pipeline._state() as state:
        filing_id = await state.add_filing(filing, processing_options=options)
        await state.set_inventory(filing_id, [document])
        await state.save_document_payloads(
            filing_id, document, old, document_fingerprint(m.file_hash(source), filing, document, options),
        )
        await state.mark_payloads_ready(filing_id)
        for p in old:
            await state.update_chunk_state(p["id"], ChunkState.UPLOADED)
        await state.update_filing_state(filing_id, FilingState.COMPLETED)
        unrelated = filing.model_copy(update={"cik": "0000000002", "ticker": "UNRELATED"})
        await state.add_filing(unrelated, processing_options=options)
    graph.items = {p["id"]: deepcopy(p) for p in old}
    output = tmp_path / "plan.json"
    digest = await m.prepare(config, graph, cik=filing.cik, accession=filing.accession_number,
                             filename=document.filename, sequence=1, source=source, output=output)
    plan = m.load_plan(output, digest)
    graph.events.clear()
    return config, graph, plan, digest, tmp_path


async def run(prepared, action="apply", **kwargs):
    config, graph, plan, digest, root = prepared
    return await m.execute(config, graph, plan, digest, action, acknowledged=True,
                           recovery=root / "recovery", **kwargs)


def local(prepared):
    config, _, plan, _, _ = prepared
    with closing(m.read_only(IngestionPipeline(config).db_path)) as db:
        return m.snapshot(db, plan["old_local"]["filing"]["id"])


def phase(prepared):
    config, _, _, digest, _ = prepared
    with closing(m.read_only(IngestionPipeline(config).db_path)) as db:
        row = db.execute("SELECT phase,data FROM maintenance_operations WHERE digest=?", (digest,)).fetchone()
        return row[0], json.loads(row[1])


async def test_prepare_readonly_apply_and_scoped_rollback(prepared):
    config, graph, plan, digest, root = prepared
    path = IngestionPipeline(config).db_path
    before = path.read_bytes()
    lock_time = path.with_suffix(".db.lock").stat().st_mtime_ns
    await m.prepare(config, graph, cik=plan["scope"]["CIK"], accession=plan["scope"]["AccessionNumber"],
                    filename="proxy.htm", sequence=1, source=Path(plan["source"]), output=root / "second.json")
    assert m.inspect(plan, digest)["phase"] == "prepared"
    assert path.read_bytes() == before
    assert path.with_suffix(".db.lock").stat().st_mtime_ns == lock_time
    with closing(m.read_only(path)) as db:
        unrelated = m.snapshot(db, 2)
    assert await run(prepared) == "completed"
    assert graph.items == plan["desired"]
    assert all("ReportPeriodEnd" not in p["properties"] for p in graph.items.values())
    first_delete = next(i for i, e in enumerate(graph.events) if e[0] == "delete")
    assert all(("put", item_id) in graph.events[:first_delete] and
               ("get", item_id) in graph.events[:first_delete] for item_id in plan["desired"])
    result = local(prepared)
    assert result["filing"]["state"] == "completed"
    assert json.loads(result["filing"]["processing_options"])["processing_version"] == 9
    assert len(result["chunks"]) == len(plan["desired"])
    assert all(c["state"] == "uploaded" for c in result["chunks"])
    assert not result["reconciliation_candidates"]
    assert {r["chunk_id"]: r["payload_hash"] for r in result["delivered_items"]} == plan["desired_hashes"]
    assert json.loads(result["document_cache"][0]["payloads"]) == [
        plan["desired"][i] for i in plan["desired_order"]
    ]
    assert (root / "recovery" / "state.db").exists()
    with closing(m.read_only(path)) as db:
        assert m.snapshot(db, 2) == unrelated
        assert db.execute("SELECT version FROM destination").fetchone()[0] == 4
    async with IngestionPipeline(config)._state() as state:
        assert all(r.id != 1 for r in await state.get_resume_candidates())
    graph.events.clear()
    assert await run(prepared, "rollback") == "rolled_back"
    assert graph.items == plan["old"]
    assert local(prepared) == plan["old_local"]
    first_delete = next(i for i, e in enumerate(graph.events) if e[0] == "delete")
    assert all(("put", i) in graph.events[:first_delete] and ("get", i) in graph.events[:first_delete]
               for i in plan["old"])
    with closing(m.read_only(path)) as db:
        assert m.snapshot(db, 2) == unrelated
        assert db.execute("SELECT version FROM destination").fetchone()[0] == 4


@pytest.mark.parametrize("stage", ["before_put", "after_put", "before_delete", "after_delete", "get"])
async def test_partial_unknown_outcomes_resume(prepared, stage):
    _, graph, plan, _, _ = prepared
    item_id = plan["stale"][0] if "delete" in stage else plan["desired_order"][1]
    # GET failure is injected after activation so the guard must remain.
    if stage == "get":
        graph.fail = ("before_put", plan["desired_order"][0])
        with pytest.raises(RuntimeError):
            await run(prepared)
        graph.fail = ("get", item_id)
        action = "resume"
    else:
        graph.fail = (stage, item_id)
        action = "apply"
    with pytest.raises(RuntimeError):
        await run(prepared, action)
    assert phase(prepared)[0] not in m.TERMINAL
    if "delete" not in stage:
        assert not any(e[0] == "delete" for e in graph.events)
    assert await run(prepared, "resume") == "completed"
    assert graph.items == plan["desired"]


async def test_omitted_property_not_removed_blocks_all_deletes(prepared):
    _, graph, plan, _, _ = prepared
    graph.keep_removed_property = True
    with pytest.raises(ValueError, match="Exact GET"):
        await run(prepared)
    assert not any(e[0] == "delete" for e in graph.events)
    # Service violated replacement semantics: do not replay/delete-recreate around it.
    with pytest.raises(ValueError, match="drift"):
        await run(prepared, "resume")
    assert phase(prepared)[0] == "forward"


@pytest.mark.parametrize("drift", ["source", "config", "schema", "destination", "app", "local", "collision", "old", "acl", "type"])
async def test_apply_preflight_drift_is_write_free(prepared, drift):
    config, graph, plan, _, root = prepared
    if drift == "source":
        Path(plan["source"]).write_text("Changed")
    elif drift == "config":
        config.chunking.overlap = 5
    elif drift == "schema":
        graph.schema["extra"] = "changed"
    elif drift == "destination":
        config.azure.connection_id = "different"
    elif drift == "app":
        config.azure.client_id = "different"
    elif drift == "local":
        with sqlite3.connect(plan["database"]) as db:
            db.execute("UPDATE filings SET error_message='drift' WHERE id=1")
    elif drift == "collision":
        graph.items[plan["new"][0]] = deepcopy(plan["desired"][plan["new"][0]])
    elif drift == "old":
        graph.items[next(iter(plan["old"]))]["content"]["value"] = "drift"
    elif drift == "acl":
        graph.items[next(iter(plan["old"]))]["acl"] = []
    else:
        graph.items[next(iter(plan["old"]))]["properties"]["Sequence"] = True
    with pytest.raises(ValueError):
        await run(prepared)
    assert not any(e[0] in {"put", "delete"} for e in graph.events)
    assert not (root / "recovery").exists()


async def test_plan_digest_rejects_tampering(prepared):
    _, _, _, digest, root = prepared
    path = root / "plan.json"
    plan = json.loads(path.read_bytes())
    plan["stale"] = []
    path.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="digest"):
        m.load_plan(path, digest)


async def test_stale_drift_after_upload_blocks_delete(prepared):
    _, graph, plan, _, _ = prepared
    graph.fail = ("before_delete", plan["stale"][0])
    with pytest.raises(RuntimeError):
        await run(prepared)
    graph.items[plan["stale"][0]]["content"]["value"] = "Foreign writer"
    graph.events.clear()
    with pytest.raises(ValueError, match="drift"):
        await run(prepared, "resume")
    assert not any(e[0] == "delete" for e in graph.events)


@pytest.mark.parametrize("failure", ["before_put", "after_put", "before_delete", "after_delete"])
async def test_resumable_rollback(prepared, failure):
    _, graph, plan, _, _ = prepared
    await run(prepared)
    item_id = plan["new"][0] if "delete" in failure else next(iter(plan["old"]))
    graph.fail = (failure, item_id)
    with pytest.raises(RuntimeError):
        await run(prepared, "rollback")
    assert phase(prepared)[0] == "rolling_back"
    with pytest.raises(ValueError, match="Rollback has started"):
        await run(prepared, "resume")
    assert await run(prepared, "rollback") == "rolled_back"
    assert graph.items == plan["old"]
    assert local(prepared) == plan["old_local"]


async def test_rollback_never_deletes_foreign_new_id(prepared):
    _, graph, plan, _, _ = prepared
    await run(prepared)
    graph.items[plan["new"][0]]["acl"] = []
    graph.events.clear()
    with pytest.raises(ValueError, match="drift"):
        await run(prepared, "rollback")
    assert all(graph.items[i] == p for i, p in plan["old"].items())
    assert ("delete", plan["new"][0]) not in graph.events
    assert phase(prepared)[0] == "rolling_back"


async def test_backup_failure_prevents_format_change_and_put(prepared, monkeypatch):
    _, graph, plan, _, _ = prepared
    monkeypatch.setattr(m, "write_new", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        await run(prepared)
    assert local(prepared) == plan["old_local"]
    with closing(m.read_only(Path(plan["database"]))) as db:
        assert db.execute("SELECT version FROM destination").fetchone()[0] == 3
    assert not any(e[0] == "put" for e in graph.events)


async def test_sqlite_backup_includes_committed_wal_and_unrelated_rows(prepared):
    _, _, plan, _, root = prepared
    with closing(sqlite3.connect(plan["database"])) as connection:
        assert connection.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        connection.execute("PRAGMA wal_autocheckpoint=0")
        connection.execute("UPDATE filings SET error_message='committed WAL row' WHERE id=2")
        connection.commit()
        assert Path(plan["database"] + "-wal").stat().st_size > 0
        await run(prepared)
        with closing(m.read_only(root / "recovery" / "state.db")) as backup:
            assert backup.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
            assert m.snapshot(backup, 1) == plan["old_local"]
            assert backup.execute("SELECT error_message FROM filings WHERE id=2").fetchone()[0] == "committed WAL row"


@pytest.mark.parametrize("checkpoint", ["intent", "ack", "verified", "gate"])
async def test_checkpoint_crash_preserves_replayable_intent(prepared, monkeypatch, checkpoint):
    _, graph, plan, _, _ = prepared
    original = m.checkpoint

    async def fail(db, digest, phase, data):
        entry = data["put"].get(plan["desired_order"][0], {})
        should_fail = (checkpoint in entry or (checkpoint == "gate" and "desired_set_verified" in data))
        if should_fail:
            raise RuntimeError("checkpoint crash")
        await original(db, digest, phase, data)

    with monkeypatch.context() as patch:
        patch.setattr(m, "checkpoint", fail)
        with pytest.raises(RuntimeError, match="checkpoint crash"):
            await run(prepared)
    assert not any(e[0] == "delete" for e in graph.events)
    assert await run(prepared, "resume") == "completed"
    assert graph.items == plan["desired"]


async def test_rollback_final_transaction_failure(prepared, monkeypatch):
    _, graph, plan, _, _ = prepared
    await run(prepared)
    original = m.save_operation

    async def fail(db, digest, phase, data):
        if phase == "rolled_back":
            raise RuntimeError("rollback final crash")
        await original(db, digest, phase, data)
    with monkeypatch.context() as patch:
        patch.setattr(m, "save_operation", fail)
        with pytest.raises(RuntimeError, match="rollback final"):
            await run(prepared, "rollback")
    assert json.loads(local(prepared)["filing"]["processing_options"])["processing_version"] == 9
    assert await run(prepared, "rollback") == "rolled_back"
    assert local(prepared) == plan["old_local"]
    assert graph.items == plan["old"]


async def test_completed_operation_cannot_rollback_later_local_work(prepared):
    _, graph, plan, _, _ = prepared
    await run(prepared)
    with sqlite3.connect(plan["database"]) as db:
        db.execute("UPDATE filings SET metadata = '{}' WHERE id = 1")
    graph.events.clear()
    with pytest.raises(ValueError, match="Local maintenance scope drift"):
        await run(prepared, "rollback")
    assert not any(e[0] in {"put", "delete"} for e in graph.events)


async def test_rollback_does_not_require_original_source(prepared):
    _, graph, plan, _, _ = prepared
    await run(prepared)
    Path(plan["source"]).unlink()
    assert await run(prepared, "rollback") == "rolled_back"
    assert graph.items == plan["old"]


async def test_unowned_new_id_is_not_removed_on_early_rollback(prepared):
    _, graph, plan, _, _ = prepared
    graph.fail = ("before_put", plan["desired_order"][0])
    with pytest.raises(RuntimeError):
        await run(prepared)
    graph.items[plan["new"][0]] = deepcopy(plan["desired"][plan["new"][0]])
    graph.events.clear()
    with pytest.raises(ValueError, match="unowned"):
        await run(prepared, "rollback")
    assert ("delete", plan["new"][0]) not in graph.events


@pytest.mark.parametrize("args", [
    ["setup"], ["ingest", "-t", "SYN"], ["resume"], ["reset", "--yes"],
])
async def test_cli_guard_precedes_logs_directories_and_network(prepared, monkeypatch, args):
    config, graph, plan, _, root = prepared
    graph.fail = ("before_put", plan["desired_order"][0])
    with pytest.raises(RuntimeError):
        await run(prepared)
    config.azure.client_secret = "offline-test-only"
    monkeypatch.setattr("sec_connector.cli.load_config", lambda _: config)
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 1
    assert "Unfinished maintenance" in result.output
    for path in ("logs", "payloads", "downloads"):
        assert not (root / path).exists()


async def test_migration_contract_is_permanent_offline(prepared):
    """The released v3 reader accepted exactly (1, 2, 3), before executescript."""
    _, _, plan, _, _ = prepared
    await run(prepared)
    for action in (None, "rollback"):
        if action:
            await run(prepared, action)
        with closing(m.read_only(Path(plan["database"]))) as db:
            row = db.execute("SELECT tenant_id, connection_id, version FROM destination").fetchone()
        # Frozen old-reader compatibility predicate; requires no git history.
        assert row["version"] not in (1, 2, 3)
        assert row["version"] == 4


def test_strict_service_metadata_normalization():
    schema = GraphClient.load_schema()
    raw = {"id": "item", "properties": {"Title": "test"},
           "content": {"type": "text", "value": "test", "@odata.type": "x"},
           "acl": [{"type": "everyone", "value": "everyone", "accessType": "grant", "@odata.type": "x"}]}
    base, metadata = m.normalized(raw, schema)
    assert not metadata
    raw["properties"].update({
        key: False if key == "IsDGBasedSecurityEnabled" else "00000000-0000-0000-0000-000000000000"
        for key in m.SERVICE_METADATA_KEYS
    })
    result, metadata = m.normalized(raw, schema)
    assert result == base and len(metadata) == 5
    raw["properties"]["ows_SiteID"] = "invalid"
    with pytest.raises(RuntimeError, match="type"):
        m.normalized(raw, schema)
    raw["properties"].pop("ows_SiteID")
    with pytest.raises(RuntimeError, match="set"):
        m.normalized(raw, schema)


@pytest.mark.parametrize("mutation", ["id", "acl", "duplicate"])
async def test_payload_scope_acl_and_duplicate_rejected(prepared, mutation):
    config, _, plan, _, _ = prepared
    payloads = list(deepcopy(plan["desired"]).values())
    if mutation == "id":
        payloads[0]["id"] = "foreign-item"
    elif mutation == "acl":
        payloads[0]["acl"] = []
    else:
        payloads.append(payloads[0])
    with pytest.raises(ValueError):
        m.validate_payloads(payloads, plan["scope"], config.chunking.max_item_bytes)


async def test_transport_does_not_retry_mutations_or_allow_connection_delete(prepared):
    config, graph, _, _, _ = prepared
    transport = m.MaintenanceGraphClient(config)
    transport._get_token = graph._get_token

    class Response:
        status = 503

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def raise_for_status(self):
            raise aiohttp.ClientResponseError(None, (), status=self.status)

    class Session:
        calls = 0

        def request(self, *args, **kwargs):
            self.calls += 1
            return Response()

    transport._session = Session()
    for verb in ("PUT", "DELETE"):
        with pytest.raises(aiohttp.ClientResponseError):
            await transport._request_result(verb, "/external/connections/testconnection/items/scoped-id")
    assert transport._session.calls == 2
    with pytest.raises(ValueError, match="forbids"):
        await transport.delete_connection()
    assert transport._session.calls == 2

async def test_missing_backup_blocks_resume_and_rollback(prepared):
    _, graph, plan, _, root = prepared
    graph.fail = ("before_put", plan["desired_order"][0])
    with pytest.raises(RuntimeError):
        await run(prepared)
    (root / "recovery" / "state.db").unlink()
    graph.events.clear()
    for action in ("resume", "rollback"):
        with pytest.raises(FileNotFoundError):
            await run(prepared, action)
    assert not any(e[0] in {"put", "delete"} for e in graph.events)


async def test_atomic_activation_failure(prepared, monkeypatch):
    _, graph, plan, _, _ = prepared
    original = m.save_operation

    async def fail(db, digest, phase, data):
        if phase == "forward":
            raise RuntimeError("activation crash")
        await original(db, digest, phase, data)
    monkeypatch.setattr(m, "save_operation", fail)
    with pytest.raises(RuntimeError, match="activation crash"):
        await run(prepared)
    assert local(prepared) == plan["old_local"]
    with closing(m.read_only(Path(plan["database"]))) as db:
        assert db.execute("SELECT version FROM destination").fetchone()[0] == 3
    assert not any(e[0] == "put" for e in graph.events)


async def test_atomic_final_transition_failure_resumes(prepared, monkeypatch):
    _, graph, plan, _, _ = prepared
    original = m.save_operation

    async def fail(db, digest, phase, data):
        if phase == "completed":
            raise RuntimeError("final crash")
        await original(db, digest, phase, data)
    with monkeypatch.context() as patch:
        patch.setattr(m, "save_operation", fail)
        with pytest.raises(RuntimeError, match="final crash"):
            await run(prepared)
    assert local(prepared)["filing"]["state"] == "parsed"
    assert await run(prepared, "resume") == "completed"
    assert graph.items == plan["desired"]


@pytest.mark.parametrize("command", ["setup", "ingest", "resume", "reset"])
async def test_guard_blocks_normal_pipeline_before_clients(prepared, monkeypatch, command):
    config, graph, plan, _, _ = prepared
    graph.fail = ("before_put", plan["desired_order"][0])
    with pytest.raises(RuntimeError):
        await run(prepared)
    def forbidden(*args):
        pytest.fail("Network client created before guard")
    forbidden.load_schema = GraphClient.load_schema
    monkeypatch.setattr("sec_connector.pipeline.GraphClient", forbidden)
    monkeypatch.setattr("sec_connector.pipeline.SECClient", forbidden)
    pipeline = IngestionPipeline(config)
    with pytest.raises(RuntimeError, match="Unfinished maintenance"):
        await getattr(pipeline, command)(*(["SYN"],) if command == "ingest" else ())


async def test_lock_fails_closed(prepared):
    config, graph, _, _, _ = prepared
    async with IngestionPipeline(config)._state():
        with pytest.raises(RuntimeError, match="Another process"):
            await run(prepared)
    assert graph.events == []


async def test_no_activation_without_operator_ack(prepared):
    config, graph, plan, digest, root = prepared
    with pytest.raises(ValueError, match="quiescing"):
        await m.execute(config, graph, plan, digest, "apply", acknowledged=False, recovery=root / "recovery")
    assert local(prepared) == plan["old_local"]
    assert not (root / "recovery").exists()
    assert not graph.events


async def test_failed_desired_get_after_stale_retirement_never_completes(prepared):
    _, graph, plan, _, _ = prepared
    original = graph.delete_item
    first = plan["desired_order"][0]

    async def delete_and_drift(item_id):
        await original(item_id)
        graph.items[first]["content"]["value"] = "Concurrent drift"
    graph.delete_item = delete_and_drift
    with pytest.raises(ValueError, match="Exact GET"):
        await run(prepared)
    assert phase(prepared)[0] == "verified"
    assert local(prepared)["filing"]["state"] == "parsed"


async def test_false_delete_success_is_not_absence(prepared):
    _, graph, plan, _, _ = prepared

    async def no_op(item_id):
        graph.events.append(("delete", item_id))
    graph.delete_item = no_op
    with pytest.raises(ValueError, match="absence not confirmed"):
        await run(prepared)
    assert phase(prepared)[0] == "verified"
    assert plan["stale"][0] in graph.items


async def test_active_scope_tamper_blocks_recovery_before_put(prepared):
    _, graph, plan, _, _ = prepared
    graph.fail = ("before_put", plan["desired_order"][0])
    with pytest.raises(RuntimeError):
        await run(prepared)
    with sqlite3.connect(plan["database"]) as db:
        db.execute("UPDATE chunks SET state = 'uploaded' WHERE filing_id = 1")
    graph.events.clear()
    with pytest.raises(ValueError, match="Local maintenance scope drift"):
        await run(prepared, "resume")
    assert not any(e[0] in {"put", "delete"} for e in graph.events)


async def test_old_code_rejects_format4_before_mutation(prepared, tmp_path):
    _, graph, plan, _, _ = prepared
    graph.fail = ("before_put", plan["desired_order"][0])
    with pytest.raises(RuntimeError):
        await run(prepared)
    # Exercise the actual default-branch implementation, not a simulated version check.
    try:
        old_code = subprocess.check_output(
            ["git", "show", "9c75379916fb2f5b10f7907ac884ebcdd7998f66:src/sec_connector/state_manager.py"],
            text=True, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("Optional historical executable check requires baseline git object")
    module = {"__name__": "sec_connector.old_state", "__package__": "sec_connector"}
    exec(compile(old_code, "<old-StateManager>", "exec"), module)
    before = Path(plan["database"]).read_bytes()
    with pytest.raises(RuntimeError, match="format"):
        async with module["StateManager"](Path(plan["database"]), "tenant", "testconnection"):
            pytest.fail("Old code adopted format 4")
    assert Path(plan["database"]).read_bytes() == before


@pytest.mark.parametrize("problem", ["multidoc", "sample", "inflight", "inventory", "ownership", "source", "cache"])
async def test_prepare_rejects_unsupported_state(prepared, problem):
    config, graph, plan, _, root = prepared
    if problem == "source":
        Path(plan["source"]).write_text("changed source")
    else:
        with sqlite3.connect(plan["database"]) as db:
            if problem == "multidoc":
                db.execute("INSERT INTO documents SELECT filing_id,'other.htm',metadata,state,error_message FROM documents WHERE filing_id=1")
            elif problem == "sample":
                db.execute("UPDATE filings SET sample_limit=1 WHERE id=1")
            elif problem == "inflight":
                db.execute("UPDATE filings SET state='failed' WHERE id=1")
            elif problem == "inventory":
                db.execute("UPDATE filings SET inventory_complete=0 WHERE id=1")
            elif problem == "ownership":
                db.execute("INSERT INTO reconciliation_candidates VALUES (?,2)", (plan["new"][0],))
            else:
                db.execute("UPDATE document_cache SET fingerprint='wrong' WHERE filing_id=1")
    before = Path(plan["database"]).read_bytes()
    with pytest.raises(ValueError):
        await m.prepare(config, graph, cik=plan["scope"]["CIK"], accession=plan["scope"]["AccessionNumber"],
                        filename="proxy.htm", sequence=1, source=Path(plan["source"]), output=root / "bad.json")
    assert Path(plan["database"]).read_bytes() == before
    assert not any(e[0] in {"put", "delete"} for e in graph.events)


def test_help_and_missing_ack_are_safe():
    runner = CliRunner()
    for action in ("prepare", "inspect", "apply", "resume", "rollback"):
        result = runner.invoke(main, ["maintenance", action, "--help"])
        assert result.exit_code == 0, result.output
    result = runner.invoke(main, ["maintenance", "--help"])
    assert "Old clients" in result.output
    assert runner.invoke(main, ["maintenance", "apply"]).exit_code != 0
