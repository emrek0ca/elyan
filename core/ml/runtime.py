from __future__ import annotations

import importlib.util
import time
from typing import Any

from config.elyan_config import elyan_config
from core.model_manager import get_model_manager

from .types import ModelCapabilitySnapshot


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


class ModelRuntime:
    _instance: "ModelRuntime | None" = None

    def __new__(cls) -> "ModelRuntime":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return
        self._initialized = True

    def _module_matrix(self) -> dict[str, bool]:
        return {
            "torch": _module_available("torch"),
            "sentence_transformers": _module_available("sentence_transformers"),
            "transformers": _module_available("transformers"),
            "peft": _module_available("peft"),
            "trl": _module_available("trl"),
            "faiss": _module_available("faiss"),
            "lancedb": _module_available("lancedb"),
            "bitsandbytes": _module_available("bitsandbytes"),
        }

    def _dependency_snapshot(self, modules: dict[str, bool]) -> dict[str, bool]:
        return {
            "torch": bool(modules.get("torch")),
            "sentence_transformers": bool(modules.get("sentence_transformers")),
            "transformers": bool(modules.get("transformers")),
            "peft": bool(modules.get("peft")),
            "trl": bool(modules.get("trl")),
            "faiss": bool(modules.get("faiss")),
            "lancedb": bool(modules.get("lancedb")),
            "bitsandbytes": bool(modules.get("bitsandbytes")),
        }

    def _config(self) -> dict[str, Any]:
        return dict(elyan_config.get("ml", {}) or {})

    def _base_environment(self) -> dict[str, Any]:
        snapshot = get_model_manager().snapshot()
        environment = dict(snapshot.get("environment") or {})
        environment["modules"] = self._module_matrix()
        return environment

    def _embedding_capability(self, environment: dict[str, Any]) -> ModelCapabilitySnapshot:
        backend = str(environment.get("backend") or "local_hashing")
        device = str(environment.get("device") or "cpu_fallback")
        fallback = backend in {"local_hashing", "cpu_fallback"}
        reason = ""
        if fallback:
            reason = "deterministic_fallback"
        return ModelCapabilitySnapshot(
            kind="embedding",
            available=True,
            backend=backend,
            device=device,
            fallback=fallback,
            reason=reason,
            metadata={
                "sentence_transformers_available": bool(environment.get("sentence_transformers_available")),
                "torch_available": bool(environment.get("torch_available")),
                "dependency_status": {
                    "torch": bool(environment.get("torch_available")),
                    "sentence_transformers": bool(environment.get("sentence_transformers_available")),
                },
                "fallback_mode": "deterministic" if fallback else "native",
            },
        )

    def _capability(self, kind: str) -> ModelCapabilitySnapshot:
        environment = self._base_environment()
        modules = environment.get("modules", {}) if isinstance(environment.get("modules"), dict) else {}
        device = str(environment.get("device") or "cpu_fallback")
        dependency_status = self._dependency_snapshot(modules)
        if kind == "embedding":
            return self._embedding_capability(environment)

        if kind == "adapter_runtime":
            available = bool(modules.get("torch")) and bool(modules.get("peft"))
            return ModelCapabilitySnapshot(
                kind=kind,
                available=available,
                backend="peft_lora" if available else "heuristic_fallback",
                device=device,
                fallback=not available,
                reason="" if available else "missing_torch_or_peft",
                metadata={
                    "requires": ["torch", "peft"],
                    "dependency_status": {key: dependency_status[key] for key in ("torch", "peft")},
                    "fallback_mode": "heuristic" if not available else "native",
                },
            )

        if kind == "reward_model":
            available = bool(modules.get("transformers")) and bool(modules.get("trl"))
            return ModelCapabilitySnapshot(
                kind=kind,
                available=available,
                backend="trl_reward_model" if available else "heuristic_scorer",
                device=device,
                fallback=not available,
                reason="" if available else "missing_transformers_or_trl",
                metadata={
                    "requires": ["transformers", "trl"],
                    "dependency_status": {key: dependency_status[key] for key in ("transformers", "trl")},
                    "fallback_mode": "heuristic" if not available else "native",
                },
            )

        if kind == "reranker":
            available = bool(modules.get("sentence_transformers")) or bool(modules.get("transformers"))
            return ModelCapabilitySnapshot(
                kind=kind,
                available=available,
                backend="semantic_reranker" if available else "lexical_reranker",
                device=device,
                fallback=not available,
                reason="" if available else "lexical_only",
                metadata={
                    "dependency_status": {
                        "sentence_transformers": bool(modules.get("sentence_transformers")),
                        "transformers": bool(modules.get("transformers")),
                    },
                    "fallback_mode": "lexical" if not available else "semantic",
                },
            )

        if kind == "intent_encoder":
            available = bool(modules.get("transformers"))
            return ModelCapabilitySnapshot(
                kind=kind,
                available=available,
                backend="distilled_classifier" if available else "heuristic_router",
                device=device,
                fallback=not available,
                reason="" if available else "heuristic_only",
                metadata={
                    "dependency_status": {"transformers": bool(modules.get("transformers"))},
                    "fallback_mode": "heuristic" if not available else "native",
                },
            )

        return ModelCapabilitySnapshot(
            kind=kind,
            available=False,
            backend="unknown",
            device=device,
            fallback=True,
            reason="unsupported_capability",
        )

    def get_capability(self, kind: str) -> dict[str, Any]:
        return self._capability(str(kind or "").strip()).to_dict()

    def snapshot(self) -> dict[str, Any]:
        ml_cfg = self._config()
        environment = self._base_environment()
        capabilities = {
            kind: self.get_capability(kind)
            for kind in ("embedding", "intent_encoder", "reranker", "reward_model", "adapter_runtime")
        }
        return {
            "enabled": bool(ml_cfg.get("enabled", True)),
            "execution_mode": str(ml_cfg.get("execution_mode") or "local_first"),
            "device_policy": str(ml_cfg.get("device_policy") or "cpu"),
            "backends": dict(ml_cfg.get("backends") or {}),
            "environment": environment,
            "capabilities": capabilities,
            "dependencies": self._dependency_snapshot(environment["modules"] if isinstance(environment.get("modules"), dict) else {}),
            "updated_at": time.time(),
        }


def get_model_runtime() -> ModelRuntime:
    return ModelRuntime()
