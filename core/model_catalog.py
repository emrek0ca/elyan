from __future__ import annotations


DEFAULT_PROVIDER_MODELS = {
    "openai": "gpt-4o",
    "openrouter": "openai/gpt-4o-mini",
    "anthropic": "claude-3-5-sonnet-latest",
    "google": "gemini-2.0-flash",
    "groq": "llama-3.3-70b-versatile",
    "ollama": "llama3.1:8b",
    "deepseek": "deepseek-chat",
    "mistral": "mistral-large-latest",
    "together": "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "cohere": "command-r-plus",
    "perplexity": "sonar-pro",
    "xai": "grok-2",
}

QWEN_LIGHT_OLLAMA_MODEL = "qwen3:0.6b"
QWEN_LIGHT_ALIASES = {
    "qwen3.5-0.8b": QWEN_LIGHT_OLLAMA_MODEL,
    "qwen3.5:0.8b": QWEN_LIGHT_OLLAMA_MODEL,
    "qwen-3.5-0.8b": QWEN_LIGHT_OLLAMA_MODEL,
    "qwen3-0.8b": QWEN_LIGHT_OLLAMA_MODEL,
    "qwen3:0.8b": QWEN_LIGHT_OLLAMA_MODEL,
    "qwen3.5-0.8": QWEN_LIGHT_OLLAMA_MODEL,
}


def default_model_for_provider(provider: str) -> str:
    return DEFAULT_PROVIDER_MODELS.get(str(provider or "").strip().lower(), "gpt-4o")


def normalize_model_name(provider: str, model: str | None) -> str:
    raw = str(model or "").strip()
    if not raw:
        return default_model_for_provider(provider)
    if str(provider or "").strip().lower() != "ollama":
        return raw
    return QWEN_LIGHT_ALIASES.get(raw.lower(), raw)


def is_qwen_light_alias(model: str | None) -> bool:
    raw = str(model or "").strip().lower()
    return raw in QWEN_LIGHT_ALIASES or raw == QWEN_LIGHT_OLLAMA_MODEL


__all__ = [
    "DEFAULT_PROVIDER_MODELS",
    "QWEN_LIGHT_ALIASES",
    "QWEN_LIGHT_OLLAMA_MODEL",
    "default_model_for_provider",
    "is_qwen_light_alias",
    "normalize_model_name",
]
