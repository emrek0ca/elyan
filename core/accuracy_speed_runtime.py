from __future__ import annotations

import hashlib
import time
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class AccuracySpeedDecision:
    request_kind: str
    provider_lane: str
    latency_budget_ms: int
    accuracy_budget: str
    verification_level: str
    fallback_policy: str
    cache_policy: str
    cache_namespace: str
    response_mode: str = "single_shot"
    typing_profile_ms: int = 220
    immediate_ack: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CollaborationDecision:
    enabled: bool
    strategy: str
    max_models: int
    synthesis_role: str
    execution_style: str
    lenses: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class AccuracySpeedRuntime:
    def __init__(self) -> None:
        self._last_decision: dict[str, Any] = {}
        self._lane_metrics: dict[str, dict[str, Any]] = {}

    def plan_for_text(
        self,
        *,
        text: str,
        request_kind: str = "chat",
        channel_type: str = "desktop",
        privacy_mode: str = "balanced",
        has_attachments: bool = False,
        force_verified: bool = False,
    ) -> AccuracySpeedDecision:
        low = str(text or "").strip().lower()
        kind = str(request_kind or "chat").strip().lower() or "chat"
        if kind == "computer_use" or any(token in low for token in ("tıkla", "tikla", "click", "screenshot", "ekran", "browser", "ui")):
            lane = "vision_lane"
            decision = AccuracySpeedDecision(kind, "vision_hybrid", 2400, "high", "strong", "hybrid_turbo", "session_hot", "vision_target", "staged", 260, "Ekrana bakıyorum.")
        elif force_verified or kind in {"research", "document", "privacy"} or any(token in low for token in ("araştır", "research", "repo", "github", "pdf", "doc", "kaynak")):
            lane = "verified_lane"
            decision = AccuracySpeedDecision(kind, "verified_cloud", 1800, "high", "strict", "hybrid_turbo", "verified_result", "verified_read", "staged", 320, "Doğruluyorum.")
        elif len(low.split()) <= 6 and not has_attachments and kind in {"chat", "status"}:
            lane = "instant_lane"
            decision = AccuracySpeedDecision(kind, "local_fast", 250, "medium", "light", "local_first", "hot", "conversation_ack", "single_shot", 160, "Bakıyorum.")
        else:
            lane = "turbo_lane"
            decision = AccuracySpeedDecision(kind, "turbo_hybrid", 900, "balanced", "standard", "hybrid_turbo", "warm", "conversation_turn", "single_shot" if channel_type != "desktop" else "staged", 220, "Tamam, hallediyorum.")
        if privacy_mode == "maximum" and decision.provider_lane.endswith("cloud"):
            decision.provider_lane = "local_fast" if lane == "instant_lane" else "local_verified"
            decision.fallback_policy = "local_only"
        self._last_decision = {"lane": lane, "decision": decision.to_dict(), "ts": time.time()}
        return decision

    def provider_order(self, lane: str, *, local_first: bool = True) -> list[str]:
        lane_name = str(lane or "turbo_hybrid").strip().lower()
        if lane_name in {"vision_hybrid", "local_verified"}:
            return ["ollama", "groq", "google", "openai"] if local_first else ["groq", "google", "openai", "ollama"]
        if lane_name in {"verified_cloud", "verified"}:
            return ["groq", "google", "openai", "anthropic", "ollama"] if local_first else ["groq", "google", "openai", "anthropic", "ollama"]
        if lane_name in {"local_fast", "instant"}:
            return ["ollama", "groq", "google", "openai"]
        return ["ollama", "groq", "google", "openai", "anthropic"] if local_first else ["groq", "google", "openai", "anthropic", "ollama"]

    def record_execution(self, *, lane: str, latency_ms: float, success: bool, fallback_active: bool = False, verification_state: str = "standard") -> None:
        row = self._lane_metrics.setdefault(str(lane or "unknown"), {"count": 0, "success": 0, "latencies": [], "fallback_active": False, "verification_state": verification_state})
        row["count"] += 1
        if success:
            row["success"] += 1
        row["latencies"].append(float(latency_ms or 0.0))
        row["latencies"] = row["latencies"][-30:]
        row["fallback_active"] = bool(fallback_active)
        row["verification_state"] = str(verification_state or "standard")

    def get_status(self) -> dict[str, Any]:
        lane = str((self._last_decision.get("lane") if isinstance(self._last_decision, dict) else "") or "unknown")
        row = dict(self._lane_metrics.get(lane) or {})
        latencies = list(row.get("latencies") or [])
        avg_latency = sum(latencies) / len(latencies) if latencies else 0.0
        if avg_latency <= 0:
            bucket = "unknown"
        elif avg_latency < 300:
            bucket = "fast"
        elif avg_latency < 1200:
            bucket = "steady"
        else:
            bucket = "slow"
        return {
            "current_lane": lane,
            "last_decision": dict(self._last_decision.get("decision") or {}),
            "fallback_active": bool(row.get("fallback_active")),
            "verification_state": str(row.get("verification_state") or "standard"),
            "average_latency_bucket": bucket,
            "lane_metrics": {
                key: {
                    "count": value.get("count", 0),
                    "success_rate": round((float(value.get("success", 0)) / max(1, int(value.get("count", 0)))) * 100.0, 2),
                }
                for key, value in self._lane_metrics.items()
            },
        }

    def recommend_collaboration(
        self,
        *,
        text: str,
        request_kind: str = "chat",
        role: str = "inference",
        provider_lane: str = "",
        has_attachments: bool = False,
    ) -> CollaborationDecision:
        low = str(text or "").strip().lower()
        kind = str(request_kind or "chat").strip().lower() or "chat"
        role_name = str(role or "inference").strip().lower() or "inference"
        lane = str(provider_lane or "").strip().lower()

        if role_name in {"code", "code_worker", "coding"} or kind in {"code", "coding"} or any(token in low for token in ("kod", "code", "refactor", "implement", "bug", "test", "repo")):
            return CollaborationDecision(
                enabled=True,
                strategy="spec_build_review",
                max_models=3,
                synthesis_role="code",
                execution_style="parallel_synthesis",
                lenses=[
                    {"name": "planner", "instruction": "İstenen çıktının kapsamını, kabul kriterlerini ve eksik anlaşılma risklerini çıkar."},
                    {"name": "builder", "instruction": "Üretim kalitesinde çözüm yaklaşımı ve somut uygulama yönü ver."},
                    {"name": "critic", "instruction": "Regresyon, güvenlik, performans ve kalite açıklarını agresif şekilde denetle."},
                ],
            )
        if kind in {"research", "document"} or lane in {"verified_cloud", "local_verified"} or has_attachments or any(token in low for token in ("araştır", "arastir", "kaynak", "pdf", "doc", "belge", "rapor")):
            return CollaborationDecision(
                enabled=True,
                strategy="read_synthesize_verify",
                max_models=3,
                synthesis_role="reasoning",
                execution_style="parallel_synthesis",
                lenses=[
                    {"name": "reader", "instruction": "İsteğin bilgi çekirdeğini, kritik claim'leri ve gerekli kaynak tiplerini çıkar."},
                    {"name": "synthesizer", "instruction": "Güçlü, net ve kullanıcıya doğrudan fayda sağlayan sentez yaklaşımı kur."},
                    {"name": "verifier", "instruction": "Kaynak güveni, boş iddia ve doğrulama eksiklerini agresif şekilde tespit et."},
                ],
            )
        if kind == "computer_use" or lane == "vision_hybrid":
            return CollaborationDecision(
                enabled=True,
                strategy="plan_act_validate",
                max_models=3,
                synthesis_role="planning",
                execution_style="gated_parallel",
                lenses=[
                    {"name": "planner", "instruction": "UI görevinin doğru hedefini, alt adımlarını ve approval risklerini çıkar."},
                    {"name": "vision_validator", "instruction": "Yanlış hedef, stale UI ve no-visual-change risklerini denetle."},
                    {"name": "critic", "instruction": "Kör tıklama ve yanlış state geçişlerini engelle."},
                ],
            )
        if len(low.split()) >= 14 or role_name in {"reasoning", "planning", "critic", "qa"}:
            return CollaborationDecision(
                enabled=True,
                strategy="reason_then_critic",
                max_models=2,
                synthesis_role="reasoning",
                execution_style="parallel_synthesis",
                lenses=[
                    {"name": "planner", "instruction": "Kullanıcının gerçek amacını, teslim kriterlerini ve en kısa çözüm yolunu çıkar."},
                    {"name": "critic", "instruction": "Yanlış anlama, kalite açığı ve eksik adım risklerini denetle."},
                ],
            )
        return CollaborationDecision(
            enabled=False,
            strategy="single_fast",
            max_models=1,
            synthesis_role=role_name,
            execution_style="single_pass",
            lenses=[],
        )

    @staticmethod
    def make_scope_key(*parts: str) -> str:
        raw = "::".join(str(part or "").strip() for part in parts if str(part or "").strip())
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


_runtime: AccuracySpeedRuntime | None = None


def get_accuracy_speed_runtime() -> AccuracySpeedRuntime:
    global _runtime
    if _runtime is None:
        _runtime = AccuracySpeedRuntime()
    return _runtime


__all__ = ["AccuracySpeedDecision", "CollaborationDecision", "AccuracySpeedRuntime", "get_accuracy_speed_runtime"]
