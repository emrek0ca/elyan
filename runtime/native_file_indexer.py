from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime import state_store


CAPABILITY_NAME = "local_files.index"
_SCAN_CACHE_VERSION = 1
_MAX_FILES_DEFAULT = 5000
_REFRESH_INTERVAL_SECONDS = 30
_SUPPORTED_SUFFIXES = {".txt", ".md", ".markdown", ".json", ".csv", ".pdf", ".docx"}
_WARMUP_LOCK = threading.RLock()
_WARMUP_THREAD: threading.Thread | None = None


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _sidecar_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "native" / "file_indexer"


def _sidecar_manifest_path() -> Path:
    return _sidecar_dir() / "Cargo.toml"


def _native_index_dir() -> Path:
    return state_store.CONFIG_DIR / "native_index"


def _metadata_cache_path() -> Path:
    return _native_index_dir() / "metadata.json"


def _status_template(*, available: bool) -> dict[str, Any]:
    return {
        "available": bool(available),
        "ready": False,
        "version": "",
        "stats": {
            "rootCount": 0,
            "indexedFileCount": 0,
            "lastScanAt": "",
        },
        "errorCode": "",
    }


def _load_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return dict(default)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(default)
    return dict(payload) if isinstance(payload, dict) else dict(default)


def _save_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _normalize_root_item(item: Any) -> dict[str, str] | None:
    if not isinstance(item, dict):
        return None
    raw_path = str(item.get("path", "") or "").strip()
    if not raw_path:
        return None
    try:
        resolved = Path(raw_path).expanduser().resolve()
    except Exception:
        return None
    if not resolved.exists() or not resolved.is_dir():
        return None
    label = " ".join(str(item.get("label", "") or "").split()).strip()[:120] or resolved.name or "Approved root"
    return {
        "path": str(resolved),
        "label": label,
        "addedAt": str(item.get("addedAt", "") or item.get("added_at", "") or _utc_now_iso())[:80],
    }


def approved_roots(state: dict[str, Any] | None = None) -> list[dict[str, str]]:
    snapshot = state if isinstance(state, dict) else state_store.snapshot()
    local_indexing = snapshot.get("localIndexing", {})
    local_indexing = local_indexing if isinstance(local_indexing, dict) else {}
    items = local_indexing.get("approvedRoots", [])
    if not isinstance(items, list):
        return []
    normalized: list[dict[str, str]] = []
    seen_paths: set[str] = set()
    for item in items:
        normalized_item = _normalize_root_item(item)
        if normalized_item is None:
            continue
        key = normalized_item["path"].lower()
        if key in seen_paths:
            continue
        seen_paths.add(key)
        normalized.append(normalized_item)
    return normalized


def indexing_enabled(state: dict[str, Any] | None = None) -> bool:
    snapshot = state if isinstance(state, dict) else state_store.snapshot()
    permissions = snapshot.get("permissions", {})
    permissions = permissions if isinstance(permissions, dict) else {}
    value = permissions.get("allow_file_indexing", False)
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _binary_name() -> str:
    return "elyan-file-indexer.exe" if os.name == "nt" else "elyan-file-indexer"


def _candidate_binary_paths() -> list[Path]:
    explicit = str(os.environ.get("ELYAN_NATIVE_FILE_INDEXER_BIN", "") or "").strip()
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    sidecar_dir = _sidecar_dir()
    candidates.extend(
        [
            sidecar_dir / "target" / "release" / _binary_name(),
            sidecar_dir / "target" / "debug" / _binary_name(),
        ]
    )
    return candidates


def _cargo_available() -> bool:
    return bool(shutil.which("cargo"))


def sidecar_available() -> bool:
    manifest = _sidecar_manifest_path()
    if not manifest.exists():
        return False
    for candidate in _candidate_binary_paths():
        if candidate.exists():
            return True
    return _cargo_available()


def _resolve_binary_path() -> Path | None:
    for candidate in _candidate_binary_paths():
        if candidate.exists():
            return candidate
    return None


def _compile_sidecar() -> Path:
    manifest = _sidecar_manifest_path()
    if not manifest.exists():
        raise RuntimeError("sidecar_manifest_missing")
    if not _cargo_available():
        raise RuntimeError("cargo_unavailable")
    result = subprocess.run(
        [
            "cargo",
            "build",
            "--manifest-path",
            str(manifest),
            "--release",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    binary_path = _sidecar_dir() / "target" / "release" / _binary_name()
    if result.returncode != 0 or not binary_path.exists():
        detail = " ".join((result.stderr or result.stdout or "").split()).strip()[:240]
        raise RuntimeError(detail or "sidecar_build_failed")
    return binary_path


def _state_status(state: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = state if isinstance(state, dict) else state_store.snapshot()
    local_indexing = snapshot.get("localIndexing", {})
    local_indexing = local_indexing if isinstance(local_indexing, dict) else {}
    status = local_indexing.get("status", {})
    status = dict(status) if isinstance(status, dict) else {}
    stats = status.get("stats", {})
    stats = dict(stats) if isinstance(stats, dict) else {}
    normalized = _status_template(available=sidecar_available())
    normalized["ready"] = bool(status.get("ready", False))
    normalized["version"] = str(status.get("version", "") or "")[:40]
    normalized["errorCode"] = str(status.get("errorCode", "") or "")[:120]
    normalized["stats"] = {
        "rootCount": max(0, int(stats.get("rootCount", 0) or 0)),
        "indexedFileCount": max(0, int(stats.get("indexedFileCount", 0) or 0)),
        "lastScanAt": str(stats.get("lastScanAt", "") or "")[:80],
    }
    return normalized


def _persist_status(status: dict[str, Any]) -> dict[str, Any]:
    normalized = _status_template(available=bool(status.get("available", False)))
    normalized["ready"] = bool(status.get("ready", False))
    normalized["version"] = str(status.get("version", "") or "")[:40]
    normalized["errorCode"] = str(status.get("errorCode", "") or "")[:120]
    stats = status.get("stats", {})
    stats = stats if isinstance(stats, dict) else {}
    normalized["stats"] = {
        "rootCount": max(0, int(stats.get("rootCount", 0) or 0)),
        "indexedFileCount": max(0, int(stats.get("indexedFileCount", 0) or 0)),
        "lastScanAt": str(stats.get("lastScanAt", "") or "")[:80],
    }
    state_store.update_state({"localIndexing": {"status": normalized}})
    return normalized


def current_capability_state(state: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = state if isinstance(state, dict) else state_store.snapshot()
    status = _state_status(snapshot)
    status["available"] = sidecar_available()
    if not status["available"]:
        status["ready"] = False
        status["errorCode"] = "sidecar_unavailable"
    elif not indexing_enabled(snapshot):
        status["ready"] = False
        status["errorCode"] = "permission_required"
    elif not approved_roots(snapshot):
        status["ready"] = False
        status["errorCode"] = "no_approved_roots"
    return status


def _request_payload(roots: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "command": "scan",
        "roots": [{"path": item["path"], "label": item["label"]} for item in roots],
        "cachePath": str(_metadata_cache_path()),
        "maxFiles": int(os.environ.get("ELYAN_NATIVE_FILE_INDEX_MAX_FILES", _MAX_FILES_DEFAULT)),
        "allowedExtensions": sorted(_SUPPORTED_SUFFIXES),
    }


def _run_scan(roots: list[dict[str, str]]) -> dict[str, Any]:
    binary_path = _resolve_binary_path()
    if binary_path is None:
        binary_path = _compile_sidecar()
    result = subprocess.run(
        [str(binary_path)],
        input=json.dumps(_request_payload(roots), ensure_ascii=False),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if result.returncode != 0:
        detail = " ".join((result.stderr or result.stdout or "").split()).strip()[:240]
        raise RuntimeError(detail or "sidecar_run_failed")
    try:
        payload = json.loads(result.stdout)
    except Exception as exc:
        raise RuntimeError("sidecar_invalid_json") from exc
    if not isinstance(payload, dict) or not payload.get("ok", False):
        error_code = str((payload or {}).get("error", "") or "sidecar_scan_failed")
        raise RuntimeError(error_code)
    return payload


def _metadata_cache() -> dict[str, Any]:
    return _load_json(
        _metadata_cache_path(),
        {"version": _SCAN_CACHE_VERSION, "scannedAtMs": 0, "files": []},
    )


def ensure_index(force: bool = False) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    state = state_store.snapshot()
    roots = approved_roots(state)
    availability = sidecar_available()
    current = _state_status(state)
    if not availability:
        status = _persist_status(
            {
                "available": False,
                "ready": False,
                "version": current.get("version", ""),
                "stats": current.get("stats", {}),
                "errorCode": "sidecar_unavailable",
            }
        )
        return [], status
    if not indexing_enabled(state):
        status = _persist_status(
            {
                "available": True,
                "ready": False,
                "version": current.get("version", ""),
                "stats": current.get("stats", {}),
                "errorCode": "permission_required",
            }
        )
        return [], status
    if not roots:
        status = _persist_status(
            {
                "available": True,
                "ready": False,
                "version": current.get("version", ""),
                "stats": {"rootCount": 0, "indexedFileCount": 0, "lastScanAt": ""},
                "errorCode": "no_approved_roots",
            }
        )
        return [], status

    recent_scan = _parse_iso(str(current.get("stats", {}).get("lastScanAt", "") or ""))
    if (
        not force
        and current.get("ready")
        and recent_scan is not None
        and (datetime.now(timezone.utc) - recent_scan).total_seconds() < _REFRESH_INTERVAL_SECONDS
    ):
        cached = _metadata_cache()
        files = cached.get("files", [])
        return [item for item in files if isinstance(item, dict)], current_capability_state(state)

    try:
        payload = _run_scan(roots)
    except Exception as exc:
        status = _persist_status(
            {
                "available": True,
                "ready": False,
                "version": current.get("version", ""),
                "stats": current.get("stats", {}),
                "errorCode": " ".join(str(exc).split()).strip()[:120] or "sidecar_scan_failed",
            }
        )
        return [], status

    scanned_at_ms = int(payload.get("scannedAtMs", 0) or 0)
    scanned_at = datetime.fromtimestamp(scanned_at_ms / 1000, tz=timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    ) if scanned_at_ms else _utc_now_iso()
    stats = payload.get("stats", {})
    stats = stats if isinstance(stats, dict) else {}
    status = _persist_status(
        {
            "available": True,
            "ready": True,
            "version": str(payload.get("version", "") or "")[:40],
            "stats": {
                "rootCount": max(0, int(stats.get("rootCount", len(roots)) or len(roots))),
                "indexedFileCount": max(0, int(stats.get("indexedFileCount", 0) or 0)),
                "lastScanAt": scanned_at,
            },
            "errorCode": "",
        }
    )
    files = payload.get("files", [])
    return [item for item in files if isinstance(item, dict)], status


def warmup_in_background() -> None:
    global _WARMUP_THREAD
    state = state_store.snapshot()
    if not indexing_enabled(state) or not approved_roots(state) or not sidecar_available():
        return
    with _WARMUP_LOCK:
        if _WARMUP_THREAD is not None and _WARMUP_THREAD.is_alive():
            return

        def _worker() -> None:
            try:
                ensure_index(force=False)
            finally:
                global _WARMUP_THREAD
                with _WARMUP_LOCK:
                    _WARMUP_THREAD = None

        _WARMUP_THREAD = threading.Thread(target=_worker, name="elyan-native-index-warmup", daemon=True)
        _WARMUP_THREAD.start()


def handle_state_change() -> None:
    state = state_store.snapshot()
    if indexing_enabled(state) and approved_roots(state):
        warmup_in_background()
        return
    _persist_status(
        {
            "available": sidecar_available(),
            "ready": False,
            "version": _state_status(state).get("version", ""),
            "stats": {"rootCount": len(approved_roots(state)), "indexedFileCount": 0, "lastScanAt": ""},
            "errorCode": "permission_required" if not indexing_enabled(state) else "no_approved_roots",
        }
    )
