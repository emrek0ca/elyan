from __future__ import annotations

import os
from typing import Any

from runtime.backend_client import BackendClient
from runtime.capability_registry import SafeCapabilityError


def _current_backend_client() -> BackendClient:
    client = BackendClient(os.environ.get("APP_BASE_URL"))
    if not client.configured:
        raise SafeCapabilityError("BACKEND_UNAVAILABLE", "Backend bağlantısı hazır değil.")
    return client


def _draft_body(topic: str, prompt: str, previous_result: dict[str, Any] | None) -> str:
    summary = ""
    sources: list[dict[str, Any]] = []
    if isinstance(previous_result, dict):
        summary = str(previous_result.get("summary") or previous_result.get("text") or "").strip()
        maybe_sources = previous_result.get("sources")
        if isinstance(maybe_sources, list):
            sources = [item for item in maybe_sources if isinstance(item, dict)]

    lines = [
        "Merhaba,",
        "",
        f"{topic} hakkında kısa bir özet hazırladım.",
    ]
    if summary:
        lines.extend(["", summary])
    if prompt.strip() and prompt.strip() != topic.strip():
        lines.extend(["", f"İstenen bağlam: {prompt.strip()}"])
    if sources:
        lines.extend(["", "Kaynaklar:"])
        for source in sources[:3]:
            title = str(source.get("title", "") or "").strip()
            url = str(source.get("url", "") or "").strip()
            if title and url:
                lines.append(f"- {title}: {url}")
    lines.extend(["", "İyi çalışmalar."])
    return "\n".join(lines).strip()


def email_draft(
    to: list[str] | None = None,
    subject: str = "",
    topic: str = "",
    prompt: str = "",
    tone: str = "professional",
    _previousResult: dict[str, Any] | None = None,
    _previousOutput: str = "",
    _confirmed: bool = False,
    **_: Any,
) -> dict[str, Any]:
    recipients = [item.strip() for item in (to or []) if str(item or "").strip()]
    if not recipients:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Alıcı belirtilmedi.")
    resolved_topic = str(topic or subject or prompt or "E-posta").strip()
    resolved_subject = str(subject or f"{resolved_topic[:80]} hakkında notlar").strip()
    body = _draft_body(resolved_topic, prompt or _previousOutput, _previousResult)
    return {
        "text": f"E-posta taslağı hazırlandı: {resolved_subject}",
        "result": {
            "kind": "email_draft",
            "to": recipients,
            "subject": resolved_subject,
            "body": body,
            "tone": tone,
            "topic": resolved_topic,
        },
        "artifacts": [],
    }


def email_send(
    to: list[str] | None = None,
    subject: str = "",
    body: str = "",
    connectionId: str = "",
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    replyTo: str = "",
    _previousResult: dict[str, Any] | None = None,
    _previousOutput: str = "",
    _confirmed: bool = False,
    **_: Any,
) -> dict[str, Any]:
    recipients = [item.strip() for item in (to or []) if str(item or "").strip()]
    if not recipients:
        raise SafeCapabilityError("INVALID_ARGUMENT", "Alıcı belirtilmedi.")
    if not _confirmed:
        raise SafeCapabilityError("PERMISSION_REQUIRED", "E-posta göndermek için açık onay gerekiyor.")

    resolved_subject = str(subject or "").strip()
    resolved_body = str(body or "").strip()
    if not resolved_body and isinstance(_previousResult, dict):
        resolved_body = str(_previousResult.get("body", "") or _previousResult.get("text", "") or "").strip()
    if not resolved_body:
        resolved_body = str(_previousOutput or "").strip()
    if not resolved_body:
        raise SafeCapabilityError("INVALID_ARGUMENT", "E-posta gövdesi hazırlanamadı.")
    if not resolved_subject and isinstance(_previousResult, dict):
        resolved_subject = str(_previousResult.get("subject", "") or "").strip()
    if not resolved_subject:
        resolved_subject = "E-posta"

    result = _current_backend_client().gmail_send_message(
        to=recipients,
        subject=resolved_subject,
        body=resolved_body,
        connection_id=str(connectionId or "").strip() or None,
        cc=[item.strip() for item in (cc or []) if str(item or "").strip()] or None,
        bcc=[item.strip() for item in (bcc or []) if str(item or "").strip()] or None,
        reply_to=str(replyTo or "").strip() or None,
    )
    if not result.ok or not isinstance(result.data, dict):
        message = str(result.error or "Gmail gönderimi başarısız oldu.").strip()
        raise SafeCapabilityError("GMAIL_SEND_FAILED", message)

    payload = result.data
    return {
        "text": f"E-posta gönderildi: {resolved_subject}",
        "result": {
            "kind": "email_send",
            "provider": str(payload.get("provider", "google") or "google"),
            "connectionId": str(payload.get("connectionId", "") or connectionId or ""),
            "messageId": str(payload.get("messageId", "") or ""),
            "threadId": str(payload.get("threadId", "") or ""),
            "labelIds": payload.get("labelIds", []),
            "to": payload.get("to", recipients),
            "subject": payload.get("subject", resolved_subject),
        },
        "artifacts": [],
    }
