from __future__ import annotations

import difflib
import hashlib
import json
import re
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from actions._platform_common import (
    capability_unavailable,
    invalid_argument,
    is_permission_detail,
    is_timeout_detail,
    permission_required,
    require_macos,
    timeout_error,
)
from actions import browser_operator, desktop_os, screen_vision
from runtime.capability_registry import SafeCapabilityError
from runtime import state_store

try:
    from PIL import Image, ImageOps
except Exception:  # pragma: no cover - optional dependency
    Image = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]

try:
    import pytesseract
except Exception:  # pragma: no cover - optional dependency
    pytesseract = None  # type: ignore[assignment]


BASE_DIR = Path(__file__).resolve().parent.parent
HELPER_SOURCE = BASE_DIR / "helpers" / "elyan_operator_helper.swift"
HELPER_BIN = BASE_DIR / "helpers" / ".operator-cache" / "elyan-operator-helper"
OPERATOR_CACHE_DIR = Path(tempfile.gettempdir()) / "elyan-operator"
OPERATOR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
ABORT_FLAG_PATH = Path(
    str(os.environ.get("ELYAN_OPERATOR_ABORT_FLAG_PATH", "") or "").strip()
    or (OPERATOR_CACHE_DIR / "abort.flag")
)
ABORT_FLAG_PATH.parent.mkdir(parents=True, exist_ok=True)
OPERATOR_LOG_LIMIT = 24
OPERATOR_STEP_LIMIT = 120
OPERATOR_SCREENSHOT_TTL_SECONDS = 60 * 20
ACTIVE_RUN_STATUSES = {"running", "observing", "locating", "executing", "verifying", "waiting_approval"}
TERMINAL_RUN_STATUSES = {"idle", "stopped", "failed", "completed", "observed"}
RISKY_TOKENS = {
    "submit",
    "apply",
    "pay",
    "delete",
    "remove",
    "send",
    "install",
    "run command",
    "upload",
    "checkout",
    "purchase",
}
TEXT_ELEMENT_TYPES = {"text", "button", "input", "menu", "checkbox"}
BROWSER_FIRST_SOURCES = {"browser_dom"}
UI_QUERY_SYNONYMS = {
    "devam": ("continue", "next", "proceed"),
    "ileri": ("continue", "next", "proceed"),
    "gonder": ("send", "submit"),
    "gönder": ("send", "submit"),
    "kaydet": ("save",),
    "iptal": ("cancel", "close"),
    "kapat": ("close",),
    "tamam": ("ok", "done", "confirm"),
    "onayla": ("confirm", "ok", "approve"),
    "ara": ("search", "find"),
    "bul": ("search", "find"),
    "ayarlar": ("settings", "preferences"),
    "giris": ("sign in", "log in", "login"),
    "giriş": ("sign in", "log in", "login"),
    "oturum": ("sign in", "log in", "login"),
    "sil": ("delete", "remove", "trash"),
    "silme": ("delete", "remove"),
    # Genişletilmiş UI fiil/isim eşanlamları — masaüstü hakimiyeti için daha
    # geniş kapsama (TR komut → EN arayüz etiketi).
    "ac": ("open",),
    "aç": ("open",),
    "geri": ("back", "previous"),
    "yenile": ("refresh", "reload"),
    "indir": ("download",),
    "yukle": ("upload", "load"),
    "yükle": ("upload", "load"),
    "duzenle": ("edit", "modify"),
    "düzenle": ("edit", "modify"),
    "ekle": ("add", "new", "create"),
    "yeni": ("new", "add", "create"),
    "olustur": ("create", "new"),
    "oluştur": ("create", "new"),
    "paylas": ("share",),
    "paylaş": ("share",),
    "kopyala": ("copy",),
    "yapistir": ("paste",),
    "yapıştır": ("paste",),
    "kes": ("cut",),
    "oynat": ("play",),
    "durdur": ("stop", "pause"),
    "duraklat": ("pause",),
    "evet": ("yes", "ok", "allow"),
    "hayir": ("no", "deny"),
    "hayır": ("no", "deny"),
    "uygula": ("apply",),
    "gir": ("enter", "submit"),
    "sec": ("select", "choose"),
    "seç": ("select", "choose"),
    "filtrele": ("filter",),
    "sirala": ("sort",),
    "sırala": ("sort",),
    "profil": ("profile", "account"),
    "hesap": ("account", "profile"),
    "cikis": ("logout", "sign out", "log out"),
    "çıkış": ("logout", "sign out", "log out"),
    "menu": ("menu",),
    "menü": ("menu",),
    "indirilenler": ("downloads",),
    "dosya": ("file",),
    "duzen": ("edit",),
    "goruntu": ("view",),
    "görüntü": ("view",),
    "yardim": ("help",),
    "yardım": ("help",),
    "gonderme": ("send",),
    "begen": ("like",),
    "beğen": ("like",),
    "abone": ("subscribe",),
    "takip": ("follow",),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _clean_text(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) > limit:
        return text[: limit - 1].rstrip() + "…"
    return text


def _normalize_query_text(value: Any) -> str:
    text = _clean_text(value, 240).lower()
    return " ".join(text.split())


# Ters eşanlam indeksi: EN arayüz etiketi → TR karşılık(lar)ı. Çift yönlü
# eşleşme sağlar — İngilizce sorgu ("send") Türkçe butonu ("Gönder") ya da
# tersini bulabilir. UI_QUERY_SYNONYMS'ten türetilir (tek kaynak).
_REVERSE_UI_SYNONYMS: dict[str, tuple[str, ...]] = {}
for _tr_key, _en_values in UI_QUERY_SYNONYMS.items():
    for _en in _en_values:
        for _en_word in _en.lower().split():
            _REVERSE_UI_SYNONYMS.setdefault(_en_word, ())
            if _tr_key not in _REVERSE_UI_SYNONYMS[_en_word]:
                _REVERSE_UI_SYNONYMS[_en_word] = (*_REVERSE_UI_SYNONYMS[_en_word], _tr_key)


def _query_tokens(value: Any) -> list[str]:
    tokens: list[str] = []
    for token in _normalize_query_text(value).split():
        if token and token not in tokens:
            tokens.append(token)
        for synonym in UI_QUERY_SYNONYMS.get(token, ()):
            for synonym_token in _normalize_query_text(synonym).split():
                if synonym_token and synonym_token not in tokens:
                    tokens.append(synonym_token)
        for reverse in _REVERSE_UI_SYNONYMS.get(token, ()):
            for reverse_token in _normalize_query_text(reverse).split():
                if reverse_token and reverse_token not in tokens:
                    tokens.append(reverse_token)
    return tokens


def _fuzzy_ratio(a: str, b: str) -> float:
    """Kısa UI etiketleri için typo-toleranslı benzerlik (0..1). Boş/çok kısa
    girişlerde 0 döner ki gürültü eşleşmesi olmasın."""
    a = (a or "").strip()
    b = (b or "").strip()
    if len(a) < 3 or len(b) < 3:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def _best_fuzzy_score(normalized_text: str, query_tokens: list[str], item_text: str, aliases: list[str]) -> float:
    """Sorgu ile öğe metni/alias'ları arasındaki en iyi fuzzy oranı. Hem tüm
    sorgu ifadesi hem tek tek tokenlar denenir (kullanıcı 'safar' yazınca
    'safari' butonu yakalanır)."""
    candidates = [item_text, *aliases]
    best = 0.0
    for candidate in candidates:
        best = max(best, _fuzzy_ratio(normalized_text, candidate))
        for token in query_tokens:
            for word in candidate.split():
                best = max(best, _fuzzy_ratio(token, word))
    return best


def _rank_targets(observation: dict[str, Any], text: str = "", element_type: str = "") -> list[dict[str, Any]]:
    elements = observation.get("elements", [])
    elements = [dict(item) for item in elements if isinstance(item, dict)]
    normalized_text = _normalize_query_text(text)
    query_tokens = _query_tokens(text)
    normalized_type = str(element_type or "").strip().lower()
    ranked: list[tuple[float, dict[str, Any]]] = []
    for item in elements:
        score = 0.0
        item_type = str(item.get("type", "") or "").strip().lower()
        item_text = _clean_text(item.get("text", ""), 160).lower()
        item_role = str(item.get("role", "") or "").strip().lower()
        enabled = bool(item.get("enabled", True))
        focused = bool(item.get("focused", False))
        aliases = _element_aliases(item)
        bbox_payload = item.get("bbox", {})
        bbox_payload = bbox_payload if isinstance(bbox_payload, dict) else {}
        area = max(0, _safe_int(bbox_payload.get("w"), 0)) * max(0, _safe_int(bbox_payload.get("h"), 0))
        source = _target_source(item)
        if source in BROWSER_FIRST_SOURCES:
            score += 12
        elif source == "accessibility":
            score += 8
        if normalized_type and item_type == normalized_type:
            score += 28
        elif normalized_type and item_role == normalized_type:
            score += 18
        if normalized_text:
            if item_text == normalized_text or normalized_text in aliases:
                score += 85
            elif normalized_text in item_text:
                score += 58
            elif any(token in item_text for token in query_tokens if token):
                score += 42
            elif item_text in normalized_text and item_text:
                score += 34
            else:
                # Typo/kısmi biçim toleransı: hiçbir kesin/altdizge/token hit
                # yoksa fuzzy benzerliğe bak ("safar"→"safari", "sittings"→
                # "settings"). Yüksek eşik: yanlış hedef seçimini önler.
                fuzzy = _best_fuzzy_score(normalized_text, query_tokens, item_text, aliases)
                if fuzzy >= 0.9:
                    score += 48
                elif fuzzy >= 0.8:
                    score += 30
                elif fuzzy >= 0.72:
                    score += 16
        if aliases and query_tokens:
            overlap = 0
            for alias in aliases:
                alias_tokens = set(alias.split())
                overlap = max(overlap, len(alias_tokens.intersection(query_tokens)))
            if overlap >= 3:
                score += 22
            elif overlap == 2:
                score += 16
            elif overlap == 1:
                score += 10
        if query_tokens and any(token in item_role for token in query_tokens):
            score += 8
        if query_tokens and any(token in item_type for token in query_tokens):
            score += 6
        if enabled:
            score += 6
        if focused:
            score += 10
        if 80 <= area <= 120000:
            score += 4
        if normalized_text and not item_text and not aliases:
            score -= 10
        if score > 0:
            candidate = dict(item)
            if aliases and "searchHints" not in candidate:
                candidate["searchHints"] = aliases[:6]
            candidate["candidateScore"] = round(score, 3)
            ranked.append((score, candidate))
    ranked.sort(
        key=lambda entry: (
            entry[0],
            _safe_float(entry[1].get("confidence"), 0.0),
            bool(entry[1].get("focused", False)),
        ),
        reverse=True,
    )
    return [candidate for _score, candidate in ranked]


def _screen_target_suggestions(observation: dict[str, Any], query: str = "", *, limit: int = 5) -> list[dict[str, Any]]:
    ranked = _rank_targets(observation, text=query)
    suggestions: list[dict[str, Any]] = []
    for item in ranked[: max(1, min(limit, 8))]:
        bbox = item.get("bbox", {})
        bbox = bbox if isinstance(bbox, dict) else {}
        suggestions.append(
            {
                "id": str(item.get("id", "") or ""),
                "text": str(item.get("text", "") or ""),
                "type": str(item.get("type", "") or ""),
                "source": str(item.get("source", "") or ""),
                "confidence": _target_confidence(item),
                "searchHints": list(item.get("searchHints", [])) if isinstance(item.get("searchHints", []), list) else [],
                "bbox": {
                    "x": _safe_int(bbox.get("x"), 0),
                    "y": _safe_int(bbox.get("y"), 0),
                    "w": _safe_int(bbox.get("w"), 0),
                    "h": _safe_int(bbox.get("h"), 0),
                },
            }
        )
    return suggestions


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _operator_runtime_state() -> dict[str, Any]:
    state = state_store.snapshot()
    operator = state.get("operator", {})
    return dict(operator) if isinstance(operator, dict) else {}


def _persist_operator_state(section_patch: dict[str, Any]) -> None:
    current = _operator_runtime_state()
    current.update(section_patch)
    state_store.update_state({"operator": current})


def _abort_flag_payload(reason: str) -> dict[str, Any]:
    return {"reason": str(reason or "user_cancel").strip() or "user_cancel", "at": _now_iso()}


def _set_abort_flag(reason: str) -> None:
    try:
        ABORT_FLAG_PATH.write_text(json.dumps(_abort_flag_payload(reason), ensure_ascii=False), encoding="utf-8")
    except Exception:
        return


def _clear_abort_flag() -> None:
    try:
        if ABORT_FLAG_PATH.exists():
            ABORT_FLAG_PATH.unlink()
    except Exception:
        return


def _abort_flag_reason() -> str:
    if not ABORT_FLAG_PATH.exists():
        return ""
    try:
        payload = json.loads(ABORT_FLAG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return "user_cancel"
    if not isinstance(payload, dict):
        return "user_cancel"
    return str(payload.get("reason", "") or "user_cancel").strip() or "user_cancel"


def _active_run_summary() -> dict[str, Any]:
    operator = _operator_runtime_state()
    return {
        "runId": str(operator.get("activeRunId", "") or "").strip(),
        "status": str(operator.get("status", "idle") or "idle").strip() or "idle",
        "abortRequested": bool(operator.get("abortRequested", False)),
        "abortReason": str(operator.get("abortReason", "") or "").strip(),
        "currentStep": max(0, _safe_int(operator.get("currentStepIndex"), 0)),
        "lastObservationId": str(operator.get("lastObservationId", "") or "").strip(),
        "lastStopReason": str(operator.get("lastStopReason", "") or "").strip(),
        "operatorResolutionMode": str(operator.get("operatorResolutionMode", "") or "").strip(),
        "lastTargetSource": str(operator.get("lastTargetSource", "") or "").strip(),
        "lastVerificationSource": str(operator.get("lastVerificationSource", "") or "").strip(),
        "lastTargetConfidence": round(_safe_float(operator.get("lastTargetConfidence"), 0.0), 3),
    }


def _update_active_run_state(
    *,
    run_id: str | None = None,
    status: str | None = None,
    abort_requested: bool | None = None,
    abort_reason: str | None = None,
    current_step_index: int | None = None,
    last_observation_id: str | None = None,
    last_stop_reason: str | None = None,
    last_completed_at: str | None = None,
    operator_resolution_mode: str | None = None,
    last_target_source: str | None = None,
    last_verification_source: str | None = None,
    last_target_confidence: float | None = None,
) -> dict[str, Any]:
    patch: dict[str, Any] = {"lastUpdatedAt": _now_iso()}
    if run_id is not None:
        patch["activeRunId"] = str(run_id or "").strip()[:80]
    if status is not None:
        patch["status"] = str(status or "idle").strip()[:64] or "idle"
    if abort_requested is not None:
        patch["abortRequested"] = bool(abort_requested)
    if abort_reason is not None:
        patch["abortReason"] = str(abort_reason or "").strip()[:80]
    if current_step_index is not None:
        patch["currentStepIndex"] = max(0, int(current_step_index))
    if last_observation_id is not None:
        patch["lastObservationId"] = str(last_observation_id or "").strip()[:120]
    if last_stop_reason is not None:
        patch["lastStopReason"] = str(last_stop_reason or "").strip()[:80]
    if last_completed_at is not None:
        patch["lastCompletedAt"] = str(last_completed_at or "").strip()[:80]
    if operator_resolution_mode is not None:
        patch["operatorResolutionMode"] = str(operator_resolution_mode or "").strip()[:80]
    if last_target_source is not None:
        patch["lastTargetSource"] = str(last_target_source or "").strip()[:80]
    if last_verification_source is not None:
        patch["lastVerificationSource"] = str(last_verification_source or "").strip()[:80]
    if last_target_confidence is not None:
        patch["lastTargetConfidence"] = round(max(0.0, min(float(last_target_confidence), 1.0)), 3)
    _persist_operator_state(patch)
    return _active_run_summary()


def _sync_run_terminal_state(run_id: str, status: str, stop_reason: str = "") -> None:
    current = _operator_runtime_state()
    items = current.get("operatorRuns", [])
    if not isinstance(items, list):
        return
    completed_at = _now_iso()
    for item in items:
        if not isinstance(item, dict):
            continue
        if str(item.get("id", "") or "").strip() != str(run_id or "").strip():
            continue
        item["status"] = status
        if stop_reason:
            item["stopReason"] = stop_reason
        item["completedAt"] = completed_at
        break
    _persist_operator_state({"operatorRuns": items, "lastUpdatedAt": completed_at})


def _finalize_active_run(run_id: str, status: str, *, stop_reason: str = "") -> dict[str, Any]:
    completed_at = _now_iso()
    _sync_run_terminal_state(run_id, status, stop_reason=stop_reason)
    _update_active_run_state(
        run_id="",
        status=status,
        abort_requested=False,
        abort_reason="",
        last_stop_reason=stop_reason,
        last_completed_at=completed_at,
    )
    _cleanup_stale_screenshots()
    _clear_abort_flag()
    return _active_run_summary()


def _request_operator_abort(reason: str, *, run_id: str = "") -> dict[str, Any]:
    normalized_reason = str(reason or "user_cancel").strip() or "user_cancel"
    _set_abort_flag(normalized_reason)
    active = _active_run_summary()
    active_run_id = str(active.get("runId", "") or "").strip()
    target_run_id = str(run_id or active_run_id).strip()
    if target_run_id:
        _update_active_run_state(
            run_id=target_run_id,
            abort_requested=True,
            abort_reason=normalized_reason,
            last_stop_reason=normalized_reason,
        )
    return _active_run_summary()


def _abort_requested_for_run(run_id: str = "") -> tuple[bool, str]:
    active = _active_run_summary()
    active_run_id = str(active.get("runId", "") or "").strip()
    if run_id and active_run_id and run_id != active_run_id:
        return False, ""
    if bool(active.get("abortRequested", False)):
        return True, str(active.get("abortReason", "") or "user_cancel").strip() or "user_cancel"
    flag_reason = _abort_flag_reason()
    if flag_reason:
        return True, flag_reason
    return False, ""


def _stopped_execution_result(
    *,
    run_id: str,
    status: str,
    step_index: int,
    action_type: str,
    target: dict[str, Any] | None,
    observation: dict[str, Any],
    observation_id: str = "",
    stop_reason: str,
    attempt_count: int,
) -> dict[str, Any]:
    operator = {
        "runId": run_id,
        "status": status,
        "currentStep": step_index,
        "requiresApproval": False,
        "activeApp": str(observation.get("activeApp", "") or ""),
        "activeWindow": str(observation.get("activeWindow", "") or ""),
        "lastVerificationOk": False,
        "observationId": observation_id,
        "stopReason": stop_reason,
    }
    return {
        "text": "Visual operator güvenli şekilde durduruldu.",
        "result": {
            "kind": "operator_execution_result",
            "runId": run_id,
            "status": status,
            "stepIndex": step_index,
            "attemptCount": attempt_count,
            "actionType": action_type,
            "target": target,
            "resolutionMode": str(observation.get("resolutionMode", "") or ""),
            "targetSource": _target_source(target),
            "verificationSource": str(observation.get("resolutionMode", "") or ""),
            "targetConfidence": _target_confidence(target),
            "candidateCount": int(target.get("candidateCount", 0) or 0) if isinstance(target, dict) else 0,
            "verification": {"ok": False, "checkedAt": _now_iso(), "reason": stop_reason},
            "observation": observation,
            "requiresApproval": False,
            "stopped": True,
            "stopReason": stop_reason,
            "operator": operator,
        },
    }


def _cleanup_stale_screenshots() -> None:
    cutoff = time.time() - OPERATOR_SCREENSHOT_TTL_SECONDS
    try:
        for item in OPERATOR_CACHE_DIR.iterdir():
            if item.is_file() and item.suffix.lower() == ".png" and item.stat().st_mtime < cutoff:
                item.unlink()
    except Exception:
        return


def _operator_permission_message() -> str:
    return (
        "Bilgisayar kontrolü için önce Ayarlar > Gizlilik bölümünden bilgisayar kontrolünü aç."
    )


def _sensitive_action_message() -> str:
    return (
        "Riskli operator aksiyonu için açık onay gerekiyor."
    )


def _active_window_key(observation: dict[str, Any]) -> str:
    app_name = _clean_text(observation.get("activeApp", ""), 120).lower()
    window_title = _clean_text(observation.get("activeWindow", ""), 160).lower()
    return f"{app_name}::{window_title}"


def _element_browser_meta(item: dict[str, Any]) -> dict[str, Any]:
    browser = item.get("browser", {})
    return dict(browser) if isinstance(browser, dict) else {}


def _element_aliases(item: dict[str, Any]) -> list[str]:
    aliases: list[str] = []
    browser = _element_browser_meta(item)
    for candidate in (
        item.get("text", ""),
        item.get("role", ""),
        item.get("type", ""),
        browser.get("selector", ""),
        browser.get("name", ""),
        browser.get("role", ""),
        browser.get("tag", ""),
        browser.get("placeholder", ""),
        browser.get("ariaLabel", ""),
        browser.get("title", ""),
        browser.get("value", ""),
        browser.get("alt", ""),
    ):
        text = _normalize_query_text(candidate)
        if text and text not in aliases:
            aliases.append(text)
    return aliases


def _target_source(item: dict[str, Any] | None) -> str:
    if not isinstance(item, dict):
        return ""
    return str(item.get("source", "") or "").strip().lower()


def _target_confidence(item: dict[str, Any] | None) -> float:
    if not isinstance(item, dict):
        return 0.0
    return round(max(0.0, min(_safe_float(item.get("confidence"), 0.0), 1.0)), 3)


def operator_runtime_status() -> dict[str, Any]:
    platform = sys.platform
    active_summary = _active_run_summary()
    browser_status = browser_operator.runtime_status()
    if platform != "darwin":
        return {
            "available": False,
            "lastErrorCode": "UNSUPPORTED_PLATFORM",
            "lastErrorMessage": "Visual desktop operator şu anda yalnız macOS'ta hazır.",
            "detail": {
                "platform": platform or "unknown",
                "screenObservationReady": False,
                "accessibilityReady": False,
                "inputControlReady": False,
                "emergencyStopAvailable": False,
                "playwrightReady": bool(browser_status.get("playwrightAvailable", False)),
                "browserFirstReady": False,
                "activeRunSummary": active_summary,
                "lastStopReason": str(active_summary.get("lastStopReason", "") or ""),
                "operatorResolutionMode": str(active_summary.get("operatorResolutionMode", "") or ""),
                "lastTargetSource": str(active_summary.get("lastTargetSource", "") or ""),
                "lastVerificationSource": str(active_summary.get("lastVerificationSource", "") or ""),
                "lastTargetConfidence": round(_safe_float(active_summary.get("lastTargetConfidence"), 0.0), 3),
            },
        }
    permissions_payload = desktop_os.desktop_os_permissions().get("result", {})
    permissions = permissions_payload.get("permissions", {}) if isinstance(permissions_payload, dict) else {}
    permissions = permissions if isinstance(permissions, dict) else {}
    accessibility = permissions.get("accessibility", {}) if isinstance(permissions.get("accessibility"), dict) else {}
    screen_recording = permissions.get("screenRecording", {}) if isinstance(permissions.get("screenRecording"), dict) else {}
    automation = permissions.get("automation", {}) if isinstance(permissions.get("automation"), dict) else {}
    input_monitoring = permissions.get("inputMonitoring", {}) if isinstance(permissions.get("inputMonitoring"), dict) else {}
    screen_ready = str(screen_recording.get("status", "") or "").lower() in {"granted", "not_required"}
    accessibility_ready = str(accessibility.get("status", "") or "").lower() in {"granted", "not_required"}
    automation_ready = str(automation.get("status", "") or "").lower() in {"granted", "not_required", "unknown"}
    input_ready = str(input_monitoring.get("status", "") or "").lower() in {"granted", "not_required", "unknown"}
    return {
        "available": True,
        "lastErrorCode": "",
        "lastErrorMessage": "",
        "detail": {
            "platform": "darwin",
            "screenObservationReady": screen_ready,
            "accessibilityReady": accessibility_ready,
            "inputControlReady": accessibility_ready and automation_ready and input_ready,
            "emergencyStopAvailable": bool(permissions_payload.get("operatorEmergencyStopAvailable", False)),
            "failSafeCornerAbort": True,
            "ocrPrimary": "pytesseract" if pytesseract is not None else "",
            "playwrightReady": bool(browser_status.get("playwrightAvailable", False)),
            "browserFirstReady": bool(browser_status.get("browserFirstReady", False)),
            "activeRunSummary": active_summary,
            "lastStopReason": str(active_summary.get("lastStopReason", "") or ""),
            "operatorResolutionMode": str(active_summary.get("operatorResolutionMode", "") or ""),
            "lastTargetSource": str(active_summary.get("lastTargetSource", "") or ""),
            "lastVerificationSource": str(active_summary.get("lastVerificationSource", "") or ""),
            "lastTargetConfidence": round(_safe_float(active_summary.get("lastTargetConfidence"), 0.0), 3),
        },
    }


def _ensure_helper_binary() -> tuple[bool, str]:
    HELPER_BIN.parent.mkdir(parents=True, exist_ok=True)
    if not HELPER_SOURCE.exists():
        return False, "Operator helper kaynak dosyası bulunamadı."
    source_mtime = HELPER_SOURCE.stat().st_mtime
    if HELPER_BIN.exists() and HELPER_BIN.stat().st_mtime >= source_mtime:
        return True, ""
    try:
        result = subprocess.run(
            ["swiftc", str(HELPER_SOURCE), "-o", str(HELPER_BIN)],
            capture_output=True,
            text=True,
            timeout=45,
        )
    except FileNotFoundError:
        return False, "swiftc bulunamadı."
    except subprocess.TimeoutExpired:
        return False, "Operator helper derlenirken zaman aşımına uğradı."
    except Exception as exc:  # pragma: no cover - subprocess safety
        return False, f"Operator helper derlenemedi: {exc}"
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        return False, detail or "Operator helper derlenemedi."
    try:
        HELPER_BIN.chmod(0o755)
    except Exception:
        pass
    # İmzasız swiftc binary'sinin Accessibility/Input izni içerik-hash'ine
    # bağlanır → relaunch'ta kaybolur. Kararlı kimlikle imzala ki izin kalıcı olsun.
    _codesign_binary(HELPER_BIN)
    return True, ""


def _codesign_binary(binary_path: Path) -> None:
    """Operatör helper binary'sini kararlı codesigning kimliğiyle imzalar
    (yoksa ad-hoc). Best-effort: TCC izin kalıcılığını iyileştirir."""
    identity = "-"
    try:
        out = subprocess.run(
            ["security", "find-identity", "-v", "-p", "codesigning"],
            capture_output=True, text=True, timeout=10,
        ).stdout
        found = re.search(r"\)\s+([0-9A-F]{40})\s+\"", out)
        if found:
            identity = found.group(1)
    except Exception:
        pass
    try:
        subprocess.run(
            ["codesign", "--force", "--sign", identity, str(binary_path)],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        pass


def _run_operator_helper(mode: str, payload: dict[str, Any] | None = None, *, timeout: int = 20) -> dict[str, Any]:
    ok, detail = _ensure_helper_binary()
    if not ok:
        raise capability_unavailable(detail or "Operator helper hazır değil.")
    payload_path: Path | None = None
    output_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(prefix="elyan-operator-payload-", suffix=".json", delete=False) as handle:
            payload_path = Path(handle.name)
            handle.write(json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"))
        with tempfile.NamedTemporaryFile(prefix="elyan-operator-output-", suffix=".json", delete=False) as handle:
            output_path = Path(handle.name)
        result = subprocess.run(
            [str(HELPER_BIN), mode, str(output_path), str(payload_path)],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise timeout_error("Operator helper zaman aşımına uğradı.") from exc
    except Exception as exc:  # pragma: no cover - subprocess safety
        raise capability_unavailable("Operator helper güvenli şekilde çalıştırılamadı.") from exc
    finally:
        if payload_path is not None:
            try:
                payload_path.unlink()
            except Exception:
                pass
    raw = ""
    if output_path is not None and output_path.exists():
        try:
            raw = output_path.read_text(encoding="utf-8").strip()
        except Exception:
            raw = ""
        try:
            output_path.unlink()
        except Exception:
            pass
    if not raw:
        raw = (result.stdout or "").strip()
    try:
        parsed = json.loads(raw) if raw else {}
    except Exception as exc:
        raise capability_unavailable("Operator helper beklenen JSON yanıtını üretmedi.") from exc
    if not isinstance(parsed, dict):
        raise capability_unavailable("Operator helper yanıtı beklenen formatta değil.")
    if not bool(parsed.get("ok", False)):
        error_code = str(parsed.get("error", "") or "").strip().lower()
        detail = str(parsed.get("detail") or parsed.get("error") or "Operator helper başarısız oldu.").strip()
        if error_code == "failsafe_corner_abort":
            raise capability_unavailable("failsafe_corner_abort")
        if error_code == "operator_abort_requested":
            raise capability_unavailable("operator_abort_requested")
        if is_permission_detail(detail):
            raise permission_required(detail)
        if is_timeout_detail(detail):
            raise timeout_error(detail)
        raise capability_unavailable(detail or "Operator helper başarısız oldu.")
    return parsed


def _copy_to_operator_cache(source: Path) -> Path:
    _cleanup_stale_screenshots()
    destination = OPERATOR_CACHE_DIR / f"screen-{int(time.time() * 1000)}-{source.name}"
    shutil.copy2(source, destination)
    return destination


def _image_dimensions(image_path: Path, bounds: dict[str, Any]) -> tuple[int, int]:
    if Image is not None:
        try:
            with Image.open(image_path) as image:
                return int(image.width), int(image.height)
        except Exception:
            pass
    return _safe_int(bounds.get("width"), 0), _safe_int(bounds.get("height"), 0)


def _ocr_elements(image_path: Path) -> list[dict[str, Any]]:
    if pytesseract is None or Image is None or ImageOps is None:
        return []
    try:
        with Image.open(image_path) as image:
            prepared = ImageOps.autocontrast(image.convert("L"))
            data = pytesseract.image_to_data(prepared, output_type=pytesseract.Output.DICT)
    except Exception:
        return []
    count = len(data.get("text", []))
    elements: list[dict[str, Any]] = []
    for index in range(count):
        text = _clean_text(data["text"][index], 120)
        confidence = _safe_float(data.get("conf", [0])[index], 0.0)
        if not text or confidence < 35:
            continue
        x = _safe_int(data.get("left", [0])[index], 0)
        y = _safe_int(data.get("top", [0])[index], 0)
        w = _safe_int(data.get("width", [0])[index], 0)
        h = _safe_int(data.get("height", [0])[index], 0)
        if w <= 1 or h <= 1:
            continue
        elements.append(
            {
                "id": f"ocr_{index + 1}",
                "type": "text",
                "text": text,
                "bbox": {"x": x, "y": y, "w": w, "h": h},
                "confidence": round(min(max(confidence / 100.0, 0.0), 1.0), 3),
                "source": "ocr",
            }
        )
    return elements[:80]


def _normalise_accessibility_elements(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("elements", [])
    if not isinstance(raw, list):
        return []
    result: list[dict[str, Any]] = []
    for index, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        bbox = item.get("bbox", {})
        bbox = bbox if isinstance(bbox, dict) else {}
        result.append(
            {
                "id": str(item.get("id", "") or f"ax_{index + 1}"),
                "type": str(item.get("type", "") or "unknown"),
                "text": _clean_text(item.get("text", ""), 160),
                "bbox": {
                    "x": _safe_int(bbox.get("x"), 0),
                    "y": _safe_int(bbox.get("y"), 0),
                    "w": _safe_int(bbox.get("w"), 0),
                    "h": _safe_int(bbox.get("h"), 0),
                },
                "confidence": round(_safe_float(item.get("confidence"), 0.99), 3),
                "source": "accessibility",
                "role": _clean_text(item.get("role", ""), 80),
                "enabled": bool(item.get("enabled", False)),
                "focused": bool(item.get("focused", False)),
            }
        )
    return result[:120]


def _observation_summary(elements: list[dict[str, Any]], active_app: str, active_window: str) -> str:
    readable = [item for item in elements if str(item.get("type", "")) in TEXT_ELEMENT_TYPES and str(item.get("text", "")).strip()]
    snippets = [_clean_text(item.get("text", ""), 48) for item in readable[:6]]
    context = " / ".join(part for part in (active_app, active_window) if part).strip()
    if snippets:
        prefix = f"[Aktif pencere: {context}]\n" if context else ""
        return prefix + "Görünen öğeler: " + " | ".join(snippets)
    if context:
        return f"[Aktif pencere: {context}]\nEkran gözlemi hazır."
    return "Ekran gözlemi hazır."


def _browser_observation_for_window(active_app: str, active_window: str) -> dict[str, Any]:
    if not browser_operator.is_supported_browser_app(active_app):
        return {}
    try:
        return browser_operator.observe_browser_window(active_app, active_window)
    except Exception:
        return {}


def _build_screen_observation(image_path: Path, capture_payload: dict[str, Any]) -> dict[str, Any]:
    try:
        active_window_payload = desktop_os.desktop_os_active_window().get("result", {})
    except Exception as exc:
        if str(getattr(exc, "code", "") or "") != "CAPABILITY_UNAVAILABLE":
            raise
        active_window_payload = {}
    active_window_payload = active_window_payload if isinstance(active_window_payload, dict) else {}
    active_app = str(active_window_payload.get("appName", "") or capture_payload.get("owner_name", "") or "").strip()
    active_window = str(active_window_payload.get("windowTitle", "") or capture_payload.get("window_title", "") or "").strip()
    bounds = capture_payload.get("bounds", {})
    bounds = bounds if isinstance(bounds, dict) else {}
    width, height = _image_dimensions(image_path, bounds)
    browser_payload = _browser_observation_for_window(active_app, active_window)
    browser_elements = browser_payload.get("elements", []) if isinstance(browser_payload.get("elements"), list) else []
    elements: list[dict[str, Any]] = [dict(item) for item in browser_elements if isinstance(item, dict)]
    resolution_mode = "browser_first" if elements else "native_accessibility"
    if not elements:
        accessibility_payload: dict[str, Any] = {}
        try:
            accessibility_payload = _run_operator_helper("accessibility_snapshot", {}, timeout=15)
        except Exception:
            accessibility_payload = {}
        accessibility_elements = _normalise_accessibility_elements(accessibility_payload) if accessibility_payload else []
        elements = accessibility_elements
        if not elements:
            elements = _ocr_elements(image_path)
            resolution_mode = "ocr_fallback"
    actionable_count = 0
    text_count = 0
    browser_dom_count = 0
    ocr_count = 0
    for item in elements:
        if not isinstance(item, dict):
            continue
        if str(item.get("source", "") or "") == "browser_dom":
            browser_dom_count += 1
        if str(item.get("source", "") or "") == "ocr":
            ocr_count += 1
        if str(item.get("type", "") or "").strip().lower() in {"button", "input", "menu", "checkbox"}:
            actionable_count += 1
        if str(item.get("text", "") or "").strip():
            text_count += 1
        aliases = _element_aliases(item)
        if aliases:
            item["searchHints"] = aliases[:6]
    screen_summary = {
        "activeApp": active_app,
        "activeWindow": active_window,
        "resolutionMode": resolution_mode,
        "elementCount": len(elements),
        "actionableCount": actionable_count,
        "textCount": text_count,
        "browserDomCount": browser_dom_count,
        "ocrCount": ocr_count,
    }
    return {
        "screenshotPath": str(image_path),
        "width": width,
        "height": height,
        "monitorId": "active_monitor",
        "scaleFactor": 1.0,
        "capturedAt": _now_iso(),
        "activeApp": active_app,
        "activeWindow": active_window,
        "elements": elements,
        "resolutionMode": resolution_mode,
        "pageTitle": str(browser_payload.get("pageTitle", "") or active_window).strip(),
        "pageUrl": str(browser_payload.get("pageUrl", "") or "").strip(),
        "screenSummary": screen_summary,
    }


def _operator_hash(value: Any) -> str:
    digest = hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:32]


def _append_operator_log(kind: str, entry: dict[str, Any], *, limit: int) -> None:
    current = _operator_runtime_state()
    existing = current.get(kind, [])
    items = list(existing) if isinstance(existing, list) else []
    next_items = [entry, *items][:limit]
    _persist_operator_state({kind: next_items, "lastUpdatedAt": _now_iso()})


def _record_observation(run_id: str, observation: dict[str, Any]) -> dict[str, Any]:
    entry = {
        "id": f"obs_{_operator_hash({'runId': run_id, 'path': observation.get('screenshotPath')})}",
        "runId": run_id,
        "screenshotHash": _operator_hash(observation.get("screenshotPath", "")),
        "activeApp": observation.get("activeApp", ""),
        "activeWindow": observation.get("activeWindow", ""),
        "resolutionMode": observation.get("resolutionMode", ""),
        "elements": observation.get("elements", []),
        "createdAt": observation.get("capturedAt", _now_iso()),
    }
    _append_operator_log("screenObservations", entry, limit=OPERATOR_LOG_LIMIT)
    return entry


def _record_run(run: dict[str, Any]) -> None:
    current = _operator_runtime_state()
    existing = current.get("operatorRuns", [])
    items = [dict(item) for item in existing if isinstance(item, dict)]
    run_id = str(run.get("id", "") or "").strip()
    next_items: list[dict[str, Any]] = []
    replaced = False
    for item in items:
        if run_id and str(item.get("id", "") or "").strip() == run_id:
            merged = dict(item)
            merged.update(run)
            next_items.append(merged)
            replaced = True
        else:
            next_items.append(item)
    if not replaced:
        next_items = [run, *next_items]
    _persist_operator_state({"operatorRuns": next_items[:OPERATOR_LOG_LIMIT], "lastUpdatedAt": _now_iso()})


def _record_step(step: dict[str, Any]) -> None:
    _append_operator_log("operatorSteps", step, limit=OPERATOR_STEP_LIMIT)


def _record_input_action(action: dict[str, Any]) -> None:
    payload = dict(action)
    if "text" in payload:
        payload.pop("text", None)
    _append_operator_log("inputActions", payload, limit=OPERATOR_STEP_LIMIT)


def _record_verification(result: dict[str, Any]) -> None:
    _append_operator_log("verificationResults", result, limit=OPERATOR_STEP_LIMIT)


def _risk_summary(action_type: str, target: dict[str, Any] | None, payload: dict[str, Any]) -> tuple[bool, str]:
    tokens = {action_type.lower()}
    if isinstance(target, dict):
        tokens.add(str(target.get("text", "") or "").lower())
    tokens.add(str(payload.get("text", "") or "").lower())
    tokens.add(str(payload.get("targetText", "") or "").lower())
    merged = " ".join(token for token in tokens if token)
    risky = any(token in merged for token in RISKY_TOKENS)
    if not risky:
        return False, ""
    return True, _sensitive_action_message()


def _match_target(observation: dict[str, Any], text: str = "", element_type: str = "", bbox: dict[str, Any] | None = None) -> dict[str, Any]:
    if bbox and isinstance(bbox, dict):
        return {
            "id": "bbox_target",
            "type": str(element_type or "unknown"),
            "text": text,
            "bbox": {
                "x": _safe_int(bbox.get("x"), 0),
                "y": _safe_int(bbox.get("y"), 0),
                "w": _safe_int(bbox.get("w"), 0),
                "h": _safe_int(bbox.get("h"), 0),
            },
            "confidence": 1.0,
            "source": "bbox",
        }
    ranked = _rank_targets(observation, text=text, element_type=element_type)
    if ranked:
        best = ranked[0]
        best_score = _safe_float(best.get("candidateScore"), 0.0)
        second_score = _safe_float(ranked[1].get("candidateScore"), -1.0) if len(ranked) > 1 else -1.0
        if best_score < 24:
            raise capability_unavailable("Hedef öğe yeterli güvenle bulunamadı.")
        if second_score >= 0 and abs(best_score - second_score) < 6:
            raise capability_unavailable("Ekranda birden fazla benzer hedef var; kör tıklama yapılmadı.")
        best["candidateCount"] = len(ranked)
        best["confidence"] = round(
            max(_safe_float(best.get("confidence"), 0.0), min(best_score / 100.0, 0.99)),
            3,
        )
        return best
    raise capability_unavailable("Hedef öğe ekranda bulunamadı.")


def _bbox_center(bbox: dict[str, Any]) -> tuple[float, float]:
    return (
        _safe_float(bbox.get("x"), 0.0) + _safe_float(bbox.get("w"), 0.0) / 2.0,
        _safe_float(bbox.get("y"), 0.0) + _safe_float(bbox.get("h"), 0.0) / 2.0,
    )


def _verification_result(
    *,
    action_type: str,
    before: dict[str, Any],
    after: dict[str, Any],
    target: dict[str, Any] | None,
) -> dict[str, Any]:
    if not after:
        return {"ok": False, "reason": "missing_post_observation", "source": ""}
    if _active_window_key(before) and _active_window_key(after) and _active_window_key(before) != _active_window_key(after):
        return {"ok": False, "reason": "active_window_changed", "source": str(after.get("resolutionMode", "") or "")}
    if action_type == "wait":
        return {"ok": True, "reason": "", "source": str(after.get("resolutionMode", "") or "")}
    if action_type == "focus_window":
        return {"ok": bool(after), "reason": "" if after else "focus_not_verified", "source": str(after.get("resolutionMode", "") or "")}
    if target is None:
        return {"ok": bool(after), "reason": "" if after else "missing_target", "source": str(after.get("resolutionMode", "") or "")}
    target_text = _clean_text(target.get("text", ""), 160)
    target_type = str(target.get("type", "") or "").strip()
    try:
        verified_target = _match_target(after, text=target_text, element_type=target_type)
    except Exception:
        verified_target = None
    if verified_target is None:
        return {"ok": False, "reason": "target_not_found_after_action", "source": str(after.get("resolutionMode", "") or "")}
    if action_type == "type_text" and not bool(verified_target.get("focused", False)) and _target_source(verified_target) not in BROWSER_FIRST_SOURCES:
        return {"ok": False, "reason": "input_not_focused", "source": _target_source(verified_target)}
    return {"ok": True, "reason": "", "source": _target_source(verified_target), "target": verified_target}


def _ensure_focus_for_input(target: dict[str, Any], observation: dict[str, Any]) -> None:
    if bool(target.get("focused", False)) or _target_source(target) in BROWSER_FIRST_SOURCES:
        return
    target_bbox = target.get("bbox", {})
    target_bbox = target_bbox if isinstance(target_bbox, dict) else {}
    x, y = _bbox_center(target_bbox)
    _run_operator_helper("input_action", {"actionType": "click", "x": x, "y": y}, timeout=20)
    focused_observation = observe_screen("", "active_window", preserve_screenshot=True).get("result", {}).get("observation", {})
    focused_observation = focused_observation if isinstance(focused_observation, dict) else {}
    refreshed_target = _match_target(
        focused_observation,
        text=str(target.get("text", "") or ""),
        element_type=str(target.get("type", "") or ""),
    )
    if not bool(refreshed_target.get("focused", False)):
        raise capability_unavailable("Input hedefi odaklanamadı; kör yazma yapılmadı.")


_OPERATOR_CLICK_RE = re.compile(
    r"^(?P<target>.+?)\s*(?:butonuna|dugmesine|düğmesine|linkine|baglantisina|bağlantısına|sekmesine|menusune|menüsüne|['’]?(?:e|a|ye|ya|na|ne|ni|yi))?\s*"
    r"(?P<kind>cift\s*tikla|çift\s*tıkla|double\s*click|sag\s*tikla|sağ\s*tıkla|sag\s*tik|sağ\s*tık|right\s*click|tikla|tıkla|bas|click|sec|seç|select)$",
    re.IGNORECASE,
)


def _deterministic_operator_steps(goal: str) -> list[dict[str, Any]]:
    """Basit, sık kullanılan GUI hedeflerini bulut beyni OLMADAN adımlara çevirir
    (kaydır / tıkla / çift-tık / sağ-tık). Hedef eşleştirmesini executor yapar
    (fuzzy + TR↔EN eşanlam). Karmaşık/çok adımlı hedefler bulut planlayıcıya kalır."""
    original = str(goal or "").strip()
    if not original:
        return []
    normalized = " ".join(_clean_text(original, 200).lower().split())

    # Kaydırma — hedef gerekmez, tamamen deterministik.
    if any(p in normalized for p in ("asagi kaydir", "aşağı kaydır", "scroll down", "asagiya in", "aşağıya in")):
        return [{"action": "scroll", "delta": -600}]
    if any(p in normalized for p in ("yukari kaydir", "yukarı kaydır", "scroll up", "yukariya cik", "yukarıya çık")):
        return [{"action": "scroll", "delta": 600}]

    match = _OPERATOR_CLICK_RE.match(original.strip())
    if match:
        target = _clean_text(match.group("target"), 120).strip(" '’\"")
        kind = " ".join(match.group("kind").lower().split())
        if target and len(target) >= 2:
            if kind in {"cift tikla", "çift tıkla", "double click"}:
                action = "double_click"
            elif kind in {"sag tik", "sağ tık", "right click", "sag tikla", "sağ tıkla"}:
                action = "right_click"
            else:
                action = "click"
            return [{"action": action, "targetText": target}]
    return []


def _plan_operator_steps(goal: str, observation: dict[str, Any]) -> dict[str, Any]:
    from runtime import bridge as runtime_bridge

    # Önce deterministik (bulutsuz) plan: basit hedefler anında + isabetli çözülür.
    deterministic = _deterministic_operator_steps(goal)
    if deterministic:
        return {
            "steps": deterministic,
            "confidence": 0.9,
            "provider": "deterministic",
            "message": "",
            "clarificationQuestion": "",
        }

    planner = getattr(runtime_bridge, "plan_visual_operator_steps", None)
    if planner is None:
        raise capability_unavailable("Operator planner hazır değil.")
    planned = planner(goal, observation)
    if not isinstance(planned, dict):
        raise capability_unavailable("Operator planner beklenen çıktıyı üretmedi.")
    return planned


def observe_screen(query: str = "", target: str = "active_window", preserve_screenshot: bool = True) -> dict[str, Any]:
    require_macos("Visual Desktop Operator")
    if str(target or "active_window").strip().lower() != "active_window":
        raise invalid_argument("Visual operator v1 şu anda yalnız aktif pencere gözlemliyor.")
    ok, raw = screen_vision._run_helper("capture_active_window", timeout=20)
    if not ok:
        if is_permission_detail(raw):
            raise permission_required(raw)
        if is_timeout_detail(raw):
            raise timeout_error(raw)
        raise capability_unavailable(raw or "Ekran görüntüsü alınamadı.")
    parsed_ok, detail, capture_payload = screen_vision._parse_capture_payload(raw)
    if not parsed_ok or capture_payload is None:
        if is_permission_detail(detail):
            raise permission_required(detail)
        raise capability_unavailable(detail or "Ekran görüntüsü hazırlanamıyor.")
    source_path = Path(str(capture_payload.get("image_path", "") or ""))
    if not source_path.exists():
        raise capability_unavailable("Ekran görüntüsü dosyası bulunamadı.")
    cached_path = _copy_to_operator_cache(source_path) if preserve_screenshot else source_path
    if preserve_screenshot and source_path.exists():
        try:
            source_path.unlink()
        except Exception:
            pass
    observation = _build_screen_observation(cached_path, capture_payload)
    suggestions = _screen_target_suggestions(observation, query)
    if suggestions:
        observation["targetSuggestions"] = suggestions
    summary = _observation_summary(observation.get("elements", []), observation.get("activeApp", ""), observation.get("activeWindow", ""))
    if suggestions:
        top = suggestions[0]
        summary = f"{summary}\nÖnerilen hedef: {top.get('text', '')} ({top.get('type', '')})"
    return {
        "text": summary,
        "result": {
            "kind": "screen_observation",
            "query": _clean_text(query, 200),
            "target": "active_window",
            "observation": observation,
            "targetSuggestions": suggestions,
        },
    }


def locate(
    text: str = "",
    element_type: str = "",
    bbox: dict[str, Any] | None = None,
    _observation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    require_macos("Visual Desktop Operator")
    observation = _observation if isinstance(_observation, dict) else observe_screen("", "active_window", preserve_screenshot=True).get("result", {}).get("observation", {})
    observation = observation if isinstance(observation, dict) else {}
    target = _match_target(observation, text=text, element_type=element_type, bbox=bbox)
    return {
        "text": f"Hedef öğe bulundu: {_clean_text(target.get('text', ''), 80) or str(target.get('type', 'öğe'))}",
        "result": {
            "kind": "operator_target",
            "target": target,
            "observation": observation,
        },
    }


def focus_window(app_name: str = "", bundle_id: str = "") -> dict[str, Any]:
    require_macos("Visual Desktop Operator")
    payload = _run_operator_helper(
        "focus_window",
        {"appName": app_name, "bundleId": bundle_id},
        timeout=15,
    )
    return {
        "text": f"{_clean_text(payload.get('app_name', app_name), 80) or 'Uygulama'} odaklandı.",
        "result": {
            "kind": "operator_focus_result",
            "focused": True,
            "appName": str(payload.get("app_name", app_name) or ""),
            "bundleId": str(payload.get("bundle_id", bundle_id) or ""),
            "processId": payload.get("process_id"),
            "detail": str(payload.get("detail", "") or ""),
        },
    }


def execute_action(
    action_type: str,
    *,
    target_text: str = "",
    element_type: str = "",
    bbox: dict[str, Any] | None = None,
    text: str = "",
    keys: list[str] | None = None,
    delta: float | int | None = None,
    duration: float | int | None = None,
    app_name: str = "",
    _confirmed: bool = False,
    _run_id: str = "",
    _step_index: int = 1,
    _attempt_count: int = 1,
    _observation: dict[str, Any] | None = None,
    _observation_id: str = "",
) -> dict[str, Any]:
    require_macos("Visual Desktop Operator")
    run_id = str(_run_id or "").strip()
    step_index = max(0, int(_step_index or 0))
    attempt_count = max(1, int(_attempt_count or 1))
    normalized_action = str(action_type or "").strip().lower()
    resolution_mode = ""
    if normalized_action == "focus_window":
        observation_payload = observe_screen("", "active_window", preserve_screenshot=True)
        observation = observation_payload.get("result", {}).get("observation", {})
        observation = observation if isinstance(observation, dict) else {}
        stopped, stop_reason = _abort_requested_for_run(run_id)
        if stopped and run_id:
            _finalize_active_run(run_id, "stopped", stop_reason=stop_reason)
            return _stopped_execution_result(
                run_id=run_id,
                status="stopped",
                step_index=step_index,
                action_type=normalized_action,
                target=None,
                observation=observation,
                observation_id=_observation_id,
                stop_reason=stop_reason,
                attempt_count=attempt_count,
            )
        payload = focus_window(app_name=app_name, bundle_id="")
        verified_payload = observe_screen("", "active_window", preserve_screenshot=True)
        verified_observation = verified_payload.get("result", {}).get("observation", {})
        verified_observation = verified_observation if isinstance(verified_observation, dict) else {}
        return {
            "text": payload.get("text", "Pencere odaklandı."),
            "result": {
                "kind": "operator_execution_result",
                "runId": run_id,
                "status": "completed" if bool(verified_observation) else "failed",
                "stepIndex": step_index,
                "attemptCount": attempt_count,
                "actionType": normalized_action,
                "resolutionMode": "native_focus",
                "targetSource": "native_focus",
                "verificationSource": str(verified_observation.get("resolutionMode", "") or ""),
                "targetConfidence": 1.0,
                "candidateCount": 1,
                "verification": {
                    "ok": bool(verified_observation),
                    "checkedAt": _now_iso(),
                },
                "observation": verified_observation,
                "requiresApproval": False,
                "stopped": False,
                "stopReason": "",
                "operator": {
                    "runId": run_id,
                    "status": "completed" if bool(verified_observation) else "failed",
                    "currentStep": step_index,
                    "requiresApproval": False,
                    "activeApp": str(verified_observation.get("activeApp", "") or observation.get("activeApp", "")),
                    "activeWindow": str(verified_observation.get("activeWindow", "") or observation.get("activeWindow", "")),
                    "lastVerificationOk": bool(verified_observation),
                    "observationId": _observation_id,
                    "stopReason": "",
                },
            },
        }

    observation = dict(_observation) if isinstance(_observation, dict) else {}
    if not observation:
        observation_payload = observe_screen("", "active_window", preserve_screenshot=True)
        observation = observation_payload.get("result", {}).get("observation", {})
    observation = observation if isinstance(observation, dict) else {}
    resolution_mode = str(observation.get("resolutionMode", "") or "")
    if run_id:
        _update_active_run_state(
            run_id=run_id,
            status="executing",
            current_step_index=step_index,
            last_observation_id=_observation_id,
            operator_resolution_mode=resolution_mode,
        )
    stopped, stop_reason = _abort_requested_for_run(run_id)
    if stopped and run_id:
        _finalize_active_run(run_id, "stopped", stop_reason=stop_reason)
        return _stopped_execution_result(
            run_id=run_id,
            status="stopped",
            step_index=step_index,
            action_type=normalized_action,
            target=None,
            observation=observation,
            observation_id=_observation_id,
            stop_reason=stop_reason,
            attempt_count=attempt_count,
        )
    target: dict[str, Any] | None = None
    if normalized_action in {"click", "double_click", "right_click", "drag", "type_text"}:
        target = _match_target(observation, text=target_text, element_type=element_type, bbox=bbox)
    if target is not None and run_id:
        _update_active_run_state(
            run_id=run_id,
            last_target_source=_target_source(target),
            last_target_confidence=_target_confidence(target),
        )

    risky, risk_message = _risk_summary(normalized_action, target, {"text": text, "targetText": target_text})
    if risky and not _confirmed:
        if run_id:
            _update_active_run_state(
                run_id=run_id,
                status="waiting_approval",
                current_step_index=step_index,
                last_observation_id=_observation_id,
            )
        raise permission_required(risk_message)

    try:
        if target is not None and _target_source(target) in BROWSER_FIRST_SOURCES and browser_operator.is_supported_browser_app(
            str(observation.get("activeApp", "") or "")
        ):
            browser_operator.execute_browser_action(
                app_name=str(observation.get("activeApp", "") or ""),
                window_title=str(observation.get("activeWindow", "") or ""),
                action_type=normalized_action,
                target=target,
                text=text,
                keys=keys,
                delta=delta,
                duration=duration,
            )
            resolution_mode = "browser_first"
        else:
            helper_payload: dict[str, Any] = {"actionType": normalized_action}
            if duration is not None:
                helper_payload["duration"] = float(duration)
            if normalized_action in {"click", "double_click", "right_click", "drag"} and target is not None:
                target_bbox = target.get("bbox", {})
                target_bbox = target_bbox if isinstance(target_bbox, dict) else {}
                x, y = _bbox_center(target_bbox)
                helper_payload["x"] = x
                helper_payload["y"] = y
                if normalized_action == "drag":
                    helper_payload["fromX"] = x
                    helper_payload["fromY"] = y
                    helper_payload["toX"] = x + max(24.0, _safe_float(target_bbox.get("w"), 40.0) * 0.6)
                    helper_payload["toY"] = y
                    helper_payload["duration"] = float(duration or 0.25)
            elif normalized_action == "scroll":
                helper_payload["delta"] = float(delta or -320)
            elif normalized_action == "type_text":
                if target is None:
                    raise invalid_argument("Yazma işlemi için hedef input bulunamadı.")
                _ensure_focus_for_input(target, observation)
                helper_payload["text"] = text
            elif normalized_action == "hotkey":
                helper_payload["keys"] = list(keys or [])
            elif normalized_action == "wait":
                helper_payload["duration"] = float(duration or 0.4)
            else:
                if normalized_action not in {"scroll", "hotkey", "wait"}:
                    raise invalid_argument("Desteklenmeyen operator aksiyonu.")
            _run_operator_helper("input_action", helper_payload, timeout=25)
    except Exception as exc:
        code = str(getattr(exc, "code", "") or "").strip().lower()
        message = str(getattr(exc, "message", "") or str(exc)).strip()
        if not code:
            raise
        if code == "capability_unavailable" and "failsafe_corner_abort" in message.lower():
            if run_id:
                _request_operator_abort("fail_safe_corner", run_id=run_id)
                _finalize_active_run(run_id, "stopped", stop_reason="fail_safe_corner")
            return _stopped_execution_result(
                run_id=run_id,
                status="stopped",
                step_index=step_index,
                action_type=normalized_action,
                target=target,
                observation=observation,
                observation_id=_observation_id,
                stop_reason="fail_safe_corner",
                attempt_count=attempt_count,
            )
        if code == "capability_unavailable" and "operator_abort_requested" in message.lower():
            requested_reason = _abort_flag_reason() or "user_cancel"
            if run_id:
                _request_operator_abort(requested_reason, run_id=run_id)
                _finalize_active_run(run_id, "stopped", stop_reason=requested_reason)
            return _stopped_execution_result(
                run_id=run_id,
                status="stopped",
                step_index=step_index,
                action_type=normalized_action,
                target=target,
                observation=observation,
                observation_id=_observation_id,
                stop_reason=requested_reason,
                attempt_count=attempt_count,
            )
        if code == "permission_required" and run_id:
            _finalize_active_run(run_id, "failed", stop_reason="permission_revoked")
            raise
    verification_payload = observe_screen("", "active_window", preserve_screenshot=True)
    verified_observation = verification_payload.get("result", {}).get("observation", {})
    verified_observation = verified_observation if isinstance(verified_observation, dict) else {}
    stopped, stop_reason = _abort_requested_for_run(run_id)
    if stopped and run_id:
        _finalize_active_run(run_id, "stopped", stop_reason=stop_reason)
        return _stopped_execution_result(
            run_id=run_id,
            status="stopped",
            step_index=step_index,
            action_type=normalized_action,
            target=target,
            observation=verified_observation or observation,
            observation_id=_observation_id,
            stop_reason=stop_reason,
            attempt_count=attempt_count,
        )
    verification = _verification_result(
        action_type=normalized_action,
        before=observation,
        after=verified_observation,
        target=target,
    )
    verified = bool(verification.get("ok", False))
    verification_source = str(verification.get("source", "") or "")
    if run_id:
        _update_active_run_state(
            run_id=run_id,
            last_verification_source=verification_source or str(verified_observation.get("resolutionMode", "") or ""),
            operator_resolution_mode=resolution_mode or str(verified_observation.get("resolutionMode", "") or ""),
        )
    return {
        "text": "Operator aksiyonu çalıştırıldı." if verified else "Operator aksiyonu tamamlandı ama doğrulama zayıf.",
        "result": {
            "kind": "operator_execution_result",
            "runId": run_id,
            "status": "completed" if verified else "failed",
            "stepIndex": step_index,
            "attemptCount": attempt_count,
            "actionType": normalized_action,
            "target": target,
            "verification": {
                "ok": verified,
                "checkedAt": _now_iso(),
                "reason": str(verification.get("reason", "") or ""),
            },
            "resolutionMode": resolution_mode or str(verified_observation.get("resolutionMode", "") or ""),
            "targetSource": _target_source(target),
            "verificationSource": verification_source or str(verified_observation.get("resolutionMode", "") or ""),
            "targetConfidence": _target_confidence(target),
            "candidateCount": int(target.get("candidateCount", 0) or 0) if isinstance(target, dict) else 0,
            "observation": verified_observation,
            "requiresApproval": risky,
            "stopped": False,
            "stopReason": "",
            "operator": {
                "runId": run_id,
                "status": "completed" if verified else "failed",
                "currentStep": step_index,
                "requiresApproval": risky,
                "activeApp": str(verified_observation.get("activeApp", "") or observation.get("activeApp", "")),
                "activeWindow": str(verified_observation.get("activeWindow", "") or observation.get("activeWindow", "")),
                "lastVerificationOk": verified,
                "observationId": _observation_id,
                "stopReason": "",
            },
        },
    }


def cancel(run_id: str = "", reason: str = "user_cancel", source: str = "manual") -> dict[str, Any]:
    require_macos("Visual Desktop Operator")
    summary = _request_operator_abort(reason, run_id=run_id)
    target_run_id = str(summary.get("runId", "") or "").strip() or str(run_id or "").strip()
    status = "stopped" if target_run_id else "idle"
    if target_run_id:
        _finalize_active_run(target_run_id, "stopped", stop_reason=str(summary.get("abortReason", "") or reason))
    return {
        "text": "Visual operator durduruldu." if target_run_id else "Aktif visual operator çalışması yok.",
        "result": {
            "kind": "operator_cancel_result",
            "runId": target_run_id,
            "status": status,
            "stopped": bool(target_run_id),
            "stopReason": str(summary.get("abortReason", "") or reason),
            "source": str(source or "manual").strip() or "manual",
            "operator": {
                "runId": target_run_id,
                "status": status,
                "currentStep": int(summary.get("currentStep", 0) or 0),
                "requiresApproval": False,
                "activeApp": "",
                "activeWindow": "",
                "lastVerificationOk": False,
                "observationId": str(summary.get("lastObservationId", "") or ""),
                "stopReason": str(summary.get("abortReason", "") or reason),
            },
        },
    }


def run(
    goal: str = "",
    action: str = "",
    target_text: str = "",
    text: str = "",
    element_type: str = "",
    app_name: str = "",
    steps: list[dict[str, Any]] | None = None,
    _confirmed: bool = False,
) -> dict[str, Any]:
    require_macos("Visual Desktop Operator")
    _cleanup_stale_screenshots()
    _clear_abort_flag()
    run_id = f"oprun_{int(time.time() * 1000)}_{_operator_hash(goal or action or target_text)[:8]}"
    current_run = {
        "id": run_id,
        "task": _clean_text(goal or action or target_text, 160),
        "status": "running",
        "createdAt": _now_iso(),
        "requiresApproval": False,
    }
    _record_run(current_run)
    _update_active_run_state(
        run_id=run_id,
        status="observing",
        abort_requested=False,
        abort_reason="",
        current_step_index=0,
        last_observation_id="",
    )

    first_observation_payload = observe_screen(goal or action or target_text, "active_window", preserve_screenshot=True)
    first_observation = first_observation_payload.get("result", {}).get("observation", {})
    first_observation = first_observation if isinstance(first_observation, dict) else {}
    observation_entry = _record_observation(run_id, first_observation)
    _update_active_run_state(
        run_id=run_id,
        status="observing",
        current_step_index=0,
        last_observation_id=observation_entry["id"],
        operator_resolution_mode=str(first_observation.get("resolutionMode", "") or ""),
    )

    if (not steps or not isinstance(steps, list)) and not action and str(goal or "").strip():
        planned = _plan_operator_steps(goal, first_observation)
        planned_steps = planned.get("steps", []) if isinstance(planned.get("steps"), list) else []
        if planned_steps:
            steps = [dict(item) for item in planned_steps if isinstance(item, dict)]
            current_run["plannerProvider"] = str(planned.get("provider", "") or "")
            current_run["plannerConfidence"] = round(_safe_float(planned.get("confidence"), 0.0), 3)
            _record_run(current_run)
        else:
            clarification = _clean_text(
                planned.get("clarificationQuestion", "") or planned.get("message", "") or "Ekrandaki hedef yeterince net değil.",
                240,
            )
            current_run["status"] = "failed"
            current_run["stopReason"] = "planner_no_action"
            _record_run(current_run)
            _finalize_active_run(run_id, "failed", stop_reason="planner_no_action")
            return {
                "text": clarification,
                "result": {
                    "kind": "operator_run_result",
                    "runId": run_id,
                    "status": "failed",
                    "currentStep": 0,
                    "requiresApproval": False,
                    "lastVerificationOk": False,
                    "stopReason": "planner_no_action",
                    "observation": first_observation,
                    "operator": {
                        "runId": run_id,
                        "status": "failed",
                        "currentStep": 0,
                        "requiresApproval": False,
                        "activeApp": first_observation.get("activeApp", ""),
                        "activeWindow": first_observation.get("activeWindow", ""),
                        "lastVerificationOk": False,
                        "observationId": observation_entry["id"],
                        "stopReason": "planner_no_action",
                    },
                },
            }

    if steps and isinstance(steps, list):
        final_payload: dict[str, Any] | None = None
        retry_counts: dict[int, int] = {}
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                continue
            proposed_action = str(step.get("action", "") or "").strip().lower()
            while True:
                stopped, stop_reason = _abort_requested_for_run(run_id)
                if stopped:
                    _finalize_active_run(run_id, "stopped", stop_reason=stop_reason)
                    return {
                        "text": "Visual operator güvenli şekilde durduruldu.",
                        "result": {
                            "kind": "operator_run_result",
                            "runId": run_id,
                            "status": "stopped",
                            "currentStep": index - 1,
                            "requiresApproval": False,
                            "lastVerificationOk": False,
                            "stopReason": stop_reason,
                            "observation": first_observation,
                            "operator": {
                                "runId": run_id,
                                "status": "stopped",
                                "currentStep": index - 1,
                                "requiresApproval": False,
                                "activeApp": first_observation.get("activeApp", ""),
                                "activeWindow": first_observation.get("activeWindow", ""),
                                "lastVerificationOk": False,
                                "observationId": observation_entry["id"],
                                "stopReason": stop_reason,
                            },
                        },
                    }
                retry_counts[index] = retry_counts.get(index, 0) + 1
                _update_active_run_state(
                    run_id=run_id,
                    status="locating",
                    current_step_index=index,
                    last_observation_id=observation_entry["id"],
                )
                current_observation_payload = observe_screen("", "active_window", preserve_screenshot=True)
                current_observation = current_observation_payload.get("result", {}).get("observation", {})
                current_observation = current_observation if isinstance(current_observation, dict) else {}
                current_observation_entry = _record_observation(run_id, current_observation)
                try:
                    payload = execute_action(
                        proposed_action,
                        target_text=str(step.get("targetText", "") or ""),
                        element_type=str(step.get("elementType", "") or ""),
                        bbox=step.get("bbox") if isinstance(step.get("bbox"), dict) else None,
                        text=str(step.get("text", "") or ""),
                        keys=step.get("keys") if isinstance(step.get("keys"), list) else None,
                        delta=step.get("delta"),
                        duration=step.get("duration"),
                        app_name=str(step.get("appName", "") or ""),
                        _confirmed=_confirmed,
                        _run_id=run_id,
                        _step_index=index,
                        _attempt_count=retry_counts[index],
                        _observation=current_observation,
                        _observation_id=current_observation_entry["id"],
                    )
                except Exception as exc:
                    if str(getattr(exc, "code", "") or "").strip().upper() == "PERMISSION_REQUIRED":
                        current_run["status"] = "waiting_approval"
                        current_run["requiresApproval"] = True
                        _record_run(current_run)
                        _update_active_run_state(
                            run_id=run_id,
                            status="waiting_approval",
                            current_step_index=index,
                            last_observation_id=current_observation_entry["id"],
                        )
                        return {
                            "text": str(getattr(exc, "message", "") or str(exc)).strip() or _sensitive_action_message(),
                            "result": {
                                "kind": "operator_run_result",
                                "runId": run_id,
                                "status": "waiting_approval",
                                "currentStep": index,
                                "requiresApproval": True,
                                "lastVerificationOk": False,
                                "stopReason": "",
                                "observation": current_observation,
                                "operator": {
                                    "runId": run_id,
                                    "status": "waiting_approval",
                                    "currentStep": index,
                                    "requiresApproval": True,
                                    "activeApp": current_observation.get("activeApp", ""),
                                    "activeWindow": current_observation.get("activeWindow", ""),
                                    "lastVerificationOk": False,
                                    "observationId": current_observation_entry["id"],
                                    "stopReason": "",
                                },
                            },
                        }
                    raise
                final_payload = payload
                result_payload = payload.get("result", {}) if isinstance(payload, dict) else {}
                result_payload = result_payload if isinstance(result_payload, dict) else {}
                verification = result_payload.get("verification", {})
                verification = verification if isinstance(verification, dict) else {}
                stop_reason = str(result_payload.get("stopReason", "") or "").strip()
                execution_status = str(result_payload.get("status", "completed") or "completed").strip()
                _record_step(
                    {
                        "runId": run_id,
                        "stepIndex": index,
                        "observationId": current_observation_entry["id"],
                        "proposedAction": proposed_action,
                        "executedAction": result_payload.get("actionType", proposed_action),
                        "result": execution_status,
                        "requiresApproval": bool(result_payload.get("requiresApproval", False)),
                        "approvedByUser": _confirmed,
                        "attemptCount": retry_counts[index],
                        "stopReason": stop_reason,
                    }
                )
                _record_input_action(
                    {
                        "stepId": f"{run_id}:{index}",
                        "actionType": proposed_action,
                        "targetBBox": result_payload.get("target", {}).get("bbox", {})
                        if isinstance(result_payload.get("target"), dict)
                        else {},
                        "textRedacted": bool(str(step.get("text", "") or "").strip()),
                        "status": execution_status,
                        "attemptCount": retry_counts[index],
                    }
                )
                _record_verification(
                    {
                        "stepId": f"{run_id}:{index}",
                        "ok": bool(verification.get("ok", False)),
                        "createdAt": _now_iso(),
                        "reason": str(verification.get("reason", "") or ""),
                    }
                )
                if execution_status == "stopped":
                    _finalize_active_run(run_id, "stopped", stop_reason=stop_reason or "user_cancel")
                    return {
                        "text": payload.get("text", "Visual operator güvenli şekilde durduruldu."),
                        "result": {
                            "kind": "operator_run_result",
                            "runId": run_id,
                            "status": "stopped",
                            "currentStep": index,
                            "requiresApproval": False,
                            "lastVerificationOk": False,
                            "stopReason": stop_reason or "user_cancel",
                            "observation": result_payload.get("observation", first_observation),
                            "operator": {
                                "runId": run_id,
                                "status": "stopped",
                                "currentStep": index,
                                "requiresApproval": False,
                                "activeApp": first_observation.get("activeApp", ""),
                                "activeWindow": first_observation.get("activeWindow", ""),
                                "lastVerificationOk": False,
                                "observationId": current_observation_entry["id"],
                                "stopReason": stop_reason or "user_cancel",
                            },
                        },
                    }
                if bool(verification.get("ok", False)):
                    _update_active_run_state(
                        run_id=run_id,
                        status="verifying",
                        current_step_index=index,
                        last_observation_id=current_observation_entry["id"],
                    )
                    break
                if retry_counts[index] >= 2:
                    current_run["status"] = "failed"
                    current_run["stopReason"] = "verification_failed"
                    _record_run(current_run)
                    _finalize_active_run(run_id, "failed", stop_reason="verification_failed")
                    return {
                        "text": "Operator aksiyonu doğrulanamadı.",
                        "result": {
                            "kind": "operator_run_result",
                            "runId": run_id,
                            "status": "failed",
                            "currentStep": index,
                            "requiresApproval": False,
                            "lastVerificationOk": False,
                            "stopReason": "verification_failed",
                            "observation": result_payload.get("observation", first_observation),
                            "operator": {
                                "runId": run_id,
                                "status": "failed",
                                "currentStep": index,
                                "requiresApproval": False,
                                "activeApp": first_observation.get("activeApp", ""),
                                "activeWindow": first_observation.get("activeWindow", ""),
                                "lastVerificationOk": False,
                                "observationId": current_observation_entry["id"],
                                "stopReason": "verification_failed",
                            },
                        },
                    }
            current_run["status"] = "running"
            _record_run(current_run)
        current_run["status"] = "completed"
        _record_run(current_run)
        _finalize_active_run(run_id, "completed")
        final_result = final_payload.get("result", {}) if isinstance(final_payload, dict) else {}
        return {
            "text": final_payload.get("text", "Operator akışı tamamlandı.") if isinstance(final_payload, dict) else "Operator akışı tamamlandı.",
            "result": {
                "kind": "operator_run_result",
                "runId": run_id,
                "status": "completed",
                "currentStep": len(steps),
                "requiresApproval": False,
                "lastVerificationOk": bool(final_result.get("verification", {}).get("ok", False)) if isinstance(final_result, dict) else False,
                "stopReason": "",
                "observation": first_observation,
                "operator": {
                    "runId": run_id,
                    "status": "completed",
                    "currentStep": len(steps),
                    "requiresApproval": False,
                    "activeApp": first_observation.get("activeApp", ""),
                    "activeWindow": first_observation.get("activeWindow", ""),
                    "lastVerificationOk": bool(final_result.get("verification", {}).get("ok", False)) if isinstance(final_result, dict) else False,
                    "observationId": observation_entry["id"],
                    "stopReason": "",
                },
            },
        }

    if not action:
        current_run["status"] = "observed"
        _record_run(current_run)
        _finalize_active_run(run_id, "completed")
        return {
            "text": first_observation_payload.get("text", "Ekran gözlemi hazır."),
            "result": {
                "kind": "operator_run_result",
                "runId": run_id,
                "status": "observed",
                "currentStep": 0,
                "requiresApproval": False,
                "lastVerificationOk": True,
                "stopReason": "",
                "observation": first_observation,
                "operator": {
                    "runId": run_id,
                    "status": "observed",
                    "currentStep": 0,
                    "requiresApproval": False,
                    "activeApp": first_observation.get("activeApp", ""),
                    "activeWindow": first_observation.get("activeWindow", ""),
                    "lastVerificationOk": True,
                    "observationId": observation_entry["id"],
                    "stopReason": "",
                },
            },
        }

    try:
        execution = execute_action(
            action,
            target_text=target_text,
            element_type=element_type,
            text=text,
            app_name=app_name,
            _confirmed=_confirmed,
            _run_id=run_id,
            _step_index=1,
            _attempt_count=1,
            _observation=first_observation,
            _observation_id=observation_entry["id"],
        )
    except Exception as exc:
        if str(getattr(exc, "code", "") or "").strip().upper() == "PERMISSION_REQUIRED":
            current_run["status"] = "waiting_approval"
            current_run["requiresApproval"] = True
            _record_run(current_run)
            _update_active_run_state(
                run_id=run_id,
                status="waiting_approval",
                current_step_index=1,
                last_observation_id=observation_entry["id"],
            )
            return {
                "text": str(getattr(exc, "message", "") or str(exc)).strip() or _sensitive_action_message(),
                "result": {
                    "kind": "operator_run_result",
                    "runId": run_id,
                    "status": "waiting_approval",
                    "currentStep": 1,
                    "requiresApproval": True,
                    "lastVerificationOk": False,
                    "stopReason": "",
                    "observation": first_observation,
                    "operator": {
                        "runId": run_id,
                        "status": "waiting_approval",
                        "currentStep": 1,
                        "requiresApproval": True,
                        "activeApp": first_observation.get("activeApp", ""),
                        "activeWindow": first_observation.get("activeWindow", ""),
                        "lastVerificationOk": False,
                        "observationId": observation_entry["id"],
                        "stopReason": "",
                    },
                },
            }
        raise
    execution_result = execution.get("result", {}) if isinstance(execution, dict) else {}
    execution_result = execution_result if isinstance(execution_result, dict) else {}
    execution_status = str(execution_result.get("status", "completed") or "completed").strip()
    stop_reason = str(execution_result.get("stopReason", "") or "").strip()
    current_run["status"] = execution_status
    if stop_reason:
        current_run["stopReason"] = stop_reason
    _record_run(current_run)
    if execution_status == "completed":
        _finalize_active_run(run_id, "completed")
    elif execution_status == "stopped":
        _finalize_active_run(run_id, "stopped", stop_reason=stop_reason or "user_cancel")
    else:
        _finalize_active_run(run_id, "failed", stop_reason=stop_reason or "verification_failed")
    return {
        "text": execution.get("text", "Operator aksiyonu tamamlandı.") if isinstance(execution, dict) else "Operator aksiyonu tamamlandı.",
        "result": {
            "kind": "operator_run_result",
            "runId": run_id,
            "status": execution_status,
            "currentStep": 1,
            "requiresApproval": bool(isinstance(execution_result, dict) and execution_result.get("requiresApproval", False)),
            "lastVerificationOk": bool(isinstance(execution_result, dict) and execution_result.get("verification", {}).get("ok", False)),
            "stopReason": stop_reason,
            "observation": execution_result.get("observation", first_observation) if isinstance(execution_result, dict) else first_observation,
            "operator": {
                "runId": run_id,
                "status": execution_status,
                "currentStep": 1,
                "requiresApproval": bool(isinstance(execution_result, dict) and execution_result.get("requiresApproval", False)),
                "activeApp": first_observation.get("activeApp", ""),
                "activeWindow": first_observation.get("activeWindow", ""),
                "lastVerificationOk": bool(isinstance(execution_result, dict) and execution_result.get("verification", {}).get("ok", False)),
                "observationId": observation_entry["id"],
                "stopReason": stop_reason,
            },
        },
    }
