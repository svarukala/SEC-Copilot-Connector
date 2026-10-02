"""Synthetic prepared-delivery and OCR provenance tests; no services or downloads."""

import base64
from contextlib import closing
from copy import deepcopy
import json
from pathlib import Path
import sqlite3
import struct
import sys
from types import SimpleNamespace
import zlib

import pytest

from sec_connector import maintenance as m, maintenance_ocr as ocr, parser
from sec_connector import ocr_engine
from sec_connector.config import OCRConfig
from sec_connector.models import DocumentInfo, FilingMetadata
from sec_connector.pipeline import IngestionPipeline, document_fingerprint
from sec_connector.payloads import serialize_item
from tests.test_maintenance import prepared, run, local, phase


async def reprepare(case, **kwargs):
    config, graph, plan, _, root = case
    output = root / "extended.json"
    digest = await m.prepare(
        config, graph, cik=plan["scope"]["CIK"], accession=plan["scope"]["AccessionNumber"],
        filename="proxy.htm", sequence=1, source=Path(plan["source"]), output=output, **kwargs,
    )
    frozen = m.load_plan(output, digest)
    graph.events.clear()
    return config, graph, frozen, digest, root


def interrupt(case, remote_ids, acknowledged=()):
    _, graph, plan, _, _ = case
    with sqlite3.connect(plan["database"]) as db:
        db.execute("UPDATE filings SET state='failed',error_message='Interrupted delivery' WHERE id=1")
        db.execute("UPDATE chunks SET state='failed',error_message='Unknown PUT outcome' WHERE filing_id=1")
        db.execute("DELETE FROM delivered_items WHERE filing_id=1")
        for item_id in acknowledged:
            db.execute("UPDATE chunks SET state='uploaded',error_message=NULL WHERE chunk_id=?", (item_id,))
            db.execute("INSERT INTO delivered_items VALUES (?,1,?,NULL)", (item_id, plan["old_hashes"][item_id]))
        db.execute("INSERT INTO reconciliation_candidates SELECT chunk_id,filing_id FROM chunks WHERE filing_id=1")
    graph.items = {i: deepcopy(plan["old"][i]) for i in remote_ids}


@pytest.fixture(params=["partial_ack", "lost_ack", "common_absent", "empty"])
async def recovering(prepared, request):
    _, _, plan, _, _ = prepared
    common, stale = list(plan["old"])
    present = {"partial_ack": [common, stale], "lost_ack": [common, stale],
               "common_absent": [stale], "empty": []}[request.param]
    interrupt(prepared, present, [common] if request.param == "partial_ack" else [])
    return await reprepare(prepared, recover_prepared=True)


async def test_recovery_restores_observed_baseline_not_prepared_manifest(recovering):
    _, graph, plan, digest, _ = recovering
    before = local(recovering)
    baseline = deepcopy(graph.items)
    assert plan["recovery_class"] == "prepared_delivery"
    assert plan["old"] == baseline
    assert m.inspect(plan, digest)["prepared_local_items"] == 2
    await run(recovering)
    assert graph.items == plan["desired"]
    assert local(recovering)["filing"]["state"] == "completed"
    if plan["stale"]:
        first_delete = next(i for i, e in enumerate(graph.events) if e[0] == "delete")
        assert all(("get", i) in graph.events[:first_delete] for i in plan["desired"])
        assert phase(recovering)[1]["desired_set_verified"]
    graph.events.clear()
    await run(recovering, "rollback")
    assert graph.items == baseline
    assert local(recovering) == before
    assert local(recovering)["filing"]["state"] == "failed"
    absent_old = set(plan["baseline_absent"]) - set(plan["desired"])
    assert all(("put", i) not in graph.events and ("delete", i) not in graph.events for i in absent_old)


@pytest.mark.parametrize("failure", ["before_put", "after_put", "get", "before_delete", "after_delete"])
async def test_recovered_delivery_failures_are_resumable(recovering, failure):
    _, graph, plan, _, _ = recovering
    target = plan["desired_order"][0]
    if "delete" in failure:
        if plan["stale"]:
            target = plan["stale"][0]
        else:
            # Exercise removal during rollback when the observed baseline has no stale IDs.
            await run(recovering)
            target = plan["new"][0]
            graph.fail = (failure, target)
            with pytest.raises(RuntimeError):
                await run(recovering, "rollback")
            await run(recovering, "rollback")
            assert graph.items == plan["old"]
            assert local(recovering) == plan["old_local"]
            return
    if failure == "get":
        graph.fail = ("before_put", target)
        with pytest.raises(RuntimeError):
            await run(recovering)
        action = "resume"
    else:
        action = "apply"
    graph.fail = (failure, target)
    with pytest.raises(RuntimeError):
        await run(recovering, action)
    await run(recovering, "resume")
    assert graph.items == plan["desired"]
    await run(recovering, "rollback")
    assert graph.items == plan["old"]
    assert local(recovering) == plan["old_local"]


@pytest.mark.parametrize("checkpoint", ["activation", "intent", "ack", "verified", "gate", "completed", "rolled_back"])
async def test_empty_baseline_atomic_recovery(prepared, monkeypatch, checkpoint):
    interrupt(prepared, [])
    case = await reprepare(prepared, recover_prepared=True)
    _, graph, plan, _, root = case
    original = m.save_operation

    async def crash(db, digest, phase, data):
        entry = data["put"].get(plan["desired_order"][0], {})
        if ((checkpoint == "activation" and not data["put"])
                or checkpoint in entry
                or (checkpoint == "gate" and phase == "verified")
                or phase == checkpoint):
            raise RuntimeError("injected crash")
        await original(db, digest, phase, data)

    if checkpoint == "rolled_back":
        await run(case)
    with monkeypatch.context() as patch:
        patch.setattr(m, "save_operation", crash)
        with pytest.raises(RuntimeError, match="injected crash"):
            await run(case, "rollback" if checkpoint == "rolled_back" else "apply")
    if checkpoint == "activation":
        assert local(case) == plan["old_local"] and not graph.items
        assert not any(e[0] in {"put", "delete"} for e in graph.events)
        await m.execute(case[0], graph, plan, case[3], "apply", acknowledged=True, recovery=root / "retry")
    else:
        await run(case, "rollback" if checkpoint == "rolled_back" else "resume")
    if checkpoint != "rolled_back":
        await run(case, "rollback")
    assert not graph.items
    assert local(case) == plan["old_local"]


@pytest.mark.parametrize("problem", [
    "inventory", "no_documents", "unprepared", "no_payloads", "download", "parse",
    "sample", "multidoc", "unknown_candidate", "old_hash", "missing_ack", "acked_absent",
    "foreign_remote", "running", "cross_filing",
])
async def test_incomplete_unsupported_classes_fail_without_writes(prepared, problem):
    _, graph, plan, _, root = prepared
    first = next(iter(plan["old"]))
    interrupt(prepared, list(plan["old"]))
    with sqlite3.connect(plan["database"]) as db:
        if problem == "inventory":
            db.execute("UPDATE filings SET inventory_complete=0 WHERE id=1")
        elif problem == "no_documents":
            db.execute("DELETE FROM documents WHERE filing_id=1")
        elif problem == "unprepared":
            db.execute("UPDATE filings SET payloads_ready=0 WHERE id=1")
        elif problem == "no_payloads":
            db.execute("DELETE FROM chunks WHERE filing_id=1")
        elif problem in {"download", "parse"}:
            db.execute("UPDATE documents SET state='failed',error_message=? WHERE filing_id=1", (problem,))
        elif problem == "sample":
            db.execute("UPDATE filings SET sample_limit=2 WHERE id=1")
        elif problem == "multidoc":
            db.execute("INSERT INTO documents SELECT filing_id,'extra.htm',metadata,state,error_message FROM documents WHERE filing_id=1")
        elif problem == "unknown_candidate":
            db.execute("INSERT INTO reconciliation_candidates VALUES ('0000000001-000000000126000001-1-8888',1)")
        elif problem == "old_hash":
            db.execute("INSERT INTO delivered_items VALUES (?,1,'different-generation',NULL)", (first,))
        elif problem == "missing_ack":
            db.execute("UPDATE chunks SET state='uploaded',error_message=NULL WHERE chunk_id=?", (first,))
        elif problem == "acked_absent":
            db.execute("INSERT INTO delivered_items VALUES (?,1,?,NULL)", (first, plan["old_hashes"][first]))
            del graph.items[first]
        elif problem == "foreign_remote":
            graph.items[first]["content"]["value"] = "An unowned different generation"
        elif problem == "running":
            db.execute("INSERT INTO runs(scope) VALUES ('{}')")
        else:
            db.execute("UPDATE reconciliation_candidates SET filing_id=2 WHERE chunk_id=?", (first,))
    before = Path(plan["database"]).read_bytes()
    remote = deepcopy(graph.items)
    with pytest.raises(ValueError):
        await reprepare(prepared, recover_prepared=True)
    assert Path(plan["database"]).read_bytes() == before
    assert graph.items == remote
    assert not (root / "extended.json").exists()
    assert not any(e[0] in {"put", "delete"} for e in graph.events)


async def test_old_only_absence_drift_is_never_adopted_or_deleted(prepared):
    _, graph, original, _, _ = prepared
    interrupt(prepared, [])
    case = await reprepare(prepared, recover_prepared=True)
    absent_stale = original["stale"][0]
    graph.fail = ("before_put", case[2]["desired_order"][0])
    with pytest.raises(RuntimeError):
        await run(case)
    graph.items[absent_stale] = original["old"][absent_stale]
    graph.events.clear()
    for action in ("resume", "rollback"):
        with pytest.raises(ValueError, match="Originally absent old-only"):
            await run(case, action)
    assert not any(e[0] in {"put", "delete"} for e in graph.events)


def png_bytes(color):
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
    header = struct.pack(">IIBBBBB", 12, 90, 8, 2, 0, 0, 0)
    pixels = (b"\0" + bytes(color) * 12) * 90
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")


@pytest.fixture
def fake_ocr(monkeypatch):
    """Exercise production rotate/upscale/cleanup; only decode and recognition are stubs."""
    calls = []
    labels = {png_bytes((255, 255, 255)): "2025", png_bytes((0, 0, 0)): "$1,234"}

    class Image:
        size = (12, 90)

        def __init__(self, asset):
            self.raw = asset.read() if hasattr(asset, "read") else Path(asset).read_bytes()
            assert self.raw in labels

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def rotate(self, degrees, expand):
            calls.append(("rotate", degrees, expand))
            self.size = (90, 12)
            return self

        def resize(self, size, resampling):
            calls.append(("resize", size, resampling))
            self.size = size
            return self

    def recognize(image, settings):
        calls.append(("ocr", "--psm 7"))
        return labels[image.raw]

    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(
        Image=SimpleNamespace(open=Image, Resampling=SimpleNamespace(LANCZOS="LANCZOS")),
    ))
    monkeypatch.setattr(parser, "image_to_text", recognize)
    engine = {"backend": ocr_engine.BACKEND, "engine_version": "offline-stub", "language": "eng", "config": "--psm 7"}
    monkeypatch.setattr(ocr, "runtime", lambda *args: deepcopy(engine))
    return calls, engine


def bind_source(case, content, *, old_ocr=True):
    _, _, plan, _, _ = case
    source = Path(plan["source"])
    source.write_text(content, encoding="utf-8")
    record = plan["old_local"]["filing"]
    filing = FilingMetadata.model_validate_json(record["metadata"])
    document = DocumentInfo.model_validate_json(plan["old_local"]["documents"][0]["metadata"])
    options = json.loads(record["processing_options"])
    options["ocr_images"] = old_ocr
    fingerprint = document_fingerprint(m.file_hash(source), filing, document, options)
    with sqlite3.connect(plan["database"]) as db:
        db.execute("UPDATE filings SET processing_options=? WHERE id=1", (json.dumps(options),))
        db.execute("UPDATE document_cache SET fingerprint=? WHERE filing_id=1", (fingerprint,))
    return filing, document


@pytest.fixture
async def with_ocr(prepared, fake_ocr):
    config, _, plan, _, root = prepared
    config.processing.ocr_images = True
    (root / "year.png").write_bytes(png_bytes((255, 255, 255)))
    (root / "amount.png").write_bytes(png_bytes((0, 0, 0)))
    html = (
        '<h1>Compensation</h1><p>Before disclosure.</p><table><tr><th>Metric</th>'
        '<th><img src="year.png" width="12" height="90"></th></tr>'
        '<tr><td>Total</td><td><img src="amount.png" width="12" height="90"></td></tr></table>'
        '<p>After disclosure.</p><img hidden src="hidden-missing.png" width="12" height="90">'
        '<img src="https://example.invalid/ordinary.png" width="300" height="200" alt="Chart">'
    )
    filing, document = bind_source(prepared, html)
    original = parser.parse_document(Path(plan["source"]), filing, document, ocr_images=True)
    capture = ocr.Capture(Path(plan["source"]))
    captured = parser.parse_document(
        Path(plan["source"]), filing, document, ocr_images=True, ocr_resolver=capture.resolve,
    )
    assert captured == original
    return await reprepare(prepared)


async def test_ocr_freezes_actual_order_outputs_without_graph_provenance(with_ocr, fake_ocr, monkeypatch):
    config, graph, plan, _, _ = with_ocr
    assets = plan["ocr"]["assets"]
    assert [a["src"] for a in assets] == ["year.png", "amount.png"]
    assert [a["text"] for a in assets] == ["2025", "$1,234"]
    assert "unknown" in plan["historical_ocr_provenance"]
    for a in assets:
        assert base64.b64decode(a["bytes"]) == Path(a["path"]).read_bytes()
    content = "\n".join(plan["desired"][i]["content"]["value"] for i in plan["desired_order"])
    assert "2025" in content and "$1,234" in content
    assert content.index("Before disclosure") < content.index("$1,234") < content.index("After disclosure")
    assert all(len(serialize_item(p)) <= config.chunking.max_item_bytes for p in plan["desired"].values())
    assert all(set(p) == {"id", "properties", "content", "acl"} for p in plan["desired"].values())
    assert all("maintenance_ocr" not in m.canonical(p) and "offline-stub" not in m.canonical(p)
               for p in plan["desired"].values())
    calls, _ = fake_ocr
    assert ("rotate", -90, True) in calls and ("resize", (720, 96), "LANCZOS") in calls
    assert ("ocr", "--psm 7") in calls
    monkeypatch.setattr(ocr, "ocr_asset_text", lambda _: pytest.fail("Recovery must never rerun OCR"))
    graph.fail = ("after_put", plan["desired_order"][0])
    with pytest.raises(RuntimeError):
        await run(with_ocr)
    await run(with_ocr, "resume")
    assert graph.items == plan["desired"]
    # A normal source-only fingerprint cannot reuse this bundle-bound cache.
    stored = local(with_ocr)
    options = IngestionPipeline(config)._processing_options()
    filing = FilingMetadata.model_validate_json(stored["filing"]["metadata"])
    doc = DocumentInfo.model_validate_json(stored["documents"][0]["metadata"])
    assert stored["document_cache"][0]["fingerprint"] != document_fingerprint(plan["source_hash"], filing, doc, options)


@pytest.mark.parametrize("drift", ["asset", "missing", "source", "language", "settings", "engine", "ocr_off"])
async def test_ocr_drift_fails_before_mutation(with_ocr, fake_ocr, monkeypatch, drift):
    config, graph, plan, _, root = with_ocr
    _, engine = fake_ocr
    if drift == "asset":
        (root / "year.png").write_bytes(b"changed")
    elif drift == "missing":
        (root / "year.png").unlink()
    elif drift == "source":
        Path(plan["source"]).write_text("changed")
    elif drift == "language":
        engine["language"] = "different"
    elif drift == "settings":
        engine["config"] = "--psm 6"
    elif drift == "engine":
        def unavailable(*args):
            raise RuntimeError("OCR engine unavailable")
        monkeypatch.setattr(ocr, "runtime", unavailable)
    else:
        config.processing.ocr_images = False
    with pytest.raises((ValueError, RuntimeError, FileNotFoundError)):
        await run(with_ocr)
    assert not any(e[0] in {"put", "delete"} for e in graph.events)
    assert not (root / "recovery").exists()


async def test_ocr_rollback_requires_neither_assets_nor_runtime(with_ocr, monkeypatch):
    _, graph, plan, _, _ = with_ocr
    await run(with_ocr)
    Path(plan["source"]).unlink()
    for a in plan["ocr"]["assets"]:
        Path(a["path"]).unlink()
    monkeypatch.setattr(ocr, "runtime", lambda: pytest.fail("Rollback must not inspect OCR runtime"))
    monkeypatch.setattr(ocr, "ocr_asset_text", lambda _: pytest.fail("Rollback must not recognize images"))
    await run(with_ocr, "rollback")
    assert graph.items == plan["old"]
    assert local(with_ocr) == plan["old_local"]


@pytest.mark.parametrize("src", [
    "../escape.png", "%2e%2e/escape.png", "sub/../year.png", "/year.png", r"C:\year.png",
    "//example.invalid/year.png", "https://example.invalid/year.png", "file:///year.png",
    "data:image/png;base64,AA", "year.png?variant=1", "year.png#view", "year.png:stream", "missing.png",
])
async def test_ocr_asset_path_rejection(prepared, fake_ocr, src):
    config, graph, plan, _, root = prepared
    config.processing.ocr_images = True
    (root / "year.png").write_bytes(png_bytes((255, 255, 255)))
    (root / "sub").mkdir()
    bind_source(prepared, f'<p>Content</p><img src="{src}" width="12" height="90">')
    before = Path(plan["database"]).read_bytes()
    with pytest.raises((ValueError, RuntimeError)):
        await reprepare(prepared)
    assert Path(plan["database"]).read_bytes() == before
    assert not any(e[0] in {"put", "delete"} for e in graph.events)


async def test_ocr_symlink_or_junction_rejected_before_read(prepared, fake_ocr, monkeypatch):
    config, _, _, _, root = prepared
    config.processing.ocr_images = True
    asset = root / "year.png"
    asset.write_bytes(png_bytes((255, 255, 255)))
    bind_source(prepared, '<img src="year.png" width="12" height="90">')
    original = Path.lstat

    def redirected(path):
        info = original(path)
        return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400) if path == asset else info

    monkeypatch.setattr(Path, "lstat", redirected)
    with pytest.raises(RuntimeError, match="symlinks/reparse"):
        await reprepare(prepared)


async def test_inherited_ocr_enabled_without_rotated_assets_needs_no_engine(prepared, monkeypatch):
    prepared[0].processing.ocr_images = True
    bind_source(prepared, "<p>No rotated image in this source.</p>")
    monkeypatch.setattr(ocr, "runtime", lambda: pytest.fail("No OCR inputs means no engine requirement"))
    case = await reprepare(prepared)
    assert case[2]["ocr"]["assets"] == [] and case[2]["ocr"]["runtime"] is None
    await run(case)


async def test_ocr_missing_dependencies_never_falls_back(prepared, monkeypatch):
    prepared[0].processing.ocr_images = True
    root = prepared[4]
    (root / "year.png").write_bytes(png_bytes((255, 255, 255)))
    bind_source(prepared, '<img src="year.png" width="12" height="90">')
    monkeypatch.setitem(sys.modules, "PIL", None)
    with pytest.raises(RuntimeError, match="requires installed"):
        await reprepare(prepared)
    assert not (root / "extended.json").exists()


@pytest.mark.parametrize("interrupted", [False, True])
async def test_genuine_format1_fixture_inspect_drift_and_source_free_rollback(prepared, monkeypatch, interrupted):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "maintenance_v1.json").read_text())
    config, graph, new, _, root = prepared
    plan = fixture["plan"]
    assert plan["format"] == 1 and "maintenance_ocr" not in plan["provenance"]["modules"]
    assert Path(new["source"]).read_text() == fixture["source_text"]
    assert local(prepared) == plan["old_local"]
    plan["source"], plan["database"] = new["source"], new["database"]
    digest = m.sha(plan)
    path = root / "legacy.json"
    m.write_new(path, plan)
    frozen = path.read_bytes()
    assert m.load_plan(path, digest) == plan
    assert m.inspect(plan, digest)["plan_format"] == 1
    case = config, graph, plan, digest, root
    with pytest.raises(ValueError, match="retain the original plan and runtime"):
        await run(case)
    assert not graph.events and not (root / "recovery").exists()
    # Simulate retaining the frozen runtime; exercise v1 replay shape unchanged.
    with monkeypatch.context() as patch:
        patch.setattr(m, "provenance", lambda _: deepcopy(plan["provenance"]))
        if interrupted:
            graph.fail = ("after_put", plan["desired_order"][0])
            with pytest.raises(RuntimeError):
                await run(case)
            await run(case, "resume")
        else:
            await run(case)
    assert graph.items == plan["desired"]
    Path(plan["source"]).unlink()
    await run(case, "rollback")
    assert graph.items == plan["old"]
    assert local(case) == plan["old_local"]
    assert path.read_bytes() == frozen
    with closing(m.read_only(Path(plan["database"]))) as db:
        assert db.execute("SELECT version FROM destination").fetchone()[0] == 4


async def test_incomplete_prepare_is_readonly_and_preserves_unrelated_scope(prepared):
    config, graph, plan, _, _ = prepared
    interrupt(prepared, [])
    path = Path(plan["database"])
    before, lock_time = path.read_bytes(), path.with_suffix(".db.lock").stat().st_mtime_ns
    with closing(m.read_only(path)) as db:
        unrelated = m.snapshot(db, 2)
    case = await reprepare(prepared, recover_prepared=True)
    assert path.read_bytes() == before
    assert path.with_suffix(".db.lock").stat().st_mtime_ns == lock_time
    assert not graph.events
    await run(case)
    await run(case, "rollback")
    with closing(m.read_only(path)) as db:
        assert m.snapshot(db, 2) == unrelated


async def test_prepared_default_routes_to_ordinary_resume(prepared):
    interrupt(prepared, [])
    with pytest.raises(ValueError, match="prefer ordinary resume"):
        await reprepare(prepared)


async def test_ocr_drift_after_activation_preserves_guard_and_allows_rollback(with_ocr, monkeypatch):
    _, graph, plan, _, root = with_ocr
    graph.fail = ("after_put", plan["desired_order"][0])
    with pytest.raises(RuntimeError):
        await run(with_ocr)
    (root / "year.png").write_bytes(b"changed after activation")
    graph.events.clear()
    with pytest.raises(ValueError, match="OCR asset drift"):
        await run(with_ocr, "resume")
    assert not graph.events
    assert phase(with_ocr)[0] == "forward"
    monkeypatch.setattr(ocr, "runtime", lambda: pytest.fail("Rollback must not inspect engine"))
    await run(with_ocr, "rollback")
    assert graph.items == plan["old"]
    assert local(with_ocr) == plan["old_local"]


async def test_ocr_source_symlink_drift_rejected_before_read(with_ocr, monkeypatch):
    source = Path(with_ocr[2]["source"])
    original = Path.lstat
    def redirect(path):
        info = original(path)
        return SimpleNamespace(st_mode=info.st_mode, st_file_attributes=0x400) if path == source else info
    monkeypatch.setattr(Path, "lstat", redirect)
    original_read = Path.read_bytes
    def forbid_read(path):
        if path == source:
            pytest.fail("Redirected source must be rejected before reading target")
        return original_read(path)
    monkeypatch.setattr(Path, "read_bytes", forbid_read)
    with pytest.raises(ValueError, match="symlinks/reparse"):
        await run(with_ocr)


async def test_ocr_asset_change_during_recognition_rejects_plan(prepared, fake_ocr, monkeypatch):
    prepared[0].processing.ocr_images = True
    root = prepared[4]
    asset = root / "year.png"
    asset.write_bytes(png_bytes((255, 255, 255)))
    bind_source(prepared, '<img src="year.png" width="12" height="90">')
    original = ocr.ocr_asset_text
    def changed(stream, settings):
        text = original(stream, settings)
        asset.write_bytes(png_bytes((0, 0, 0)))
        return text
    monkeypatch.setattr(ocr, "ocr_asset_text", changed)
    with pytest.raises(ValueError, match="OCR asset drift"):
        await reprepare(prepared)


async def test_ocr_sgml_selection_and_hidden_images_share_production_discovery(prepared, fake_ocr):
    prepared[0].processing.ocr_images = True
    root = prepared[4]
    (root / "year.png").write_bytes(png_bytes((255, 255, 255)))
    def document(filename, sequence, text):
        return f"<DOCUMENT>\n<TYPE>DEF 14A\n<SEQUENCE>{sequence}\n<FILENAME>{filename}\n<TEXT>{text}</TEXT>\n</DOCUMENT>"
    other = document("other.htm", 2, '<img src="never-read.png" width="12" height="90">')
    selected = document("proxy.htm", 1, '<style>.secret {display:none}</style>'
                        '<img class="secret" src="hidden.png" width="12" height="90">'
                        '<img src="year.png" width="12" height="90"><p>Selected text.</p>')
    bind_source(prepared, other + selected)
    case = await reprepare(prepared)
    assert [a["src"] for a in case[2]["ocr"]["assets"]] == ["year.png"]
    assert "Selected text" in m.canonical(case[2]["desired"])


@pytest.mark.parametrize("problem", ["executable", "language", "language_file", "probe_error", "empty_output"])
def test_runtime_inventory_fails_closed(tmp_path, monkeypatch, problem):
    executable = tmp_path / "tesseract.exe"
    executable.write_bytes(b"synthetic executable, never executed")
    model = tmp_path / "eng.traineddata"
    model.write_bytes(b"synthetic language data")
    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(__version__="stub-pillow", __file__=str(tmp_path / "__init__.py")))
    monkeypatch.setattr(ocr_engine.shutil, "which", lambda _: None if problem == "executable" else str(executable))
    def probe(args, **kwargs):
        assert args[1] in {"--version", "--list-langs"}
        if problem == "probe_error":
            raise OSError("probe failed")
        text = f'List of available languages in "{tmp_path}" (1):\neng'
        if problem == "language":
            text = text.replace("\neng", "\nosd")
        if problem == "empty_output":
            text = ""
        return SimpleNamespace(stdout=(text if args[1] == "--list-langs" else "tesseract stub").encode(), stderr=b"", returncode=0)
    monkeypatch.setattr(ocr_engine.subprocess, "run", probe)
    if problem == "language_file":
        model.unlink()
    with pytest.raises((RuntimeError, FileNotFoundError)):
        ocr.runtime(OCRConfig(tessdata_dir=str(tmp_path)))


def test_runtime_inventory_freezes_model_and_engine_bytes(tmp_path, monkeypatch):
    monkeypatch.setattr(ocr.platform, "system", lambda: "Windows")
    executable = tmp_path / "tesseract.exe"
    executable.write_bytes(b"synthetic executable")
    model = tmp_path / "eng.traineddata"
    model.write_bytes(b"synthetic language data")
    (tmp_path / "runtime.dll").write_bytes(b"runtime")
    monkeypatch.setitem(sys.modules, "PIL", SimpleNamespace(__version__="stub-pillow", __file__=str(tmp_path / "__init__.py")))
    monkeypatch.setattr(ocr_engine.shutil, "which", lambda _: str(executable))
    monkeypatch.setattr(ocr_engine.subprocess, "run", lambda args, **kwargs: SimpleNamespace(
        stdout=(f'List of available languages in "{tmp_path}" (1):\neng'
                if args[1] == "--list-langs" else "tesseract stub").encode(), stderr=b"", returncode=0,
    ))
    first = ocr.runtime(OCRConfig(tessdata_dir=str(tmp_path)))
    assert first["config"] == "--psm 7" and first["language"] == "eng"
    assert first["executable_hash"] == ocr.digest(executable.read_bytes())
    model.write_bytes(b"changed model")
    assert ocr.runtime(OCRConfig(tessdata_dir=str(tmp_path)))["language_hash"] != first["language_hash"]
    (tmp_path / "runtime.dll").write_bytes(b"changed runtime")
    assert ocr.runtime(OCRConfig(tessdata_dir=str(tmp_path)))["runtime_dlls"] != first["runtime_dlls"]
    (tmp_path / "__init__.py").write_text("changed Pillow preprocessing")
    assert ocr.runtime(OCRConfig(tessdata_dir=str(tmp_path)))["pillow_files"] != first["pillow_files"]
    executable.write_bytes(b"changed executable")
    assert ocr.runtime(OCRConfig(tessdata_dir=str(tmp_path)))["executable_hash"] != first["executable_hash"]


async def test_ocr_recognition_failure_is_not_a_successful_plan(prepared, fake_ocr, monkeypatch):
    prepared[0].processing.ocr_images = True
    (prepared[4] / "year.png").write_bytes(png_bytes((255, 255, 255)))
    bind_source(prepared, '<img src="year.png" width="12" height="90">')
    monkeypatch.setattr(ocr, "ocr_asset_text", lambda *args: "")
    with pytest.raises(RuntimeError, match="no usable text"):
        await reprepare(prepared)
    assert not (prepared[4] / "extended.json").exists()


@pytest.mark.parametrize("interrupted", [False, True])
async def test_genuine_pre_cli_format2_source_free_rollback(prepared, monkeypatch, interrupted):
    fixture = json.loads((Path(__file__).parent / "fixtures" / "maintenance_v2_pytesseract.json").read_text())
    config, graph, original, _, root = prepared
    config.processing.ocr_images = True
    bind_source(prepared, fixture["source_text"])
    plan = fixture["plan"]
    assert plan["format"] == 2 and "ocr_engine" not in plan["provenance"]["modules"]
    assert "ocr_backend" not in plan["provenance"]["options"]
    assert "pytesseract" in plan["ocr"]["runtime"]["dependencies"]
    assert local(prepared) == plan["old_local"]
    plan["source"], plan["database"] = original["source"], original["database"]
    plan["ocr"]["root"] = str(root)
    plan["ocr"]["assets"][0]["path"] = str(root / "header.png")
    plan["provenance"]["options"]["maintenance_ocr_bundle_hash"] = m.sha(plan["ocr"])
    digest = m.sha(plan)
    path = root / "legacy-ocr.json"
    m.write_new(path, plan)
    frozen = path.read_bytes()
    case = config, graph, plan, digest, root
    assert m.load_plan(path, digest) == plan
    assert m.inspect(plan, digest)["plan_format"] == 2
    with pytest.raises(ValueError, match="retain the original plan and runtime"):
        await run(case)
    assert not graph.events and not (root / "recovery").exists()
    # Recreate the existing format-2 journal boundary, not a forward runtime migration.
    binding = m.check_binding
    with monkeypatch.context() as old_runtime:
        old_runtime.setattr(m, "check_binding", lambda p, c: binding(p, c, forward=False))
        async with IngestionPipeline(config)._state() as state:
            phase, data = await m.activate(state, graph, plan, digest, root / "recovery")
            if interrupted:
                graph.fail = ("after_put", plan["desired_order"][0])
                with pytest.raises(RuntimeError):
                    await m.put_verified(state, graph, plan, digest, phase, data, plan["desired_order"][0])
    Path(plan["source"]).unlink()
    monkeypatch.setattr(ocr, "runtime", lambda *a: pytest.fail("Legacy rollback needs no engine"))
    monkeypatch.setattr(ocr, "ocr_asset_text", lambda *a: pytest.fail("Legacy rollback needs no images"))
    await run(case, "rollback")
    assert graph.items == plan["old"]
    assert local(case) == plan["old_local"]
    assert path.read_bytes() == frozen and m.sha(plan) == digest
    with closing(m.read_only(Path(plan["database"]))) as db:
        assert db.execute("SELECT version FROM destination").fetchone()[0] == 4


@pytest.mark.parametrize("field", ["backend", "runtime_dlls", "pillow_files", "environment"])
async def test_cli_runtime_identity_drift_blocks_forward(with_ocr, fake_ocr, field):
    fake_ocr[1][field] = "changed runtime evidence"
    with pytest.raises(ValueError, match="backend|runtime"):
        await run(with_ocr)
    assert not any(event[0] in {"put", "delete"} for event in with_ocr[1].events)
