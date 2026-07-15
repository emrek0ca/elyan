"""P5 — Kullanıcıya özel, izole öğrenme kayıtları.

Kurallar:
- Ham özel veri SAKLANMAZ: kullanıcı kimliği yalnız tek yönlü hash anahtarı
  olarak, görev içerikleri hiç tutulmaz; yalnız sayaçlar ve hata sınıfları.
- Kullanıcılar arası öğrenme YOKTUR: her kayıt kendi kullanıcı anahtarının
  altında yaşar; okuma API'leri yalnız o kullanıcının verisini döndürür.
- Sınırlar: capability ve hata sınıfı tabloları budanır; state şişmez.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable

from runtime import state_store

_MAX_CAPABILITIES = 64
_MAX_ERROR_CLASSES = 32


def _user_key(user_id: str) -> str:
    text = str(user_id or "").strip()
    if not text:
        return "local"
    return hashlib.sha256(f"elyan.learning.v1:{text}".encode("utf-8")).hexdigest()[:16]


def _learning_bucket(state: dict[str, Any], user_key: str) -> dict[str, Any]:
    intelligence = state.setdefault("taskIntelligence", {})
    if not isinstance(intelligence, dict):
        intelligence = {}
        state["taskIntelligence"] = intelligence
    learning = intelligence.setdefault("userLearning", {})
    if not isinstance(learning, dict):
        learning = {}
        intelligence["userLearning"] = learning
    bucket = learning.get(user_key)
    if not isinstance(bucket, dict):
        bucket = {
            "plansCompleted": 0,
            "plansFailed": 0,
            "replans": 0,
            "errorClasses": {},
            "capabilityStats": {},
            "lastSeenAt": "",
        }
        learning[user_key] = bucket
    return bucket


def _trim(table: dict[str, Any], limit: int) -> None:
    while len(table) > limit:
        table.pop(next(iter(table)))


def record_plan_outcome(
    user_id: str,
    *,
    ok: bool,
    error_class: str = "",
    capabilities: Iterable[str] = (),
    replans: int = 0,
) -> None:
    """Plan sonucunu ve capability başarı sayaçlarını kullanıcının kovasında günceller."""
    user_key = _user_key(user_id)
    error_class = str(error_class or "").strip()[:64]
    capability_names = [str(item or "").strip()[:80] for item in capabilities if str(item or "").strip()]
    with state_store._LOCK:
        state = state_store.load_state()
        bucket = _learning_bucket(state, user_key)
        if ok:
            bucket["plansCompleted"] = int(bucket.get("plansCompleted", 0) or 0) + 1
        else:
            bucket["plansFailed"] = int(bucket.get("plansFailed", 0) or 0) + 1
            if error_class:
                errors = bucket.setdefault("errorClasses", {})
                if isinstance(errors, dict):
                    errors[error_class] = int(errors.get(error_class, 0) or 0) + 1
                    _trim(errors, _MAX_ERROR_CLASSES)
        bucket["replans"] = int(bucket.get("replans", 0) or 0) + max(0, int(replans or 0))
        stats = bucket.setdefault("capabilityStats", {})
        if isinstance(stats, dict):
            for capability in capability_names:
                entry = stats.get(capability)
                if not isinstance(entry, dict):
                    entry = {"ok": 0, "fail": 0}
                if ok:
                    entry["ok"] = int(entry.get("ok", 0) or 0) + 1
                else:
                    entry["fail"] = int(entry.get("fail", 0) or 0) + 1
                stats[capability] = entry
            _trim(stats, _MAX_CAPABILITIES)
        bucket["lastSeenAt"] = state_store._intelligence_timestamp()
        state_store.save_state(state)


def user_learning_summary(user_id: str) -> dict[str, Any]:
    """Yalnız bu kullanıcının izole öğrenme özeti (salt-okunur kopya)."""
    user_key = _user_key(user_id)
    snapshot = state_store.snapshot()
    intelligence = snapshot.get("taskIntelligence", {})
    intelligence = intelligence if isinstance(intelligence, dict) else {}
    learning = intelligence.get("userLearning", {})
    learning = learning if isinstance(learning, dict) else {}
    bucket = learning.get(user_key)
    return dict(bucket) if isinstance(bucket, dict) else {}


def capability_success_rate(user_id: str, capability: str) -> float | None:
    """0..1 arası oran; hiç gözlem yoksa None (planner temkinli davranır)."""
    summary = user_learning_summary(user_id)
    stats = summary.get("capabilityStats", {})
    entry = stats.get(str(capability or "").strip()[:80]) if isinstance(stats, dict) else None
    if not isinstance(entry, dict):
        return None
    ok = int(entry.get("ok", 0) or 0)
    fail = int(entry.get("fail", 0) or 0)
    total = ok + fail
    if total <= 0:
        return None
    return ok / total
