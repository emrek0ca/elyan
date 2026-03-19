"""
Phase 0 model manager for Elyan.

Goals:
- Detect the local ML environment
- Lazily load and cache the shared embedding model
- Fall back to a deterministic local embedder when torch / sentence-transformers
  are unavailable
- Provide unload, snapshot, and benchmark helpers for startup validation

This module is intentionally lightweight: it does not require PyTorch to be
installed in order to operate. When torch is available it will use it; when it
is not, the fallback embedder keeps semantic-search paths functional.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib.util
import inspect
import io
import os
import platform
import re
import statistics
import time
import warnings
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

import numpy as np
import psutil

from utils.logger import get_logger

logger = get_logger("model_manager")

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_SHARED_MODEL_NAME = "shared_embedder"
FALLBACK_EMBEDDING_DIMENSION = 384
PHASE0_LOAD_TARGET_SECONDS = 3.0
PHASE0_IDLE_MEMORY_TARGET_MB = 2048.0


@dataclass(slots=True)
class ModelSpec:
    """Declarative model definition used by the manager."""

    name: str
    model_name: str | None = None
    kind: str = "embedding"
    device: str | None = None
    cacheable: bool = True
    fallback_allowed: bool = True
    loader: Callable[[], Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ModelEnvironment:
    """Snapshot of the local model environment."""

    python_version: str
    platform: str
    torch_available: bool
    torch_version: str | None
    sentence_transformers_available: bool
    cuda_available: bool
    mps_available: bool
    device: str
    backend: str
    process_rss_mb: float
    available_memory_mb: float
    total_memory_mb: float


@dataclass(slots=True)
class ModelRecord:
    """Cached model entry."""

    name: str
    model: Any
    spec: ModelSpec
    backend: str
    device: str
    load_seconds: float
    vector_dimension: int | None
    loaded_at: float
    last_used_at: float
    cache_hit: bool = False


@dataclass(slots=True)
class ModelBenchmark:
    """Benchmark result used by phase-0 validation."""

    model_name: str
    backend: str
    device: str
    load_seconds: float
    encode_seconds: float
    memory_before_mb: float
    memory_after_mb: float
    process_rss_mb: float
    available_memory_mb: float
    vector_dimension: int
    sample_count: int
    cache_hit: bool
    passed: bool
    thresholds: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LocalHashingEmbedder:
    """
    Deterministic local fallback embedder.

    The goal is to preserve semantic-search functionality when external ML
    packages are unavailable. It is intentionally simple and stable.
    """

    def __init__(self, dimension: int = FALLBACK_EMBEDDING_DIMENSION):
        self.dimension = int(dimension)
        self.model_name = "local-hashing-embedder"
        self.backend = "local_hashing"
        self.device = "cpu"

    def get_sentence_embedding_dimension(self) -> int:
        return self.dimension

    def to(self, *_args: Any, **_kwargs: Any) -> "LocalHashingEmbedder":
        return self

    def eval(self) -> "LocalHashingEmbedder":
        return self

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        return self.encode(*args, **kwargs)

    def encode(
        self,
        sentences: str | list[str] | tuple[str, ...],
        *,
        convert_to_numpy: bool = True,
        normalize_embeddings: bool = False,
        batch_size: int | None = None,
        **_kwargs: Any,
    ) -> np.ndarray | list[list[float]] | list[float]:
        if isinstance(sentences, str):
            items = [sentences]
            single = True
        else:
            items = list(sentences)
            single = False

        vectors = np.zeros((len(items), self.dimension), dtype=np.float32)
        for row, text in enumerate(items):
            vectors[row] = self._encode_one(text)
            if normalize_embeddings:
                norm = float(np.linalg.norm(vectors[row]))
                if norm > 0:
                    vectors[row] /= norm

        if single:
            result: np.ndarray | list[list[float]] | list[float] = vectors[0]
        else:
            result = vectors

        if convert_to_numpy:
            return result
        if isinstance(result, np.ndarray):
            return result.tolist()
        return result

    def _encode_one(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dimension, dtype=np.float32)
        tokens = re.findall(r"[\w']+", str(text).lower(), flags=re.UNICODE)
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=16).digest()
            index = int.from_bytes(digest[:4], "little") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            weight = 1.0 + min(len(token), 12) / 12.0
            vector[index] += sign * weight

            # Add a tiny character-shape signal to improve collisions.
            for char in token[:3]:
                digest = hashlib.blake2b(char.encode("utf-8"), digest_size=8).digest()
                index = int.from_bytes(digest[:4], "little") % self.dimension
                vector[index] += 0.15

        return vector


class ModelManager:
    """Singleton model manager with lazy load / cache / unload support."""

    _instance: "ModelManager | None" = None

    def __new__(cls) -> "ModelManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        if getattr(self, "_initialized", False):
            return

        self._initialized = True
        self._load_lock = asyncio.Lock()
        self._registry: dict[str, ModelSpec] = {}
        self._records: dict[str, ModelRecord] = {}
        self._environment = self._detect_environment()
        self._register_default_spec()

    @staticmethod
    def _normalize_name(name: str | None) -> str:
        return str(name or DEFAULT_SHARED_MODEL_NAME).strip() or DEFAULT_SHARED_MODEL_NAME

    @staticmethod
    def _process_memory_mb() -> float:
        try:
            return psutil.Process(os.getpid()).memory_info().rss / (1024 * 1024)
        except Exception:
            return 0.0

    @staticmethod
    def _system_memory_snapshot() -> tuple[float, float]:
        try:
            vm = psutil.virtual_memory()
            return vm.available / (1024 * 1024), vm.total / (1024 * 1024)
        except Exception:
            return 0.0, 0.0

    @staticmethod
    def _module_available(module_name: str) -> bool:
        try:
            return importlib.util.find_spec(module_name) is not None
        except Exception:
            return False

    def _detect_environment(self) -> ModelEnvironment:
        torch_available = self._module_available("torch")
        st_available = self._module_available("sentence_transformers")
        cuda_available = False
        mps_available = False
        torch_version = None
        device = "cpu_fallback"
        backend = "local_hashing"

        if torch_available:
            try:
                import torch  # type: ignore

                torch_version = getattr(torch, "__version__", None)
                cuda_available = bool(getattr(torch.cuda, "is_available", lambda: False)())
                mps_backend = getattr(getattr(torch, "backends", None), "mps", None)
                mps_available = bool(getattr(mps_backend, "is_available", lambda: False)())
                if cuda_available:
                    device = "cuda"
                elif mps_available:
                    device = "mps"
                else:
                    device = "cpu"
                backend = "torch"
            except Exception as exc:
                logger.warning("Torch detected but environment probe failed: %s", exc)
                torch_available = False
                device = "cpu_fallback"
                backend = "local_hashing"

        available_memory_mb, total_memory_mb = self._system_memory_snapshot()
        environment = ModelEnvironment(
            python_version=platform.python_version(),
            platform=platform.platform(),
            torch_available=torch_available,
            torch_version=torch_version,
            sentence_transformers_available=st_available,
            cuda_available=cuda_available,
            mps_available=mps_available,
            device=device,
            backend=backend,
            process_rss_mb=self._process_memory_mb(),
            available_memory_mb=available_memory_mb,
            total_memory_mb=total_memory_mb,
        )
        return environment

    def _register_default_spec(self) -> None:
        if DEFAULT_SHARED_MODEL_NAME not in self._registry:
            self._registry[DEFAULT_SHARED_MODEL_NAME] = ModelSpec(
                name=DEFAULT_SHARED_MODEL_NAME,
                model_name=DEFAULT_EMBEDDING_MODEL,
                kind="embedding",
                fallback_allowed=True,
                metadata={"purpose": "shared embeddings"},
            )

    def register_model(
        self,
        name: str,
        loader: Callable[[], Any] | None = None,
        spec: ModelSpec | None = None,
    ) -> ModelSpec:
        model_name = self._normalize_name(name)
        if spec is None:
            spec = ModelSpec(name=model_name, loader=loader)
        else:
            if loader is not None:
                spec.loader = loader
            spec.name = model_name
        self._registry[model_name] = spec
        logger.debug("Registered model spec: %s", model_name)
        return spec

    def get_spec(self, name: str | None = None) -> ModelSpec | None:
        return self._registry.get(self._normalize_name(name))

    async def get_model(self, name: str | None = None, *, force_reload: bool = False) -> Any:
        model_name = self._normalize_name(name)
        cached = self._records.get(model_name)
        if cached is not None and not force_reload:
            cached.last_used_at = time.time()
            cached.cache_hit = True
            return cached.model

        async with self._load_lock:
            cached = self._records.get(model_name)
            if cached is not None and not force_reload:
                cached.last_used_at = time.time()
                cached.cache_hit = True
                return cached.model

            spec = self._registry.get(model_name)
            if spec is None:
                if model_name == DEFAULT_SHARED_MODEL_NAME:
                    self._register_default_spec()
                    spec = self._registry[DEFAULT_SHARED_MODEL_NAME]
                else:
                    raise KeyError(f"Unknown model spec: {model_name}")

            model, backend, device, load_seconds, vector_dimension = await self._load_spec(spec)
            record = ModelRecord(
                name=model_name,
                model=model,
                spec=spec,
                backend=backend,
                device=device,
                load_seconds=load_seconds,
                vector_dimension=vector_dimension,
                loaded_at=time.time(),
                last_used_at=time.time(),
                cache_hit=False,
            )
            if spec.cacheable:
                self._records[model_name] = record
            return model

    async def get_embedding_model(self, name: str | None = None, *, force_reload: bool = False) -> Any:
        return await self.get_model(name or DEFAULT_SHARED_MODEL_NAME, force_reload=force_reload)

    async def _load_spec(self, spec: ModelSpec) -> tuple[Any, str, str, float, int | None]:
        started = time.perf_counter()
        model = await self._resolve_model(spec)
        load_seconds = time.perf_counter() - started
        backend = self._infer_backend(model, spec)
        device = self._infer_device(model, spec)
        vector_dimension = self._infer_dimension(model)
        logger.info(
            "Loaded model spec %s via backend=%s device=%s load=%.3fs dim=%s",
            spec.name,
            backend,
            device,
            load_seconds,
            vector_dimension if vector_dimension is not None else "?",
        )
        return model, backend, device, load_seconds, vector_dimension

    async def _resolve_model(self, spec: ModelSpec) -> Any:
        if spec.loader is not None:
            return await self._invoke_loader(spec.loader)

        if spec.kind == "embedding" and self._environment.torch_available and self._environment.sentence_transformers_available:
            try:
                return await self._load_sentence_transformer(spec)
            except Exception as exc:
                if not spec.fallback_allowed:
                    raise
                logger.warning(
                    "Falling back to local hashing embedder after SentenceTransformer load failure for %s: %s",
                    spec.name,
                    exc,
                )

        if spec.kind == "embedding":
            return LocalHashingEmbedder()

        raise ValueError(f"Unsupported model kind: {spec.kind}")

    async def _invoke_loader(self, loader: Callable[[], Any]) -> Any:
        if inspect.iscoroutinefunction(loader):
            return await loader()

        result = await asyncio.to_thread(loader)
        if inspect.isawaitable(result):
            result = await result  # type: ignore[assignment]
        return result

    async def _load_sentence_transformer(self, spec: ModelSpec) -> Any:
        model_name = spec.model_name or DEFAULT_EMBEDDING_MODEL
        device = spec.device or self._environment.device or "cpu"

        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
        warnings.filterwarnings(
            "ignore",
            message=".*unauthenticated requests to the HF Hub.*",
        )

        from sentence_transformers import SentenceTransformer  # type: ignore

        try:
            from transformers.utils import logging as hf_logging  # type: ignore

            hf_logging.set_verbosity_error()
        except Exception:
            pass

        logger.info("Loading SentenceTransformer model %s on %s", model_name, device)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return SentenceTransformer(model_name, device=device)

    def unload_model(self, name: str | None = None) -> None:
        if name is None:
            self._records.clear()
            return

        model_name = self._normalize_name(name)
        self._records.pop(model_name, None)

    def clear_cache(self) -> None:
        self._records.clear()

    def list_loaded_models(self) -> list[dict[str, Any]]:
        loaded: list[dict[str, Any]] = []
        for record in self._records.values():
            loaded.append(
                {
                    "name": record.name,
                    "backend": record.backend,
                    "device": record.device,
                    "load_seconds": record.load_seconds,
                    "vector_dimension": record.vector_dimension,
                    "loaded_at": record.loaded_at,
                    "last_used_at": record.last_used_at,
                    "cache_hit": record.cache_hit,
                }
            )
        loaded.sort(key=lambda item: item["name"])
        return loaded

    def describe_environment(self) -> dict[str, Any]:
        env = asdict(self._environment)
        env["registered_models"] = sorted(self._registry.keys())
        env["cached_models"] = self.list_loaded_models()
        env["fallback_embedding_dimension"] = FALLBACK_EMBEDDING_DIMENSION
        env["shared_model_name"] = DEFAULT_SHARED_MODEL_NAME
        return env

    def snapshot(self) -> dict[str, Any]:
        return {
            "environment": self.describe_environment(),
            "active_model_count": len(self._records),
            "registered_model_count": len(self._registry),
            "loaded_models": self.list_loaded_models(),
            "cache_hit_models": [name for name, record in self._records.items() if record.cache_hit],
            "default_shared_model": DEFAULT_SHARED_MODEL_NAME,
        }

    async def benchmark_model(
        self,
        name: str | None = None,
        *,
        sample_texts: list[str] | None = None,
        force_reload: bool = True,
    ) -> dict[str, Any]:
        model_name = self._normalize_name(name)
        if model_name not in self._registry:
            if model_name == DEFAULT_SHARED_MODEL_NAME:
                self._register_default_spec()
            else:
                raise KeyError(f"Unknown model spec: {model_name}")

        sample_texts = sample_texts or [
            "PyTorch framework performance validation.",
            "Elyan model manager benchmark sample.",
            "Phase 0 fallback embedding smoke test.",
        ]

        memory_before_mb = self._process_memory_mb()
        cached_before = model_name in self._records and not force_reload
        if force_reload:
            self.unload_model(model_name)

        load_started = time.perf_counter()
        model = await self.get_model(model_name, force_reload=force_reload)
        load_seconds = time.perf_counter() - load_started
        if cached_before and not force_reload:
            load_seconds = 0.0

        encode_started = time.perf_counter()
        encoded = self._encode(model, sample_texts)
        encode_seconds = time.perf_counter() - encode_started
        memory_after_mb = self._process_memory_mb()

        vector_dimension = self._embedding_dimension(encoded)
        record = self._records.get(model_name)
        backend = record.backend if record else self._infer_backend(model, self._registry[model_name])
        device = record.device if record else self._infer_device(model, self._registry[model_name])

        benchmark = ModelBenchmark(
            model_name=model_name,
            backend=backend,
            device=device,
            load_seconds=load_seconds,
            encode_seconds=encode_seconds,
            memory_before_mb=memory_before_mb,
            memory_after_mb=memory_after_mb,
            process_rss_mb=self._process_memory_mb(),
            available_memory_mb=self._environment.available_memory_mb,
            vector_dimension=vector_dimension,
            sample_count=len(sample_texts),
            cache_hit=bool(record.cache_hit if record else cached_before),
            passed=load_seconds <= PHASE0_LOAD_TARGET_SECONDS and memory_after_mb <= PHASE0_IDLE_MEMORY_TARGET_MB,
            thresholds={
                "load_seconds": PHASE0_LOAD_TARGET_SECONDS,
                "idle_memory_mb": PHASE0_IDLE_MEMORY_TARGET_MB,
            },
        )
        return benchmark.to_dict()

    def _encode(self, model: Any, texts: list[str]) -> Any:
        if hasattr(model, "encode"):
            try:
                return model.encode(
                    texts,
                    convert_to_numpy=True,
                    normalize_embeddings=True,
                )
            except TypeError:
                return model.encode(texts)
        if callable(model):
            return model(texts)
        raise TypeError(f"Model {type(model)!r} does not expose an encode method")

    @staticmethod
    def _embedding_dimension(encoded: Any) -> int:
        if isinstance(encoded, np.ndarray):
            if encoded.ndim == 1:
                return int(encoded.shape[0])
            if encoded.ndim >= 2:
                return int(encoded.shape[-1])
        if isinstance(encoded, list) and encoded:
            first = encoded[0]
            if isinstance(first, (list, tuple, np.ndarray)):
                return len(first)
            return len(encoded)
        return 0

    @staticmethod
    def _infer_backend(model: Any, spec: ModelSpec) -> str:
        backend = getattr(model, "backend", None) or spec.metadata.get("backend")
        if backend:
            return str(backend)
        module_name = type(model).__module__
        if "sentence_transformers" in module_name:
            return "torch_sentence_transformers"
        if isinstance(model, LocalHashingEmbedder):
            return model.backend
        return "custom"

    @staticmethod
    def _infer_device(model: Any, spec: ModelSpec) -> str:
        device = getattr(model, "device", None) or spec.device
        if device:
            return str(device)
        return "cpu"

    @staticmethod
    def _infer_dimension(model: Any) -> int | None:
        if model is None:
            return None

        attr_candidates = (
            "get_sentence_embedding_dimension",
            "embedding_dimension",
            "dimension",
            "dim",
        )
        for attr in attr_candidates:
            value = getattr(model, attr, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    continue
            if isinstance(value, (int, float)) and value > 0:
                return int(value)

        if hasattr(model, "encode"):
            probe = None
            try:
                probe = model.encode("phase0_probe", convert_to_numpy=True, normalize_embeddings=False)
            except TypeError:
                try:
                    probe = model.encode("phase0_probe")
                except Exception:
                    return None
            except Exception:
                return None

            if isinstance(probe, np.ndarray):
                if probe.ndim == 1:
                    return int(probe.shape[0])
                if probe.ndim >= 2:
                    return int(probe.shape[-1])
            if isinstance(probe, list) and probe:
                first = probe[0]
                if isinstance(first, (list, tuple, np.ndarray)):
                    return len(first)
                return len(probe)

        return None

    def get_phase0_report(self, model_name: str | None = None) -> dict[str, Any]:
        model_name = self._normalize_name(model_name)
        report = self.snapshot()
        report["phase0"] = {
            "shared_embedder": model_name,
            "load_target_seconds": PHASE0_LOAD_TARGET_SECONDS,
            "idle_memory_target_mb": PHASE0_IDLE_MEMORY_TARGET_MB,
            "environment_ready": bool(self._environment.torch_available),
        }
        return report


_manager = ModelManager()


def get_model_manager() -> ModelManager:
    return _manager


async def get_shared_embedder() -> Any:
    return await _manager.get_embedding_model()


__all__ = [
    "DEFAULT_EMBEDDING_MODEL",
    "DEFAULT_SHARED_MODEL_NAME",
    "FALLBACK_EMBEDDING_DIMENSION",
    "ModelBenchmark",
    "ModelEnvironment",
    "ModelManager",
    "ModelRecord",
    "ModelSpec",
    "LocalHashingEmbedder",
    "PHASE0_IDLE_MEMORY_TARGET_MB",
    "PHASE0_LOAD_TARGET_SECONDS",
    "get_model_manager",
    "get_shared_embedder",
]
