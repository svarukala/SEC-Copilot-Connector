"""Bounded local Tesseract subprocess adapter; no shell, installs or downloads."""

import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from .config import OCRConfig


BACKEND = "tesseract-cli-v1"


def captured_options(settings: OCRConfig) -> dict:
    return {"backend": BACKEND, **settings.model_dump()}


def captured_settings(options: dict) -> OCRConfig:
    if options.get("backend") != BACKEND:
        raise ValueError(
            "Missing or unsupported captured OCR backend; use the original runtime to finish "
            "preparation, or explicitly reprocess with reviewed current OCR settings"
        )
    if set(options) != {"backend", "executable", "tessdata_dir", "timeout_seconds"}:
        raise ValueError("Incomplete or unknown captured OCR settings")
    return OCRConfig.model_validate({k: v for k, v in options.items() if k != "backend"})


def resolve(settings: OCRConfig) -> tuple[Path, Path]:
    command = shutil.which(settings.executable)
    if command is None:
        raise RuntimeError("Local Tesseract executable unavailable; configure processing.ocr.executable")
    executable = Path(command).resolve(strict=True)
    if executable.suffix.lower() in {".bat", ".cmd", ".ps1"}:
        raise ValueError("OCR executable must be a native engine, not a shell script")
    directory = (Path(settings.tessdata_dir) if settings.tessdata_dir else executable.parent / "tessdata")
    directory = directory.resolve(strict=True)
    if not (directory / "eng.traineddata").is_file():
        raise RuntimeError("Local Tesseract English model missing; supply eng.traineddata in configured tessdata_dir")
    return executable, directory


def environment(executable: Path, directory: Path, temporary: str) -> dict:
    # Do not inherit mutable PATH, language/model overrides, or OpenMP settings.
    env = {k: os.environ[k] for k in ("SystemRoot", "WINDIR") if k in os.environ}
    env.update({
        "PATH": str(executable.parent), "TESSDATA_PREFIX": str(directory),
        "OMP_THREAD_LIMIT": "1", "LANG": "C", "LC_ALL": "C", "TEMP": temporary, "TMP": temporary,
    })
    return env


def run(executable: Path, directory: Path, args: list[str], settings: OCRConfig, temporary: str,
        *, recognition: bool = False) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            [str(executable), *args], shell=False, stdin=subprocess.DEVNULL,
            capture_output=True, timeout=settings.timeout_seconds,
            cwd=temporary,
            env=environment(executable, directory, temporary),
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"Tesseract exceeded {settings.timeout_seconds:g}s timeout") from exc
    except OSError as exc:
        raise RuntimeError(f"Cannot execute local Tesseract: {exc}") from exc
    diagnostics = result.stderr.decode("utf-8", errors="replace").strip()
    combined = result.stdout.decode("utf-8", errors="replace") + "\n" + diagnostics
    if (result.returncode != 0 or (recognition and diagnostics)
            or (not recognition and re.search(r"\b(error|failed|couldn't|cannot)\b", combined, re.IGNORECASE))):
        raise RuntimeError(f"Tesseract failed (exit {result.returncode}): {diagnostics or combined.strip()}")
    return result


def image_to_text(image, settings: OCRConfig | None = None) -> str:
    settings = settings or OCRConfig()
    executable, directory = resolve(settings)
    with tempfile.TemporaryDirectory(prefix="sec-ocr-") as temporary:
        source = Path(temporary) / "input.png"
        image.save(source, format="PNG")
        result = run(
            executable, directory,
            [str(source), "stdout", "--tessdata-dir", str(directory), "-l", "eng", "--psm", "7"],
            settings, temporary, recognition=True,
        )
        try:
            text = result.stdout.decode("utf-8").strip()
        except UnicodeDecodeError as exc:
            raise RuntimeError("Tesseract returned invalid UTF-8 text") from exc
        if not text:
            raise RuntimeError("Tesseract returned no usable text")
        return text
