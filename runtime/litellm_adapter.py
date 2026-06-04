from __future__ import annotations

from typing import Any

try:
    from litellm import completion as _litellm_completion
except Exception:  # pragma: no cover - optional dependency
    _litellm_completion = None


def available() -> bool:
    return _litellm_completion is not None


def _resolved_model(provider: str, model: str) -> str:
    cleaned = str(model or "").strip()
    if not cleaned:
        return ""
    if "/" in cleaned:
        return cleaned
    prefixes = {
        "openai": "openai",
        "anthropic": "anthropic",
        "gemini": "gemini",
        "groq": "groq",
    }
    prefix = prefixes.get(provider, "")
    return f"{prefix}/{cleaned}" if prefix else cleaned


def _message_content(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, dict) and str(item.get("type", "") or "") == "text":
                parts.append(str(item.get("text", "") or ""))
            elif isinstance(item, str):
                parts.append(item)
        return "".join(parts).strip()
    return str(value or "").strip()


def chat_completion(
    *,
    provider: str,
    model: str,
    messages: list[dict[str, str]],
    api_key: str = "",
    base_url: str = "",
    temperature: float = 0.2,
    timeout: int = 60,
) -> dict[str, Any]:
    if _litellm_completion is None:
        return {"ok": False, "error": "litellm_unavailable"}
    resolved_model = _resolved_model(provider, model)
    if not resolved_model:
        return {"ok": False, "error": f"{provider}_model_missing"}

    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "messages": messages,
        "temperature": temperature,
        "timeout": timeout,
    }
    if api_key:
        kwargs["api_key"] = api_key
    if base_url:
        kwargs["base_url"] = base_url

    try:
        response = _litellm_completion(**kwargs)
    except Exception as exc:  # pragma: no cover - network/provider surface
        return {"ok": False, "error": str(exc) or "litellm_chat_failed"}

    choices = getattr(response, "choices", None)
    if not choices and isinstance(response, dict):
        choices = response.get("choices")
    content = ""
    if isinstance(choices, list) and choices:
        first = choices[0]
        if isinstance(first, dict):
            message = first.get("message", {})
            if isinstance(message, dict):
                content = _message_content(message.get("content"))
        else:
            message = getattr(first, "message", None)
            if message is not None:
                raw_content = getattr(message, "content", "")
                content = _message_content(raw_content)

    return {
        "ok": True,
        "content": content,
        "provider": provider,
        "model": resolved_model,
        "router": "litellm",
    }
