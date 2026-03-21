from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from config.elyan_config import elyan_config
from core.dependencies import get_dependency_runtime, get_system_dependency_runtime
from core.knowledge_base import get_knowledge_base
from core.self_improvement import get_self_improvement
from core.security.secure_vault import vault
from core.task_brain import task_brain
from utils.logger import get_logger

from . import onboard as onboarding

logger = get_logger("bootstrap_manager")

BOOTSTRAP_STATE_PATH = Path.home() / ".elyan" / "bootstrap_state.json"
BOOTSTRAP_BUNDLE_DIR = Path.home() / ".elyan" / "backups"


def _now_ts() -> float:
    return time.time()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(dict(merged.get(key) or {}), value)
        else:
            merged[key] = value
    return merged


@dataclass
class BootstrapResult:
    ok: bool
    action: str
    message: str
    bundle_path: str = ""
    state: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "action": self.action,
            "message": self.message,
            "bundle_path": self.bundle_path,
            "state": dict(self.state or {}),
        }


class BootstrapManager:
    DEFAULT_STATE: dict[str, Any] = {
        "installed": False,
        "onboarded": False,
        "repaired": False,
        "restored": False,
        "last_action": "",
        "last_message": "",
        "last_run_at": 0.0,
        "setup_complete": False,
    }

    def __init__(self, *, state_path: Path | None = None) -> None:
        self.state_path = Path(state_path or BOOTSTRAP_STATE_PATH).expanduser()
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self.bundle_dir = BOOTSTRAP_BUNDLE_DIR.expanduser()
        self.bundle_dir.mkdir(parents=True, exist_ok=True)

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return dict(self.DEFAULT_STATE)
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except Exception:
            return dict(self.DEFAULT_STATE)
        if not isinstance(payload, dict):
            return dict(self.DEFAULT_STATE)
        return _deep_merge(self.DEFAULT_STATE, payload)

    def _save_state(self, state: dict[str, Any]) -> None:
        payload = dict(state or {})
        payload["last_run_at"] = _now_ts()
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _set_state(self, **updates: Any) -> dict[str, Any]:
        state = self._load_state()
        state.update(updates)
        self._save_state(state)
        return state

    def _runtime_snapshot(self) -> dict[str, Any]:
        dep_runtime = get_dependency_runtime()
        system_runtime = get_system_dependency_runtime()
        snapshot = {
            "dependencies": dep_runtime.snapshot() if hasattr(dep_runtime, "snapshot") else {},
            "system_dependencies": system_runtime.snapshot() if hasattr(system_runtime, "snapshot") else {},
            "setup_complete": bool(elyan_config.get("agent.setup.completed", False)),
            "config": {
                "provider": str(elyan_config.get("models.default.provider", "") or ""),
                "model": str(elyan_config.get("models.default.model", "") or ""),
                "local_first": bool(elyan_config.get("agent.model.local_first", True)),
                "channels": list(elyan_config.get("channels", []) or []),
            },
            "knowledge": {
                "optimization_rules": len(get_self_improvement().optimization_rules),
                "feedback_entries": len(get_self_improvement().feedback_history),
                "knowledge_records": len(get_knowledge_base().list_experiences()),
            },
        }
        try:
            snapshot["task_brain"] = {
                "tasks": len(task_brain.list_all(limit=500)),
                "latest_state": str((task_brain.list_all(limit=1)[0].state if task_brain.list_all(limit=1) else "") or ""),
            }
        except Exception:
            snapshot["task_brain"] = {}
        return snapshot

    def status(self) -> dict[str, Any]:
        state = self._load_state()
        return {
            **state,
            "state_path": str(self.state_path),
            "bundle_dir": str(self.bundle_dir),
            "runtime": self._runtime_snapshot(),
        }

    def install(self, *, headless: bool = False, force: bool = False) -> dict[str, Any]:
        state = self._load_state()
        if onboarding.is_setup_complete() and not force:
            return BootstrapResult(
                ok=True,
                action="install",
                message="Elyan zaten kurulmuş.",
                state=state,
            ).to_dict()

        ok = bool(onboarding.start_onboarding(headless=headless, force=force))
        state = self._set_state(
            installed=True,
            onboarded=ok,
            setup_complete=bool(ok),
            last_action="install",
            last_message="installation completed" if ok else "installation incomplete",
        )
        return BootstrapResult(
            ok=ok,
            action="install",
            message="Kurulum tamamlandı." if ok else "Kurulum kısmen tamamlandı.",
            state=state,
        ).to_dict()

    def onboard(
        self,
        *,
        headless: bool = False,
        channel: str | None = None,
        install_daemon: bool = False,
        force: bool = False,
    ) -> dict[str, Any]:
        ok = bool(
            onboarding.start_onboarding(
                headless=headless,
                channel=channel,
                install_daemon=install_daemon,
                force=force,
            )
        )
        state = self._set_state(
            installed=True,
            onboarded=ok,
            setup_complete=bool(ok),
            last_action="onboard",
            last_message="onboarding completed" if ok else "onboarding incomplete",
        )
        return BootstrapResult(
            ok=ok,
            action="onboard",
            message="Onboarding tamamlandı." if ok else "Onboarding yarım kaldı.",
            state=state,
        ).to_dict()

    def repair(self, *, force: bool = False) -> dict[str, Any]:
        from cli.commands import doctor

        try:
            doctor.run_doctor(fix=True)
        except Exception as exc:
            logger.debug(f"bootstrap repair doctor error: {exc}")

        ok = bool(onboarding.is_setup_complete())
        if not ok or force:
            try:
                ok = bool(onboarding.start_onboarding(headless=True, force=force))
            except Exception as exc:
                logger.debug(f"bootstrap repair onboarding error: {exc}")
        state = self._set_state(
            installed=True,
            repaired=ok,
            setup_complete=bool(ok),
            last_action="repair",
            last_message="repair completed" if ok else "repair incomplete",
        )
        return BootstrapResult(
            ok=ok,
            action="repair",
            message="Onarım tamamlandı." if ok else "Onarım kısmen tamamlandı.",
            state=state,
        ).to_dict()

    def export_bundle(self, *, output: str | None = None) -> dict[str, Any]:
        bundle = {
            "version": 1,
            "created_at": _now_ts(),
            "config": elyan_config.get_all(),
            "vault": vault.export_bundle(),
            "memory": {},
            "task_brain": {},
            "knowledge_base": get_knowledge_base().list_experiences(),
            "self_improvement": {
                "summary": get_self_improvement().get_summary(),
                "optimization_rules": {
                    rule_id: {
                        "area": rule.area.value,
                        "condition": rule.condition,
                        "action": rule.action,
                        "confidence": rule.confidence,
                        "success_count": rule.success_count,
                        "failure_count": rule.failure_count,
                        "created_at": rule.created_at,
                    }
                    for rule_id, rule in get_self_improvement().optimization_rules.items()
                },
            },
            "state": self._load_state(),
        }
        try:
            memory_manager = __import__("core.memory", fromlist=["MemoryManager"]).MemoryManager()
            bundle["memory"] = memory_manager.export(format="json")
        except Exception as exc:
            bundle["memory"] = {"error": str(exc)}
        try:
            bundle["task_brain"] = {task.task_id: task.to_dict() for task in task_brain.list_all(limit=1000)}
        except Exception as exc:
            bundle["task_brain"] = {"error": str(exc)}
        path = Path(output).expanduser() if output else self.bundle_dir / f"bootstrap_bundle_{int(_now_ts())}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
        return {"ok": True, "bundle_path": str(path), "bundle": bundle}

    def restore(self, *, bundle_path: str | None = None) -> dict[str, Any]:
        if not bundle_path:
            candidates = sorted(self.bundle_dir.glob("bootstrap_bundle_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            if not candidates:
                return {"ok": False, "error": "restore bundle bulunamadı"}
            bundle_path = str(candidates[0])
        payload = json.loads(Path(bundle_path).expanduser().read_text(encoding="utf-8"))
        if isinstance(payload.get("config"), dict):
            for key, value in payload["config"].items():
                if key:
                    elyan_config.set(key, value)
            try:
                elyan_config.save()
            except Exception:
                pass
        if payload.get("vault"):
            vault.import_bundle(payload["vault"])
        if payload.get("memory") and isinstance(payload["memory"], str):
            try:
                memory_manager = __import__("core.memory", fromlist=["MemoryManager"]).MemoryManager()
                memory_manager.import_data(json.loads(payload["memory"]))
            except Exception:
                pass
        elif payload.get("memory") and isinstance(payload["memory"], dict):
            try:
                memory_manager = __import__("core.memory", fromlist=["MemoryManager"]).MemoryManager()
                memory_manager.import_data(payload["memory"])
            except Exception:
                pass
        if isinstance(payload.get("state"), dict):
            self._save_state(_deep_merge(self.DEFAULT_STATE, payload["state"]))
        state = self._set_state(
            installed=True,
            onboarded=True,
            restored=True,
            setup_complete=True,
            last_action="restore",
            last_message=f"restored from {bundle_path}",
        )
        try:
            onboarding.mark_setup_complete(extra={"restored_from": str(bundle_path)})
        except Exception:
            pass
        return {
            "ok": True,
            "bundle_path": str(bundle_path),
            "state": state,
        }


_BOOTSTRAP_MANAGER: BootstrapManager | None = None


def get_bootstrap_manager() -> BootstrapManager:
    global _BOOTSTRAP_MANAGER
    if _BOOTSTRAP_MANAGER is None:
        _BOOTSTRAP_MANAGER = BootstrapManager()
    return _BOOTSTRAP_MANAGER


__all__ = ["BootstrapManager", "BootstrapResult", "get_bootstrap_manager"]
