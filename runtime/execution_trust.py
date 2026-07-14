from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runtime import state_store
from runtime.desktop_work_order import V2_SCHEMA, canonical_capability


GRANT_SCHEMA = "elyan.capability_grant.v1"
DEFAULT_WORK_ORDER_TTL_SECONDS = 15 * 60
_SIGNATURE_PREFIX = "hmac-sha256:"
_HASH_PREFIX = "sha256:"


class TrustError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = str(code or "TRUST_VALIDATION_FAILED").upper()
        self.message = message


@dataclass(frozen=True)
class DeliveryClaim:
    claimed: bool
    status: str


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _utc_iso(value: dt.datetime | None = None) -> str:
    current = value or _utc_now()
    return current.astimezone(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_iso(value: Any) -> dt.datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def sha256_value(value: Any) -> str:
    return _HASH_PREFIX + hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def prompt_hash(prompt: str) -> str:
    return _HASH_PREFIX + hashlib.sha256(str(prompt or "").encode("utf-8")).hexdigest()


def args_hash(args: dict[str, Any]) -> str:
    filtered = {
        str(key): value
        for key, value in (args if isinstance(args, dict) else {}).items()
        if str(key) not in {"_capabilityGrant", "_confirmed"}
    }
    return sha256_value(filtered)


def _derive_key(device_secret: str) -> bytes:
    secret = str(device_secret or "").strip()
    if len(secret) < 16:
        raise TrustError("DEVICE_SECRET_MISSING", "Görev güven anahtarı hazır değil.")
    return hmac.new(secret.encode("utf-8"), b"elyan.execution-trust.v1", hashlib.sha256).digest()


def _sign(payload: dict[str, Any], device_secret: str) -> str:
    digest = hmac.new(_derive_key(device_secret), _canonical_json(payload).encode("utf-8"), hashlib.sha256).hexdigest()
    return _SIGNATURE_PREFIX + digest


def _verify_signature(payload: dict[str, Any], signature: Any, device_secret: str) -> bool:
    expected = _sign(payload, device_secret)
    supplied = str(signature or "")
    return len(supplied) == len(expected) and hmac.compare_digest(supplied, expected)


def _work_order_binding(order: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": V2_SCHEMA,
        "userId": str(order.get("userId", "") or ""),
        "taskId": str(order.get("taskId", "") or ""),
        "revision": int(order.get("revision", 0) or 0),
        "deviceId": str(order.get("deviceId", "") or ""),
        "promptHash": str(order.get("promptHash", "") or ""),
        "planHash": str(order.get("planHash", "") or ""),
        "capabilityScope": list(order.get("capabilityScope", []) or []),
        "expiresAt": str(order.get("expiresAt", "") or ""),
        "nonce": str(order.get("nonce", "") or ""),
    }


def _grant_binding(grant: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": GRANT_SCHEMA,
        "grantId": str(grant.get("grantId", "") or ""),
        "userId": str(grant.get("userId", "") or ""),
        "taskId": str(grant.get("taskId", "") or ""),
        "revision": int(grant.get("revision", 0) or 0),
        "stepId": str(grant.get("stepId", "") or ""),
        "capability": canonical_capability(grant.get("capability")),
        "argsHash": str(grant.get("argsHash", "") or ""),
        "expiresAt": str(grant.get("expiresAt", "") or ""),
        "nonce": str(grant.get("nonce", "") or ""),
    }


def _ledger_path() -> Path:
    return Path(state_store.STATE_PATH).parent / "execution_ledger.sqlite3"


class ExecutionLedger:
    def __init__(self, path: Path | None = None) -> None:
        self.path = Path(path) if path is not None else _ledger_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS work_orders (
                    user_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    device_id TEXT NOT NULL,
                    prompt_hash TEXT NOT NULL,
                    plan_hash TEXT NOT NULL,
                    capability_scope TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    nonce_hash TEXT NOT NULL UNIQUE,
                    nonce TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, task_id, revision),
                    UNIQUE (task_id, revision)
                );
                CREATE TABLE IF NOT EXISTS deliveries (
                    user_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    claimed_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, task_id, revision),
                    FOREIGN KEY (user_id, task_id, revision)
                      REFERENCES work_orders(user_id, task_id, revision)
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    user_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    decision TEXT NOT NULL,
                    approval_nonce_hash TEXT NOT NULL UNIQUE,
                    claimed_at TEXT NOT NULL,
                    PRIMARY KEY (user_id, task_id, revision),
                    FOREIGN KEY (user_id, task_id, revision)
                      REFERENCES work_orders(user_id, task_id, revision)
                );
                CREATE TABLE IF NOT EXISTS capability_grants (
                    grant_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    step_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    args_hash TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    nonce_hash TEXT NOT NULL UNIQUE,
                    nonce TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    consumed_at TEXT,
                    completed_at TEXT,
                    UNIQUE (user_id, task_id, revision, step_id, capability, args_hash),
                    FOREIGN KEY (user_id, task_id, revision)
                      REFERENCES work_orders(user_id, task_id, revision)
                );
                CREATE TABLE IF NOT EXISTS effects (
                    grant_id TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    step_id TEXT NOT NULL,
                    capability TEXT NOT NULL,
                    args_hash TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_hash TEXT NOT NULL DEFAULT '',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    FOREIGN KEY (grant_id) REFERENCES capability_grants(grant_id)
                );
                """
            )
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def get_work_order_binding(self, user_id: str, task_id: str, revision: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM work_orders WHERE user_id=? AND task_id=? AND revision=?",
                (user_id, task_id, revision),
            ).fetchone()
        if row is None:
            return None
        return {
            "schema": V2_SCHEMA,
            "userId": row["user_id"],
            "taskId": row["task_id"],
            "revision": row["revision"],
            "deviceId": row["device_id"],
            "promptHash": row["prompt_hash"],
            "planHash": row["plan_hash"],
            "capabilityScope": json.loads(row["capability_scope"]),
            "expiresAt": row["expires_at"],
            "nonce": row["nonce"],
            "signature": row["signature"],
        }

    def register_work_order(self, order: dict[str, Any]) -> None:
        binding = _work_order_binding(order)
        nonce_hash = sha256_value(binding["nonce"])
        values = (
            binding["userId"], binding["taskId"], binding["revision"], binding["deviceId"],
            binding["promptHash"], binding["planHash"], _canonical_json(binding["capabilityScope"]),
            binding["expiresAt"], nonce_hash, binding["nonce"], str(order.get("signature", "") or ""), _utc_iso(),
        )
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing_owner = connection.execute(
                "SELECT user_id FROM work_orders WHERE task_id=? AND revision=?",
                (binding["taskId"], binding["revision"]),
            ).fetchone()
            if existing_owner is not None and existing_owner["user_id"] != binding["userId"]:
                raise TrustError("CROSS_USER_TASK_MISMATCH", "Görev başka bir kullanıcıya ait.")
            existing = connection.execute(
                "SELECT * FROM work_orders WHERE user_id=? AND task_id=? AND revision=?",
                (binding["userId"], binding["taskId"], binding["revision"]),
            ).fetchone()
            if existing is None:
                connection.execute(
                    """INSERT INTO work_orders
                    (user_id,task_id,revision,device_id,prompt_hash,plan_hash,capability_scope,
                     expires_at,nonce_hash,nonce,signature,created_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    values,
                )
            else:
                current = (
                    existing["device_id"], existing["prompt_hash"], existing["plan_hash"],
                    existing["capability_scope"], existing["expires_at"], existing["nonce_hash"], existing["signature"],
                )
                incoming = (
                    binding["deviceId"], binding["promptHash"], binding["planHash"],
                    _canonical_json(binding["capabilityScope"]), binding["expiresAt"], nonce_hash, str(order.get("signature", "") or ""),
                )
                if current != incoming:
                    raise TrustError("WORK_ORDER_REVISION_MISMATCH", "İş emri aynı revision için değiştirildi.")
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise TrustError("WORK_ORDER_NONCE_REPLAY", "İş emri nonce değeri daha önce kullanılmış.") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def claim_delivery(self, order: dict[str, Any]) -> DeliveryClaim:
        binding = _work_order_binding(order)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM deliveries WHERE user_id=? AND task_id=? AND revision=?",
                (binding["userId"], binding["taskId"], binding["revision"]),
            ).fetchone()
            if row is not None:
                connection.commit()
                return DeliveryClaim(False, str(row["status"]))
            now = _utc_iso()
            connection.execute(
                "INSERT INTO deliveries(user_id,task_id,revision,status,claimed_at,updated_at) VALUES(?,?,?,?,?,?)",
                (binding["userId"], binding["taskId"], binding["revision"], "executing", now, now),
            )
            connection.commit()
            return DeliveryClaim(True, "executing")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def set_delivery_status(self, user_id: str, task_id: str, revision: int, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE deliveries SET status=?, updated_at=? WHERE user_id=? AND task_id=? AND revision=?",
                (str(status or "failed")[:32], _utc_iso(), user_id, task_id, revision),
            )

    def claim_approval(self, order: dict[str, Any], approved: bool) -> bool:
        binding = _work_order_binding(order)
        _assert_not_expired(binding["expiresAt"], "WORK_ORDER_EXPIRED")
        decision = "approved" if approved else "rejected"
        approval_nonce = sha256_value(f"{binding['nonce']}:{decision}")
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT decision FROM approvals WHERE user_id=? AND task_id=? AND revision=?",
                (binding["userId"], binding["taskId"], binding["revision"]),
            ).fetchone()
            if existing is not None:
                if existing["decision"] != decision:
                    raise TrustError("APPROVAL_DECISION_MISMATCH", "Görev onay kararı daha önce kesinleşmiş.")
                connection.commit()
                return False
            connection.execute(
                "INSERT INTO approvals(user_id,task_id,revision,decision,approval_nonce_hash,claimed_at) VALUES(?,?,?,?,?,?)",
                (binding["userId"], binding["taskId"], binding["revision"], decision, approval_nonce, _utc_iso()),
            )
            connection.execute(
                "UPDATE deliveries SET status=?, updated_at=? WHERE user_id=? AND task_id=? AND revision=?",
                ("executing" if approved else "canceled", _utc_iso(), binding["userId"], binding["taskId"], binding["revision"]),
            )
            connection.commit()
            return True
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise TrustError("APPROVAL_NONCE_REPLAY", "Onay nonce değeri daha önce kullanılmış.") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def issue_grant(
        self,
        order: dict[str, Any],
        *,
        step_id: str,
        capability: str,
        args: dict[str, Any],
        device_secret: str,
    ) -> dict[str, Any]:
        binding = _work_order_binding(order)
        _assert_not_expired(binding["expiresAt"], "WORK_ORDER_EXPIRED")
        normalized_capability = canonical_capability(capability)
        if normalized_capability not in set(binding["capabilityScope"]):
            raise TrustError("CAPABILITY_SCOPE_MISMATCH", "Capability iş emri kapsamı dışında.")
        normalized_step_id = str(step_id or "").strip()
        if not normalized_step_id:
            raise TrustError("STEP_ID_MISSING", "CapabilityGrant stepId alanı eksik.")
        digest = args_hash(args)
        with self._connect() as connection:
            existing = connection.execute(
                """SELECT * FROM capability_grants
                   WHERE user_id=? AND task_id=? AND revision=? AND step_id=? AND capability=? AND args_hash=?""",
                (binding["userId"], binding["taskId"], binding["revision"], normalized_step_id, normalized_capability, digest),
            ).fetchone()
        if existing is not None:
            if existing["status"] != "issued":
                raise TrustError("CAPABILITY_GRANT_REPLAY", "CapabilityGrant daha önce kullanılmış.")
            return _grant_from_row(existing)

        nonce = secrets.token_urlsafe(24)
        grant_id = "grant_" + secrets.token_hex(16)
        grant = {
            "schema": GRANT_SCHEMA,
            "grantId": grant_id,
            "userId": binding["userId"],
            "taskId": binding["taskId"],
            "revision": binding["revision"],
            "stepId": normalized_step_id,
            "capability": normalized_capability,
            "argsHash": digest,
            "expiresAt": binding["expiresAt"],
            "nonce": nonce,
        }
        grant["signature"] = _sign(_grant_binding(grant), device_secret)
        try:
            with self._connect() as connection:
                connection.execute(
                    """INSERT INTO capability_grants
                    (grant_id,user_id,task_id,revision,step_id,capability,args_hash,expires_at,
                     nonce_hash,nonce,signature,status,created_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        grant_id, binding["userId"], binding["taskId"], binding["revision"],
                        normalized_step_id, normalized_capability, digest, binding["expiresAt"],
                        sha256_value(nonce), nonce, grant["signature"], "issued", _utc_iso(),
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise TrustError("CAPABILITY_GRANT_REPLAY", "CapabilityGrant tekrar üretilemedi.") from exc
        return grant

    def consume_grant(
        self,
        grant: dict[str, Any],
        *,
        capability: str,
        args: dict[str, Any],
        trust_context: dict[str, Any],
        device_secret: str,
    ) -> None:
        verify_capability_grant(
            grant,
            capability=capability,
            args=args,
            trust_context=trust_context,
            device_secret=device_secret,
        )
        binding = _grant_binding(grant)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT status FROM capability_grants WHERE grant_id=? AND user_id=? AND task_id=? AND revision=?",
                (binding["grantId"], binding["userId"], binding["taskId"], binding["revision"]),
            ).fetchone()
            if row is None:
                raise TrustError("CAPABILITY_GRANT_UNKNOWN", "CapabilityGrant ledger içinde bulunamadı.")
            if row["status"] != "issued":
                raise TrustError("CAPABILITY_GRANT_REPLAY", "CapabilityGrant daha önce kullanılmış.")
            now = _utc_iso()
            connection.execute(
                "UPDATE capability_grants SET status='consumed', consumed_at=? WHERE grant_id=? AND status='issued'",
                (now, binding["grantId"]),
            )
            connection.execute(
                """INSERT INTO effects
                (grant_id,user_id,task_id,revision,step_id,capability,args_hash,status,started_at)
                VALUES(?,?,?,?,?,?,?,?,?)""",
                (
                    binding["grantId"], binding["userId"], binding["taskId"], binding["revision"],
                    binding["stepId"], binding["capability"], binding["argsHash"], "executing", now,
                ),
            )
            connection.commit()
        except sqlite3.IntegrityError as exc:
            connection.rollback()
            raise TrustError("CAPABILITY_EFFECT_REPLAY", "Capability yan etkisi daha önce başlatılmış.") from exc
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def finish_grant(self, grant_id: str, *, ok: bool, result: Any = None) -> None:
        result_digest = sha256_value(_safe_result_fingerprint(result)) if result is not None else ""
        status = "completed" if ok else "failed"
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            now = _utc_iso()
            connection.execute(
                "UPDATE effects SET status=?, result_hash=?, completed_at=? WHERE grant_id=? AND status='executing'",
                (status, result_digest, now, grant_id),
            )
            connection.execute(
                "UPDATE capability_grants SET status=?, completed_at=? WHERE grant_id=? AND status='consumed'",
                (status, now, grant_id),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def _grant_from_row(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "schema": GRANT_SCHEMA,
        "grantId": row["grant_id"],
        "userId": row["user_id"],
        "taskId": row["task_id"],
        "revision": row["revision"],
        "stepId": row["step_id"],
        "capability": row["capability"],
        "argsHash": row["args_hash"],
        "expiresAt": row["expires_at"],
        "nonce": row["nonce"],
        "signature": row["signature"],
    }


def _safe_result_fingerprint(result: Any) -> dict[str, Any]:
    if not isinstance(result, dict):
        return {"type": type(result).__name__}
    error = result.get("error") if isinstance(result.get("error"), dict) else {}
    return {
        "ok": result.get("ok") is True,
        "tool": str(result.get("tool", "") or ""),
        "errorCode": str(error.get("code", "") or result.get("errorCode", "") or ""),
        "artifactCount": len(result.get("artifacts", [])) if isinstance(result.get("artifacts"), list) else 0,
    }


def _assert_not_expired(expires_at: Any, code: str) -> None:
    parsed = _parse_iso(expires_at)
    if parsed is None or parsed <= _utc_now():
        raise TrustError(code, "Görev yetkisi sona ermiş.")


def _capability_scope(work_order: dict[str, Any]) -> list[str]:
    values: list[Any] = []
    raw_scope = work_order.get("requiredCapabilities")
    if isinstance(raw_scope, list):
        values.extend(raw_scope)
    preview = work_order.get("planPreview")
    steps = preview.get("steps", []) if isinstance(preview, dict) else []
    for step in steps if isinstance(steps, list) else []:
        if isinstance(step, dict):
            values.append(step.get("capability"))
    return sorted({canonical_capability(value) for value in values if canonical_capability(value)})


def prepare_work_order_v2(
    task: dict[str, Any],
    work_order: dict[str, Any],
    *,
    prompt: str,
    state: dict[str, Any],
    ledger: ExecutionLedger | None = None,
) -> dict[str, Any]:
    runtime = state.get("runtime", {}) if isinstance(state, dict) else {}
    runtime = runtime if isinstance(runtime, dict) else {}
    user_id = str(task.get("userId", "") or "").strip()
    task_id = str(task.get("id", "") or "").strip()
    device_id = str(runtime.get("deviceId", "") or "").strip()
    target_device_id = str(task.get("targetDeviceId", "") or "").strip()
    device_secret = str(runtime.get("deviceSecret", "") or "").strip()
    if not user_id:
        raise TrustError("WORK_ORDER_USER_MISSING", "İş emri kullanıcı kimliğine bağlanamadı.")
    if not task_id:
        raise TrustError("WORK_ORDER_TASK_MISSING", "İş emri görev kimliğine bağlanamadı.")
    if not device_id or not target_device_id or device_id != target_device_id:
        raise TrustError("WORK_ORDER_DEVICE_MISMATCH", "İş emri bu masaüstü cihazına ait değil.")
    _derive_key(device_secret)
    try:
        revision = int(work_order.get("revision", task.get("revision", 1)) or 1)
    except (TypeError, ValueError) as exc:
        raise TrustError("WORK_ORDER_REVISION_INVALID", "İş emri revision alanı geçersiz.") from exc
    if revision < 1:
        raise TrustError("WORK_ORDER_REVISION_INVALID", "İş emri revision alanı geçersiz.")

    scope = _capability_scope(work_order)
    if not scope:
        raise TrustError("WORK_ORDER_SCOPE_MISSING", "İş emri capability kapsamı boş.")
    expected_prompt_hash = prompt_hash(prompt)
    expected_plan_hash = sha256_value(work_order.get("planPreview", {}))
    store = ledger or ExecutionLedger()
    persisted = store.get_work_order_binding(user_id, task_id, revision)
    if persisted is not None:
        order = {**work_order, **persisted}
    else:
        expiry = _parse_iso(
            work_order.get("expiresAt")
            or task.get("dispatchLeaseExpiresAt")
            or task.get("leaseExpiresAt")
        )
        if expiry is None:
            expiry = _utc_now() + dt.timedelta(seconds=DEFAULT_WORK_ORDER_TTL_SECONDS)
        if expiry <= _utc_now():
            raise TrustError("WORK_ORDER_EXPIRED", "İş emri teslim alınmadan sona ermiş.")
        order = {
            **work_order,
            "schema": V2_SCHEMA,
            "userId": user_id,
            "taskId": task_id,
            "revision": revision,
            "deviceId": device_id,
            "promptHash": expected_prompt_hash,
            "planHash": expected_plan_hash,
            "capabilityScope": scope,
            "expiresAt": _utc_iso(expiry),
            "nonce": secrets.token_urlsafe(24),
        }
        order["signature"] = _sign(_work_order_binding(order), device_secret)

    expected = {
        "userId": user_id,
        "taskId": task_id,
        "revision": revision,
        "deviceId": device_id,
        "promptHash": expected_prompt_hash,
        "planHash": expected_plan_hash,
        "capabilityScope": scope,
    }
    for key, value in expected.items():
        if order.get(key) != value:
            raise TrustError("WORK_ORDER_BINDING_MISMATCH", f"İş emri {key} alanı yürütme bağlamıyla uyuşmuyor.")
    _assert_not_expired(order.get("expiresAt"), "WORK_ORDER_EXPIRED")
    if not _verify_signature(_work_order_binding(order), order.get("signature"), device_secret):
        raise TrustError("WORK_ORDER_SIGNATURE_INVALID", "İş emri imzası doğrulanamadı.")
    store.register_work_order(order)
    return order


def verify_capability_grant(
    grant: dict[str, Any],
    *,
    capability: str,
    args: dict[str, Any],
    trust_context: dict[str, Any],
    device_secret: str,
) -> None:
    if not isinstance(grant, dict) or grant.get("schema") != GRANT_SCHEMA:
        raise TrustError("CAPABILITY_GRANT_MISSING", "CapabilityGrant eksik veya geçersiz.")
    binding = _grant_binding(grant)
    expected = {
        "userId": str(trust_context.get("userId", "") or ""),
        "taskId": str(trust_context.get("taskId", "") or ""),
        "revision": int(trust_context.get("revision", 0) or 0),
        "stepId": str(trust_context.get("stepId", "") or ""),
        "capability": canonical_capability(capability),
        "argsHash": args_hash(args),
    }
    for key, value in expected.items():
        if binding.get(key) != value:
            raise TrustError("CAPABILITY_GRANT_BINDING_MISMATCH", f"CapabilityGrant {key} alanı uyuşmuyor.")
    _assert_not_expired(binding["expiresAt"], "CAPABILITY_GRANT_EXPIRED")
    if not _verify_signature(binding, grant.get("signature"), device_secret):
        raise TrustError("CAPABILITY_GRANT_SIGNATURE_INVALID", "CapabilityGrant imzası doğrulanamadı.")


def verify_grant_for_policy(tool_name: str, args: dict[str, Any], state: dict[str, Any]) -> TrustError | None:
    runtime = state.get("runtime", {}) if isinstance(state, dict) else {}
    runtime = runtime if isinstance(runtime, dict) else {}
    trust_context = runtime.get("executionTrust")
    if not isinstance(trust_context, dict) or not trust_context:
        return None
    try:
        verify_capability_grant(
            args.get("_capabilityGrant") if isinstance(args.get("_capabilityGrant"), dict) else {},
            capability=tool_name,
            args=args,
            trust_context=trust_context,
            device_secret=str(runtime.get("deviceSecret", "") or ""),
        )
    except TrustError as exc:
        return exc
    return None


def consume_grant_for_call(tool_name: str, args: dict[str, Any], state: dict[str, Any]) -> TrustError | None:
    runtime = state.get("runtime", {}) if isinstance(state, dict) else {}
    runtime = runtime if isinstance(runtime, dict) else {}
    trust_context = runtime.get("executionTrust")
    if not isinstance(trust_context, dict) or not trust_context:
        return None
    grant = args.get("_capabilityGrant") if isinstance(args.get("_capabilityGrant"), dict) else {}
    try:
        ExecutionLedger().consume_grant(
            grant,
            capability=tool_name,
            args=args,
            trust_context=trust_context,
            device_secret=str(runtime.get("deviceSecret", "") or ""),
        )
    except TrustError as exc:
        return exc
    return None


def finish_grant_for_call(args: dict[str, Any], *, ok: bool, result: Any = None) -> None:
    grant = args.get("_capabilityGrant") if isinstance(args.get("_capabilityGrant"), dict) else {}
    grant_id = str(grant.get("grantId", "") or "")
    if grant_id:
        ExecutionLedger().finish_grant(grant_id, ok=ok, result=result)
