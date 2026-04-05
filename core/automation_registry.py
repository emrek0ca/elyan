"""
Automation Registry — Persist ve Yönetim katmanı
Zamanlanmış görevleri (Natural Language Cron) ve otomasyonları saklar.
"""

import os
import json
import time
import asyncio
import uuid
import fcntl
from pathlib import Path
from typing import Dict, List, Any

from utils.logger import get_logger
from core.agents.registry import get_agent_module_spec, list_agent_modules, run_agent_module
from core.storage_paths import resolve_elyan_data_dir

logger = get_logger("automation_registry")


class AutomationRegistry:
    def __init__(self, db_path: Path | None = None):
        self.db_path = Path(db_path or (resolve_elyan_data_dir() / "automations.json")).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.automations: Dict[str, Any] = self._load()
        self._running = False
        self._scheduler_task: asyncio.Task | None = None

    def _load(self) -> Dict[str, Any]:
        if not self.db_path.exists():
            return {}
        try:
            with open(self.db_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if not isinstance(payload, dict):
                return {}
            out: Dict[str, Any] = {}
            for task_id, row in payload.items():
                if not isinstance(row, dict):
                    continue
                rid = str(row.get("id") or task_id).strip()
                if not rid:
                    continue
                row["id"] = rid
                out[rid] = row
            return out
        except Exception as e:
            logger.error(f"Registry load error: {e}")
            return {}

    def _save(self) -> None:
        try:
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(self.automations, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"Registry save error: {e}")

    def _load_locked(self) -> Dict[str, Any]:
        lock_path = self.db_path.with_suffix(self.db_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(lock_path, "a+", encoding="utf-8") as lockf:
                fcntl.flock(lockf.fileno(), fcntl.LOCK_SH)
                payload = self._load()
                fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
                return payload
        except Exception as exc:
            logger.error(f"Registry locked load error: {exc}")
            return self._load()

    def _locked_mutate(self, mutator) -> None:
        lock_path = self.db_path.with_suffix(self.db_path.suffix + ".lock")
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(lock_path, "a+", encoding="utf-8") as lockf:
                fcntl.flock(lockf.fileno(), fcntl.LOCK_EX)
                current = self._load()
                self.automations = current
                changed = mutator(self.automations)
                if changed is False:
                    fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
                    return
                with open(self.db_path, "w", encoding="utf-8") as out:
                    json.dump(self.automations, out, indent=2, ensure_ascii=False)
                fcntl.flock(lockf.fileno(), fcntl.LOCK_UN)
        except Exception as exc:
            logger.error(f"Registry locked mutate error: {exc}")
            raise

    @staticmethod
    def _as_interval_seconds(raw: Any, default_seconds: int = 3600) -> int:
        try:
            value = int(raw)
        except Exception:
            value = int(default_seconds)
        return max(30, min(7 * 24 * 3600, value))

    @staticmethod
    def _max_parallel_jobs() -> int:
        raw = str(os.environ.get("ELYAN_AUTOMATION_MAX_PARALLEL", "4") or "4").strip()
        try:
            value = int(raw)
        except Exception:
            value = 4
        return max(1, min(16, value))

    @staticmethod
    def _as_timeout_seconds(raw: Any, default_seconds: int = 120) -> int:
        try:
            value = int(raw)
        except Exception:
            value = int(default_seconds)
        return max(5, min(3600, value))

    @staticmethod
    def _as_retry_count(raw: Any, default_count: int = 1) -> int:
        try:
            value = int(raw)
        except Exception:
            value = int(default_count)
        return max(0, min(5, value))

    @staticmethod
    def _as_backoff_seconds(raw: Any, default_seconds: int = 15) -> int:
        try:
            value = int(raw)
        except Exception:
            value = int(default_seconds)
        return max(1, min(600, value))

    @staticmethod
    def _as_circuit_threshold(raw: Any, default_value: int = 3) -> int:
        try:
            value = int(raw)
        except Exception:
            value = int(default_value)
        return max(1, min(10, value))

    @staticmethod
    def _as_circuit_cooldown_seconds(raw: Any, default_seconds: int = 900) -> int:
        try:
            value = int(raw)
        except Exception:
            value = int(default_seconds)
        return max(30, min(24 * 3600, value))

    @staticmethod
    def _as_float(raw: Any, default_value: float = 0.0) -> float:
        try:
            return float(raw)
        except Exception:
            return float(default_value)

    @staticmethod
    def _stable_json(value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        except Exception:
            return str(value)

    @staticmethod
    def _normalize_module_params(params: Dict[str, Any] | None) -> Dict[str, Any]:
        if not isinstance(params, dict):
            return {}
        out: dict[str, Any] = {}
        for key, value in params.items():
            k = str(key)
            if k in {"workspace", "path", "root", "project_root"} and isinstance(value, str):
                text = str(value or "").strip()
                if text:
                    try:
                        out[k] = str(Path(text).expanduser().resolve())
                    except Exception:
                        out[k] = str(Path(text).expanduser())
                else:
                    out[k] = ""
                continue
            if isinstance(value, list):
                if k.endswith("_urls"):
                    cleaned = [str(item).strip() for item in value if str(item).strip()]
                    out[k] = sorted(set(cleaned))
                else:
                    out[k] = list(value)
                continue
            out[k] = value
        return out

    @staticmethod
    def _compact_result(payload: dict[str, Any], max_len: int = 4000) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return {"raw": str(payload)[:max_len]}
        safe: dict[str, Any] = {}
        for key, value in payload.items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                safe[key] = value
            elif isinstance(value, dict):
                safe[key] = {k: v for k, v in list(value.items())[:15]}
            elif isinstance(value, list):
                safe[key] = value[:20]
            else:
                safe[key] = str(value)
        try:
            raw = json.dumps(safe, ensure_ascii=False)
            if len(raw) > max_len:
                return {"summary": raw[:max_len]}
        except Exception:
            return {"summary": str(safe)[:max_len]}
        return safe

    def register(self, task_id: str, definition: Dict[str, Any]) -> str:
        rid = str(task_id or "").strip() or str(uuid.uuid4())[:8]
        row = dict(definition or {})
        row["id"] = rid
        row["created_at"] = float(row.get("created_at") or time.time())
        row["status"] = str(row.get("status") or "active")
        row["task"] = str(row.get("task") or row.get("name") or "").strip()
        row["interval_seconds"] = self._as_interval_seconds(
            row.get("interval_seconds", row.get("interval", 3600)),
            default_seconds=3600,
        )
        row["timeout_seconds"] = self._as_timeout_seconds(row.get("timeout_seconds", row.get("timeout", 120)), 120)
        row["max_retries"] = self._as_retry_count(row.get("max_retries", 1), default_count=1)
        row["retry_backoff_seconds"] = self._as_backoff_seconds(
            row.get("retry_backoff_seconds", row.get("retry_backoff", 15)),
            default_seconds=15,
        )
        row["circuit_breaker_threshold"] = self._as_circuit_threshold(
            row.get("circuit_breaker_threshold", row.get("circuit_threshold", 3)),
            default_value=3,
        )
        row["circuit_breaker_cooldown_seconds"] = self._as_circuit_cooldown_seconds(
            row.get("circuit_breaker_cooldown_seconds", row.get("circuit_cooldown_seconds", 900)),
            default_seconds=900,
        )
        row["fail_streak"] = int(row.get("fail_streak") or 0)
        row["next_retry_at"] = self._as_float(row.get("next_retry_at"), 0.0)
        row["circuit_open_until"] = self._as_float(row.get("circuit_open_until"), 0.0)

        def _mutate(items: Dict[str, Any]) -> None:
            items[rid] = row

        self._locked_mutate(_mutate)
        logger.info(f"Registered automation: {rid}")
        return rid

    def register_module(
        self,
        module_id: str,
        *,
        task_id: str = "",
        user_id: str = "system",
        channel: str = "automation",
        interval_seconds: int | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: int | None = None,
        circuit_breaker_threshold: int | None = None,
        circuit_breaker_cooldown_seconds: int | None = None,
        params: Dict[str, Any] | None = None,
    ) -> str:
        spec = get_agent_module_spec(module_id)
        if spec is None:
            raise ValueError(f"Unknown agent module: {module_id}")
        rid = str(task_id or "").strip() or str(uuid.uuid4())[:8]
        normalized_module_id = str(module_id).strip().lower()
        normalized_user_id = str(user_id or "system")
        normalized_channel = str(channel or "automation")
        normalized_params = self._normalize_module_params(params)
        definition = {
            "id": rid,
            "name": spec.get("name"),
            "task": spec.get("description"),
            "module_id": normalized_module_id,
            "user_id": normalized_user_id,
            "channel": normalized_channel,
            "params": normalized_params,
            "interval_seconds": self._as_interval_seconds(
                interval_seconds if interval_seconds is not None else spec.get("default_interval_seconds", 3600),
                default_seconds=int(spec.get("default_interval_seconds", 3600) or 3600),
            ),
            "timeout_seconds": self._as_timeout_seconds(
                timeout_seconds if timeout_seconds is not None else spec.get("timeout_seconds", 120),
                default_seconds=int(spec.get("timeout_seconds", 120) or 120),
            ),
            "max_retries": self._as_retry_count(
                max_retries if max_retries is not None else spec.get("max_retries", 1),
                default_count=int(spec.get("max_retries", 1) or 1),
            ),
            "retry_backoff_seconds": self._as_backoff_seconds(
                retry_backoff_seconds if retry_backoff_seconds is not None else spec.get("retry_backoff_seconds", 15),
                default_seconds=int(spec.get("retry_backoff_seconds", 15) or 15),
            ),
            "circuit_breaker_threshold": self._as_circuit_threshold(
                circuit_breaker_threshold if circuit_breaker_threshold is not None else spec.get("circuit_breaker_threshold", 3),
                default_value=int(spec.get("circuit_breaker_threshold", 3) or 3),
            ),
            "circuit_breaker_cooldown_seconds": self._as_circuit_cooldown_seconds(
                circuit_breaker_cooldown_seconds
                if circuit_breaker_cooldown_seconds is not None
                else spec.get("circuit_breaker_cooldown_seconds", 900),
                default_seconds=int(spec.get("circuit_breaker_cooldown_seconds", 900) or 900),
            ),
            "fail_streak": 0,
            "next_retry_at": 0.0,
            "circuit_open_until": 0.0,
            "status": "active",
        }

        matched = {"id": ""}
        params_fp = self._stable_json(normalized_params)

        def _mutate(items: Dict[str, Any]) -> bool:
            # Upsert semantics: if same module+scope+params exists, update policy instead of duplicating rows.
            for existing_id, row in items.items():
                if not isinstance(row, dict):
                    continue
                if str(row.get("module_id") or "").strip().lower() != normalized_module_id:
                    continue
                if str(row.get("user_id") or "system").strip() != normalized_user_id:
                    continue
                if str(row.get("channel") or "automation").strip() != normalized_channel:
                    continue
                row_params = self._normalize_module_params(row.get("params") if isinstance(row.get("params"), dict) else {})
                if self._stable_json(row_params) != params_fp:
                    continue
                keep_created_at = float(row.get("created_at") or time.time())
                merged = dict(definition)
                merged["id"] = str(row.get("id") or existing_id)
                merged["created_at"] = keep_created_at
                # Preserve runtime history while updating policy/config.
                for key in (
                    "last_run",
                    "last_status",
                    "last_error",
                    "last_result",
                    "last_started_at",
                    "last_duration_ms",
                    "last_retry_count",
                    "last_timeout_seconds",
                    "fail_streak",
                    "next_retry_at",
                    "circuit_open_until",
                ):
                    if key in row:
                        merged[key] = row[key]
                items[str(existing_id)] = merged
                matched["id"] = str(existing_id)
                return True

            items[rid] = definition
            matched["id"] = rid
            return True

        self._locked_mutate(_mutate)
        if matched["id"] == rid:
            logger.info(f"Registered automation: {rid}")
        else:
            logger.info(f"Updated automation: {matched['id']}")
        return matched["id"]

    def update_module_task(
        self,
        task_id: str,
        *,
        interval_seconds: int | None = None,
        timeout_seconds: int | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: int | None = None,
        circuit_breaker_threshold: int | None = None,
        circuit_breaker_cooldown_seconds: int | None = None,
        params: Dict[str, Any] | None = None,
        channel: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any] | None:
        rid = str(task_id or "").strip()
        updated: dict[str, Any] = {}

        def _mutate(items: Dict[str, Any]) -> bool:
            row = items.get(rid)
            if not isinstance(row, dict):
                return False
            if interval_seconds is not None:
                row["interval_seconds"] = self._as_interval_seconds(interval_seconds, default_seconds=3600)
            if timeout_seconds is not None:
                row["timeout_seconds"] = self._as_timeout_seconds(timeout_seconds, default_seconds=120)
            if max_retries is not None:
                row["max_retries"] = self._as_retry_count(max_retries, default_count=1)
            if retry_backoff_seconds is not None:
                row["retry_backoff_seconds"] = self._as_backoff_seconds(retry_backoff_seconds, default_seconds=15)
            if circuit_breaker_threshold is not None:
                row["circuit_breaker_threshold"] = self._as_circuit_threshold(circuit_breaker_threshold, default_value=3)
            if circuit_breaker_cooldown_seconds is not None:
                row["circuit_breaker_cooldown_seconds"] = self._as_circuit_cooldown_seconds(
                    circuit_breaker_cooldown_seconds, default_seconds=900
                )
            if params is not None:
                row["params"] = self._normalize_module_params(params)
            if channel is not None:
                row["channel"] = str(channel or "automation").strip() or "automation"
            if status is not None:
                status_norm = str(status or "").strip().lower()
                if status_norm in {"active", "paused", "disabled"}:
                    row["status"] = status_norm
                    if status_norm == "active":
                        row["next_retry_at"] = 0.0
                        row["circuit_open_until"] = 0.0
            updated.clear()
            updated.update(dict(row))
            updated["id"] = rid
            return True

        self._locked_mutate(_mutate)
        return dict(updated) if updated else None

    def reconcile_module_tasks(self) -> dict[str, Any]:
        report: dict[str, Any] = {"groups": 0, "removed_count": 0, "removed_ids": [], "kept_ids": []}

        def _fingerprint(row: dict[str, Any]) -> tuple[str, str, str, str]:
            module_id = str(row.get("module_id") or "").strip().lower()
            user_id = str(row.get("user_id") or "system").strip()
            channel = str(row.get("channel") or "automation").strip()
            params = self._normalize_module_params(row.get("params") if isinstance(row.get("params"), dict) else {})
            return (module_id, user_id, channel, self._stable_json(params))

        def _score(row: dict[str, Any]) -> tuple[float, float]:
            last_run = self._as_float(row.get("last_run"), 0.0)
            created_at = self._as_float(row.get("created_at"), 0.0)
            return (last_run, created_at)

        def _mutate(items: Dict[str, Any]) -> bool:
            groups: dict[tuple[str, str, str, str], list[tuple[str, dict[str, Any]]]] = {}
            for key, row in list(items.items()):
                if not isinstance(row, dict):
                    continue
                if not str(row.get("module_id") or "").strip():
                    continue
                groups.setdefault(_fingerprint(row), []).append((str(key), row))

            changed = False
            for _, entries in groups.items():
                if len(entries) <= 1:
                    continue
                report["groups"] = int(report.get("groups") or 0) + 1
                entries.sort(key=lambda item: _score(item[1]), reverse=True)
                keep_id, keep_row = entries[0]
                keep_row["created_at"] = min(self._as_float(x[1].get("created_at"), time.time()) for x in entries)
                keep_row["status"] = "active" if any(str(x[1].get("status") or "").strip().lower() == "active" for x in entries) else str(keep_row.get("status") or "active")
                items[keep_id] = keep_row
                report["kept_ids"].append(keep_id)
                for drop_id, _ in entries[1:]:
                    items.pop(drop_id, None)
                    report["removed_ids"].append(drop_id)
                    report["removed_count"] = int(report.get("removed_count") or 0) + 1
                    changed = True
            return changed

        self._locked_mutate(_mutate)
        return report

    def unregister(self, task_id: str) -> bool:
        rid = str(task_id or "").strip()
        removed = {"ok": False}

        def _mutate(items: Dict[str, Any]) -> bool:
            existed = rid in items
            if existed:
                items.pop(rid, None)
                removed["ok"] = True
                return True
            return False

        self._locked_mutate(_mutate)
        if removed["ok"]:
            logger.info(f"Unregistered automation: {rid}")
        return bool(removed["ok"])

    def get_active(self) -> List[Dict[str, Any]]:
        # Refresh from disk so scheduler sees CLI-created automations from other processes.
        self.automations = self._load_locked()
        rows: list[dict[str, Any]] = []
        for task_id, row in self.automations.items():
            if str(row.get("status") or "").strip().lower() != "active":
                continue
            payload = dict(row)
            payload["id"] = str(payload.get("id") or task_id)
            rows.append(payload)
        rows.sort(key=lambda item: str(item.get("id") or ""))
        return rows

    def get_all(self) -> List[Dict[str, Any]]:
        self.automations = self._load_locked()
        rows: list[dict[str, Any]] = []
        for task_id, row in self.automations.items():
            if not isinstance(row, dict):
                continue
            payload = dict(row)
            payload["id"] = str(payload.get("id") or task_id)
            rows.append(payload)
        rows.sort(key=lambda item: str(item.get("id") or ""))
        return rows

    def set_status(self, task_id: str, status: str) -> bool:
        rid = str(task_id or "").strip()
        target_status = str(status or "").strip().lower()
        if target_status not in {"active", "paused", "disabled"}:
            return False

        changed = {"ok": False}

        def _mutate(items: Dict[str, Any]) -> bool:
            row = items.get(rid)
            if not isinstance(row, dict):
                return False
            row["status"] = target_status
            if target_status == "active":
                row["next_retry_at"] = 0.0
                row["circuit_open_until"] = 0.0
            changed["ok"] = True
            return True

        self._locked_mutate(_mutate)
        return bool(changed["ok"])

    def list_modules(self) -> List[Dict[str, Any]]:
        return list_agent_modules()

    def update_last_run(
        self,
        task_id: str,
        *,
        last_result: dict[str, Any] | None = None,
        last_status: str = "",
        last_error: str = "",
        runtime_patch: dict[str, Any] | None = None,
    ) -> None:
        rid = str(task_id or "").strip()

        def _mutate(items: Dict[str, Any]) -> bool:
            row = items.get(rid)
            if not isinstance(row, dict):
                return False
            row["last_run"] = time.time()
            if last_status:
                row["last_status"] = str(last_status)
            if last_error:
                row["last_error"] = str(last_error)
            if isinstance(last_result, dict):
                row["last_result"] = self._compact_result(last_result)
            if isinstance(runtime_patch, dict):
                for key, value in runtime_patch.items():
                    row[str(key)] = value
            return True

        self._locked_mutate(_mutate)

    def _task_policy(self, task: dict[str, Any]) -> dict[str, Any]:
        return {
            "timeout_seconds": self._as_timeout_seconds(task.get("timeout_seconds", 120), default_seconds=120),
            "max_retries": self._as_retry_count(task.get("max_retries", 1), default_count=1),
            "retry_backoff_seconds": self._as_backoff_seconds(
                task.get("retry_backoff_seconds", 15), default_seconds=15
            ),
            "circuit_breaker_threshold": self._as_circuit_threshold(
                task.get("circuit_breaker_threshold", 3), default_value=3
            ),
            "circuit_breaker_cooldown_seconds": self._as_circuit_cooldown_seconds(
                task.get("circuit_breaker_cooldown_seconds", 900), default_seconds=900
            ),
        }

    def _module_health_value(self, row: dict[str, Any], now: float | None = None) -> str:
        ts = float(now if now is not None else time.time())
        last_status = str(row.get("last_status") or "").strip().lower()
        runtime_status = str(row.get("status") or "").strip().lower()
        circuit_open_until = self._as_float(row.get("circuit_open_until"), 0.0)
        if runtime_status in {"paused", "disabled"}:
            return "paused"
        if circuit_open_until > ts:
            return "circuit_open"
        if last_status == "ok":
            return "healthy"
        if last_status in {"failed", "circuit_open"}:
            return "failing"
        return "unknown"

    async def _execute_with_policy(self, task_id: str, task: dict[str, Any], agent) -> dict[str, Any]:
        policy = self._task_policy(task)
        timeout_s = int(policy["timeout_seconds"])
        max_retries = int(policy["max_retries"])
        retry_backoff_s = int(policy["retry_backoff_seconds"])
        fail_streak = int(task.get("fail_streak") or 0)
        started_at = time.time()
        last_result: dict[str, Any] = {}
        last_error = ""
        attempts = 0

        for attempt in range(max_retries + 1):
            attempts = attempt + 1
            try:
                result = await asyncio.wait_for(
                    self._execute_automation(task_id, task, agent),
                    timeout=float(timeout_s),
                )
                if isinstance(result, dict):
                    last_result = result
                else:
                    last_result = {"success": bool(result), "result": str(result)}
                if bool(last_result.get("success", False)):
                    return {
                        "ok": True,
                        "status": "ok",
                        "result": last_result,
                        "error": "",
                        "attempts": attempts,
                        "started_at": started_at,
                        "duration_ms": int((time.time() - started_at) * 1000),
                        "fail_streak": 0,
                        "next_retry_at": 0.0,
                        "circuit_open_until": 0.0,
                        "timeout_seconds": timeout_s,
                    }
                last_error = str(last_result.get("error") or "execution_failed")
            except asyncio.TimeoutError:
                last_result = {
                    "success": False,
                    "error": "timeout",
                    "timeout_seconds": timeout_s,
                    "task_id": task_id,
                }
                last_error = f"timeout>{timeout_s}s"
            except Exception as exc:
                last_result = {"success": False, "error": str(exc), "task_id": task_id}
                last_error = str(exc)

            if attempt < max_retries:
                await asyncio.sleep(min(300.0, float(retry_backoff_s) * (2 ** attempt)))

        fail_streak += 1
        now = time.time()
        circuit_open_until = 0.0
        status = "failed"
        threshold = int(policy["circuit_breaker_threshold"])
        if fail_streak >= threshold:
            status = "circuit_open"
            circuit_open_until = now + float(policy["circuit_breaker_cooldown_seconds"])
        retry_delay = min(
            float(self._as_interval_seconds(task.get("interval_seconds", 3600), default_seconds=3600)),
            float(retry_backoff_s) * (2 ** max_retries),
        )
        next_retry_at = now + max(30.0, retry_delay)
        return {
            "ok": False,
            "status": status,
            "result": last_result,
            "error": str(last_error or "execution_failed"),
            "attempts": attempts,
            "started_at": started_at,
            "duration_ms": int((time.time() - started_at) * 1000),
            "fail_streak": fail_streak,
            "next_retry_at": next_retry_at,
            "circuit_open_until": circuit_open_until,
            "timeout_seconds": timeout_s,
        }

    def get_module_health(self, limit: int = 12) -> dict[str, Any]:
        now = time.time()
        rows: list[dict[str, Any]] = []
        for task in self.get_active():
            module_id = str(task.get("module_id") or "").strip().lower()
            if not module_id:
                continue
            policy = self._task_policy(task)
            circuit_open_until = self._as_float(task.get("circuit_open_until"), 0.0)
            health = self._module_health_value(task, now=now)
            rows.append(
                {
                    "task_id": str(task.get("id") or ""),
                    "module_id": module_id,
                    "name": str(task.get("name") or module_id),
                    "health": health,
                    "status": str(task.get("status") or ""),
                    "last_status": str(task.get("last_status") or ""),
                    "last_error": str(task.get("last_error") or ""),
                    "last_run": self._as_float(task.get("last_run"), 0.0),
                    "last_duration_ms": int(task.get("last_duration_ms") or 0),
                    "last_retry_count": int(task.get("last_retry_count") or 0),
                    "fail_streak": int(task.get("fail_streak") or 0),
                    "interval_seconds": self._as_interval_seconds(task.get("interval_seconds", 3600), default_seconds=3600),
                    "timeout_seconds": int(policy["timeout_seconds"]),
                    "next_retry_at": self._as_float(task.get("next_retry_at"), 0.0),
                    "circuit_open_until": circuit_open_until,
                }
            )

        def _severity(item: dict[str, Any]) -> int:
            health = str(item.get("health") or "")
            if health == "circuit_open":
                return 0
            if health == "failing":
                return 1
            if health == "unknown":
                return 2
            return 3

        rows.sort(key=lambda item: (_severity(item), -float(item.get("last_run") or 0.0), str(item.get("module_id") or "")))
        summary = {
            "active_modules": len(rows),
            "healthy": sum(1 for row in rows if str(row.get("health")) == "healthy"),
            "failing": sum(1 for row in rows if str(row.get("health")) == "failing"),
            "unknown": sum(1 for row in rows if str(row.get("health")) == "unknown"),
            "circuit_open": sum(1 for row in rows if str(row.get("health")) == "circuit_open"),
        }
        return {"summary": summary, "modules": rows[: max(1, int(limit or 12))]}

    def list_module_tasks(self, *, include_inactive: bool = True, limit: int = 100) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        now = time.time()
        source = self.get_all() if include_inactive else self.get_active()
        for task in source:
            module_id = str(task.get("module_id") or "").strip().lower()
            if not module_id:
                continue
            policy = self._task_policy(task)
            rows.append(
                {
                    "task_id": str(task.get("id") or ""),
                    "module_id": module_id,
                    "name": str(task.get("name") or module_id),
                    "status": str(task.get("status") or ""),
                    "health": self._module_health_value(task, now=now),
                    "last_status": str(task.get("last_status") or ""),
                    "last_error": str(task.get("last_error") or ""),
                    "last_run": self._as_float(task.get("last_run"), 0.0),
                    "last_duration_ms": int(task.get("last_duration_ms") or 0),
                    "last_retry_count": int(task.get("last_retry_count") or 0),
                    "fail_streak": int(task.get("fail_streak") or 0),
                    "interval_seconds": self._as_interval_seconds(task.get("interval_seconds", 3600), default_seconds=3600),
                    "timeout_seconds": int(policy["timeout_seconds"]),
                    "max_retries": int(policy["max_retries"]),
                    "retry_backoff_seconds": int(policy["retry_backoff_seconds"]),
                    "circuit_breaker_threshold": int(policy["circuit_breaker_threshold"]),
                    "circuit_breaker_cooldown_seconds": int(policy["circuit_breaker_cooldown_seconds"]),
                    "next_retry_at": self._as_float(task.get("next_retry_at"), 0.0),
                    "circuit_open_until": self._as_float(task.get("circuit_open_until"), 0.0),
                }
            )
        rows.sort(key=lambda item: (str(item.get("module_id") or ""), str(item.get("task_id") or "")))
        return rows[: max(1, int(limit or 100))]

    def _persist_execution_outcome(self, task_id: str, task: dict[str, Any], outcome: dict[str, Any]) -> None:
        result = outcome.get("result") if isinstance(outcome.get("result"), dict) else {"result": outcome.get("result")}
        ok = bool(outcome.get("ok", False))
        self.update_last_run(
            task_id,
            last_result=result if isinstance(result, dict) else {"result": str(result)},
            last_status=str(outcome.get("status") or ("ok" if ok else "failed")),
            last_error="" if ok else str(outcome.get("error") or (result or {}).get("error") or "unknown"),
            runtime_patch={
                "last_started_at": float(outcome.get("started_at") or time.time()),
                "last_duration_ms": int(outcome.get("duration_ms") or 0),
                "last_retry_count": max(0, int(outcome.get("attempts") or 1) - 1),
                "fail_streak": int(outcome.get("fail_streak") or (0 if ok else int(task.get("fail_streak") or 0) + 1)),
                "next_retry_at": float(outcome.get("next_retry_at") or 0.0),
                "circuit_open_until": float(outcome.get("circuit_open_until") or 0.0),
                "last_timeout_seconds": int(outcome.get("timeout_seconds") or 0),
            },
        )

    async def run_task_now(self, task_id: str, agent=None) -> dict[str, Any]:
        rid = str(task_id or "").strip()
        current = self._load_locked()
        task = current.get(rid)
        if not isinstance(task, dict):
            return {"success": False, "task_id": rid, "error": "task_not_found", "status": "failed"}
        outcome = await self._execute_with_policy(rid, dict(task), agent)
        self._persist_execution_outcome(rid, dict(task), outcome)
        return {
            "success": bool(outcome.get("ok", False)),
            "task_id": rid,
            "module_id": str(task.get("module_id") or ""),
            "status": str(outcome.get("status") or ""),
            "attempts": int(outcome.get("attempts") or 0),
            "duration_ms": int(outcome.get("duration_ms") or 0),
            "error": str(outcome.get("error") or ""),
            "result": outcome.get("result") if isinstance(outcome.get("result"), dict) else {"result": outcome.get("result")},
        }

    async def start_scheduler(self, agent) -> None:
        """Otomasyon döngüsünü başlat."""
        if self._scheduler_task and not self._scheduler_task.done():
            return
        self._running = True
        self._scheduler_task = asyncio.create_task(self._scheduler_loop(agent))
        logger.info("Automation scheduler started")

    async def stop_scheduler(self) -> None:
        """Otomasyon döngüsünü durdur ve task'i temiz kapat."""
        self._running = False
        task = self._scheduler_task
        self._scheduler_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _execute_automation(self, task_id: str, task: dict[str, Any], agent) -> dict[str, Any]:
        module_id = str(task.get("module_id") or "").strip().lower()
        if module_id:
            module_payload = {
                "task_id": task_id,
                "workspace": str(task.get("workspace") or Path.cwd()),
                **(task.get("params") if isinstance(task.get("params"), dict) else {}),
            }
            return await run_agent_module(module_id, module_payload)

        from core.pipeline import PipelineContext, pipeline_runner

        ctx = PipelineContext(
            user_input=str(task.get("task") or ""),
            user_id=str(task.get("user_id") or "system"),
            channel=str(task.get("channel") or "automation"),
        )
        await pipeline_runner.run(ctx, agent)
        return {
            "success": True,
            "module_id": "",
            "status": "pipeline_triggered",
            "task_id": task_id,
            "task": str(task.get("task") or ""),
        }

    async def _scheduler_loop(self, agent) -> None:
        try:
            while getattr(self, "_running", False):
                try:
                    now = time.time()
                    active = self.get_active()
                    due: list[tuple[str, dict[str, Any]]] = []

                    for task in active:
                        task_id = str(task.get("id") or "").strip()
                        if not task_id:
                            continue
                        last = float(task.get("last_run") or 0.0)
                        next_retry_at = self._as_float(task.get("next_retry_at"), 0.0)
                        if next_retry_at > now:
                            continue
                        circuit_open_until = self._as_float(task.get("circuit_open_until"), 0.0)
                        if circuit_open_until > now:
                            continue
                        interval_seconds = self._as_interval_seconds(task.get("interval_seconds", 3600), default_seconds=3600)
                        if next_retry_at > 0.0:
                            due.append((task_id, task))
                        elif now - last >= interval_seconds:
                            due.append((task_id, task))

                    if due:
                        logger.info(f"Triggering {len(due)} automation job(s)")
                        sem = asyncio.Semaphore(self._max_parallel_jobs())

                        async def _run_one(task_id: str, task: dict[str, Any]) -> None:
                            display = str(task.get("task") or task.get("module_id") or task_id)
                            async with sem:
                                try:
                                    logger.info(f"Triggering automation: {task_id} -> {display}")
                                    outcome = await self._execute_with_policy(task_id, task, agent)
                                    self._persist_execution_outcome(task_id, task, outcome)
                                except Exception as exc:
                                    logger.error(f"Automation execution failed ({task_id}): {exc}")
                                    self.update_last_run(
                                        task_id,
                                        last_status="failed",
                                        last_error=str(exc),
                                        runtime_patch={
                                            "fail_streak": int(task.get("fail_streak") or 0) + 1,
                                            "next_retry_at": time.time() + 60.0,
                                        },
                                    )

                        await asyncio.gather(*[_run_one(task_id, task) for task_id, task in due])
                except Exception as e:
                    logger.error(f"Scheduler error: {e}")

                await asyncio.sleep(60)  # Check every minute
        except asyncio.CancelledError:
            raise
        finally:
            self._running = False
            current_task = asyncio.current_task()
            if self._scheduler_task is current_task:
                self._scheduler_task = None

# Global Instance
automation_registry = AutomationRegistry()
