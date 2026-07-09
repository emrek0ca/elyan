"""Genel amaçlı görsel indirme — bir konu için herkese açık görsel kaynağından
(Openverse, yedek olarak Wikimedia Commons) DOĞRUDAN HTTP ile görsel indirir ve
kullanıcının klasörüne (varsayılan ~/Desktop) kaydeder.

Kırılgan pikselli GUI otomasyonu yerine %100 güvenilir bir yol: "kedi resmi bul
ve masaüstüne kaydet" gibi komutların "kaydet" kısmını otonom tamamlar.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus, urlparse

from actions._read_only_common import content_type_for
from actions._write_common import artifact_payload, normalize_source_context, slugify_filename
from runtime.capability_registry import SafeCapabilityError

_OPENVERSE_ENDPOINT = "https://api.openverse.org/v1/images/"
_WIKIMEDIA_ENDPOINT = "https://commons.wikimedia.org/w/api.php"
_USER_AGENT = "ElyanDesktop/1.0 (+https://elyan.app; contact: support@elyan.app)"
_MAX_COUNT = 5
_MAX_BYTES = 25 * 1024 * 1024  # 25 MB — makul üst sınır
_REQUEST_TIMEOUT = 30

_CONTENT_TYPE_EXT = {
    "image/jpeg": ".jpg",
    "image/pjpeg": ".jpg",
    "image/png": ".png",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/x-ms-bmp": ".bmp",
    "image/svg+xml": ".svg",
    "image/tiff": ".tiff",
}


def _requests_module() -> Any:
    import requests  # type: ignore[reportMissingImports]

    return requests


def _resolve_destination_dir(destination: str) -> tuple[Path, str]:
    """Hedef klasörü çözer. Varsayılan ~/Desktop. Güvenlik için yalnız kullanıcının
    ev dizini altına yazılmasına izin verir. (klasör, dostça-etiket) döndürür."""
    home = Path.home().resolve()
    raw = str(destination or "").strip()
    if not raw:
        resolved = home / "Desktop"
    else:
        candidate = Path(raw).expanduser()
        # Görsel uzantılı tam dosya yolu verildiyse üst klasörünü kullan.
        if candidate.suffix.lower() in _CONTENT_TYPE_EXT.values():
            candidate = candidate.parent
        resolved = candidate if candidate.is_absolute() else (home / candidate)
    resolved = resolved.resolve()
    try:
        resolved.relative_to(home)
    except ValueError as exc:
        raise SafeCapabilityError(
            "ACCESS_DENIED",
            "Görsel yalnızca kullanıcı klasörünün (ev dizini) içine kaydedilebilir.",
        ) from exc
    try:
        resolved.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise SafeCapabilityError("ACCESS_DENIED", "Hedef klasör oluşturulamadı.") from exc
    label = "masaüstüne" if resolved == home / "Desktop" else f"{resolved.name} klasörüne"
    return resolved, label


def _sniff_extension(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return ".gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return ".webp"
    if data[:2] == b"BM":
        return ".bmp"
    if data[:4] in (b"II*\x00", b"MM\x00*"):
        return ".tiff"
    head = data[:256].lstrip().lower()
    if head.startswith(b"<?xml") and b"<svg" in data[:512].lower():
        return ".svg"
    if head.startswith(b"<svg"):
        return ".svg"
    return ""


def _extension_for(content_type: str, url: str, data: bytes) -> str:
    normalized = str(content_type or "").split(";")[0].strip().lower()
    if normalized in _CONTENT_TYPE_EXT:
        return _CONTENT_TYPE_EXT[normalized]
    sniffed = _sniff_extension(data)
    if sniffed:
        return sniffed
    suffix = Path(urlparse(str(url or "")).path).suffix.lower()
    if suffix in _CONTENT_TYPE_EXT.values():
        return suffix
    return ".jpg"


def _looks_like_image(content_type: str, data: bytes) -> bool:
    normalized = str(content_type or "").split(";")[0].strip().lower()
    if normalized.startswith("image/"):
        return True
    return bool(_sniff_extension(data))


def _unique_path(directory: Path, base_slug: str, extension: str, *, overwrite: bool) -> Path:
    base = base_slug or "gorsel"
    candidate = directory / f"{base}{extension}"
    if overwrite or not candidate.exists():
        return candidate
    index = 2
    while True:
        candidate = directory / f"{base}-{index}{extension}"
        if not candidate.exists():
            return candidate
        index += 1


def _http_get(url: str, *, stream: bool = False) -> Any:
    requests = _requests_module()
    return requests.get(
        url,
        headers={"User-Agent": _USER_AGENT, "Accept": "image/*,*/*;q=0.8"},
        timeout=_REQUEST_TIMEOUT,
        stream=stream,
        allow_redirects=True,
    )


def _download_bytes(url: str) -> tuple[bytes, str] | None:
    """Verilen URL'den görsel indirir. (bytes, content_type) veya başarısızsa None."""
    if not url:
        return None
    requests = _requests_module()
    try:
        response = _http_get(url, stream=True)
    except requests.RequestException:
        return None
    try:
        if not response.ok:
            return None
        content_type = str(response.headers.get("Content-Type", "") or "")
        declared_length = response.headers.get("Content-Length")
        if declared_length and str(declared_length).isdigit() and int(declared_length) > _MAX_BYTES:
            return None
        buffer = bytearray()
        for chunk in response.iter_content(chunk_size=65536):
            if not chunk:
                continue
            buffer.extend(chunk)
            if len(buffer) > _MAX_BYTES:
                return None
        data = bytes(buffer)
    except requests.RequestException:
        return None
    finally:
        response.close()
    if not data or not _looks_like_image(content_type, data):
        return None
    return data, content_type


def _search_openverse(query: str, count: int) -> list[dict[str, Any]]:
    requests = _requests_module()
    url = (
        f"{_OPENVERSE_ENDPOINT}?q={quote_plus(query)}"
        f"&page_size={max(count * 3, 6)}&mature=false"
    )
    try:
        response = _http_get(url)
    except requests.RequestException:
        return []
    if not response.ok:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    results = payload.get("results", []) if isinstance(payload, dict) else []
    candidates: list[dict[str, Any]] = []
    for item in results if isinstance(results, list) else []:
        if not isinstance(item, dict):
            continue
        candidates.append(
            {
                "url": str(item.get("url", "") or ""),
                "thumbnail": str(item.get("thumbnail", "") or ""),
                "title": str(item.get("title", "") or ""),
                "creator": str(item.get("creator", "") or ""),
                "license": str(item.get("license", "") or ""),
                "landing": str(item.get("foreign_landing_url", "") or ""),
                "provider": "openverse",
            }
        )
    return candidates


def _search_wikimedia(query: str, count: int) -> list[dict[str, Any]]:
    requests = _requests_module()
    url = (
        f"{_WIKIMEDIA_ENDPOINT}?action=query&format=json&generator=search"
        f"&gsrsearch={quote_plus(query)}&gsrnamespace=6&gsrlimit={max(count * 2, 4)}"
        f"&prop=imageinfo&iiprop=url%7Cmime"
    )
    try:
        response = _http_get(url)
    except requests.RequestException:
        return []
    if not response.ok:
        return []
    try:
        payload = response.json()
    except ValueError:
        return []
    pages = (
        payload.get("query", {}).get("pages", {})
        if isinstance(payload, dict) and isinstance(payload.get("query"), dict)
        else {}
    )
    candidates: list[dict[str, Any]] = []
    for page in pages.values() if isinstance(pages, dict) else []:
        if not isinstance(page, dict):
            continue
        info = page.get("imageinfo", [])
        if not isinstance(info, list) or not info:
            continue
        first = info[0] if isinstance(info[0], dict) else {}
        mime = str(first.get("mime", "") or "")
        if mime and not mime.startswith("image/"):
            continue
        candidates.append(
            {
                "url": str(first.get("url", "") or ""),
                "thumbnail": "",
                "title": str(page.get("title", "") or ""),
                "creator": "",
                "license": "Wikimedia Commons",
                "landing": str(first.get("descriptionurl", "") or ""),
                "provider": "wikimedia",
            }
        )
    return candidates


def _fetch_one(candidate: dict[str, Any]) -> tuple[bytes, str, str] | None:
    """Adayın tam çözünürlüklü URL'sini, sonra Openverse thumbnail proxy'sini dener.
    (bytes, content_type, used_url) veya None döndürür."""
    for key in ("url", "thumbnail"):
        url = str(candidate.get(key, "") or "")
        if not url:
            continue
        downloaded = _download_bytes(url)
        if downloaded is not None:
            data, content_type = downloaded
            return data, content_type, url
    return None


def _log_event(event: str, **fields: Any) -> None:
    payload = {"event": event, **fields}
    print(f"image_fetch {json.dumps(payload, ensure_ascii=False)}", file=sys.stderr)


def image_fetch(
    query: str,
    destination: str = "",
    count: int = 1,
    overwrite: bool = False,
) -> dict[str, Any]:
    subject = " ".join(str(query or "").split()).strip()
    if not subject:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Görsel indirmek için bir konu gerekli.")

    try:
        requested = int(count)
    except (TypeError, ValueError):
        requested = 1
    requested = max(1, min(requested, _MAX_COUNT))

    directory, dest_label = _resolve_destination_dir(destination)

    candidates = _search_openverse(subject, requested)
    if len(candidates) < requested:
        candidates = candidates + _search_wikimedia(subject, requested)
    if not candidates:
        _log_event("no_results", query=subject)
        raise SafeCapabilityError(
            "IMAGE_NOT_FOUND",
            "Bu konu için herkese açık bir görsel bulunamadı. Farklı bir arama terimi dene.",
        )

    base_slug = slugify_filename(subject, fallback="gorsel")
    saved: list[dict[str, Any]] = []
    used_urls: set[str] = set()
    for candidate in candidates:
        if len(saved) >= requested:
            break
        if str(candidate.get("url", "") or "") in used_urls:
            continue
        fetched = _fetch_one(candidate)
        if fetched is None:
            continue
        data, content_type, used_url = fetched
        used_urls.add(str(candidate.get("url", "") or ""))
        extension = _extension_for(content_type, used_url, data)
        slug = base_slug if requested == 1 else f"{base_slug}-{len(saved) + 1}"
        output_path = _unique_path(directory, slug, extension, overwrite=overwrite)
        try:
            output_path.write_bytes(data)
        except OSError as exc:
            raise SafeCapabilityError("WRITE_FAILED", "Görsel dosyaya kaydedilemedi.") from exc
        saved.append(
            {
                "outputPath": str(output_path),
                "name": output_path.name,
                "sourceUrl": used_url,
                "landingUrl": str(candidate.get("landing", "") or ""),
                "title": normalize_source_context(str(candidate.get("title", "") or ""), max_chars=160),
                "creator": str(candidate.get("creator", "") or ""),
                "license": str(candidate.get("license", "") or ""),
                "provider": str(candidate.get("provider", "") or ""),
                "contentType": content_type_for(output_path),
                "bytes": len(data),
            }
        )

    if not saved:
        _log_event("download_failed", query=subject, candidates=len(candidates))
        raise SafeCapabilityError(
            "IMAGE_DOWNLOAD_FAILED",
            "Bulunan görseller indirilemedi. Lütfen tekrar dene.",
        )

    _log_event("success", query=subject, saved=len(saved), destination=str(directory))
    if len(saved) == 1:
        text = f"Görsel {dest_label} kaydedildi.\n{saved[0]['name']}"
    else:
        names = "\n".join(entry["name"] for entry in saved)
        text = f"{len(saved)} görsel {dest_label} kaydedildi.\n{names}"

    return {
        "text": text,
        "result": {
            "kind": "image_fetch",
            "query": subject,
            "destination": str(directory),
            "savedCount": len(saved),
            "images": saved,
        },
        "artifacts": [artifact_payload(Path(entry["outputPath"])) for entry in saved],
    }
