from __future__ import annotations

import json
import shutil
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from core.storage_paths import resolve_elyan_data_dir
from utils.logger import get_logger

logger = get_logger("personalization.adapters")


def _slug(value: Any, *, default: str = "unknown", max_len: int = 64) -> str:
    text = "".join(ch.lower() if str(ch).isalnum() else "-" for ch in str(value or "").strip())
    text = "-".join(part for part in text.split("-") if part)
    text = text[:max_len].strip("-")
    return text or default


def _now() -> float:
    return time.time()


class AdapterArtifactStore:
    def __init__(self, storage_root: Path | None = None):
        self.storage_root = Path(storage_root or (resolve_elyan_data_dir() / "personalization" / "adapters")).expanduser()
        self.storage_root.mkdir(parents=True, exist_ok=True)

    def _user_root(self, user_id: str) -> Path:
        root = self.storage_root / _slug(user_id, default="local")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _base_root(self, user_id: str, base_model_id: str) -> Path:
        root = self._user_root(user_id) / _slug(base_model_id, default="base-model")
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _versions_root(self, user_id: str, base_model_id: str) -> Path:
        root = self._base_root(user_id, base_model_id) / "versions"
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _active_pointer(self, user_id: str, base_model_id: str) -> Path:
        return self._base_root(user_id, base_model_id) / "active.json"

    def create_candidate_adapter(
        self,
        user_id: str,
        base_model_id: str,
        *,
        strategy: str,
        metrics: dict[str, Any] | None = None,
        training_step: int = 0,
        quality_metrics: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        version = f"v{int(_now())}_{uuid.uuid4().hex[:8]}"
        version_root = self._versions_root(user_id, base_model_id) / version
        version_root.mkdir(parents=True, exist_ok=True)

        adapter_file = version_root / "adapter_model.safetensors"
        adapter_file.write_bytes(b"ELYAN-PERSONAL-ADAPTER-STUB\n")
        (version_root / "adapter_config.json").write_text(
            json.dumps(
                {
                    "format": "peft_lora_stub",
                    "strategy": str(strategy or "hybrid"),
                    "base_model_id": str(base_model_id or ""),
                    "created_at": _now(),
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        manifest = {
            "user_id": str(user_id or "local"),
            "base_model_id": str(base_model_id or ""),
            "adapter_version": version,
            "training_step": int(training_step or 0),
            "last_trained_at": _now(),
            "quality_metrics": dict(quality_metrics or {}),
            "metrics": dict(metrics or {}),
            "status": "candidate",
            "strategy": str(strategy or "hybrid"),
            "adapter_path": str(adapter_file),
            "metadata": dict(metadata or {}),
        }
        (version_root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        return manifest

    def list_versions(self, user_id: str, base_model_id: str) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        versions_root = self._versions_root(user_id, base_model_id)
        for item in sorted(versions_root.iterdir(), reverse=True) if versions_root.exists() else []:
            manifest_path = item / "manifest.json"
            if not manifest_path.exists():
                continue
            try:
                out.append(json.loads(manifest_path.read_text(encoding="utf-8")))
            except Exception as exc:
                logger.debug(f"adapter manifest load skipped: {exc}")
        return out

    def promote_version(self, user_id: str, base_model_id: str, adapter_version: str) -> dict[str, Any] | None:
        for item in self.list_versions(user_id, base_model_id):
            if str(item.get("adapter_version") or "") != str(adapter_version or ""):
                continue
            item["status"] = "ready"
            item["promoted_at"] = _now()
            manifest_path = Path(str(item.get("adapter_path") or "")).parent / "manifest.json"
            manifest_path.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
            self._active_pointer(user_id, base_model_id).write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
            return item
        return None

    def resolve_active_metadata(self, user_id: str, base_model_id: str) -> dict[str, Any] | None:
        pointer = self._active_pointer(user_id, base_model_id)
        if not pointer.exists():
            return None
        try:
            return json.loads(pointer.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.debug(f"adapter active pointer load skipped: {exc}")
            return None

    def count_active_adapters(self) -> int:
        count = 0
        for user_root in self.storage_root.iterdir() if self.storage_root.exists() else []:
            if not user_root.is_dir():
                continue
            for base_root in user_root.iterdir():
                if (base_root / "active.json").exists():
                    count += 1
        return count

    def delete_user(self, user_id: str) -> dict[str, Any]:
        user_root = self.storage_root / _slug(user_id, default="local")
        deleted_versions = 0
        if user_root.exists():
            for path in user_root.rglob("manifest.json"):
                deleted_versions += 1
            shutil.rmtree(user_root, ignore_errors=True)
        return {"user_id": str(user_id or "local"), "deleted_versions": deleted_versions}


class AdapterRegistry:
    _LOCAL_PROVIDERS = {"ollama", "local", "transformers", "huggingface", "hf", "vllm"}

    def __init__(self, artifact_store: AdapterArtifactStore, *, max_hot: int = 32):
        self.artifact_store = artifact_store
        self.max_hot = max(1, int(max_hot or 32))
        self._hot_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()

    @classmethod
    def is_local_provider(cls, provider: str) -> bool:
        return str(provider or "").strip().lower() in cls._LOCAL_PROVIDERS

    def _cache_key(self, user_id: str, base_model_id: str) -> str:
        return f"{user_id}::{base_model_id}"

    def _mark_hot(self, key: str, binding: dict[str, Any]) -> None:
        if key in self._hot_cache:
            self._hot_cache.pop(key, None)
        self._hot_cache[key] = dict(binding)
        while len(self._hot_cache) > self.max_hot:
            self._hot_cache.popitem(last=False)

    def evict_user(self, user_id: str) -> None:
        prefix = f"{user_id}::"
        for key in list(self._hot_cache.keys()):
            if key.startswith(prefix):
                self._hot_cache.pop(key, None)

    def resolve_binding(self, user_id: str, base_model_id: str, provider: str, *, allow_adapter: bool = True) -> dict[str, Any]:
        binding = {
            "user_id": str(user_id or "local"),
            "base_model_id": str(base_model_id or ""),
            "provider": str(provider or ""),
            "state": "none",
            "adapter_version": "",
            "adapter_path": "",
            "status": "memory_only",
            "reason": "",
            "is_local_provider": self.is_local_provider(provider),
        }
        if not allow_adapter:
            binding["reason"] = "adapter_not_allowed"
            return binding
        if not binding["is_local_provider"]:
            binding["reason"] = "memory_only_provider"
            return binding

        active = self.artifact_store.resolve_active_metadata(str(user_id or "local"), str(base_model_id or ""))
        if not isinstance(active, dict):
            binding["reason"] = "no_adapter"
            binding["status"] = "memory_only"
            return binding

        adapter_path = Path(str(active.get("adapter_path") or "")).expanduser()
        if not adapter_path.exists():
            binding["reason"] = "missing_artifact"
            binding["status"] = "fallback_base_model"
            return binding

        key = self._cache_key(binding["user_id"], binding["base_model_id"])
        binding["adapter_version"] = str(active.get("adapter_version") or "")
        binding["adapter_path"] = str(adapter_path)
        binding["status"] = str(active.get("status") or "ready")
        binding["state"] = "hot" if key in self._hot_cache else "warm"
        binding["quality_metrics"] = dict(active.get("quality_metrics") or {})
        self._mark_hot(key, binding)
        return binding

    def stats(self) -> dict[str, Any]:
        return {
            "hot_cache_size": len(self._hot_cache),
            "max_hot": self.max_hot,
            "active_adapters": self.artifact_store.count_active_adapters(),
        }
