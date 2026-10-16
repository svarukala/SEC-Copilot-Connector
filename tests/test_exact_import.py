"""Exact selection, offline preparation and opt-in delivery regressions."""

import copy
import json
from pathlib import Path
from unittest.mock import AsyncMock

from click.testing import CliRunner
import pytest

from sec_connector import exact_import as exact
from sec_connector.cli import main
from sec_connector.config import AppConfig
from sec_connector.models import DocumentInfo, FilingMetadata
from sec_connector.sec_client import SECClient


@pytest.fixture
def case(tmp_path):
    manifest = exact.ExactManifest.model_validate({"documents": [{
        "ticker": "PNC", "cik": "0000713676", "accession_number": "0001193125-25-052937",
        "form": "DEF 14A", "filing_date": "2025-03-12", "filename": "proxy.htm",
    }]})
    filing = FilingMetadata(
        **manifest.documents[0].model_dump(exclude={"filename", "filing_date"}),
        filing_date="2025-03-12", primary_document="proxy.htm", company_name="PNC",
    )
    raw = b"<html><body><h1>Annual proxy</h1><p>Complete primary document.</p></body></html>"
    document = DocumentInfo(sequence=1, filename="proxy.htm", document_type="DEF 14A", size=len(raw))
    config = AppConfig(paths={"database": str(tmp_path / "state.db"),
                             "payloads": str(tmp_path / "payloads")})
    return config, manifest, filing, document, raw


def network(monkeypatch, case):
    _, _, filing, document, raw = case
    monkeypatch.setattr(SECClient, "get_filings", AsyncMock(return_value=[filing]))
    monkeypatch.setattr(SECClient, "get_filing_documents", AsyncMock(return_value=[document]))
    getter = AsyncMock(return_value=raw)
    monkeypatch.setattr(SECClient, "_get", getter)
    return getter


@pytest.mark.parametrize("change", [
    {"filename": "../evil.htm"}, {"filename": "CON.htm"}, {"filename": "x%2ehtm"},
    {"form": "10-K/A"}, {"cik": "../123"}, {"accession_number": "123"},
    {"extra": True}, {"filing_date": "yesterday"},
])
def test_invalid_manifest(case, change):
    data = case[1].model_dump(mode="json")
    data["documents"][0].update(change)
    with pytest.raises(ValueError):
        exact.ExactManifest.model_validate(data)


def test_duplicate_manifest(case):
    data = case[1].model_dump(mode="json")
    data["documents"] *= 2
    with pytest.raises(ValueError, match="unique"):
        exact.ExactManifest.model_validate(data)


@pytest.mark.asyncio
async def test_full_prepare_cache_offline_never_graph(case, tmp_path, monkeypatch):
    config, manifest, *_ = case
    get = network(monkeypatch, case)
    monkeypatch.setattr(exact.GraphClient, "__aenter__", AsyncMock(side_effect=AssertionError("Graph")))
    monkeypatch.setattr(exact.GraphClient, "_get_token", AsyncMock(side_effect=AssertionError("Auth")))
    first = await exact.prepare(config, manifest, tmp_path / "cache")
    assert len(first["documents"]) == 1
    assert first["documents"][0]["payloads"]
    assert not list(tmp_path.glob("*.db"))
    assert get.await_count == 1
    second = await exact.prepare(config, manifest, tmp_path / "cache")
    assert first == second
    assert get.await_count == 1
    monkeypatch.setattr(SECClient, "__aenter__", AsyncMock(side_effect=AssertionError("Network")))
    third = await exact.prepare(config, manifest, tmp_path / "cache", offline=True)
    assert third == first
    exact.validate_bundle(third, manifest, config)


@pytest.mark.asyncio
async def test_refresh_refetches(case, tmp_path, monkeypatch):
    get = network(monkeypatch, case)
    await exact.prepare(case[0], case[1], tmp_path)
    await exact.prepare(case[0], case[1], tmp_path, refresh=True)
    assert get.await_count == 2
    with pytest.raises(ValueError):
        await exact.prepare(case[0], case[1], tmp_path, offline=True, refresh=True)


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["cik", "filename", "form", "date", "missing", "extra"])
async def test_preflight_fail_closed_before_download(case, tmp_path, monkeypatch, mismatch):
    config, manifest, filing, document, _ = case
    getter = network(monkeypatch, case)
    if mismatch == "cik":
        filing.cik = "0000000001"
    elif mismatch == "filename":
        document.filename = "another.htm"
    elif mismatch == "form":
        filing.form = "10-K"
    elif mismatch == "date":
        filing.filing_date = filing.filing_date.replace(day=13)
    elif mismatch == "missing":
        monkeypatch.setattr(SECClient, "get_filings", AsyncMock(return_value=[]))
    else:
        monkeypatch.setattr(SECClient, "get_filing_documents", AsyncMock(return_value=[document, document]))
    with pytest.raises(ValueError):
        await exact.prepare(config, manifest, tmp_path)
    getter.assert_not_awaited()


@pytest.mark.parametrize("src", [
    "../name.jpg", "https://evil.test/name.jpg", "//evil.test/name.jpg",
    "http://www.sec.gov/Archives/edgar/data/713676/000119312525052937/name.jpg",
    "name.jpg?x=1", "name.jpg#x", "a%2fb.jpg", "a\\b.jpg", "CON.jpg",
    "/Archives/edgar/data/713676/000119312525000000/name.jpg", "name.svg", "",
])
def test_unsafe_selected_assets(case, tmp_path, src):
    config, _, filing, *_ = case
    source = tmp_path / "proxy.htm"
    source.write_text(f'<img width="12" height="100" src="{src}">')
    with pytest.raises(ValueError):
        exact.asset_names(source, filing, SECClient(config))


def test_only_rotated_visible_same_filing_assets(case, tmp_path):
    config, _, filing, *_ = case
    source = tmp_path / "proxy.htm"
    absolute = "https://www.sec.gov/Archives/edgar/data/713676/000119312525052937/name.jpg"
    source.write_text(
        f'<img width="12" height="100" src="{absolute}">'
        '<img width="100" height="100" src="unrelated.jpg">'
        '<div hidden><img width="12" height="100" src="hidden.jpg"></div>'
    )
    assert exact.asset_names(source, filing, SECClient(config)) == {absolute: "name.jpg"}


@pytest.mark.asyncio
async def test_asset_staging_bounds_cache_and_missing(case, tmp_path, monkeypatch):
    from PIL import Image
    from io import BytesIO
    config, _, filing, *_ = case
    image = BytesIO()
    Image.new("RGB", (12, 100), "white").save(image, "PNG")
    getter = AsyncMock(return_value=image.getvalue())
    monkeypatch.setattr(SECClient, "_get", getter)
    source = tmp_path / "proxy.htm"
    names = {"name.png": "name.png"}
    sec = SECClient(config)
    first = await exact.stage_assets(sec, filing, source, names)
    assert first == await exact.stage_assets(sec, filing, source, names)
    assert getter.await_count == 1
    assert getter.call_args.kwargs == {"max_bytes": exact.MAX_ASSET_BYTES}
    assert first == await exact.stage_assets(sec, filing, source, names, offline=True)
    (tmp_path / "name.png").unlink()
    with pytest.raises(FileNotFoundError):
        await exact.stage_assets(sec, filing, source, names, offline=True)
    getter.return_value = b"<html>not an image</html>"
    with pytest.raises(OSError):
        await exact.stage_assets(sec, filing, source, names)
    assert not (tmp_path / "name.png").exists()
    getter.return_value = image.getvalue()
    monkeypatch.setattr(exact, "MAX_TOTAL_ASSET_BYTES", 1)
    with pytest.raises(ValueError, match="total"):
        await exact.stage_assets(sec, filing, source, names)
    assert not (tmp_path / "name.png").exists()


@pytest.mark.asyncio
async def test_bundle_extra_scope_and_version_rejected(case, tmp_path, monkeypatch):
    network(monkeypatch, case)
    config, manifest, *_ = case
    bundle = await exact.prepare(config, manifest, tmp_path)
    for change in ("extra", "version", "scope", "settings"):
        bad = copy.deepcopy(bundle)
        if change == "extra":
            bad["documents"].append(bad["documents"][0])
        elif change == "version":
            bad["processing_version"] += 1
        elif change == "scope":
            bad["documents"][0]["payloads"][0]["properties"]["DocumentName"] = "exhibit.htm"
        else:
            bad["options"]["ocr_images"] = True
        with pytest.raises(ValueError):
            exact.validate_bundle(bad, manifest, config)


@pytest.mark.asyncio
async def test_offline_drift_and_missing_engine(case, tmp_path, monkeypatch):
    network(monkeypatch, case)
    config, manifest, *_ = case
    await exact.prepare(config, manifest, tmp_path)
    source = next(tmp_path.rglob("proxy.htm"))
    source.write_bytes(source.read_bytes().replace(b"Annual", b"Alter!"))
    with pytest.raises(ValueError, match="hashes"):
        await exact.prepare(config, manifest, tmp_path, offline=True)
    getter = AsyncMock(side_effect=AssertionError("Do not fetch assets from a changed cached source"))
    monkeypatch.setattr(SECClient, "_get", getter)
    with pytest.raises(ValueError, match="hashes"):
        await exact.prepare(config, manifest, tmp_path)
    getter.assert_not_awaited()
    config.processing.ocr_images = True
    config.processing.ocr.executable = str(tmp_path / "missing.exe")
    with pytest.raises(RuntimeError, match="Tesseract"):
        await exact.prepare(config, manifest, tmp_path)


def test_atomic_failed_write_preserves_cache(tmp_path, monkeypatch):
    path = tmp_path / "asset.png"
    path.write_bytes(b"old")
    monkeypatch.setattr(Path, "replace", lambda *args: (_ for _ in ()).throw(OSError("locked")))
    with pytest.raises(OSError, match="locked"):
        exact.atomic_write(path, b"new")
    assert path.read_bytes() == b"old"
    assert not list(tmp_path.glob("*.part"))


def test_upload_requires_explicit_ack_and_matching_digest(case, tmp_path, monkeypatch):
    config, manifest, *_ = case
    monkeypatch.setattr("sec_connector.cli.load_config", lambda _: config)
    selection = tmp_path / "manifest.yaml"
    selection.write_text(json.dumps(manifest.model_dump(mode="json")))
    bundle = tmp_path / "bundle.json"
    bundle.write_text("{}")
    args = ["import-exact", "--manifest", str(selection), "--bundle", str(bundle),
            "--bundle-sha256", "wrong"]
    result = CliRunner().invoke(main, args)
    assert result.exit_code != 0
    result = CliRunner().invoke(main, args + ["--upload"])
    assert result.exit_code != 0 and "SHA256 mismatch" in result.output
    assert not list(tmp_path.glob("*.db"))


@pytest.mark.asyncio
async def test_import_checkpoints_all_documents_and_retries_only_pending(case, tmp_path, monkeypatch):
    import sqlite3
    from sec_connector.pipeline import IngestionPipeline
    config, manifest, filing, document, raw = case
    config.azure.tenant_id = "test-tenant"
    config.azure.connection_id = "testexact"
    second_filing = filing.model_copy(update={"accession_number": "0001193125-25-052938"})
    manifest.documents.append(manifest.documents[0].model_copy(
        update={"accession_number": second_filing.accession_number}))
    monkeypatch.setattr(SECClient, "get_filings", AsyncMock(return_value=[filing, second_filing]))
    monkeypatch.setattr(SECClient, "get_filing_documents", AsyncMock(return_value=[document]))
    monkeypatch.setattr(SECClient, "_get", AsyncMock(return_value=raw))
    bundle = await exact.prepare(config, manifest, tmp_path / "cache")
    schema = exact.GraphClient.load_schema()
    monkeypatch.setattr(exact.GraphClient, "get_schema_status", AsyncMock(return_value=schema))
    deleted = AsyncMock(side_effect=AssertionError("No deletes"))
    monkeypatch.setattr(exact.GraphClient, "delete_item", deleted)
    db = IngestionPipeline(config).db_path
    attempts = []

    async def upload(_, item_id, payload):
        with sqlite3.connect(db) as connection:
            assert connection.execute("SELECT count(*) FROM filings WHERE payloads_ready=1").fetchone()[0] == 2
            assert connection.execute("SELECT count(*) FROM chunks").fetchone()[0] == 2
        attempts.append(item_id)
        if len(attempts) == 1:
            raise RuntimeError("retryable failure")

    monkeypatch.setattr(exact.GraphClient, "upload_payload", upload)
    sha = exact.digest(exact.json_bytes(bundle))
    first = await exact.import_bundle(config, manifest, bundle, sha)
    assert first["errors"] == 1 and first["chunks_uploaded"] == 1
    second = await exact.import_bundle(config, manifest, bundle, sha)
    assert second["errors"] == 0 and second["chunks_uploaded"] == 1
    third = await exact.import_bundle(config, manifest, bundle, sha)
    assert third["chunks_uploaded"] == 0
    assert len(attempts) == 3
    deleted.assert_not_awaited()
    with pytest.raises(ValueError, match="another generation"):
        await exact.import_bundle(config, manifest, bundle, "different-digest")


@pytest.mark.asyncio
async def test_bad_schema_does_not_leave_prepared_filings(case, tmp_path, monkeypatch):
    from sec_connector.pipeline import IngestionPipeline
    network(monkeypatch, case)
    config, manifest, *_ = case
    config.azure.tenant_id = "test-tenant"
    bundle = await exact.prepare(config, manifest, tmp_path / "cache")
    monkeypatch.setattr(exact.GraphClient, "get_schema_status", AsyncMock(return_value={}))
    with pytest.raises(ValueError, match="schema"):
        await exact.import_bundle(config, manifest, bundle, "digest")
    async with IngestionPipeline(config)._state() as state:
        assert (await state.get_stats())["total_filings"] == 0


@pytest.mark.asyncio
async def test_partial_exact_preparation_cannot_resume_discovery(case, monkeypatch):
    from sec_connector.pipeline import IngestionPipeline, processing_options
    config, _, filing, *_ = case
    config.azure.tenant_id = "test-tenant"
    pipeline = IngestionPipeline(config)
    async with pipeline._state() as state:
        filing_id = await state.add_filing(
            filing, processing_options={**processing_options(config), "exact_bundle_sha256": "hash"})
        sec = SECClient(config)
        sec.get_filing_documents = AsyncMock(side_effect=AssertionError("must not discover"))
        with pytest.raises(ValueError, match="repeat import-exact"):
            await pipeline._prepare_filing(filing_id, sec, state, None, pipeline._stats())


@pytest.mark.asyncio
async def test_ocr_uses_staged_absolute_alias_without_changing_default(case, tmp_path, monkeypatch):
    from sec_connector.parser import html_to_markdown
    config, _, filing, *_ = case
    source = tmp_path / "proxy.htm"
    src = "https://www.sec.gov/Archives/edgar/data/713676/000119312525052937/name.jpg"
    html = f'<p><img width="12" height="100" src="{src}"></p>'
    source.write_text(html)
    (tmp_path / "name.jpg").write_bytes(b"fake image; mocked recognition")
    names = exact.asset_names(source, filing, SECClient(config))
    with pytest.raises(ValueError, match="predownloaded"):
        html_to_markdown(html, local_image_dir=tmp_path)
    assert "Director Name" in html_to_markdown(
        html, local_image_dir=tmp_path, ocr_asset_names=names,
        ocr_resolver=lambda original, path: "Director Name",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status,blocks", [(302, []), (200, [b"123", b"456"]), (200, [b"123"])])
async def test_bounded_http_does_not_follow_redirects(case, status, blocks):
    from unittest.mock import MagicMock
    config = case[0]
    config.sec.user_agent = "SEC connector contact contact@contoso.test"
    sec = SECClient(config)
    response = MagicMock()
    response.status = status
    response.headers = {}

    async def chunks(_):
        for block in blocks:
            yield block

    response.content.iter_chunked = chunks
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=response)
    manager.__aexit__ = AsyncMock(return_value=False)
    sec._session = MagicMock()
    sec._session.get.return_value = manager
    if status != 200 or sum(map(len, blocks)) > 4:
        with pytest.raises(ValueError):
            await sec._get("https://www.sec.gov/asset.png", max_bytes=4)
    else:
        assert await sec._get("https://www.sec.gov/asset.png", max_bytes=4) == b"123"
    assert sec._session.get.call_args.kwargs["allow_redirects"] is False


def test_actual_asset_count_byte_and_pixel_limits(case, tmp_path):
    from io import BytesIO
    from PIL import Image
    source = tmp_path / "proxy.htm"
    source.write_text("".join(
        f'<img width="12" height="100" src="name{i}.png">'
        for i in range(exact.MAX_ASSETS + 1)
    ))
    with pytest.raises(ValueError, match="256"):
        exact.asset_names(source, case[2], SECClient(case[0]))
    stream = BytesIO()
    Image.new("RGB", (12, 100)).save(stream, format="PNG")
    raw = stream.getvalue()
    exact.validate_image(raw + b"\0" * (exact.MAX_ASSET_BYTES - len(raw)))
    with pytest.raises(ValueError, match="oversized"):
        exact.validate_image(raw + b"\0" * (exact.MAX_ASSET_BYTES + 1 - len(raw)))
    cache = tmp_path / "oversized.png"
    cache.write_bytes(raw + b"\0" * (exact.MAX_ASSET_BYTES + 1 - len(raw)))
    with pytest.raises(ValueError, match="oversized"):
        exact.read_image(cache)
    stream = BytesIO()
    Image.new("1", (4001, 4000)).save(stream, format="PNG")
    with pytest.raises(ValueError, match="pixel"):
        exact.validate_image(stream.getvalue())


def test_output_and_cache_reject_symlinks_before_writing(tmp_path):
    target = tmp_path / "target"
    target.mkdir()
    redirect = tmp_path / "redirect"
    try:
        redirect.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks is not available to this user")
    with pytest.raises(ValueError, match="symlinks"):
        exact.atomic_write(redirect / "new" / "asset.png", b"not written")
    assert not list(target.iterdir())


def test_shipped_customer_config_and_manifest(monkeypatch):
    from sec_connector.config import load_config
    root = Path(__file__).parents[1]
    monkeypatch.setenv("SEC_TESSERACT_EXE", r"C:\ApprovedTools\tesseract.exe")
    monkeypatch.setenv("SEC_TESSDATA_DIR", r"C:\ApprovedTools\tessdata")
    config = load_config(root / "config" / "customer-v9" / "config.yaml")
    manifest = exact.load_manifest(root / "config" / "customer-v9" / "documents.yaml")
    assert len(manifest.documents) == 3
    assert {(d.accession_number, d.filename) for d in manifest.documents} == {
        ("0001193125-25-052937", "d889589ddef14a.htm"),
        ("0000713676-24-000028", "pnc-20231231.htm"),
        ("0000713676-25-000027", "pnc-20241231.htm"),
    }
    assert config.processing.ocr_images
    assert config.filings.include_history
    assert not config.filings.include_exhibits and not config.filings.include_amendments
    assert not config.sync.prune_missing_filings
    assert config.chunking.max_item_bytes == 31457280
