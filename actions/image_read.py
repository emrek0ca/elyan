from __future__ import annotations

from pathlib import Path
from typing import Any

from actions._read_only_common import content_type_for, ensure_allowed_path, summarize_text, workspace_root
from runtime.capability_registry import SafeCapabilityError

_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
_IMAGE_MODES = {"summary", "metadata", "palette"}


def _workspace_root() -> Path:
    return workspace_root()


def _ensure_mode(value: str) -> str:
    mode = str(value or "summary").strip().lower() or "summary"
    if mode not in _IMAGE_MODES:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Geçersiz görsel okuma modu.")
    return mode


def _open_image(path: Path) -> Any:
    from PIL import Image  # type: ignore[reportMissingImports]

    return Image.open(path)


def _metadata_payload(image: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    for key, value in dict(getattr(image, "info", {}) or {}).items():
        if len(payload) >= 12:
            break
        if isinstance(value, (str, int, float, bool)):
            payload[str(key)] = value
        else:
            payload[str(key)] = str(value)[:120]
    return payload


def _palette_payload(image: Any, *, limit: int = 5) -> list[dict[str, Any]]:
    sample = image.convert("RGB")
    sample.thumbnail((64, 64))
    colors = sample.getcolors(maxcolors=64 * 64) or []
    if not colors:
        return []
    total = sum(count for count, _rgb in colors) or 1
    ranked = sorted(colors, key=lambda item: item[0], reverse=True)[:limit]
    payload: list[dict[str, Any]] = []
    for count, rgb in ranked:
        red, green, blue = (int(channel) for channel in rgb)
        payload.append(
            {
                "hex": f"#{red:02X}{green:02X}{blue:02X}",
                "rgb": [red, green, blue],
                "ratio": round(float(count) / float(total), 4),
            }
        )
    return payload


def _summary_text(
    path: Path,
    *,
    width: int,
    height: int,
    color_mode: str,
    has_alpha: bool,
    frame_count: int,
    palette: list[dict[str, Any]],
) -> str:
    parts = [
        f"{path.name}: {width}×{height}px",
        color_mode or "unknown mode",
        "alpha var" if has_alpha else "alpha yok",
    ]
    if frame_count > 1:
        parts.append(f"{frame_count} frame")
    if palette:
        top = palette[0]
        parts.append(f"baskın renk {top.get('hex', '')}")
    return summarize_text(", ".join(part for part in parts if part), max_chars=320)


def _user_facing_text(
    path: Path,
    *,
    mode: str,
    summary: str,
    metadata: dict[str, Any],
    palette: list[dict[str, Any]],
) -> str:
    if mode == "metadata":
        details = [f"{key}: {value}" for key, value in metadata.items()]
        return f"{path.name}\n" + ("\n".join(details) if details else summary)
    if mode == "palette":
        if not palette:
            return f"{path.name}\nBelirgin renk paleti çıkarılamadı."
        return f"{path.name}\n" + "\n".join(
            f"• {item.get('hex', '')} ({round(float(item.get('ratio', 0.0)) * 100)}%)"
            for item in palette
        )
    return f"{path.name}\n{summary}"


def image_read(path: str, mode: str = "summary", _selectedPaths: list[str] | None = None) -> dict[str, Any]:
    resolved = ensure_allowed_path(
        path,
        allowed_suffixes=_IMAGE_SUFFIXES,
        selected_paths=_selectedPaths,
        root_resolver=_workspace_root,
    )
    normalized_mode = _ensure_mode(mode)
    with _open_image(resolved) as image:
        width, height = image.size
        color_mode = str(getattr(image, "mode", "") or "")
        bands = tuple(str(band) for band in (getattr(image, "getbands", lambda: ())() or ()))
        has_alpha = "A" in bands or color_mode.endswith("A")
        frame_count = int(getattr(image, "n_frames", 1) or 1)
        metadata = _metadata_payload(image)
        palette = _palette_payload(image)
    summary = _summary_text(
        resolved,
        width=width,
        height=height,
        color_mode=color_mode,
        has_alpha=has_alpha,
        frame_count=frame_count,
        palette=palette,
    )
    return {
        "text": _user_facing_text(
            resolved,
            mode=normalized_mode,
            summary=summary,
            metadata=metadata,
            palette=palette,
        ),
        "result": {
            "kind": "image_read",
            "sourcePath": str(resolved),
            "contentType": content_type_for(resolved),
            "mode": normalized_mode,
            "width": width,
            "height": height,
            "colorMode": color_mode,
            "hasAlpha": has_alpha,
            "frameCount": frame_count,
            "summary": summary,
            "palette": palette,
            "metadata": metadata,
        },
        "artifacts": [],
    }
