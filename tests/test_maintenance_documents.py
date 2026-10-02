"""Exact multi-document inventory maintenance using only synthetic local data."""

import asyncio
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3

from click.testing import CliRunner
import pytest

from sec_connector import maintenance as m
from sec_connector.chunker import chunk_with_limit
from sec_connector.cli import main
from sec_connector.models import ChunkState, DocumentInfo, FilingMetadata, FilingState
from sec_connector.parser import parse_document
from sec_connector.pipeline import IngestionPipeline, document_fingerprint
from tests.test_maintenance import prepared, run, local, phase  # noqa: F401


def selections(plan):
    return [(d["scope"]["DocumentName"], d["scope"]["Sequence"], Path(d["source"]))
            for d in plan["documents"]]


async def reprepare(case, selected=None):
    config, graph, plan, _, root = case
    output = root / "second-multi.json"
    digest = await m.prepare_documents(
        config, graph, cik=plan["scope"]["CIK"], accession=plan["scope"]["AccessionNumber"],
        selections=selections(plan) if selected is None else selected, output=output,
    )
    return config, graph, m.load_plan(output, digest), digest, root


def unrelated(case):
    with closing(m.read_only(Path(case[2]["database"]))) as db:
        return m.snapshot(db, 2)


def remote_unrelated(case):
    return {i: p for i, p in case[1].items.items() if i not in m.tracked_ids(case[2])}


def ids_for(plan, index, kind="desired"):
    name = plan["documents"][index]["scope"]["DocumentName"]
    payloads = plan["old"] if kind == "stale" else plan["desired"]
    order = plan["desired_order"] if kind == "desired" else plan[kind]
    return [i for i in order if payloads[i]["properties"]["DocumentName"] == name]


@pytest.fixture
async def multi(prepared, request):
    config, graph, single, _, root = prepared
    count = getattr(request, "param", 4)
    filing = FilingMetadata.model_validate_json(single["old_local"]["filing"]["metadata"])
    options = json.loads(single["old_local"]["filing"]["processing_options"])
    selected = [("proxy.htm", 1, Path(single["source"]))]
    documents = [
        DocumentInfo(sequence=2, filename="subsidiaries.htm", document_type="EX-21"),
        DocumentInfo(sequence=5, filename="consent.txt", document_type="EX-23"),
        DocumentInfo(sequence=10, filename="certification.htm", document_type="EX-31"),
    ][:count - 1]
    async with IngestionPipeline(config)._state() as state:
        await state.set_inventory(1, documents)
        for doc in documents:
            source = root / doc.filename
            text = f"Synthetic {doc.document_type} disclosure. " * 12
            source.write_text(text if source.suffix == ".txt" else f"<html><body><p>{text}</p></body></html>")
            payloads = [graph.build_payload(c) for c in chunk_with_limit(
                parse_document(source, filing, doc), config.chunking,
            )]
            assert len(payloads) > 2
            old = [deepcopy(payloads[0]), deepcopy(payloads[0])]
            old[0]["content"]["value"] = f"Old common {doc.filename}"
            old[1]["id"] = old[1]["id"].rsplit("-", 1)[0] + "-9999"
            old[1]["properties"].update(Page=9999, ChunkOrdinal=2)
            old[1]["content"]["value"] = f"Old stale {doc.filename}"
            await state.save_document_payloads(
                1, doc, old, document_fingerprint(m.file_hash(source), filing, doc, options),
            )
            for p in old:
                await state.update_chunk_state(p["id"], ChunkState.UPLOADED)
                graph.items[p["id"]] = deepcopy(p)
            selected.append((doc.filename, doc.sequence, source))
        await state.mark_payloads_ready(1)
        await state.update_filing_state(1, FilingState.COMPLETED)
        other_filing = FilingMetadata.model_validate_json((await m.async_snapshot(state._db, 2))["filing"]["metadata"])
        other_doc = DocumentInfo(sequence=1, filename="unrelated.txt", document_type="DEF 14A")
        other_source = root / other_doc.filename
        other_source.write_text("Unrelated disclosure must not be rewritten.")
        other = [graph.build_payload(c) for c in chunk_with_limit(
            parse_document(other_source, other_filing, other_doc), config.chunking,
        )]
        await state.set_inventory(2, [other_doc])
        await state.save_document_payloads(
            2, other_doc, other, document_fingerprint(m.file_hash(other_source), other_filing, other_doc, options),
        )
        await state.mark_payloads_ready(2)
        for p in other:
            await state.update_chunk_state(p["id"], ChunkState.UPLOADED)
            graph.items[p["id"]] = deepcopy(p)
        await state.update_filing_state(2, FilingState.COMPLETED)
    output = root / "multi.json"
    digest = await m.prepare_documents(
        config, graph, cik=filing.cik, accession=filing.accession_number,
        selections=list(reversed(selected)), output=output,
    )
    graph.events.clear()
    return config, graph, m.load_plan(output, digest), digest, root


@pytest.mark.parametrize("multi", [2, 4], indirect=True)
async def test_complete_inventory_atomic_apply_and_rollback(multi, monkeypatch):
    config, graph, plan, digest, root = multi
    db_path = Path(plan["database"])
    before, lock_time = db_path.read_bytes(), db_path.with_suffix(".db.lock").stat().st_mtime_ns
    other_rows, other_remote = unrelated(multi), remote_unrelated(multi)
    second = await reprepare(multi, list(reversed(selections(plan))))
    assert db_path.read_bytes() == before
    assert db_path.with_suffix(".db.lock").stat().st_mtime_ns == lock_time
    assert second[2]["documents"] == plan["documents"]
    assert second[2]["desired_order"] == plan["desired_order"]
    assert len(plan["documents"]) == len(plan["old_local"]["documents"])
    assert len(plan["desired"]) > len(plan["documents"])
    assert set(plan["baseline_absent"]) == set(plan["new"])
    info = m.inspect(plan, digest)
    assert info["plan_format"] == 3 and info["processing_version"] == 8
    assert len(info["documents"]) == len(plan["documents"])
    # Forward replay and rollback must not reparse any document.
    monkeypatch.setattr(m, "parse_document", lambda *a, **k: pytest.fail("reparsed frozen payloads"))
    assert await run(multi) == "completed"
    assert graph.items == {**other_remote, **plan["desired"]}
    first_delete = next(n for n, event in enumerate(graph.events) if event[0] == "delete")
    for item_id in plan["desired"]:
        assert ("put", item_id) in graph.events[:first_delete]
        assert ("get", item_id) in graph.events[:first_delete]
    current = local(multi)
    assert current["documents"] == plan["old_local"]["documents"]
    assert all(c["state"] == "uploaded" for c in current["chunks"])
    assert {r["chunk_id"]: r["payload_hash"] for r in current["delivered_items"]} == plan["desired_hashes"]
    for entry in plan["documents"]:
        name = entry["scope"]["DocumentName"]
        cache = next(r for r in current["document_cache"] if r["filename"] == name)
        expected = [plan["desired"][i] for i in plan["desired_order"]
                    if plan["desired"][i]["properties"]["DocumentName"] == name]
        assert json.loads(cache["payloads"]) == expected
        assert cache["fingerprint"] == entry["fingerprint"]
        assert [p["properties"]["ChunkOrdinal"] for p in expected] == list(range(1, len(expected) + 1))
    with closing(m.read_only(root / "recovery" / "state.db")) as backup:
        assert m.snapshot(backup, 1) == plan["old_local"]
        assert m.snapshot(backup, 2) == other_rows
    assert unrelated(multi) == other_rows
    for entry in plan["documents"]:
        Path(entry["source"]).unlink()
    graph.events.clear()
    assert await run(multi, "rollback") == "rolled_back"
    assert local(multi) == plan["old_local"]
    assert graph.items == {**other_remote, **plan["old"]}
    assert unrelated(multi) == other_rows
    first_delete = next(n for n, event in enumerate(graph.events) if event[0] == "delete")
    assert all(("put", i) in graph.events[:first_delete] and ("get", i) in graph.events[:first_delete]
               for i in plan["old"])
    with closing(m.read_only(db_path)) as db:
        assert db.execute("SELECT version FROM destination").fetchone()[0] == 4


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("failure", ["before_put", "after_put", "before_delete", "after_delete", "get"])
@pytest.mark.parametrize("recovery", ["resume", "rollback"])
async def test_every_document_unknown_outcome_is_recoverable(multi, index, failure, recovery):
    _, graph, plan, _, _ = multi
    other_rows, other_remote = unrelated(multi), remote_unrelated(multi)
    item_id = ids_for(plan, index, "stale")[0] if "delete" in failure else ids_for(plan, index)[1]
    action = "apply"
    if failure == "get":
        graph.fail = ("before_put", plan["desired_order"][0])
        with pytest.raises(RuntimeError):
            await run(multi)
        action = "resume"
    graph.fail = (failure, item_id)
    with pytest.raises(RuntimeError, match=failure):
        await run(multi, action)
    state, journal = phase(multi)
    assert state not in m.TERMINAL
    if "delete" in failure:
        assert all(journal["put"][i].get("ack") and journal["put"][i].get("verified") for i in plan["desired"])
        assert "desired_set_verified" in journal
        assert journal["delete"][item_id]["intent"]
    else:
        assert not any(e[0] == "delete" for e in graph.events)
    assert await run(multi, recovery) == ("completed" if recovery == "resume" else "rolled_back")
    assert graph.items == {**other_remote, **plan["desired" if recovery == "resume" else "old"]}
    assert unrelated(multi) == other_rows
    if recovery == "rollback":
        assert local(multi) == plan["old_local"]


@pytest.mark.parametrize("index", range(4))
@pytest.mark.parametrize("failure", ["after_put", "after_delete"])
async def test_rollback_crash_in_each_document(multi, index, failure):
    _, graph, plan, _, _ = multi
    other = remote_unrelated(multi)
    await run(multi)
    item_id = ids_for(plan, index, "new")[0] if failure == "after_delete" else ids_for(plan, index, "stale")[0]
    graph.fail = (failure, item_id)
    with pytest.raises(RuntimeError):
        await run(multi, "rollback")
    assert phase(multi)[0] == "rolling_back"
    with pytest.raises(ValueError, match="Rollback has started"):
        await run(multi, "resume")
    assert await run(multi, "rollback") == "rolled_back"
    assert graph.items == {**other, **plan["old"]}
    assert local(multi) == plan["old_local"]


@pytest.mark.parametrize("checkpoint", ["intent", "ack", "verified", "gate"])
async def test_later_document_checkpoint_crash(multi, monkeypatch, checkpoint):
    _, graph, plan, _, _ = multi
    original = m.checkpoint
    item_id = ids_for(plan, 2)[1]

    async def fail(db, digest, phase_name, data):
        if checkpoint in data["put"].get(item_id, {}) or (checkpoint == "gate" and "desired_set_verified" in data):
            raise RuntimeError("checkpoint crash")
        await original(db, digest, phase_name, data)

    with monkeypatch.context() as patch:
        patch.setattr(m, "checkpoint", fail)
        with pytest.raises(RuntimeError, match="checkpoint crash"):
            await run(multi)
    assert not any(e[0] == "delete" for e in graph.events)
    assert await run(multi, "resume") == "completed"


@pytest.mark.parametrize("transition", ["forward", "completed", "rolled_back"])
async def test_atomic_full_manifest_transitions(multi, monkeypatch, transition):
    config, graph, plan, digest, root = multi
    other = unrelated(multi)
    action = "apply"
    if transition == "rolled_back":
        await run(multi)
        action = "rollback"
    before = local(multi)
    original = m.save_operation

    async def fail(db, digest, phase_name, data):
        if phase_name == transition:
            raise RuntimeError("transaction crash")
        await original(db, digest, phase_name, data)

    with monkeypatch.context() as patch:
        patch.setattr(m, "save_operation", fail)
        with pytest.raises(RuntimeError, match="transaction crash"):
            await run(multi, action)
    assert unrelated(multi) == other
    if transition == "forward":
        assert local(multi) == before
        assert not any(e[0] in {"put", "delete"} for e in graph.events)
        with closing(m.read_only(Path(plan["database"]))) as db:
            assert db.execute("SELECT version FROM destination").fetchone()[0] == 3
        assert await m.execute(config, graph, plan, digest, "apply", acknowledged=True,
                               recovery=root / "retry-recovery") == "completed"
        return
    assert local(multi)["filing"]["state"] == ("completed" if transition == "rolled_back" else "parsed")
    assert await run(multi, "rollback" if transition == "rolled_back" else "resume") in m.TERMINAL
    if transition == "rolled_back":
        assert local(multi) == plan["old_local"]


@pytest.mark.parametrize("problem", [
    "subset", "duplicate", "sequence", "source_name", "source", "cache", "mixed_options",
    "missing_cache", "orphan_cache", "empty_document", "orphan_chunk", "orphan_delivery",
    "inventory", "pending", "sample", "not_ready", "doc_error", "doc_failed",
    "pending_chunk", "delivered_hash", "reconciliation", "old_ocr", "new_ocr", "missing_old_ocr",
    "remote_absent", "remote_foreign", "remote_acl", "new_collision", "cross_filing",
])
async def test_unsupported_inventory_is_readonly(multi, problem):
    config, graph, plan, _, root = multi
    selected = selections(plan)
    name = selected[-1][0]
    old_id = ids_for(plan, 3, "stale")[0]
    with sqlite3.connect(plan["database"]) as db:
        if problem == "subset":
            selected.pop()
        elif problem == "duplicate":
            selected.append(selected[0])
        elif problem == "sequence":
            selected[-1] = (name, 1, selected[-1][2])
        elif problem == "source_name":
            selected[-1] = (name, selected[-1][1], selected[0][2])
        elif problem == "source":
            selected[-1][2].write_text("Wrong source")
        elif problem == "cache":
            db.execute("UPDATE document_cache SET fingerprint='unknown' WHERE filename=?", (name,))
        elif problem == "mixed_options":
            options = json.loads(plan["old_local"]["filing"]["processing_options"])
            options["processing_version"] += 1
            doc = DocumentInfo.model_validate_json(plan["old_local"]["documents"][-1]["metadata"])
            filing = FilingMetadata.model_validate_json(plan["old_local"]["filing"]["metadata"])
            fingerprint = document_fingerprint(m.file_hash(selected[-1][2]), filing, doc, options)
            db.execute("UPDATE document_cache SET fingerprint=? WHERE filename=?", (fingerprint, name))
        elif problem == "missing_cache":
            db.execute("DELETE FROM document_cache WHERE filename=?", (name,))
        elif problem == "orphan_cache":
            db.execute("INSERT INTO document_cache SELECT filing_id,'orphan.htm',fingerprint,payloads FROM document_cache LIMIT 1")
        elif problem == "empty_document":
            db.execute("DELETE FROM chunks WHERE filename=?", (name,))
        elif problem == "orphan_chunk":
            db.execute("UPDATE chunks SET filename='orphan.htm' WHERE chunk_id=?", (old_id,))
        elif problem == "orphan_delivery":
            db.execute("INSERT INTO delivered_items VALUES ('orphan',1,'hash',NULL)")
        elif problem in {"inventory", "pending", "sample", "not_ready"}:
            sql = {"inventory": "inventory_complete=0", "pending": "state='parsed'",
                   "sample": "sample_limit=5", "not_ready": "payloads_ready=0"}[problem]
            db.execute(f"UPDATE filings SET {sql} WHERE id=1")
        elif problem in {"doc_error", "doc_failed"}:
            sql = "error_message='parse problem'" if problem == "doc_error" else "state='failed'"
            db.execute(f"UPDATE documents SET {sql} WHERE filename=?", (name,))
        elif problem == "pending_chunk":
            db.execute("UPDATE chunks SET state='pending' WHERE chunk_id=?", (old_id,))
        elif problem == "delivered_hash":
            db.execute("UPDATE delivered_items SET payload_hash='wrong' WHERE chunk_id=?", (old_id,))
        elif problem == "reconciliation":
            db.execute("INSERT INTO reconciliation_candidates VALUES (?,1)", (old_id,))
        elif problem in {"old_ocr", "missing_old_ocr"}:
            options = json.loads(plan["old_local"]["filing"]["processing_options"])
            if problem == "old_ocr":
                options["ocr_images"] = True
            else:
                del options["ocr_images"]
            db.execute("UPDATE filings SET processing_options=? WHERE id=1", (json.dumps(options),))
        elif problem == "new_ocr":
            config.processing.ocr_images = True
        elif problem == "remote_absent":
            del graph.items[old_id]
        elif problem == "remote_foreign":
            graph.items[old_id]["properties"]["DocumentName"] = "foreign.htm"
        elif problem == "remote_acl":
            graph.items[old_id]["acl"] = []
        elif problem == "new_collision":
            item_id = ids_for(plan, 3, "new")[0]
            graph.items[item_id] = deepcopy(plan["desired"][item_id])
        elif problem == "cross_filing":
            db.execute("INSERT INTO reconciliation_candidates VALUES (?,2)", (ids_for(plan, 3, "new")[0],))
    path = Path(plan["database"])
    before = path.read_bytes()
    old_remote = deepcopy(graph.items)
    with pytest.raises(ValueError):
        await reprepare(multi, selected)
    assert path.read_bytes() == before and graph.items == old_remote
    assert not (root / "second-multi.json").exists()
    assert not any(e[0] in {"put", "delete"} for e in graph.events)


@pytest.mark.parametrize("drift", ["source", "local", "schema", "tenant", "app", "destination", "acl"])
async def test_apply_rechecks_all_document_bindings(multi, drift):
    config, graph, plan, _, root = multi
    if drift == "source":
        Path(plan["documents"][-1]["source"]).write_text("Changed after review")
    elif drift == "local":
        with sqlite3.connect(plan["database"]) as db:
            db.execute("UPDATE document_cache SET payloads='[]' WHERE filename=?", (selections(plan)[-1][0],))
    elif drift == "schema":
        graph.schema["changed"] = True
    elif drift == "acl":
        graph.items[ids_for(plan, 3, "stale")[0]]["acl"] = []
    else:
        setattr(config.azure, {"tenant": "tenant_id", "app": "client_id", "destination": "connection_id"}[drift], "other")
    with pytest.raises(ValueError):
        await run(multi)
    assert not (root / "recovery").exists()
    assert not any(e[0] in {"put", "delete"} for e in graph.events)


async def test_cross_document_desired_gate_and_stale_drift(multi):
    _, graph, plan, _, _ = multi
    graph.fail = ("before_delete", plan["stale"][0])
    with pytest.raises(RuntimeError):
        await run(multi)
    graph.items[ids_for(plan, 3)[0]]["content"]["value"] = "Later document drift"
    graph.events.clear()
    with pytest.raises(ValueError, match="drift"):
        await run(multi, "resume")
    assert not any(e[0] == "delete" for e in graph.events)
    graph.items[ids_for(plan, 3)[0]] = deepcopy(plan["desired"][ids_for(plan, 3)[0]])
    graph.items[plan["stale"][0]]["acl"] = []
    graph.events.clear()
    with pytest.raises(ValueError, match="drift"):
        await run(multi, "resume")
    assert not any(e[0] == "delete" for e in graph.events)


async def test_unrelated_later_work_survives_rollback(multi):
    _, graph, plan, _, _ = multi
    await run(multi)
    with sqlite3.connect(plan["database"]) as db:
        db.execute("UPDATE documents SET error_message='unrelated later work' WHERE filing_id=2")
    other = unrelated(multi)
    other_id = next(iter(remote_unrelated(multi)))
    graph.items[other_id]["content"]["value"] = "Unrelated later remote work"
    other_remote = remote_unrelated(multi)
    await run(multi, "rollback")
    assert unrelated(multi) == other and remote_unrelated(multi) == other_remote


async def test_later_document_changes_block_rollback(multi):
    _, graph, plan, _, _ = multi
    await run(multi)
    with sqlite3.connect(plan["database"]) as db:
        db.execute("UPDATE document_cache SET fingerprint='later-ingestion' WHERE filename=?", (selections(plan)[-1][0],))
    graph.events.clear()
    with pytest.raises(ValueError, match="Local maintenance scope drift"):
        await run(multi, "rollback")
    assert not any(e[0] in {"put", "delete"} for e in graph.events)


@pytest.mark.parametrize("problem", [
    "scope", "duplicate_sequence", "missing_primary", "cache_payload", "chunk_scope",
    "new_fingerprint", "source_bytes", "absences", "ordinals", "ordering", "desired_acl",
])
async def test_frozen_multidocument_structure_rejected_without_writes(multi, problem):
    config, graph, original, _, root = multi
    plan = deepcopy(original)
    entry = plan["documents"][-1]
    if problem == "scope":
        entry["scope"]["AccessionNumber"] = "0000000001-26-000999"
    elif problem == "duplicate_sequence":
        entry["scope"]["Sequence"] = 1
    elif problem == "missing_primary":
        metadata = json.loads(plan["old_local"]["filing"]["metadata"])
        metadata["primary_document"] = "missing.htm"
        plan["old_local"]["filing"]["metadata"] = json.dumps(metadata)
    elif problem == "cache_payload":
        plan["old_local"]["document_cache"][-1]["payloads"] = "[]"
    elif problem == "chunk_scope":
        plan["old_local"]["chunks"][-1]["sequence"] = 1
    elif problem == "new_fingerprint":
        entry["fingerprint"] = "wrong"
    elif problem == "source_bytes":
        entry["source_bytes"] = "d3Jvbmc="
    elif problem == "absences":
        plan["baseline_absent"].pop(next(iter(plan["baseline_absent"])))
    elif problem == "ordinals":
        plan["desired"][ids_for(plan, 3)[0]]["properties"]["ChunkOrdinal"] = 2
        plan["desired_hashes"] = {i: m.payload_hash(p) for i, p in plan["desired"].items()}
    elif problem == "ordering":
        plan["desired_order"] = list(reversed(plan["desired_order"]))
    elif problem == "desired_acl":
        plan["desired"][ids_for(plan, 3)[0]]["acl"] = []
    with pytest.raises(ValueError):
        await m.execute(config, graph, plan, m.sha(plan), "apply", acknowledged=True, recovery=root / "invalid")
    assert not graph.events and not (root / "invalid").exists()


async def test_multidocument_lock_guard_backup_and_ack(multi, monkeypatch):
    config, graph, plan, digest, root = multi
    with pytest.raises(ValueError, match="quiescing"):
        await m.execute(config, graph, plan, digest, "apply", acknowledged=False, recovery=root / "recovery")
    async with IngestionPipeline(config)._state():
        with pytest.raises(RuntimeError, match="Another process"):
            await run(multi)
    assert not graph.events
    with monkeypatch.context() as patch:
        def disk_full(*args):
            raise OSError("disk full")
        patch.setattr(m, "write_new", disk_full)
        with pytest.raises(OSError, match="disk full"):
            await run(multi)
    assert not any(e[0] in {"put", "delete"} for e in graph.events)
    assert local(multi) == plan["old_local"]
    graph.fail = ("after_put", ids_for(plan, 2)[0])
    with pytest.raises(RuntimeError):
        await m.execute(config, graph, plan, digest, "apply", acknowledged=True, recovery=root / "good-recovery")
    with pytest.raises(RuntimeError, match="Unfinished maintenance"):
        async with IngestionPipeline(config)._state():
            pytest.fail("ordinary writer entered guarded state")
    (root / "good-recovery" / "state.db").unlink()
    graph.events.clear()
    for action in ("resume", "rollback"):
        with pytest.raises(FileNotFoundError):
            await run(multi, action)
    assert not any(e[0] in {"put", "delete"} for e in graph.events)


@pytest.mark.parametrize("interrupted", [False, True])
async def test_legacy_format2_digest_drift_and_source_free_rollback(prepared, monkeypatch, interrupted):
    """Freeze the v2 shape with PR4 provenance; never rehash an activated plan."""
    from tests.test_maintenance_recovery import interrupt

    config, graph, current, _, root = prepared
    if interrupted:
        interrupt(prepared, remote_ids=[])
    inherited = deepcopy(current["provenance"])
    inherited["modules"]["maintenance"] = "b7becf9da52cb5514be1636e4fe276a899609466269ae72a9cc90db4659e7f66"
    output = root / "legacy-v2.json"
    with monkeypatch.context() as patch:
        patch.setattr(m, "provenance", lambda _: deepcopy(inherited))
        digest = await m.prepare(
            config, graph, cik=current["scope"]["CIK"], accession=current["scope"]["AccessionNumber"],
            filename="proxy.htm", sequence=1, source=Path(current["source"]), output=output,
            recover_prepared=interrupted,
        )
        plan = m.load_plan(output, digest)
        case = config, graph, plan, digest, root
        frozen = output.read_bytes()
        graph.fail = ("after_put", plan["desired_order"][0])
        with pytest.raises(RuntimeError):
            await run(case)
    assert m.inspect(plan, digest)["plan_format"] == 2
    with pytest.raises(ValueError, match="retain the original plan and runtime"):
        await run(case, "resume")
    Path(plan["source"]).unlink()
    assert await run(case, "rollback") == "rolled_back"
    assert graph.items == plan["old"] and local(case) == plan["old_local"]
    assert m.load_plan(output, digest) == plan and output.read_bytes() == frozen


def test_cli_selection_validation_precedes_configuration(tmp_path, monkeypatch):
    source = tmp_path / "doc.htm"
    source.write_text("<p>synthetic</p>")
    monkeypatch.setattr("sec_connector.cli.maintenance_config", lambda _: pytest.fail("configuration accessed"))
    base = ["maintenance", "prepare", "--cik", "0000000001", "--accession", "0000000001-26-000001",
            "--out", str(tmp_path / "plan.json")]
    selected = ["--document", source.name, "1", str(source)]
    for options in ([], selected, selected * 2 + ["--recover-prepared"],
                    selected * 2 + ["--filename", source.name]):
        result = CliRunner().invoke(main, base + options)
        assert result.exit_code == 2, result.output
    help_result = CliRunner().invoke(main, ["maintenance", "prepare", "--help"])
    assert help_result.exit_code == 0 and "--document" in help_result.output


async def test_cli_dispatches_exact_selection(multi, monkeypatch):
    config, graph, plan, _, root = multi
    config.azure.client_secret = "offline-only"
    monkeypatch.setattr("sec_connector.cli.maintenance_config", lambda _: config)
    seen = []

    class Client:
        def __init__(self, _):
            pass

        async def __aenter__(self):
            return graph

        async def __aexit__(self, *args):
            pass

    async def capture(configuration, client, **kwargs):
        assert configuration is config and client is graph
        seen.append(kwargs["selections"])
        return "synthetic-digest"

    monkeypatch.setattr(m, "MaintenanceGraphClient", Client)
    monkeypatch.setattr(m, "prepare_documents", capture)
    # CliRunner's synchronous dispatcher owns its own event loop.
    args = ["maintenance", "prepare", "--cik", plan["scope"]["CIK"],
            "--accession", plan["scope"]["AccessionNumber"], "--out", str(root / "cli-plan.json")]
    for name, sequence, source in selections(plan):
        args.extend(["--document", name, str(sequence), str(source)])
    result = await asyncio.to_thread(CliRunner().invoke, main, args)
    assert result.exit_code == 0, result.output
    assert seen == [tuple(selections(plan))]
