"""Strict local OCR capture for maintenance; no discovery, downloads or replay."""

import base64
import hashlib
from io import BytesIO
from pathlib import Path, PureWindowsPath
import platform
import stat
import sys
import tempfile
from urllib.parse import unquote, urlsplit

from .parser import ocr_asset_text
from .config import OCRConfig
from . import ocr_engine


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def regular_file(path: Path) -> Path:
    """Reject links/junctions, including ancestor redirects, before reading bytes."""
    path = path.absolute()
    for part in (path, *path.parents):
        info = part.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError(f"Maintenance source bundle forbids symlinks/reparse points: {part}")
    if not path.is_file():
        raise ValueError(f"Maintenance source bundle requires a regular file: {path}")
    return path


def asset_path(root: Path, src: str) -> Path:
    url = urlsplit(src)
    name = unquote(url.path)
    parts = name.replace("\\", "/").split("/")
    if (not name or url.scheme or url.netloc or url.query or url.fragment
            or name.startswith(("/", "\\")) or PureWindowsPath(name).drive
            or any(p in ("", ".", "..") or ":" in p or p.endswith((".", " "))
                   or PureWindowsPath(p).is_reserved() for p in parts)):
        raise ValueError(f"OCR bundle requires an unambiguous relative local asset: {src!r}")
    asset = regular_file(root.joinpath(*parts))
    if not asset.resolve().is_relative_to(root.resolve()):
        raise ValueError(f"OCR asset escapes the approved source bundle: {src!r}")
    return asset


def runtime(settings: OCRConfig | None = None) -> dict:
    """Identify the actual default-English engine/model, never run recognition."""
    try:
        import PIL
    except ImportError as exc:
        raise RuntimeError("Maintenance OCR requires installed Pillow and Tesseract") from exc
    settings = settings or OCRConfig()
    executable, directory = ocr_engine.resolve(settings)
    regular_file(executable)
    model = regular_file(directory / "eng.traineddata")
    with tempfile.TemporaryDirectory(prefix="sec-ocr-probe-") as temporary:
        engine = ocr_engine.run(executable, directory, ["--version"], settings, temporary)
        languages = ocr_engine.run(
            executable, directory, ["--list-langs", "--tessdata-dir", str(directory)], settings, temporary,
        )
    engine = (engine.stdout + engine.stderr).decode("utf-8", errors="strict").strip()
    languages = (languages.stdout + languages.stderr).decode("utf-8", errors="strict").strip()
    if "eng" not in languages.splitlines():
        raise RuntimeError("Cannot bind Tesseract's English language data; no OCR plan was prepared")
    if platform.system() != "Windows":
        raise RuntimeError("Maintenance OCR runtime capture currently requires a bundled Windows engine")
    libraries = {p.name: digest(regular_file(p).read_bytes()) for p in sorted(executable.parent.glob("*.dll"))}
    if not libraries:
        raise RuntimeError("Maintenance OCR requires an approved engine bundle including its runtime DLLs")
    return {
        "backend": ocr_engine.BACKEND, "settings": settings.model_dump(),
        "python": sys.version, "platform": platform.platform(),
        "dependencies": {"Pillow": PIL.__version__},
        "pillow_files": {
            str(p.relative_to(Path(PIL.__file__).parent)): digest(regular_file(p).read_bytes())
            for p in sorted(Path(PIL.__file__).parent.rglob("*"))
            if p.suffix.lower() in {".py", ".pyd", ".dll"}
        },
        "executable": str(executable), "executable_hash": digest(executable.read_bytes()),
        "runtime_dlls": libraries,
        "engine_version": engine, "languages": languages,
        "language": "eng", "language_file": str(model), "language_hash": digest(model.read_bytes()),
        "config": "--psm 7", "rotation": -90, "minimum_height": 100,
        "upscale_minimum": 3, "resampling": "LANCZOS",
        "environment": ocr_engine.environment(executable, directory, "<private-per-call-directory>"),
    }


class Capture:
    """Called at the production parser's image replacement point, in source order."""

    def __init__(self, source: Path, settings: OCRConfig | None = None):
        self.settings = settings or OCRConfig()
        self.bundle = {"root": str(source.parent), "runtime": None, "assets": []}

    def resolve(self, src: str, resolved: Path) -> str:
        asset = asset_path(Path(self.bundle["root"]), src)
        if asset.resolve() != resolved:
            raise ValueError("OCR asset resolution differs from the production parser")
        raw = asset.read_bytes()
        if self.bundle["runtime"] is None:
            self.bundle["runtime"] = runtime(self.settings)
        text = ocr_asset_text(BytesIO(raw), self.settings)
        if not isinstance(text, str) or not text.strip():
            raise ValueError("OCR returned no usable text")
        self.bundle["assets"].append({
            "src": src, "path": str(asset), "sha256": digest(raw),
            "bytes": base64.b64encode(raw).decode("ascii"), "text": text,
        })
        return text


def validate(bundle: dict, source: Path, *, forward: bool, settings: OCRConfig | None = None) -> None:
    if bundle["root"] != str(source.parent):
        raise ValueError("OCR bundle root mismatch")
    if bool(bundle["assets"]) != (bundle["runtime"] is not None):
        raise ValueError("OCR runtime/asset provenance missing")
    for entry in bundle["assets"]:
        if (digest(base64.b64decode(entry["bytes"], validate=True)) != entry["sha256"]
                or not isinstance(entry["text"], str) or not entry["text"].strip()):
            raise ValueError("Frozen OCR asset/output mismatch")
        if forward:
            asset = asset_path(source.parent, entry["src"])
            if str(asset) != entry["path"] or digest(asset.read_bytes()) != entry["sha256"]:
                raise ValueError("OCR asset drift")
    if forward and bundle["runtime"] is not None:
        if bundle["runtime"].get("backend") != ocr_engine.BACKEND:
            raise ValueError("Legacy or unknown OCR backend; retain the prepared runtime for forward recovery")
        if runtime(settings) != bundle["runtime"]:
            raise ValueError("OCR runtime/language/settings drift; retain the prepared runtime")
