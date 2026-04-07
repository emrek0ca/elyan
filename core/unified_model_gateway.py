from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional

from config.elyan_config import elyan_config
from core.model_orchestrator import model_orchestrator
from core.multi_agent.specialists import get_specialist_registry
from core.security.contracts import contains_sensitive_data, redact_for_cloud
from utils.logger import get_logger

logger = get_logger("unified_model_gateway")


@dataclass(slots=True)
class UnifiedModelRequest:
    specialist_key: str = ""
    role: str = "inference"
    explicit_model: str = ""
    explicit_provider: str = ""
    prefer_local: Optional[bool] = None
    allow_cloud_fallback: bool = True
    cloud_allowed: Optional[bool] = None
    contains_sensitive_data: bool = False
    redaction_level: str = "auto"
    max_models: int = 4


@dataclass(slots=True)
class UnifiedModelCandidate:
    provider: str
    model: str
    reason: str
    model_config: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UnifiedModelResponse:
    text: str
    provider: str
    model: str
    transport: str
    security_path: str = "local_only"
    redactions_applied: list[str] = field(default_factory=list)
    candidate_chain: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class UnifiedModelGateway:
    """Local-first facade over the existing Elyan model orchestrator."""

    def __init__(self, *, orchestrator=None, specialist_registry=None) -> None:
        self.orchestrator = orchestrator or model_orchestrator
        self.specialists = specialist_registry or get_specialist_registry()

    @staticmethod
    def _record_security_event(event_name: str, payload: dict[str, Any]) -> None:
        try:
            from core.elyan_runtime import get_elyan_runtime
            from core.events.event_store import EventType

            event_type = getattr(EventType, event_name, None)
            if event_type is None:
                return
            get_elyan_runtime().record_event(
                event_type=event_type,
                aggregate_id=str(payload.get("provider") or payload.get("specialist_key") or "security"),
                aggregate_type="security",
                payload=dict(payload or {}),
            )
        except Exception:
            return

    def _transport(self) -> str:
        configured = str(self._transport_settings().get("transport") or "native").strip().lower()
        if configured == "litellm" and self._litellm_available():
            return "litellm"
        if configured == "litellm":
            logger.debug("LiteLLM transport unavailable, native fallback active")
        return "native"

    @staticmethod
    def _transport_settings() -> dict[str, Any]:
        return dict(elyan_config.get("operator.multi_llm", {}) or {})

    @staticmethod
    def _litellm_available() -> bool:
        try:
            import litellm  # noqa: F401

            return True
        except Exception:
            return False

    def describe(self) -> dict[str, Any]:
        settings = self._transport_settings()
        return {
            "transport_requested": str(settings.get("transport") or "native"),
            "transport": self._transport(),
            "litellm_available": self._litellm_available(),
            "local_first_default": bool(elyan_config.get("agent.model.local_first", True)),
            "native_fallback_on_transport_error": bool(settings.get("native_fallback_on_transport_error", True)),
            "timeout_seconds": float(settings.get("timeout_seconds", 45) or 45),
            "max_tokens": int(settings.get("max_tokens", 4096) or 4096),
            "local_only_default": bool(elyan_config.get("operator.local_first", True)),
            "cloud_redaction_default": bool(elyan_config.get("security.kvkk.redactCloudPrompts", True)),
            "specialists": sorted(list(self.specialists.get_nextgen_team().keys())),
        }

    def build_candidates(self, request: UnifiedModelRequest) -> list[UnifiedModelCandidate]:
        explicit_provider = str(request.explicit_provider or "").strip().lower()
        explicit_model = str(request.explicit_model or "").strip()
        if explicit_provider or explicit_model:
            resolved = self.orchestrator.resolve_model_hint(
                explicit_model or explicit_provider,
                role=request.role,
            )
            provider = str(resolved.get("provider") or resolved.get("type") or explicit_provider or "").strip().lower()
            model = str(resolved.get("model") or explicit_model or "").strip()
            if provider and model:
                return [
                    UnifiedModelCandidate(
                        provider=provider,
                        model=model,
                        reason="explicit_model_override",
                        model_config=dict(resolved),
                    )
                ]

        specialist = self.specialists.get(request.specialist_key)
        provider_chain = list(self.specialists.get_provider_chain(request.specialist_key))
        prefer_local = request.prefer_local
        if prefer_local is None:
            prefer_local = bool(getattr(specialist, "local_first", True))
        cloud_allowed = request.cloud_allowed
        if cloud_allowed is None:
            cloud_allowed = bool(getattr(specialist, "cloud_allowed", False))
        if not bool(prefer_local):
            provider_chain = [provider for provider in provider_chain if provider != "ollama"] + ["ollama"]
        if request.contains_sensitive_data and not bool(cloud_allowed):
            provider_chain = [provider for provider in provider_chain if provider == "ollama"] or ["ollama"]
        elif not bool(request.allow_cloud_fallback):
            provider_chain = [provider for provider in provider_chain if provider == "ollama"] or ["ollama"]

        ranked = self.orchestrator.rank_candidates(role=request.role)
        ordered: list[UnifiedModelCandidate] = []
        seen: set[str] = set()
        provider_rank = {provider: index for index, provider in enumerate(provider_chain)}
        decorated: list[tuple[tuple[int, int, str], dict[str, Any]]] = []
        for index, entry in enumerate(ranked):
            provider = str(entry.get("provider") or entry.get("type") or "").strip().lower()
            model = str(entry.get("model") or "").strip()
            if not provider or not model:
                continue
            order_key = provider_rank.get(provider, len(provider_chain) + index)
            decorated.append(((order_key, index, f"{provider}:{model}"), entry))
        decorated.sort(key=lambda item: item[0])

        for _, entry in decorated:
            provider = str(entry.get("provider") or entry.get("type") or "").strip().lower()
            model = str(entry.get("model") or "").strip()
            key = f"{provider}:{model}"
            if key in seen:
                continue
            seen.add(key)
            ordered.append(
                UnifiedModelCandidate(
                    provider=provider,
                    model=model,
                    reason=f"specialist:{request.specialist_key or 'default'}",
                    model_config=self.orchestrator.get_provider_config(provider, role=request.role, model=model),
                )
            )
            if len(ordered) >= max(1, int(request.max_models or 1)):
                break

        if not ordered:
            fallback = self.orchestrator.get_best_available(role=request.role)
            provider = str(fallback.get("provider") or fallback.get("type") or "").strip().lower()
            model = str(fallback.get("model") or "").strip()
            if provider and model:
                ordered.append(
                    UnifiedModelCandidate(
                        provider=provider,
                        model=model,
                        reason="orchestrator_fallback",
                        model_config=dict(fallback),
                    )
                )
        return ordered

    async def _call_native(
        self,
        llm_client: Any,
        candidate: UnifiedModelCandidate,
        *,
        prompt: str,
        system_prompt: str | None,
        role: str,
        user_id: str,
        temperature: float | None,
    ) -> str:
        return await llm_client.generate(
            prompt,
            system_prompt=system_prompt,
            role=role,
            user_id=user_id,
            temperature=temperature,
            model_config=dict(candidate.model_config),
            strict_model_config=True,
            disable_collaboration=True,
        )

    @staticmethod
    def _litellm_model_ref(provider: str, model: str) -> str:
        provider_name = str(provider).strip().lower()
        model_name = str(model).strip()
        if not provider_name:
            return model_name
        if model_name.lower().startswith(f"{provider_name}/"):
            return model_name
        return f"{provider_name}/{model_name}"

    @staticmethod
    def _extract_litellm_content(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                    continue
                if isinstance(item, dict):
                    text = item.get("text")
                    if text:
                        parts.append(str(text))
            return "\n".join(part for part in parts if part).strip()
        return str(content or "").strip()

    async def _call_litellm(
        self,
        candidate: UnifiedModelCandidate,
        *,
        prompt: str,
        system_prompt: str | None,
        temperature: float | None,
    ) -> str:
        import litellm

        settings = self._transport_settings()
        messages: list[dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": str(system_prompt)})
        messages.append({"role": "user", "content": str(prompt)})

        try:
            litellm.drop_params = True
        except Exception:
            pass

        completion_kwargs: dict[str, Any] = {
            "model": self._litellm_model_ref(candidate.provider, candidate.model),
            "messages": messages,
            "temperature": temperature if temperature is not None else float(settings.get("temperature", 0.2) or 0.2),
            "timeout": float(settings.get("timeout_seconds", 45) or 45),
        }
        api_key = candidate.model_config.get("apiKey") or candidate.model_config.get("api_key")
        api_base = candidate.model_config.get("endpoint") or candidate.model_config.get("api_base")
        max_tokens = candidate.model_config.get("max_tokens") or candidate.model_config.get("maxTokens") or settings.get("max_tokens")
        if api_key and str(candidate.provider).strip().lower() != "ollama":
            completion_kwargs["api_key"] = api_key
        if api_base:
            completion_kwargs["api_base"] = api_base
        if max_tokens:
            completion_kwargs["max_tokens"] = int(max_tokens)

        completion = await litellm.acompletion(**completion_kwargs)
        choices = getattr(completion, "choices", None)
        if choices is None and isinstance(completion, dict):
            choices = completion.get("choices")
        choices = list(choices or [])
        if not choices:
            raise RuntimeError("litellm_empty_choices")
        first_choice = choices[0]
        message = getattr(first_choice, "message", None)
        if message is None and isinstance(first_choice, dict):
            message = first_choice.get("message") or {}
        content = getattr(message, "content", None)
        if content is None and isinstance(message, dict):
            content = message.get("content") or ""
        text = self._extract_litellm_content(content)
        if not text:
            raise RuntimeError("litellm_empty_content")
        return text

    async def execute(
        self,
        llm_client: Any,
        prompt: str,
        *,
        request: UnifiedModelRequest,
        system_prompt: str | None = None,
        user_id: str = "local",
        temperature: float | None = None,
    ) -> UnifiedModelResponse:
        transport = self._transport()
        settings = self._transport_settings()
        specialist = self.specialists.get(request.specialist_key)
        contains_sensitive = bool(request.contains_sensitive_data or contains_sensitive_data(prompt) or contains_sensitive_data(system_prompt or ""))
        request.contains_sensitive_data = contains_sensitive
        if request.cloud_allowed is None:
            request.cloud_allowed = bool(getattr(specialist, "cloud_allowed", False))
        candidates = self.build_candidates(request)
        errors: list[str] = []
        chain = [f"{candidate.provider}:{candidate.model}" for candidate in candidates]

        for candidate in candidates:
            try:
                prompt_for_candidate = prompt
                system_prompt_for_candidate = system_prompt
                redactions_applied: list[str] = []
                is_cloud_candidate = str(candidate.provider).strip().lower() != "ollama"
                if contains_sensitive and is_cloud_candidate:
                    if not bool(request.cloud_allowed):
                        self._record_security_event(
                            "CLOUD_ESCALATION_DENIED",
                            {"provider": candidate.provider, "model": candidate.model, "specialist_key": request.specialist_key},
                        )
                        errors.append(f"{candidate.provider}:{candidate.model}:cloud_denied_for_sensitive_context")
                        continue
                    if str(request.redaction_level or "auto").strip().lower() != "none":
                        prompt_for_candidate, prompt_redactions = redact_for_cloud(prompt)
                        redactions_applied.extend(prompt_redactions)
                        if system_prompt:
                            system_prompt_for_candidate, system_redactions = redact_for_cloud(system_prompt)
                            redactions_applied.extend(system_redactions)
                        if redactions_applied:
                            self._record_security_event(
                                "SECRET_REDACTED",
                                {
                                    "provider": candidate.provider,
                                    "model": candidate.model,
                                    "specialist_key": request.specialist_key,
                                    "redactions": list(redactions_applied),
                                },
                            )
                    self._record_security_event(
                        "CLOUD_ESCALATION_APPROVED",
                        {"provider": candidate.provider, "model": candidate.model, "specialist_key": request.specialist_key},
                    )
                if transport == "litellm":
                    text = await self._call_litellm(
                        candidate,
                        prompt=str(prompt_for_candidate),
                        system_prompt=str(system_prompt_for_candidate) if system_prompt_for_candidate is not None else None,
                        temperature=temperature,
                    )
                else:
                    text = await self._call_native(
                        llm_client,
                        candidate,
                        prompt=str(prompt_for_candidate),
                        system_prompt=str(system_prompt_for_candidate) if system_prompt_for_candidate is not None else None,
                        role=request.role,
                        user_id=user_id,
                        temperature=temperature,
                    )
                return UnifiedModelResponse(
                    text=str(text),
                    provider=candidate.provider,
                    model=candidate.model,
                    transport=transport,
                    security_path="redacted_cloud" if redactions_applied else ("cloud" if is_cloud_candidate else "local_only"),
                    redactions_applied=redactions_applied,
                    candidate_chain=chain,
                    errors=errors,
                )
            except Exception as exc:
                errors.append(f"{candidate.provider}:{candidate.model}:{exc}")
                logger.warning(f"Unified model candidate failed: {candidate.provider}:{candidate.model} -> {exc}")
                if transport == "litellm" and bool(settings.get("native_fallback_on_transport_error", True)):
                    try:
                        text = await self._call_native(
                            llm_client,
                            candidate,
                            prompt=prompt,
                            system_prompt=system_prompt,
                            role=request.role,
                            user_id=user_id,
                            temperature=temperature,
                        )
                        return UnifiedModelResponse(
                            text=str(text),
                            provider=candidate.provider,
                            model=candidate.model,
                            transport="native_fallback",
                            security_path="local_only" if str(candidate.provider).strip().lower() == "ollama" else "cloud",
                            candidate_chain=chain,
                            errors=errors,
                        )
                    except Exception as native_exc:
                        errors.append(f"{candidate.provider}:{candidate.model}:native_fallback:{native_exc}")
                        logger.warning(
                            f"Unified model native fallback failed: {candidate.provider}:{candidate.model} -> {native_exc}"
                        )

        return UnifiedModelResponse(
            text="Hata: Uygun model zinciri yanıt üretemedi.",
            provider="",
            model="",
            transport=transport,
            security_path="local_only" if not bool(request.cloud_allowed) else "degraded",
            candidate_chain=chain,
            errors=errors,
        )

    async def generate_text(
        self,
        llm_client: Any,
        prompt: str,
        *,
        specialist_key: str = "",
        role: str = "inference",
        system_prompt: str | None = None,
        user_id: str = "local",
        temperature: float | None = None,
        explicit_model: str = "",
        explicit_provider: str = "",
        allow_cloud_fallback: bool = True,
    ) -> str:
        response = await self.execute(
            llm_client,
            prompt,
            request=UnifiedModelRequest(
                specialist_key=specialist_key,
                role=role,
                explicit_model=explicit_model,
                explicit_provider=explicit_provider,
                allow_cloud_fallback=allow_cloud_fallback,
            ),
            system_prompt=system_prompt,
            user_id=user_id,
            temperature=temperature,
        )
        return response.text


__all__ = [
    "UnifiedModelCandidate",
    "UnifiedModelGateway",
    "UnifiedModelRequest",
    "UnifiedModelResponse",
]
