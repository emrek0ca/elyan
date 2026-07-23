from __future__ import annotations

import re
from typing import Any


def _clean_text(value: Any, *, limit: int = 48000) -> str:
    text = " ".join(str(value or "").split()).strip()
    return text[:limit]


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", text)
    return [part.strip() for part in parts if part.strip()]


def _bullets(text: str) -> list[str]:
    sentences = _sentences(text)
    if not sentences and text:
        sentences = [text]
    return sentences[:6]


def text_analyze(
    prompt: str,
    source_context: str = "",
    mode: str = "professional",
    _previousOutput: str = "",
    _previousResult: dict[str, Any] | None = None,
    _dependencyResults: dict[str, Any] | None = None,
) -> dict[str, Any]:
    instruction = _clean_text(prompt, limit=12000)
    context = _clean_text(source_context or _previousOutput, limit=36000)
    dependency_results = _dependencyResults if isinstance(_dependencyResults, dict) else {}
    previous_result = _previousResult if isinstance(_previousResult, dict) else {}
    if not context and previous_result:
        for key in ("summary", "text", "output", "body", "result"):
            value = previous_result.get(key)
            if value:
                context = _clean_text(value, limit=36000)
                break
    if not context and dependency_results:
        chunks: list[str] = []
        for value in dependency_results.values():
            if isinstance(value, dict):
                for key in ("summary", "text", "output", "result"):
                    if value.get(key):
                        chunks.append(_clean_text(value.get(key), limit=8000))
                        break
            elif value:
                chunks.append(_clean_text(value, limit=8000))
        context = "\n\n".join(chunk for chunk in chunks if chunk)

    if not instruction and not context:
        raise ValueError("Analiz için metin veya önceki adım çıktısı gerekli.")

    evidence = _bullets(context or instruction)
    summary_source = context or instruction
    summary = _clean_text(summary_source, limit=900)
    focus = _clean_text(instruction, limit=900)
    analysis = {
        "kind": "text_analyze",
        "mode": _clean_text(mode, limit=80) or "professional",
        "summary": summary,
        "focus": focus,
        "keyPoints": evidence,
        "verificationNotes": [
            "Kaynak bağlamdaki açık bulgular esas alındı.",
            "Eksik veya doğrulanması gereken noktalar nihai çıktıda işaretlenmeli.",
        ],
    }
    output = "\n".join(
        [
            "Analiz özeti:",
            summary,
            "",
            "Öne çıkan noktalar:",
            *[f"- {item}" for item in evidence],
            "",
            "Yazım odağı:",
            focus,
        ]
    ).strip()
    return {"text": output, "result": analysis, "artifacts": []}
