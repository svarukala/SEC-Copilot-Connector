"""Strict local OCR capture for maintenance; no discovery, downloads or replay."""

import base64
import hashlib
from importlib.metadata import version
from io import BytesIO
import os
from pathlib import Path, PureWindowsPath
import platform
import re
import shutil
import stat
import subprocess
import sys
from urllib.parse import unquote, urlsplit

from .parser import ocr_asset_text


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


def runtime() -> dict:
    """Identify the actual default-English engine/model, never run recognition."""
    try:
        import PIL
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("Maintenance OCR requires installed Pillow, pytesseract and Tesseract") from exc
    executable = shutil.which(pytesseract.pytesseract.tesseract_cmd)
    if executable is None:
        raise RuntimeError("Maintenance OCR requires an available local Tesseract executable")
    executable = Path(executable).resolve()

    def info(arg):
        result = subprocess.run(
            [str(executable), arg], capture_output=True, text=True, check=True, timeout=15,
        )
        return (result.stdout + result.stderr).strip()

    engine = info("--version")
    languages = info("--list-langs")
    match = re.search(r'List of available languages in "([^"]+)"', languages)
    if match is None or "eng" not in languages.splitlines():
        raise RuntimeError("Cannot bind Tesseract's default eng language data; no OCR plan was prepared")
    model = regular_file(Path(match.group(1)) / "eng.traineddata")
    return {
        "python": sys.version, "platform": platform.platform(),
        "dependencies": {"Pillow": PIL.__version__, "pytesseract": version("pytesseract")},
        "executable": str(executable), "executable_hash": digest(executable.read_bytes()),
        "engine_version": engine, "languages": languages,
        "language": "eng", "language_file": str(model), "language_hash": digest(model.read_bytes()),
        "config": "--psm 7", "rotation": -90, "minimum_height": 100,
        "upscale_minimum": 3, "resampling": "LANCZOS",
        "environment": {key: os.environ.get(key) for key in ("TESSDATA_PREFIX", "OMP_THREAD_LIMIT")},
    }


class Capture:
    """Called at the production parser's image replacement point, in source order."""

    def __init__(self, source: Path):
        self.bundle = {"root": str(source.parent), "runtime": None, "assets": []}

    def resolve(self, src: str, resolved: Path) -> str:
        asset = asset_path(Path(self.bundle["root"]), src)
        if asset.resolve() != resolved:
            raise ValueError("OCR asset resolution differs from the production parser")
        raw = asset.read_bytes()
        if self.bundle["runtime"] is None:
            self.bundle["runtime"] = runtime()
        text = ocr_asset_text(BytesIO(raw))
        if not isinstance(text, str) or not text.strip():
            raise ValueError("OCR returned no usable text")
        self.bundle["assets"].append({
            "src": src, "path": str(asset), "sha256": digest(raw),
            "bytes": base64.b64encode(raw).decode("ascii"), "text": text,
        })
        return text


def validate(bundle: dict, source: Path, *, forward: bool) -> None:
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
    if forward and bundle["runtime"] is not None and runtime() != bundle["runtime"]:
        raise ValueError("OCR runtime/language/settings drift; retain the prepared runtime")
