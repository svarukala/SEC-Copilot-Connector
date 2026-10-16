"""Exact primary-document preparation and delivery; preparation never opens Graph."""

import asyncio
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import tempfile
from datetime import date
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .chunker import chunk_with_limit
from .config import AppConfig
from .graph_client import GraphClient
from .maintenance import scope_for, validate_payloads
from .maintenance_ocr import regular_file, runtime
from .models import DocumentInfo, FilingMetadata, FilingState
from .parser import (
    _clean_page_markers, _is_rotated_text_image, _remove_hidden_content,
    ocr_asset_text, parse_document,
)
from .payloads import serialize_item
from .pipeline import IngestionPipeline, PROCESSING_VERSION, processing_options
from .sec_client import SECClient, _validate_download

MAX_ASSETS = 256
MAX_ASSET_BYTES = 4 * 1024 * 1024
MAX_TOTAL_ASSET_BYTES = 32 * 1024 * 1024
MAX_IMAGE_PIXELS = 16_000_000


class ExactDocument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.-]*$")
    cik: str = Field(pattern=r"^[0-9]{10}$")
    accession_number: str = Field(pattern=r"^[0-9]{10}-[0-9]{2}-[0-9]{6}$")
    form: str
    filing_date: date
    filename: str

    @field_validator("filename")
    @classmethod
    def safe_filename(cls, value):
        SECClient._safe_filename(value)
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.(?:htm|txt)", value):
            raise ValueError("Exact imports support primary .htm/.txt documents only")
        return value

    @field_validator("form")
    @classmethod
    def primary_form(cls, value):
        if value not in {"10-K", "10-Q", "8-K", "DEF 14A"}:
            raise ValueError("Exact imports require a supported non-amended primary form")
        return value


class ExactManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    documents: list[ExactDocument] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique(self):
        keys = {(d.cik, d.accession_number) for d in self.documents}
        if len(keys) != len(self.documents):
            raise ValueError("Manifest must contain one primary document per unique filing")
        return self


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False).encode()


def atomic_write(path: Path, raw: bytes) -> None:
    check_existing_parents(path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Check ancestors even when the destination does not exist.
    regular_file(path) if path.exists() else regular_file_directory(path.parent)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, suffix=".part", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def regular_file_directory(path: Path) -> None:
    import stat
    for part in (path.absolute(), *path.absolute().parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Exact import forbids symlinks/reparse points: {part}")


def check_existing_parents(path: Path) -> None:
    while not path.exists():
        if path.is_symlink():
            raise ValueError(f"Exact import forbids symlinks: {path}")
        path = path.parent
    regular_file_directory(path)


def load_manifest(path: Path) -> ExactManifest:
    import yaml
    return ExactManifest.model_validate(yaml.safe_load(regular_file(path).read_text(encoding="utf-8")))


def verify_identity(expected: ExactDocument, filing: FilingMetadata, document: DocumentInfo) -> None:
    actual = ExactDocument(
        ticker=filing.ticker, cik=filing.cik, accession_number=filing.accession_number,
        form=filing.form, filing_date=filing.filing_date.date(), filename=document.filename,
    )
    if (actual != expected or filing.primary_document != expected.filename
            or document.document_type != expected.form or document.sequence < 1
            or document.size is None or document.size <= 0):
        raise ValueError(f"Exact primary-document identity mismatch: {expected.accession_number}")


async def discover(sec: SECClient, manifest: ExactManifest) -> list[dict]:
    selected = []
    inventories = {}
    for expected in manifest.documents:
        if expected.ticker not in inventories:
            inventories[expected.ticker] = await sec.get_filings(expected.ticker)
        matches = [f for f in inventories[expected.ticker]
                   if f.cik == expected.cik and f.accession_number == expected.accession_number]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one SEC filing: {expected.accession_number}")
        filing = matches[0]
        documents = await sec.get_filing_documents(filing)
        if len(documents) != 1:
            raise ValueError("Exact import requires a sole primary-document inventory")
        verify_identity(expected, filing, documents[0])
        selected.append({"filing": filing.model_dump(mode="json"),
                         "document": documents[0].model_dump(mode="json")})
    return selected


def asset_names(source: Path, filing: FilingMetadata, sec: SECClient) -> dict[str, str]:
    html = source.read_text(encoding="utf-8-sig")
    html = re.sub(r"^\s*<\?xml\b.*?\?>", "", html, count=1, flags=re.IGNORECASE | re.DOTALL)
    soup = BeautifulSoup(_clean_page_markers(html), "lxml")
    _remove_hidden_content(soup)
    for tag in soup.find_all(["script", "style", "meta", "link"]):
        tag.decompose()
    names = {}
    for img in soup.find_all("img"):
        if not _is_rotated_text_image(img):
            continue
        src = str(img.get("src", ""))
        url = urlsplit(src)
        if (not src or url.scheme not in {"", "https"} or url.query or url.fragment
                or "\\" in src or "%" in src or any(p in {".", ".."} for p in url.path.split("/"))):
            raise ValueError(f"Unsafe OCR image URL: {src!r}")
        name = sec._document_link_filename(filing, filing.sec_url, src)
        if not name.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".tif", ".tiff", ".bmp")):
            raise ValueError(f"Unsupported OCR image type: {src!r}")
        if name == source.name:
            raise ValueError("OCR image collides with the primary document")
        names[src] = name
    if len(set(names.values())) > MAX_ASSETS:
        raise ValueError(f"More than {MAX_ASSETS} selected OCR assets")
    return names


def validate_image(raw: bytes) -> None:
    from PIL import Image
    if not raw or len(raw) > MAX_ASSET_BYTES:
        raise ValueError("Empty or oversized OCR image")
    with Image.open(BytesIO(raw)) as image:
        if image.width * image.height > MAX_IMAGE_PIXELS:
            raise ValueError("OCR image exceeds pixel limit")
        image.verify()


def read_image(path: Path) -> bytes:
    with regular_file(path).open("rb") as stream:
        raw = stream.read(MAX_ASSET_BYTES + 1)
    validate_image(raw)
    return raw


async def stage_assets(sec, filing, source, names, *, offline=False, refresh=False):
    total = 0
    evidence = {}
    for name in sorted(set(names.values())):
        path = source.parent / name
        if offline or (path.exists() and not refresh):
            raw = read_image(path)
        else:
            canonical = filing.model_copy(update={"cik": str(int(filing.cik))})
            raw = await sec._get(sec._archive_url(canonical, name), max_bytes=MAX_ASSET_BYTES)
            validate_image(raw)
            if total + len(raw) > MAX_TOTAL_ASSET_BYTES:
                raise ValueError("Selected OCR assets exceed total byte limit")
            atomic_write(path, raw)
        total += len(raw)
        if total > MAX_TOTAL_ASSET_BYTES:
            raise ValueError("Selected OCR assets exceed total byte limit")
        evidence[name] = digest(raw)
    return evidence


def preparation_config(config: AppConfig, manifest: ExactManifest) -> AppConfig:
    config = config.model_copy(deep=True)
    if config.sec.base_url != "https://www.sec.gov" or config.sec.data_url != "https://data.sec.gov":
        raise ValueError("Exact preparation requires the official HTTPS SEC hosts")
    config.filings.forms = sorted({d.form for d in manifest.documents})
    config.filings.include_history = True
    config.filings.include_exhibits = False
    config.filings.include_amendments = False
    config.filings.start_date = min(d.filing_date for d in manifest.documents)
    config.filings.end_date = max(d.filing_date for d in manifest.documents)
    config.sync.prune_missing_filings = False
    return config


async def prepare(config, manifest, cache: Path, *, offline=False, refresh=False) -> dict:
    if offline and refresh:
        raise ValueError("--offline and --refresh cannot be combined")
    config = preparation_config(config, manifest)
    cache = cache.absolute() / digest(json_bytes(manifest.model_dump(mode="json")))
    check_existing_parents(cache)
    cache.mkdir(parents=True, exist_ok=True)
    regular_file_directory(cache)
    inventory_path = cache / "inventory.json"
    engine = await asyncio.to_thread(runtime, config.processing.ocr) if config.processing.ocr_images else None
    if offline:
        inventory = json.loads(regular_file(inventory_path).read_bytes())
    else:
        async with SECClient(config) as sec:
            inventory = await discover(sec, manifest)
        atomic_write(inventory_path, json_bytes(inventory))
    if len(inventory) != len(manifest.documents):
        raise ValueError("Cached inventory does not match the exact manifest")
    # Validate the entire selection before staging any document.
    for expected, entry in zip(manifest.documents, inventory):
        verify_identity(expected, FilingMetadata.model_validate(entry["filing"]),
                        DocumentInfo.model_validate(entry["document"]))
    inputs_path = cache / "inputs.json"
    prior_inputs = (json.loads(regular_file(inputs_path).read_bytes())
                    if offline or (inputs_path.exists() and not refresh) else None)
    if prior_inputs is not None and len(prior_inputs) != len(inventory):
        raise ValueError("Cached input receipts do not match the exact manifest")
    entries = []
    inputs = []
    builder = GraphClient(config)  # Pure payload construction; no context, session or authentication.

    async def process(sec):
        for entry in inventory:
            filing = FilingMetadata.model_validate(entry["filing"])
            document = DocumentInfo.model_validate(entry["document"])
            source = cache / filing.cik / filing.accession_no_dashes / document.filename
            if offline:
                _validate_download(regular_file(source).read_bytes(), document)
            else:
                check_existing_parents(source.parent)
                source.parent.mkdir(parents=True, exist_ok=True)
                regular_file_directory(source.parent)
                if source.exists():
                    regular_file(source)
                source = await sec.download_document(filing, document, cache, refresh=refresh)
                _validate_download(regular_file(source).read_bytes(), document)
            source_hash = digest(source.read_bytes())
            if prior_inputs is not None and source_hash != prior_inputs[len(inputs)]["source_sha256"]:
                raise ValueError("Cached source hashes differ; use --refresh online before staging assets")
            names = asset_names(source, filing, sec) if config.processing.ocr_images else {}
            assets = await stage_assets(sec, filing, source, names, offline=offline, refresh=refresh)
            captured = {"source_sha256": source_hash, "assets": assets}
            inputs.append(captured)
            if prior_inputs is not None and captured != prior_inputs[len(inputs) - 1]:
                raise ValueError("Cached source/asset hashes differ; use --refresh online to replace them")
            recognized = []

            def recognize(src, path):
                raw = read_image(path)
                if digest(raw) != assets[path.name]:
                    raise ValueError("OCR asset changed during preparation")
                text = ocr_asset_text(BytesIO(raw), config.processing.ocr)
                recognized.append({"src": src, "filename": path.name, "text": text})
                return text

            parsed = await asyncio.to_thread(
                parse_document, source, filing, document,
                ocr_images=config.processing.ocr_images, ocr_settings=config.processing.ocr,
                ocr_resolver=recognize, ocr_asset_names=names,
            )
            if parsed is None:
                raise ValueError(f"Empty primary document: {document.filename}")
            if set(names) != {r["src"] for r in recognized}:
                raise ValueError("Not every selected rotated image was recognized")
            if digest(regular_file(source).read_bytes()) != captured["source_sha256"]:
                raise ValueError("Primary source changed during preparation")
            payloads = [builder.build_payload(chunk)
                        for chunk in chunk_with_limit(parsed, config.chunking)]
            validate_payloads(payloads, scope_for(filing, document), config.chunking.max_item_bytes)
            entries.append({
                **entry, **captured, "ocr": recognized, "payloads": payloads,
                "largest_item_bytes": max(len(serialize_item(p)) for p in payloads),
            })
    if offline:
        await process(SECClient(config))  # No HTTP session is created in offline mode.
    else:
        async with SECClient(config) as sec:
            await process(sec)
    if engine is not None and await asyncio.to_thread(runtime, config.processing.ocr) != engine:
        raise ValueError("OCR engine/model changed during preparation")
    if not offline:
        atomic_write(inputs_path, json_bytes(inputs))
    return {
        "format": 1, "processing_version": PROCESSING_VERSION,
        "manifest": manifest.model_dump(mode="json"),
        "options": processing_options(config),
        "ocr_runtime": engine, "documents": entries,
    }


def validate_bundle(bundle, manifest, config):
    if (bundle["format"] != 1 or bundle["processing_version"] != PROCESSING_VERSION
            or bundle["manifest"] != manifest.model_dump(mode="json")):
        raise ValueError("Prepared bundle version or exact manifest mismatch")
    options = processing_options(preparation_config(config, manifest))
    if bundle["options"] != options:
        raise ValueError("Configuration differs from the prepared processing settings")
    if len(bundle["documents"]) != len(manifest.documents):
        raise ValueError("Prepared bundle has missing/extra documents")
    ids = set()
    for expected, entry in zip(manifest.documents, bundle["documents"]):
        filing = FilingMetadata.model_validate(entry["filing"])
        document = DocumentInfo.model_validate(entry["document"])
        verify_identity(expected, filing, document)
        validate_payloads(entry["payloads"], scope_for(filing, document), config.chunking.max_item_bytes)
        for payload in entry["payloads"]:
            if payload["id"] in ids:
                raise ValueError("Duplicate payload across documents")
            ids.add(payload["id"])


async def import_bundle(config, manifest, bundle, bundle_digest):
    """Import only this frozen generation. Repeating it resumes acknowledged delivery."""
    validate_bundle(bundle, manifest, config)
    pipeline = IngestionPipeline(config, save_payloads=True)
    options = {**bundle["options"], "exact_bundle_sha256": bundle_digest}
    stats = pipeline._stats()
    expected_entries = {
        (entry["filing"]["cik"], entry["filing"]["accession_number"]): entry
        for entry in bundle["documents"]
    }
    async with pipeline._state() as state, GraphClient(config) as graph:
        # A fresh destination or a retry of this exact bundle only, never adopt a live crawl.
        for status in FilingState:
            for record in await state.get_filings_by_state(status):
                if (record.processing_options != options
                        or (record.cik, record.accession_number) not in expected_entries
                        or record.sample_limit is not None or record.state == FilingState.RETIRING):
                    raise ValueError("Destination contains another generation; use a new connection/database")
        if not graph.schema_matches(await graph.get_schema_status(), graph.load_schema()):
            raise ValueError("Destination schema differs; set up a new connection before import")
        for entry in bundle["documents"]:
            filing = FilingMetadata.model_validate(entry["filing"])
            document = DocumentInfo.model_validate(entry["document"])
            filing_id = await state.add_filing(filing, processing_options=options)
            record = await state.get_filing(filing_id)
            if not record.inventory_complete:
                await state.set_inventory(filing_id, [document])
            documents = await state.get_documents(filing_id)
            if len(documents) != 1 or documents[0]["document"] != document:
                raise ValueError("Stored document inventory differs from the exact bundle")
            if not record.payloads_ready:
                if documents[0]["state"] != "parsed":
                    await state.save_document_payloads(filing_id, document, entry["payloads"])
                await state.mark_payloads_ready(filing_id)
            stored = {chunk.chunk_id: chunk.payload for chunk in await state.get_chunks(filing_id)}
            if stored != {payload["id"]: payload for payload in entry["payloads"]}:
                raise ValueError("Stored payloads differ from the exact bundle")
        # All documents are durable before the first Graph mutation.
        run_id = await state.start_run({"exact_bundle_sha256": bundle_digest})
        try:
            for entry in bundle["documents"]:
                filing = FilingMetadata.model_validate(entry["filing"])
                filing_id = await state.get_filing_id(filing.cik, filing.accession_number)
                await pipeline._deliver_filing(filing_id, state, graph, stats)
        except Exception:
            stats["errors"] += 1
            raise
        finally:
            await state.finish_run(run_id, stats)
    return stats
