from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field, ValidationError


class LLMIntentEnvelope(BaseModel):
    intent: dict[str, Any]
    confidence: float = Field(ge=0.0, le=1.0)
    required_artifacts: list[str] = Field(default_factory=list)
    tools_needed: list[str] = Field(default_factory=list)
    safety_flags: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)


class IntentScoreResult(BaseModel):
    score: float = Field(ge=0.0, le=1.0)
    actionable: bool
    reasons: list[str] = Field(default_factory=list)


_ACTION_MARKERS = (
    "yap", "olustur", "oluştur", "kaydet", "sil", "çalıştır", "calistir", "run", "create", "write", "build", "fix",
    "tıkla", "tikla", "mouse", "klavye", "wallpaper", "screenshot", "http", "api", "dosya", "klasor", "klasör",
)
_QUESTION_MARKERS = ("nedir", "kimdir", "what", "why", "how", "where", "when")


def deterministic_intent_score(user_input: str, *, memory_context: str = "", attachments: list[str] | None = None) -> IntentScoreResult:
    low = str(user_input or "").strip().lower()
    score = 0.0
    reasons: list[str] = []

    if not low:
        return IntentScoreResult(score=0.0, actionable=False, reasons=["empty_input"])

    if any(m in low for m in _ACTION_MARKERS):
        score += 0.45
        reasons.append("action_markers")

    if any(q in low for q in _QUESTION_MARKERS) and low.endswith("?"):
        score -= 0.2
        reasons.append("question_shape")

    if attachments:
        score += 0.35
        reasons.append("attachments_present")

    mem = str(memory_context or "").lower()
    if "task" in mem or "previous" in mem or "önceki" in mem:
        score += 0.1
        reasons.append("recent_context")

    if any(tok in low for tok in ("1)", "2)", "sonra", "ardından", "ardindan")):
        score += 0.2
        reasons.append("multi_step_shape")

    final = max(0.0, min(1.0, score))
    return IntentScoreResult(score=final, actionable=final >= 0.42, reasons=reasons)


def _safe_size(path: Path) -> int:
    try:
        return int(path.stat().st_size)
    except Exception:
        return 0


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            while True:
                chunk = f.read(65536)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return ""


def _quick_summary(path: Path, ext: str) -> str:
    if ext in {".txt", ".md", ".py", ".json", ".csv", ".log"}:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            line_count = len(text.splitlines())
            preview = " ".join(text.strip().split())[:120]
            return f"text lines={line_count}; preview={preview}"
        except Exception:
            return "text unreadable"
    if ext in {".pdf"}:
        return "pdf document"
    if ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
        return "image asset"
    return "binary/unknown"


def index_attachments(paths: list[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for raw in paths or []:
        p = Path(str(raw)).expanduser().resolve()
        ext = p.suffix.lower()
        exists = p.exists() and p.is_file()
        line_or_page = 0
        width = 0
        height = 0
        if exists and ext in {".txt", ".md", ".py", ".json", ".csv", ".log"}:
            try:
                line_or_page = len(p.read_text(encoding="utf-8", errors="ignore").splitlines())
            except Exception:
                line_or_page = 0
        if exists and ext in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
            try:
                from PIL import Image

                with Image.open(p) as img:
                    width, height = img.size
            except Exception:
                width = 0
                height = 0
        item = {
            "path": str(p),
            "exists": exists,
            "type": ext.lstrip(".") or "unknown",
            "size_bytes": _safe_size(p) if exists else 0,
            "line_or_page_count": line_or_page,
            "width": int(width or 0),
            "height": int(height or 0),
            "content_hash": _sha256(p) if exists else "",
            "quick_summary": _quick_summary(p, ext) if exists else "missing",
        }
        items.append(item)
    return items


def parse_llm_intent_envelope(payload: Any) -> LLMIntentEnvelope | None:
    obj: Any = payload
    if isinstance(payload, str):
        txt = payload.strip()
        if not txt:
            return None
        try:
            obj = json.loads(txt)
        except Exception:
            return None
    if not isinstance(obj, dict):
        return None
    try:
        return LLMIntentEnvelope.model_validate(obj)
    except ValidationError:
        return None


def context_fingerprint(user_input: str, *, memory_context: str = "", attachment_index: list[dict[str, Any]] | None = None) -> str:
    payload = {
        "input": str(user_input or "")[:3000],
        "memory": str(memory_context or "")[:1200],
        "attachments": [
            {"path": a.get("path"), "hash": a.get("content_hash"), "size": a.get("size_bytes")}
            for a in (attachment_index or [])
            if isinstance(a, dict)
        ],
    }
    digest = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return digest[:24]


def build_context_working_set(ctx: Any, *, max_chars: int = 1600) -> str:
    parts: list[str] = []
    mem = str(getattr(ctx, "memory_context", "") or "").strip()
    if mem:
        parts.append(f"Digest:{mem[:700]}")

    constraints = getattr(ctx, "goal_constraints", {})
    if isinstance(constraints, dict) and constraints:
        parts.append(f"Constraints:{json.dumps(constraints, ensure_ascii=False)[:500]}")

    attach = getattr(ctx, "attachment_index", [])
    if isinstance(attach, list) and attach:
        compact = [{"type": a.get("type"), "size": a.get("size_bytes")} for a in attach[:4] if isinstance(a, dict)]
        parts.append(f"Attachments:{json.dumps(compact, ensure_ascii=False)}")

    world = getattr(ctx, "world_snapshot", None)
    if isinstance(world, dict):
        summary = str(world.get("summary") or "").strip()
        if summary:
            parts.append(f"World:{summary[:400]}")
        hints = world.get("strategy_hints")
        if isinstance(hints, list) and hints:
            parts.append(f"Strategies:{'; '.join(str(h) for h in hints[:3])}")

    base = "\n".join(parts)
    return base[:max_chars]


def route_model_tier(*, complexity_score: float, is_code_job: bool, needs_reasoning: bool) -> dict[str, Any]:
    c = max(0.0, min(1.0, float(complexity_score or 0.0)))
    if is_code_job or needs_reasoning or c >= 0.8:
        return {"tier": "strong", "budget": "high", "reason": "hard_reasoning"}
    if c >= 0.45:
        return {"tier": "mid", "budget": "medium", "reason": "skeleton_plan"}
    return {"tier": "cheap", "budget": "low", "reason": "classification_first"}
