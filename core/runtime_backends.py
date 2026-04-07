from __future__ import annotations

import importlib
import json
import os
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Optional

from config.elyan_config import elyan_config
from config.settings import get_gateway_root_url
from utils.logger import get_logger

logger = get_logger("runtime_backends")


@dataclass(slots=True)
class BackendStatus:
    name: str
    language: str
    configured: bool
    available: bool
    active: bool
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class NativeEventStoreAdapter:
    """Optional bridge for a future Rust event store backend."""

    _APPEND_METHODS = ("append_event_json", "append_event")

    def __init__(self, backend: Any, module_name: str):
        self._backend = backend
        self.module_name = module_name

    @property
    def contract_ready(self) -> bool:
        return any(callable(getattr(self._backend, name, None)) for name in self._APPEND_METHODS)

    def append_event(self, event: Any) -> Optional[int]:
        if not self.contract_ready:
            return None

        envelope = json.dumps(
            {
                "event_id": str(getattr(event, "event_id", "") or ""),
                "event_type": str(getattr(getattr(event, "event_type", None), "value", getattr(event, "event_type", "")) or ""),
                "aggregate_id": str(getattr(event, "aggregate_id", "") or ""),
                "aggregate_type": str(getattr(event, "aggregate_type", "") or ""),
                "payload": dict(getattr(event, "payload", {}) or {}),
                "timestamp": float(getattr(event, "timestamp", 0.0) or 0.0),
                "sequence_number": int(getattr(event, "sequence_number", 0) or 0),
                "causation_id": getattr(event, "causation_id", None),
            },
            ensure_ascii=False,
            default=str,
        )

        for method_name in self._APPEND_METHODS:
            method = getattr(self._backend, method_name, None)
            if not callable(method):
                continue
            try:
                result = method(envelope)
                if result is None:
                    return None
                return int(result)
            except Exception as exc:
                logger.warning(f"Native event store append failed via {method_name}: {exc}")
                return None
        return None


class RuntimeBackendRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._rust_module: Any = None
        self._rust_module_name = ""
        self._rust_import_error = ""

    def _config(self, key: str, default: Any = None) -> Any:
        try:
            return elyan_config.get(key, default)
        except Exception:
            return default

    def _load_rust_module(self) -> tuple[Any, str]:
        with self._lock:
            module_name = str(
                os.getenv("ELYAN_RUST_CORE_MODULE", "")
                or self._config("runtime_backends.rust_core.module", "elyan_core")
                or "elyan_core"
            ).strip()
            if self._rust_module is not None and self._rust_module_name == module_name:
                return self._rust_module, ""
            if self._rust_import_error and self._rust_module_name == module_name:
                return None, self._rust_import_error

            self._rust_module_name = module_name
            self._rust_module = None
            self._rust_import_error = ""
            try:
                self._rust_module = importlib.import_module(module_name)
                return self._rust_module, ""
            except Exception as exc:
                self._rust_import_error = str(exc)
                return None, self._rust_import_error

    @staticmethod
    def _probe_http_health(root_url: str, enabled: bool) -> bool:
        if not enabled or not root_url:
            return False
        health_url = f"{str(root_url).rstrip('/')}/health"
        try:
            with urllib.request.urlopen(health_url, timeout=0.35) as response:
                return int(getattr(response, "status", 0) or 0) < 500
        except (urllib.error.URLError, TimeoutError, ValueError):
            return False
        except Exception:
            return False

    def describe(self) -> dict[str, Any]:
        rust_enabled = bool(self._config("runtime_backends.rust_core.enabled", True))
        rust_required = bool(self._config("runtime_backends.rust_core.required", False))
        rust_module, rust_error = self._load_rust_module() if rust_enabled else (None, "")
        rust_available = rust_module is not None
        rust_features = {
            "event_store": bool(rust_module and hasattr(rust_module, "FastEventStore")),
            "memory_index": bool(rust_module and hasattr(rust_module, "MemoryIndex")),
            "vault": bool(rust_module and hasattr(rust_module, "FastVault")),
        }

        gateway_mode = str(
            os.getenv("ELYAN_GATEWAY_RUNTIME", "")
            or self._config("gateway.runtime", self._config("gateway.mode", "python"))
            or "python"
        ).strip().lower()
        gateway_root = get_gateway_root_url()
        gateway_probe_enabled = gateway_mode in {"go", "auto"}
        gateway_online = self._probe_http_health(gateway_root, gateway_probe_enabled)
        gateway_active = gateway_mode == "go" and gateway_online

        dashboard_mode = str(self._config("runtime_backends.dashboard.preferred", "python_embedded") or "python_embedded").strip().lower()
        dashboard_available = str(os.getenv("ELYAN_TS_DASHBOARD_AVAILABLE", "")).strip().lower() in {"1", "true", "yes", "on"}
        desktop_mode = str(self._config("runtime_backends.desktop_shell.preferred", "pyqt6") or "pyqt6").strip().lower()
        swift_available = str(os.getenv("ELYAN_SWIFT_DESKTOP_AVAILABLE", "")).strip().lower() in {"1", "true", "yes", "on"}

        statuses = [
            BackendStatus(
                name="python_core",
                language="python",
                configured=True,
                available=True,
                active=True,
                details={"role": "agent_logic,tooling,nlu,ml"},
            ),
            BackendStatus(
                name="rust_core",
                language="rust",
                configured=rust_enabled,
                available=rust_available,
                active=rust_available and any(rust_features.values()),
                details={
                    "module": self._rust_module_name or "elyan_core",
                    "required": rust_required,
                    "import_error": rust_error,
                    "features": rust_features,
                },
            ),
            BackendStatus(
                name="go_gateway",
                language="go",
                configured=gateway_mode in {"go", "auto"},
                available=gateway_online if gateway_probe_enabled else False,
                active=gateway_active,
                details={
                    "mode": gateway_mode,
                    "root_url": gateway_root,
                    "grpc_target": str(self._config("gateway.grpc_target", "127.0.0.1:50051") or "127.0.0.1:50051"),
                    "healthcheck_ok": gateway_online,
                },
            ),
            BackendStatus(
                name="typescript_dashboard",
                language="typescript",
                configured=dashboard_mode in {"react_vite", "embedded_web"},
                available=dashboard_available,
                active=dashboard_available and dashboard_mode == "react_vite",
                details={"preferred": dashboard_mode, "env_available": dashboard_available},
            ),
            BackendStatus(
                name="swift_desktop",
                language="swift",
                configured=desktop_mode in {"swiftui", "auto"},
                available=swift_available,
                active=swift_available and desktop_mode == "swiftui",
                details={"preferred": desktop_mode, "env_available": swift_available},
            ),
        ]
        return {item.name: item.to_dict() for item in statuses}

    def get_event_store_adapter(self, db_path: str | Path) -> Optional[NativeEventStoreAdapter]:
        rust_enabled = bool(self._config("runtime_backends.rust_core.enabled", True))
        if not rust_enabled:
            return None

        rust_module, rust_error = self._load_rust_module()
        if rust_module is None:
            if rust_error:
                logger.debug(f"Rust core unavailable: {rust_error}")
            return None

        backend_cls = getattr(rust_module, "FastEventStore", None)
        if not callable(backend_cls):
            return None

        try:
            adapter = NativeEventStoreAdapter(backend_cls(str(Path(db_path).expanduser())), self._rust_module_name or "elyan_core")
        except Exception as exc:
            logger.warning(f"Rust event store init failed: {exc}")
            return None

        if not adapter.contract_ready:
            logger.debug("Rust event store loaded but append_event contract is not ready")
            return None
        return adapter


_registry: Optional[RuntimeBackendRegistry] = None


def get_runtime_backend_registry() -> RuntimeBackendRegistry:
    global _registry
    if _registry is None:
        _registry = RuntimeBackendRegistry()
    return _registry
