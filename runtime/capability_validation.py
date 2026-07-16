"""P3 — Capability doğrulama katmanı: ön koşul + bağımsız readback kanıtı.

Her adım için iki kapı:

1. ``precondition_error`` — yürütme ÖNCESİ: girdi dosyası gerçekten var mı,
   yazma hedefi izinli kaynak kapsamında mı, zorunlu argümanlar dolu mu.
2. ``readback_evidence`` — yürütme SONRASI: capability'nin kendi "ok" beyanından
   bağımsız kanıt. Dosya yazan adımlar için diskten hash/boyut okunur; sağlayıcı
   (takvim/e-posta/anımsatıcı) adımları için provider kimliği veya gözlemlenen
   durum (stateReadback) aranır. Boş olmayan araç çıktısı tek başına yan etkili
   bir adımı doğrulamaz. Uyuşmazlık fail-closed'dur.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path
from typing import Any

# Dosya üreten adımlarda çıktı yolunun arandığı argüman anahtarları.
_OUTPUT_PATH_ARG_KEYS = ("outputPath", "output_path", "targetPath", "target_path", "path")
# Girdi dosyası okuyan adımlarda yolun arandığı argüman anahtarları.
_INPUT_PATH_ARG_KEYS = ("path", "inputPath", "input_path", "filePath", "file_path")
# Sağlayıcı kanıtı: sonuç yükünde bu anahtarlardan biri kimlik taşımalı.
_PROVIDER_ID_KEYS = (
    "eventId", "event_id", "messageId", "message_id", "reminderId", "reminder_id",
    "providerId", "provider_id", "externalId", "external_id", "uid",
)

_INPUT_FILE_CAPABILITIES = {"file_read", "document_read", "ocr_read", "image_read", "image_edit"}
_FILE_WRITE_CAPABILITIES = {
    "document_write", "spreadsheet_write", "presentation_write", "canvas_write",
    "file_write", "file_patch", "image_generate", "image_edit", "image_fetch", "chart_generate",
}
_PROVIDER_EVIDENCE_CAPABILITIES = {
    "add_calendar_event", "delete_calendar_event", "add_reminder",
    "email_send", "send_whatsapp_message", "save_whatsapp_contact",
}
# Yazma hedefi bu köklerin dışına çıkamaz (kaynak kapsamı, fail-closed).
_BLOCKED_WRITE_PREFIXES = (
    "/System", "/usr", "/bin", "/sbin", "/etc", "/Library", "/private/etc",
)


def _first_text_arg(args: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = str(args.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _allowed_write_root(path: Path) -> bool:
    text = str(path)
    for prefix in _BLOCKED_WRITE_PREFIXES:
        if text == prefix or text.startswith(prefix + "/"):
            return False
    allowed_roots = [Path.home(), Path(tempfile.gettempdir()), Path("/tmp"), Path("/private/tmp"), Path("/private/var/folders"), Path("/Volumes")]
    return any(text == str(root) or text.startswith(str(root) + "/") for root in allowed_roots)


def step_resource_scope(capability: str, args: dict[str, Any]) -> list[str]:
    """Adımın dokunduğu kaynakları (yol, alıcı, uygulama) normalize listeler."""
    scope: list[str] = []
    for key in (*_OUTPUT_PATH_ARG_KEYS, *_INPUT_PATH_ARG_KEYS, "to", "recipient", "app_name", "appName", "url", "calendarId", "calendar_id"):
        value = args.get(key)
        values = value if isinstance(value, list) else [value]
        for item in values:
            text = str(item or "").strip()
            if text and text not in scope:
                scope.append(text)
    return scope


def precondition_error(capability: str, args: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, str] | None:
    """Yürütme öncesi kapı; ihlalde ``{"code", "message"}`` döner."""
    name = str(capability or "").strip()
    if not isinstance(args, dict):
        return {"code": "PRECONDITION_ARGS_INVALID", "message": "Adım argümanları nesne olmalı."}

    if name in _INPUT_FILE_CAPABILITIES:
        raw = _first_text_arg(args, _INPUT_PATH_ARG_KEYS)
        if raw:
            candidate = Path(raw).expanduser()
            if not candidate.exists():
                return {
                    "code": "PRECONDITION_INPUT_MISSING",
                    "message": f"Girdi dosyası bulunamadı: {candidate}",
                }
            if candidate.is_dir():
                return {
                    "code": "PRECONDITION_INPUT_IS_DIR",
                    "message": f"Girdi bir dosya olmalı, dizin verildi: {candidate}",
                }

    if name in _FILE_WRITE_CAPABILITIES:
        raw = _first_text_arg(args, _OUTPUT_PATH_ARG_KEYS)
        if raw:
            candidate = Path(raw).expanduser()
            try:
                resolved = candidate if candidate.is_absolute() else (Path.home() / candidate)
                resolved = Path(str(resolved))
            except (OSError, ValueError):
                return {"code": "PRECONDITION_OUTPUT_INVALID", "message": f"Çıktı yolu çözümlenemedi: {raw}"}
            if resolved.exists() and resolved.is_dir():
                return {
                    "code": "PRECONDITION_OUTPUT_IS_DIR",
                    "message": f"Çıktı yolu mevcut bir dizini gösteriyor: {resolved}",
                }
            if resolved.is_absolute() and not _allowed_write_root(resolved):
                return {
                    "code": "PRECONDITION_RESOURCE_SCOPE",
                    "message": f"Yazma hedefi izinli kaynak kapsamı dışında: {resolved}",
                }

    if name == "email_send":
        to_value = args.get("to")
        recipients = to_value if isinstance(to_value, list) else [to_value]
        cleaned = [str(item or "").strip() for item in recipients if str(item or "").strip()]
        if cleaned and not all("@" in item for item in cleaned):
            return {
                "code": "PRECONDITION_RECIPIENT_INVALID",
                "message": "E-posta alıcısı geçerli bir adres değil.",
            }

    if name == "shell_run":
        command = str(args.get("command", "") or args.get("cmd", "") or "").strip()
        if not command:
            return {"code": "PRECONDITION_COMMAND_MISSING", "message": "Çalıştırılacak komut boş."}

    return None


def pre_execution_state(capability: str, args: dict[str, Any]) -> dict[str, Any]:
    """Yürütme öncesi kaynak durumu (P4 compensation için): hedef dosya var mıydı?"""
    name = str(capability or "").strip()
    if name in _FILE_WRITE_CAPABILITIES and isinstance(args, dict):
        raw = _first_text_arg(args, _OUTPUT_PATH_ARG_KEYS)
        if raw:
            candidate = Path(raw).expanduser()
            return {"path": str(candidate), "preExisted": candidate.exists()}
    return {}


def file_evidence(path: str | Path) -> dict[str, Any]:
    """Diskten bağımsız readback: hash + boyut. Okunamazsa verified=False."""
    candidate = Path(str(path)).expanduser()
    try:
        if not candidate.exists() or not candidate.is_file():
            return {"kind": "file_hash", "verified": False, "path": str(candidate), "reason": "file_missing"}
        digest = hashlib.sha256()
        size = 0
        with candidate.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 256), b""):
                digest.update(chunk)
                size += len(chunk)
        if size <= 0:
            return {"kind": "file_hash", "verified": False, "path": str(candidate), "reason": "file_empty"}
        return {
            "kind": "file_hash",
            "verified": True,
            "path": str(candidate),
            "sha256": digest.hexdigest(),
            "sizeBytes": size,
        }
    except OSError as exc:
        return {"kind": "file_hash", "verified": False, "path": str(candidate), "reason": str(exc)[:120]}


def _result_payload(tool_result: dict[str, Any]) -> dict[str, Any]:
    payload = tool_result.get("result")
    return payload if isinstance(payload, dict) else {}


def _observed_readback(payload: dict[str, Any]) -> bool:
    if payload.get("stateVerified") is True or payload.get("readBackVerified") is True:
        return True
    readback = payload.get("stateReadback")
    return isinstance(readback, dict) and readback.get("observed") is True


def _find_provider_id(payload: dict[str, Any]) -> str:
    for key in _PROVIDER_ID_KEYS:
        value = str(payload.get(key, "") or "").strip()
        if value:
            return value
    for nested_key in ("event", "message", "reminder", "data", "detail"):
        nested = payload.get(nested_key)
        if isinstance(nested, dict):
            found = _find_provider_id(nested)
            if found:
                return found
    return ""


def readback_evidence(capability: str, args: dict[str, Any], tool_result: dict[str, Any]) -> dict[str, Any]:
    """Capability'nin beyanından bağımsız kanıt üretir; bulunamazsa verified=False."""
    name = str(capability or "").strip()
    payload = _result_payload(tool_result)
    scope = step_resource_scope(name, args if isinstance(args, dict) else {})

    if name in _FILE_WRITE_CAPABILITIES:
        raw = _first_text_arg(args if isinstance(args, dict) else {}, _OUTPUT_PATH_ARG_KEYS)
        candidates = [raw] if raw else []
        artifacts = tool_result.get("artifacts")
        if isinstance(artifacts, list):
            candidates.extend(
                str(item.get("path", "") or "").strip()
                for item in artifacts
                if isinstance(item, dict) and str(item.get("path", "") or "").strip()
            )
        for candidate in candidates:
            evidence = file_evidence(candidate)
            if evidence.get("verified"):
                evidence["resourceScope"] = scope
                return evidence
        return {
            "kind": "file_hash",
            "verified": False,
            "resourceScope": scope,
            "reason": "output_file_unverified" if candidates else "output_path_unknown",
        }

    if name in _PROVIDER_EVIDENCE_CAPABILITIES:
        provider_id = _find_provider_id(payload)
        if provider_id:
            return {"kind": "provider_id", "verified": True, "providerId": provider_id, "resourceScope": scope}
        if _observed_readback(payload):
            return {"kind": "state_readback", "verified": True, "resourceScope": scope}
        return {"kind": "provider_id", "verified": False, "resourceScope": scope, "reason": "provider_id_missing"}

    if _observed_readback(payload):
        return {"kind": "state_readback", "verified": True, "resourceScope": scope}
    if payload:
        return {"kind": "structured_output", "verified": True, "resourceScope": scope}
    return {"kind": "structured_output", "verified": False, "resourceScope": scope, "reason": "structured_result_missing"}


def attach_step_evidence(tool_result: dict[str, Any], evidence: dict[str, Any]) -> None:
    """Kanıtı sonuç yüküne işler; iş emri doğrulaması (verify_result) bunu okur."""
    tool_result["stepEvidence"] = dict(evidence)
    payload = tool_result.get("result")
    if isinstance(payload, dict):
        payload["stepEvidence"] = dict(evidence)
        if evidence.get("verified") is True and evidence.get("kind") in {"file_hash", "provider_id", "state_readback"}:
            payload.setdefault("readBackVerified", True)
