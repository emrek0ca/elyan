from __future__ import annotations

import re
from typing import Any


def compact_text(value: str, *, limit: int = 280) -> str:
    compact = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(0, limit - 3)].rstrip() + "..."


def normalize_intake_source(value: str) -> str:
    normalized = str(value or "").strip().lower().replace(" ", "_")
    return normalized or "manual"


def extract_task_summary(content: str, *, source_type: str, title: str = "") -> dict[str, Any]:
    normalized_content = str(content or "").strip()
    lines = [line.strip() for line in normalized_content.splitlines() if line.strip()]
    derived_title = str(title or (lines[0] if lines else "")).strip()
    if not derived_title:
        derived_title = f"{normalize_intake_source(source_type).replace('_', ' ').title()} intake"
    task_type = _infer_task_type(normalized_content)
    urgency = _infer_urgency(normalized_content)
    action_items = _extract_action_items(normalized_content)
    approval_required = _requires_approval(normalized_content)
    summary = compact_text(" ".join(lines[:2]) if lines else normalized_content, limit=220)
    if not summary:
        summary = f"{normalize_intake_source(source_type).replace('_', ' ').title()} kanalindan yakalanan yeni is girdisi."
    prompt_parts = [
        f"{summary}",
        f"Gorev tipi: {task_type}.",
    ]
    if action_items:
        prompt_parts.append("Odak adimlari: " + "; ".join(action_items[:4]) + ".")
    if approval_required:
        prompt_parts.append("Riskli veya dis dunyaya etkisi olan adimlardan once onay iste.")
    else:
        prompt_parts.append("Gerekli yerlerde bir sonraki en iyi adimi netlestir ve ilerle.")
    confidence = 0.84 if action_items else 0.68
    if task_type == "cowork":
        confidence -= 0.06
    return {
        "title": compact_text(derived_title, limit=120),
        "summary": summary,
        "task_type": task_type,
        "urgency": urgency,
        "approval_required": approval_required,
        "action_items": action_items,
        "recommended_prompt": " ".join(part for part in prompt_parts if part).strip(),
        "confidence": round(max(0.4, min(0.95, confidence)), 2),
        "source_type": normalize_intake_source(source_type),
    }


def _extract_action_items(content: str) -> list[str]:
    action_items: list[str] = []
    seen: set[str] = set()
    lines = [line.strip(" \t-•*0123456789.)") for line in str(content or "").splitlines() if line.strip()]
    verb_hint = re.compile(
        r"\b(prepare|draft|review|reply|send|plan|schedule|create|update|fix|ship|deploy|connect|sync|call|follow up|hazırla|incele|yanıtla|gönder|planla|oluştur|düzelt|bağla|ara|takip et)\b",
        re.IGNORECASE,
    )
    for line in lines:
        candidate = compact_text(line, limit=120)
        lowered = candidate.lower()
        if len(candidate) < 8:
            continue
        if line[:1] in {"-", "*", "•"} or re.match(r"^\d+[.)]", line.strip()) or verb_hint.search(lowered):
            if lowered not in seen:
                action_items.append(candidate)
                seen.add(lowered)
        if len(action_items) >= 4:
            return action_items
    sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", str(content or "").strip()) if segment.strip()]
    for sentence in sentences:
        candidate = compact_text(sentence, limit=120)
        lowered = candidate.lower()
        if len(candidate) < 12 or lowered in seen:
            continue
        action_items.append(candidate)
        seen.add(lowered)
        if len(action_items) >= 4:
            break
    return action_items[:4]


def _infer_task_type(content: str) -> str:
    text = str(content or "").lower()
    if re.search(r"\b(slide|deck|presentation|sunum\w*|ppt|pitch)\b", text):
        return "presentation"
    if re.search(r"\b(site|website|landing|web app|web|react|nextjs|frontend|vite|ui)\b", text):
        return "website"
    if re.search(r"\b(report|proposal|brief|document|doc|doküman\w*|belge\w*|teklif\w*|rapor\w*|sunuş metni)\b", text):
        return "document"
    return "cowork"


def _infer_urgency(content: str) -> str:
    text = str(content or "").lower()
    if re.search(r"\b(acil|urgent|asap|today|bugün|hemen|critical|kritik|production|prod)\b", text):
        return "high"
    if re.search(r"\b(soon|this week|yakında|hafta|review|inceleme|follow up|takip)\b", text):
        return "medium"
    return "low"


def _requires_approval(content: str) -> bool:
    return bool(
        re.search(
            r"\b(delete|remove|drop|reset|restart|deploy|publish|purchase|pay|refund|invoice|transfer|revoke|send|reply|production|prod|sil|kaldır|yayınla\w*|satın al|ödeme|iade|fatura|aktarım|gönder\w*|gonder\w*|yanıtla\w*|yanitla\w*)\b",
            str(content or "").lower(),
        )
    )
