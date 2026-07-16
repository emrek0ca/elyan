"""P4 — Dayanıklılık: şifreli yerel SQLite checkpoint + execution journal.

ExecutorCore her tamamlanan adımdan sonra buraya checkpoint yazar. Süreç
yeniden başladığında aynı (taskId, planHash) için journal'dan son güvenli
noktaya kadar tamamlanmış adımlar geri yüklenir; yan etkiler tekrar
çalıştırılmaz. Kurallar:

- Ham kullanıcı dosyası, token veya özel içerik journal'a YAZILMAZ: argümanlar
  yalnız hash olarak, adım çıktıları yalnız cihaz sırrından türetilmiş Fernet
  anahtarıyla şifreli saklanır. Şifreleme mümkün değilse çıktı hiç saklanmaz
  (resume, effects idempotency'sine güvenerek yeniden yürütmeye düşer).
- Compensation: bu koşuda YENİ oluşturulmuş (öncesinde var olmayan) dosyalar,
  plan başarısız biterse güvenle silinir; önceden var olan dosyalara dokunulmaz.
"""

from __future__ import annotations

import base64
import datetime as dt
import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from runtime import state_store
from runtime.execution_trust import args_hash, sha256_value

try:
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover - optional dependency
    Fernet = None
    InvalidToken = Exception


def _utc_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _text(value: Any) -> str:
    return str(value or "").strip()


def _journal_path() -> Path:
    return Path(state_store.STATE_PATH).parent / "execution_journal.sqlite3"


def _device_secret() -> str:
    runtime = state_store.snapshot().get("runtime", {})
    runtime = runtime if isinstance(runtime, dict) else {}
    return str(runtime.get("deviceSecret", "") or "").strip()


def _local_key_path() -> Path:
    return Path(state_store.STATE_PATH).parent / "journal.key"


def _fernet() -> "Fernet | None":
    """Cihaz sırrından türetilmiş anahtar; yoksa 0600 izinli yerel anahtar."""
    if Fernet is None:
        return None
    secret = _device_secret()
    if secret:
        digest = hashlib.sha256(f"elyan.journal.v1:{secret}".encode("utf-8")).digest()
        return Fernet(base64.urlsafe_b64encode(digest))
    key_path = _local_key_path()
    try:
        if key_path.exists():
            return Fernet(key_path.read_bytes().strip())
        key = Fernet.generate_key()
        key_path.parent.mkdir(parents=True, exist_ok=True)
        key_path.write_bytes(key)
        os.chmod(key_path, 0o600)
        return Fernet(key)
    except OSError:
        return None


def plan_hash(steps: list[dict[str, Any]]) -> str:
    """Bind resume state to the complete executable plan shape."""
    shape = [
        {
            "id": str(step.get("id", "") or ""),
            "capability": str(step.get("capability", "") or ""),
            "args": {
                str(key): value
                for key, value in (step.get("args", {}) if isinstance(step.get("args"), dict) else {}).items()
                if not str(key).startswith("_")
            },
            "dependsOn": list(step.get("dependsOn", []) or []),
            "forEach": step.get("forEach"),
            "resourceScope": list(step.get("resourceScope", []) or []),
        }
        for step in steps
        if isinstance(step, dict)
    ]
    return sha256_value(shape)


class ExecutionJournal:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else _journal_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS executions (
                    execution_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL DEFAULT '',
                    user_id TEXT NOT NULL DEFAULT '',
                    plan_hash TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'running',
                    stop_reason TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_executions_task
                    ON executions(task_id, plan_hash, started_at);
                CREATE TABLE IF NOT EXISTS journal_steps (
                    execution_id TEXT NOT NULL,
                    step_id TEXT NOT NULL,
                    capability TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    attempt INTEGER NOT NULL DEFAULT 1,
                    args_hash TEXT NOT NULL DEFAULT '',
                    side_effect INTEGER NOT NULL DEFAULT 0,
                    pre_existed INTEGER,
                    evidence_kind TEXT NOT NULL DEFAULT '',
                    evidence_fingerprint TEXT NOT NULL DEFAULT '',
                    output_path TEXT NOT NULL DEFAULT '',
                    output_cipher BLOB,
                    compensation TEXT NOT NULL DEFAULT '',
                    compensation_status TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (execution_id, step_id)
                );
                """
            )

    # ------------------------------------------------------------------ yaşam döngüsü

    def begin(self, execution_id: str, *, task_id: str = "", user_id: str = "", plan_signature: str = "") -> None:
        if not str(execution_id or "").strip():
            return
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO executions (execution_id, task_id, user_id, plan_hash, status, started_at)
                VALUES (?, ?, ?, ?, 'running', ?)
                ON CONFLICT(execution_id) DO NOTHING
                """,
                (execution_id, task_id, user_id, plan_signature, _utc_iso()),
            )

    def record_step_completed(
        self,
        execution_id: str,
        step_id: str,
        *,
        capability: str,
        args: dict[str, Any],
        output_payload: dict[str, Any] | None,
        evidence: dict[str, Any] | None = None,
        side_effect: bool = False,
        pre_existed: bool | None = None,
        attempt: int = 1,
    ) -> None:
        evidence = evidence if isinstance(evidence, dict) else {}
        cipher: bytes | None = None
        fernet = _fernet()
        if fernet is not None and isinstance(output_payload, dict):
            try:
                cipher = fernet.encrypt(json.dumps(output_payload, ensure_ascii=False, default=str).encode("utf-8"))
            except (TypeError, ValueError):
                cipher = None
        output_path = str(evidence.get("path", "") or "")
        safe_args = {k: v for k, v in (args or {}).items() if not str(k).startswith("_")}
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO journal_steps (
                    execution_id, step_id, capability, status, attempt, args_hash,
                    side_effect, pre_existed, evidence_kind, evidence_fingerprint,
                    output_path, output_cipher, updated_at
                ) VALUES (?, ?, ?, 'completed', ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(execution_id, step_id) DO UPDATE SET
                    status='completed', attempt=excluded.attempt,
                    evidence_kind=excluded.evidence_kind,
                    evidence_fingerprint=excluded.evidence_fingerprint,
                    output_path=excluded.output_path,
                    output_cipher=excluded.output_cipher,
                    updated_at=excluded.updated_at
                """,
                (
                    execution_id,
                    step_id,
                    capability,
                    max(1, int(attempt or 1)),
                    args_hash(safe_args),
                    1 if side_effect else 0,
                    None if pre_existed is None else (1 if pre_existed else 0),
                    str(evidence.get("kind", "") or ""),
                    str(evidence.get("sha256", "") or evidence.get("providerId", "") or ""),
                    output_path,
                    cipher,
                    _utc_iso(),
                ),
            )

    def finish(self, execution_id: str, *, ok: bool, stop_reason: str = "") -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE executions SET status = ?, stop_reason = ?, finished_at = ? WHERE execution_id = ?",
                ("completed" if ok else "failed", str(stop_reason or "")[:240], _utc_iso(), _text(execution_id)),
            )

    # ------------------------------------------------------------------ restart devamı

    def resume_state(self, task_id: str, plan_signature: str) -> dict[str, Any]:
        """Aynı görev+plan için yarım kalmış son koşunun güvenli durumu."""
        empty = {"executionId": "", "completedStepIds": [], "stepOutputs": {}}
        task_id = str(task_id or "").strip()
        if not task_id or not plan_signature:
            return empty
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT execution_id FROM executions
                WHERE task_id = ? AND plan_hash = ? AND status != 'completed'
                ORDER BY started_at DESC LIMIT 1
                """,
                (task_id, plan_signature),
            ).fetchone()
            if row is None:
                return empty
            execution_id = str(row["execution_id"])
            steps = connection.execute(
                "SELECT step_id, output_cipher, side_effect FROM journal_steps WHERE execution_id = ? AND status = 'completed'",
                (execution_id,),
            ).fetchall()
        completed: list[str] = []
        outputs: dict[str, dict[str, Any]] = {}
        fernet = _fernet()
        for step in steps:
            step_id = str(step["step_id"])
            cipher = step["output_cipher"]
            if fernet is None or not cipher:
                if bool(step["side_effect"]):
                    completed.append(step_id)
                continue
            try:
                payload = json.loads(fernet.decrypt(bytes(cipher)).decode("utf-8"))
                if isinstance(payload, dict):
                    outputs[step_id] = payload
                    completed.append(step_id)
            except (InvalidToken, ValueError, TypeError):
                if bool(step["side_effect"]):
                    completed.append(step_id)
                continue
        return {"executionId": execution_id, "completedStepIds": completed, "stepOutputs": outputs}

    def step_outputs_for(self, task_id: str, plan_signature: str) -> dict[str, dict[str, Any]]:
        """Aynı görev+plan imzasının SON koşusundaki adım çıktıları (şifresi çözülmüş).

        resume_state'ten farkı: koşu tamamlanmış olsa da okur — onay için
        bölünen planlarda ön-onay çıktılarının onay adımına taşınmasını sağlar.
        """
        task_id = str(task_id or "").strip()
        if not task_id or not plan_signature:
            return {}
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT execution_id FROM executions
                WHERE task_id = ? AND plan_hash = ?
                ORDER BY started_at DESC LIMIT 1
                """,
                (task_id, plan_signature),
            ).fetchone()
            if row is None:
                return {}
            steps = connection.execute(
                "SELECT step_id, output_cipher FROM journal_steps WHERE execution_id = ? AND status = 'completed'",
                (str(row["execution_id"]),),
            ).fetchall()
        outputs: dict[str, dict[str, Any]] = {}
        fernet = _fernet()
        if fernet is None:
            return {}
        for step in steps:
            cipher = step["output_cipher"]
            if not cipher:
                continue
            try:
                payload = json.loads(fernet.decrypt(bytes(cipher)).decode("utf-8"))
                if isinstance(payload, dict):
                    outputs[str(step["step_id"])] = payload
            except (InvalidToken, ValueError, TypeError):
                continue
        return outputs

    # ------------------------------------------------------------------ compensation

    def compensate_failed_execution(self, execution_id: str) -> list[dict[str, Any]]:
        """Bu koşuda yeni oluşturulan dosyaları güvenle geri alır (siler).

        Önceden var olan dosyalara dokunulmaz; desteklenmeyen yan etkiler
        yalnız 'unsupported' olarak işaretlenir.
        """
        actions: list[dict[str, Any]] = []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT step_id, capability, side_effect, pre_existed, evidence_kind, output_path
                FROM journal_steps WHERE execution_id = ? AND status = 'completed'
                """,
                (execution_id,),
            ).fetchall()
            for row in rows:
                if not int(row["side_effect"] or 0):
                    continue
                step_id = str(row["step_id"])
                path_text = str(row["output_path"] or "")
                created_by_run = row["pre_existed"] == 0 and bool(path_text)
                if created_by_run and path_text:
                    status = "reverted"
                    try:
                        candidate = Path(path_text)
                        if candidate.is_file():
                            candidate.unlink()
                    except OSError:
                        status = "revert_failed"
                    action = {"stepId": step_id, "action": "delete_created_file", "path": path_text, "status": status}
                else:
                    action = {"stepId": step_id, "action": "none", "status": "unsupported"}
                actions.append(action)
                connection.execute(
                    "UPDATE journal_steps SET compensation = ?, compensation_status = ?, updated_at = ? "
                    "WHERE execution_id = ? AND step_id = ?",
                    (action["action"], action["status"], _utc_iso(), execution_id, step_id),
                )
        return actions

