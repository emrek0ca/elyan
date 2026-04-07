"""Optional LiteParse adapter for Elyan document ingestion.

If LiteParse is available locally, Elyan uses it as a fast primary parser for
PDF/Office/image ingestion. Otherwise the existing parsing stack remains active.
"""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from utils.logger import get_logger

logger = get_logger("office.liteparse")

SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".doc",
    ".docx",
    ".ppt",
    ".pptx",
    ".xls",
    ".xlsx",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".bmp",
    ".tif",
    ".tiff",
    ".gif",
    ".md",
    ".markdown",
    ".txt",
}


def liteparse_available() -> bool:
    if os.getenv("ELYAN_DISABLE_LITEPARSE", "").strip().lower() in {"1", "true", "yes", "on"}:
        return False
    if shutil.which(os.getenv("ELYAN_LITEPARSE_CMD", "liteparse")):
        return True
    try:
        importlib.import_module("liteparse")
        return True
    except Exception:
        return False


async def parse_document_with_liteparse(path: str, *, max_chars: int = 200_000) -> dict[str, Any]:
    file_path = Path(path).expanduser().resolve()
    if file_path.suffix.lower() not in SUPPORTED_EXTENSIONS:
        return {"success": False, "error": "liteparse_unsupported_extension"}

    payload = await _run_liteparse(file_path)
    if not payload.get("success"):
        return payload

    parsed = _normalize_liteparse_payload(payload.get("payload"))
    content = str(parsed.get("content") or "")[:max_chars]
    if not content.strip():
        return {"success": False, "error": "liteparse_empty_output", "backend": "liteparse"}

    return {
        "success": True,
        "backend": "liteparse",
        "path": str(file_path),
        "content": content,
        "pages": list(parsed.get("pages") or []),
        "screenshots": list(parsed.get("screenshots") or []),
        "metadata": dict(parsed.get("metadata") or {}),
    }


async def _run_liteparse(file_path: Path) -> dict[str, Any]:
    module_result = await _run_liteparse_module(file_path)
    if module_result.get("success"):
        return module_result
    return await _run_liteparse_cli(file_path)


async def _run_liteparse_module(file_path: Path) -> dict[str, Any]:
    try:
        module = importlib.import_module("liteparse")
    except Exception:
        return {"success": False, "error": "liteparse_module_missing"}

    try:
        for attr in ("parse_file", "parse", "load_file"):
            func = getattr(module, attr, None)
            if callable(func):
                result = await _maybe_await(func(str(file_path)))
                return {"success": True, "payload": result}
        parser_cls = getattr(module, "LiteParser", None)
        if parser_cls is not None:
            parser = parser_cls()
            for attr in ("parse_file", "parse"):
                func = getattr(parser, attr, None)
                if callable(func):
                    result = await _maybe_await(func(str(file_path)))
                    return {"success": True, "payload": result}
    except Exception as exc:
        logger.debug(f"liteparse module run failed: {exc}")
        return {"success": False, "error": str(exc)}
    return {"success": False, "error": "liteparse_module_no_supported_entrypoint"}


async def _run_liteparse_cli(file_path: Path) -> dict[str, Any]:
    candidates = [
        [os.getenv("ELYAN_LITEPARSE_CMD", "liteparse"), "parse", str(file_path), "--json"],
        [os.getenv("ELYAN_LITEPARSE_CMD", "liteparse"), str(file_path), "--json"],
        ["lit", "parse", str(file_path), "--json"],
    ]
    for command in candidates:
        binary = shutil.which(command[0])
        if not binary:
            continue
        try:
            proc = await asyncio.create_subprocess_exec(
                binary,
                *command[1:],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.debug("liteparse cli failed: %s", stderr.decode("utf-8", errors="ignore"))
                continue
            raw = stdout.decode("utf-8", errors="ignore").strip()
            if not raw:
                continue
            try:
                return {"success": True, "payload": json.loads(raw)}
            except Exception:
                return {"success": True, "payload": {"content": raw}}
        except Exception as exc:
            logger.debug(f"liteparse cli invoke failed: {exc}")
            continue
    return {"success": False, "error": "liteparse_cli_missing"}


async def _maybe_await(value: Any) -> Any:
    if asyncio.iscoroutine(value):
        return await value
    return value


def _normalize_liteparse_payload(payload: Any) -> dict[str, Any]:
    if isinstance(payload, str):
        return {"content": payload, "pages": [], "screenshots": [], "metadata": {}}
    if not isinstance(payload, dict):
        return {"content": str(payload or ""), "pages": [], "screenshots": [], "metadata": {}}

    pages_raw = payload.get("pages") if isinstance(payload.get("pages"), list) else []
    pages: list[dict[str, Any]] = []
    page_texts: list[str] = []
    screenshots: list[str] = []
    for index, page in enumerate(pages_raw, start=1):
        if not isinstance(page, dict):
            continue
        page_text = _coalesce_text(
            page.get("text"),
            page.get("markdown"),
            page.get("content"),
            page.get("md"),
        )
        if page_text:
            page_texts.append(page_text)
        screenshot = str(page.get("screenshot") or page.get("image") or "").strip()
        if screenshot:
            screenshots.append(screenshot)
        pages.append(
            {
                "page_number": int(page.get("page_number") or page.get("page") or index),
                "text": page_text,
                "title": str(page.get("title") or "").strip(),
                "bbox_text": _coalesce_text(page.get("layout_text"), page.get("spatial_text")),
            }
        )

    content = _coalesce_text(
        payload.get("text"),
        payload.get("markdown"),
        payload.get("content"),
        payload.get("md"),
        "\n\n".join(page_texts),
    )
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    if "page_count" not in metadata:
        metadata = {**metadata, "page_count": len(pages)}
    return {
        "content": content,
        "pages": pages,
        "screenshots": screenshots,
        "metadata": metadata,
    }


def _coalesce_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


__all__ = ["SUPPORTED_EXTENSIONS", "liteparse_available", "parse_document_with_liteparse"]
