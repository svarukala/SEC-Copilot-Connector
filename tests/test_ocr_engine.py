"""Offline direct-engine boundary tests; no native engine or Pillow required."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from sec_connector import ocr_engine as engine
from sec_connector.config import OCRConfig
from sec_connector.pipeline import IngestionPipeline, document_fingerprint
from .test_recovery import config, filing, clients


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    executable = tmp_path / "engine with spaces.exe"
    executable.write_bytes(b"test engine, never executed")
    data = tmp_path / "tessdata"
    data.mkdir()
    (data / "eng.traineddata").write_bytes(b"test model")
    monkeypatch.setattr(engine.shutil, "which", lambda _: str(executable))
    return OCRConfig(executable=str(executable)), executable, data


class Image:
    def save(self, path, format):
        assert format == "PNG"
        Path(path).write_bytes(b"preprocessed image")


@pytest.mark.parametrize("outcome", ["ok", "nonzero", "model-error-zero", "timeout", "oserror", "empty", "utf8"])
def test_subprocess_boundary_and_cleanup(bundle, monkeypatch, outcome):
    settings, executable, data = bundle
    temporary = []
    monkeypatch.setenv("TESSDATA_PREFIX", "untrusted")
    monkeypatch.setenv("OMP_THREAD_LIMIT", "32")
    monkeypatch.setenv("PATH", "untrusted")

    def run(args, **kwargs):
        path = Path(args[1])
        temporary.append(path.parent)
        assert path.read_bytes() == b"preprocessed image"
        assert args == [str(executable), str(path), "stdout", "--tessdata-dir", str(data), "-l", "eng", "--psm", "7"]
        assert kwargs["shell"] is False and kwargs["stdin"] == engine.subprocess.DEVNULL
        assert kwargs["timeout"] == 60 and kwargs["capture_output"] is True
        assert kwargs["cwd"] == str(path.parent)
        assert kwargs["env"]["PATH"] == str(executable.parent)
        assert kwargs["env"]["TESSDATA_PREFIX"] == str(data)
        assert kwargs["env"]["OMP_THREAD_LIMIT"] == "1"
        assert kwargs["env"]["TEMP"] == str(path.parent)
        if outcome == "timeout":
            raise engine.subprocess.TimeoutExpired(args, 60)
        if outcome == "oserror":
            raise OSError("DLL unavailable")
        return SimpleNamespace(
            stdout=b"" if outcome == "empty" else b"\xff" if outcome == "utf8" else b"No error in this disclosure.\n",
            stderr=b"Error opening data file; Failed loading language" if outcome == "model-error-zero" else b"",
            returncode=1 if outcome == "nonzero" else 0,
        )

    monkeypatch.setattr(engine.subprocess, "run", run)
    if outcome == "ok":
        assert engine.image_to_text(Image(), settings) == "No error in this disclosure."
    else:
        with pytest.raises(RuntimeError):
            engine.image_to_text(Image(), settings)
    assert temporary and all(not p.exists() for p in temporary)


@pytest.mark.parametrize("problem", ["executable", "model", "script"])
def test_missing_or_unsafe_engine(bundle, monkeypatch, problem):
    settings, executable, data = bundle
    if problem == "executable":
        monkeypatch.setattr(engine.shutil, "which", lambda _: None)
    elif problem == "model":
        (data / "eng.traineddata").unlink()
    else:
        script = executable.with_suffix(".cmd")
        script.write_text("not executed")
        monkeypatch.setattr(engine.shutil, "which", lambda _: str(script))
    monkeypatch.setattr(engine.subprocess, "run", lambda *a, **kw: pytest.fail("Must fail before execution"))
    with pytest.raises((RuntimeError, ValueError)):
        engine.image_to_text(Image(), settings)


def test_save_failure_cleans_temporary_directory(bundle, monkeypatch):
    directories = []

    class BrokenImage:
        def save(self, path, format):
            directories.append(path.parent)
            path.write_bytes(b"partial")
            raise OSError("encode failed")

    with pytest.raises(OSError, match="encode failed"):
        engine.image_to_text(BrokenImage(), bundle[0])
    assert directories and not directories[0].exists()


@pytest.mark.parametrize("timeout", [0, -1, 301, float("nan"), float("inf")])
def test_invalid_timeout_rejected(timeout):
    with pytest.raises(ValueError):
        OCRConfig(timeout_seconds=timeout)


def test_non_ocr_options_and_fingerprints_unchanged(config, filing, clients):
    pipeline = IngestionPipeline(config)
    original = pipeline._processing_options()
    assert set(original) == {
        "chunking", "ocr_images", "filings", "refresh_downloads", "icon_url",
        "schema_hash", "processing_version",
    }
    assert original["processing_version"] == 8
    before = document_fingerprint("source", filing, clients[2][0], original)
    config.processing.ocr = OCRConfig(executable="unavailable", tessdata_dir="missing", timeout_seconds=1)
    assert pipeline._processing_options() == original
    assert document_fingerprint("source", filing, clients[2][0], pipeline._processing_options()) == before
    config.processing.ocr_images = True
    captured = pipeline._processing_options()
    assert captured["ocr_backend"] == engine.captured_options(config.processing.ocr)
    assert document_fingerprint("source", filing, clients[2][0], captured) != before


@pytest.mark.parametrize("backend", [None, {}, {"backend": "pytesseract"}, {"backend": engine.BACKEND}])
async def test_unprepared_legacy_ocr_rejected_before_source_access(config, filing, clients, backend):
    config.processing.ocr_images = True
    pipeline = IngestionPipeline(config)
    options = pipeline._processing_options()
    if backend is None:
        del options["ocr_backend"]
    else:
        options["ocr_backend"] = backend
    sec, graph, _, _ = clients
    async with pipeline._state() as state:
        filing_id = await state.add_filing(filing, processing_options=options)
        with pytest.raises(ValueError, match="captured OCR"):
            await pipeline._prepare_filing(filing_id, sec, state, graph, pipeline._stats())
    sec.get_filing_documents.assert_not_awaited()
    sec.download_document.assert_not_awaited()
    graph.upload_payload.assert_not_awaited()


async def test_prepared_legacy_ocr_replay_does_not_resolve_backend(config, filing, clients, monkeypatch):
    pipeline = IngestionPipeline(config)
    sec, graph, _, _ = clients
    async with pipeline._state() as state:
        filing_id = await state.add_filing(filing, processing_options=pipeline._processing_options())
        await pipeline._prepare_filing(filing_id, sec, state, graph, pipeline._stats())
        options = pipeline._processing_options()
        options["ocr_images"] = True
        import json
        await state._db.execute("UPDATE filings SET processing_options=? WHERE id=?", (json.dumps(options), filing_id))
        monkeypatch.setattr("sec_connector.pipeline.captured_settings", lambda _: pytest.fail("Prepared replay"))
        sec.download_document.reset_mock()
        await pipeline._prepare_filing(filing_id, sec, state, graph, pipeline._stats())
        sec.download_document.assert_not_awaited()


async def test_ocr_generation_never_reuses_source_only_cache(config, filing, clients, monkeypatch):
    config.processing.ocr_images = True
    pipeline = IngestionPipeline(config)
    sec, graph, _, _ = clients
    seen = []
    from sec_connector.parser import parse_document

    def parse(*args, **kwargs):
        seen.append(kwargs["ocr_settings"])
        return parse_document(*args, **kwargs)

    monkeypatch.setattr("sec_connector.pipeline.parse_document", parse)
    async with pipeline._state() as state:
        filing_id = await state.add_filing(filing, processing_options=pipeline._processing_options())
        state.cached_payloads = AsyncMock(side_effect=AssertionError("HTML-only OCR cache reuse"))
        await pipeline._prepare_filing(filing_id, sec, state, graph, pipeline._stats())
        state.cached_payloads.assert_not_awaited()
    assert len(seen) == 2 and all(s == config.processing.ocr for s in seen)
