from __future__ import annotations

import shutil
import subprocess
import tempfile
from importlib.util import find_spec
from pathlib import Path
from typing import Any

from actions._read_only_common import (
    bulletize_text,
    content_type_for,
    ensure_allowed_path,
    ensure_mode,
    preview_text,
    summarize_text,
    workspace_root,
)
from runtime.capability_registry import SafeCapabilityError

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff"}
_ALLOWED_SUFFIXES = _IMAGE_SUFFIXES | {".pdf"}


def _workspace_root() -> Path:
    return workspace_root()


def _tesseract_binary() -> str:
    binary = shutil.which("tesseract")
    if not binary:
        raise ModuleNotFoundError("tesseract")
    return binary


def _ocr_image_with_tesseract(path: Path, language_hint: str) -> str:
    language = str(language_hint or "").strip() or "eng+tur"
    result = subprocess.run(
        [_tesseract_binary(), str(path), "stdout", "-l", language],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=45,
        check=False,
    )
    text = str(result.stdout or "").strip()
    if result.returncode != 0 and not text:
        raise SafeCapabilityError("OCR_FAILED", "OCR güvenli şekilde tamamlanamadı.")
    if not text:
        raise SafeCapabilityError("EMPTY_DOCUMENT", "Görselde okunabilir metin bulunamadı.")
    return text


def _easyocr_language_codes(language_hint: str) -> list[str]:
    requested = [item.strip().lower() for item in str(language_hint or "").replace(",", "+").split("+") if item.strip()]
    normalized = requested or ["eng", "tur"]
    mapping = {
        "eng": "en",
        "en": "en",
        "tur": "tr",
        "tr": "tr",
    }
    languages: list[str] = []
    for item in normalized:
        code = mapping.get(item)
        if code and code not in languages:
            languages.append(code)
    if "en" not in languages:
        languages.insert(0, "en")
    return languages


def _easyocr_available() -> bool:
    return find_spec("easyocr") is not None


def _ocr_image_with_easyocr(path: Path, language_hint: str) -> str:
    import easyocr  # type: ignore[reportMissingImports]

    reader = easyocr.Reader(_easyocr_language_codes(language_hint), gpu=False, verbose=False)
    results = reader.readtext(str(path), detail=0, paragraph=True)
    text = "\n".join(str(item or "").strip() for item in results if str(item or "").strip()).strip()
    if not text:
        raise SafeCapabilityError("EMPTY_DOCUMENT", "Görselde okunabilir metin bulunamadı.")
    return text


def _run_ocr_backend(path: Path, language_hint: str) -> tuple[str, str]:
    if _easyocr_available():
        return _ocr_image_with_easyocr(path, language_hint), "easyocr"
    return _ocr_image_with_tesseract(path, language_hint), "tesseract"


def _pdf_to_images(path: Path, target_dir: Path) -> list[Path]:
    import fitz  # type: ignore[reportMissingImports]

    rendered: list[Path] = []
    document = fitz.open(path)
    try:
        for index, page in enumerate(document):
            pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            output = target_dir / f"page-{index + 1}.png"
            pixmap.save(output)
            rendered.append(output)
    finally:
        document.close()
    return rendered


def _extract_ocr_text(path: Path, language_hint: str) -> tuple[str, int | None, str]:
    if path.suffix.lower() in _IMAGE_SUFFIXES:
        text, backend = _run_ocr_backend(path, language_hint)
        return text, 1, backend

    with tempfile.TemporaryDirectory(prefix="elyan-ocr-") as temp_dir:
        images = _pdf_to_images(path, Path(temp_dir))
        chunks: list[str] = []
        backend_used = ""
        for image in images:
            text, backend = _run_ocr_backend(image, language_hint)
            if not backend_used:
                backend_used = backend
            if text:
                chunks.append(text)
        combined = "\n\n".join(chunk.strip() for chunk in chunks if chunk.strip()).strip()
        if not combined:
            raise SafeCapabilityError("EMPTY_DOCUMENT", "OCR sonucunda okunabilir metin bulunamadı.")
        return combined, len(images), backend_used or "unknown"


def _user_facing_text(path: Path, mode: str, summary: str, bullets: list[str], text: str) -> str:
    title = path.name
    if mode == "summary":
        return f"{title}\n{summary}"
    if mode == "bullets":
        if not bullets:
            return f"{title}\nOCR çıktısından madde çıkarılamadı."
        return f"{title}\n" + "\n".join(f"• {item}" for item in bullets)
    preview = summarize_text(text, max_chars=640)
    return f"{title}\n{preview}"


def ocr_read(
    path: str,
    mode: str = "read",
    language_hint: str = "",
    _selectedPaths: list[str] | None = None,
) -> dict[str, Any]:
    resolved = ensure_allowed_path(
        path,
        allowed_suffixes=_ALLOWED_SUFFIXES,
        selected_paths=_selectedPaths,
        root_resolver=_workspace_root,
    )
    normalized_mode = ensure_mode(mode)
    extracted_text, pages, backend = _extract_ocr_text(resolved, language_hint)
    trimmed_text = preview_text(extracted_text)
    summary = summarize_text(trimmed_text, max_chars=320)
    bullets = bulletize_text(trimmed_text)
    return {
        "text": _user_facing_text(resolved, normalized_mode, summary, bullets, trimmed_text),
        "result": {
            "kind": "ocr_read",
            "sourcePath": str(resolved),
            "contentType": content_type_for(resolved),
            "pages": pages,
            "backend": backend,
            "mode": normalized_mode,
            "languageHint": str(language_hint or "").strip() or "eng+tur",
            "text": trimmed_text,
            "summary": summary,
            "bullets": bullets,
        },
        "artifacts": [],
    }


def ocr_read_status() -> dict[str, Any]:
    easyocr_available = _easyocr_available()
    tesseract_available = bool(shutil.which("tesseract"))
    pymupdf_available = find_spec("fitz") is not None
    available = bool((easyocr_available or tesseract_available) and pymupdf_available)
    if available:
        return {
            "available": True,
            "lastErrorCode": "",
            "lastErrorMessage": "",
            "backend": "easyocr" if easyocr_available else "tesseract",
            "supportedFormats": ["image", "pdf"],
        }
    missing: list[str] = []
    if not pymupdf_available:
        missing.append("fitz")
    if not easyocr_available and not tesseract_available:
        missing.append("easyocr/tesseract")
    return {
        "available": False,
        "lastErrorCode": "DEPENDENCY_UNAVAILABLE",
        "lastErrorMessage": "OCR için gerekli yerel bağımlılıklar hazır değil.",
        "missingDependencies": missing,
        "supportedFormats": ["image", "pdf"],
    }
