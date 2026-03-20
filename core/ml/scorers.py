from __future__ import annotations

import math
import re
from typing import Any

from config.elyan_config import elyan_config
from core.reliability import get_confidence_calibrator


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, float(value)))


def _tokenize(text: str) -> list[str]:
    return [tok for tok in re.findall(r"[\w.-]+", str(text or "").lower(), flags=re.UNICODE) if tok]


def _as_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        try:
            mapped = value.to_dict()
            if isinstance(mapped, dict):
                return mapped
        except Exception:
            return {}
    return {}


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value.strip()
        else:
            raw = str(value).strip()
            if raw:
                return raw
    return ""


class IntentScorer:
    def __init__(self) -> None:
        self.calibrator = get_confidence_calibrator()

    def score(self, text: str, *, quick_intent: Any = None, parsed_intent: Any = None) -> dict[str, Any]:
        parsed = _as_mapping(parsed_intent)
        label = _first_non_empty(
            parsed.get("action"),
            parsed.get("intent"),
            parsed.get("primary_intent"),
            getattr(quick_intent, "value", None),
            quick_intent,
        )
        parsed_conf = parsed.get("confidence")
        raw_conf = 0.0
        source = "heuristic"
        reasons: list[str] = []

        if parsed_conf not in (None, ""):
            try:
                raw_conf = float(parsed_conf)
                source = "intent_parser"
                reasons.append("parser_confidence")
            except Exception:
                raw_conf = 0.0

        if raw_conf <= 0.0 and label:
            raw_conf = 0.74 if quick_intent is not None else 0.66
            source = "parser+quick_intent" if quick_intent is not None else "heuristic_label"
            reasons.append("label_detected")

        if not label:
            low = str(text or "").lower()
            if any(token in low for token in ("araştır", "arastir", "research", "kaynak")):
                label = "research"
                raw_conf = 0.62
                reasons.append("research_keyword")
            elif any(token in low for token in ("dosya", "kaydet", ".txt", ".md", "masaüst", "desktop")):
                label = "file"
                raw_conf = 0.58
                reasons.append("file_keyword")
            elif any(token in low for token in ("python", "kod", "code", "react", "typescript", "html")):
                label = "code"
                raw_conf = 0.61
                reasons.append("code_keyword")
            elif any(token in low for token in ("safari", "chrome", "tarayıcı", "browser", "openai.com", "http://", "https://")):
                label = "browser"
                raw_conf = 0.59
                reasons.append("browser_keyword")
            else:
                raw_conf = 0.36 if len(_tokenize(text)) >= 3 else 0.22
                reasons.append("low_signal")

        calibrated = self.calibrator.calibrate("intent_prediction", label or "unknown", raw_conf)
        should_clarify = calibrated < 0.55 and len(_tokenize(text)) >= 2
        advisory = "execute" if calibrated >= 0.68 else ("clarify" if should_clarify else "fallback")
        return {
            "label": label or "unknown",
            "confidence": round(calibrated, 4),
            "raw_confidence": round(raw_conf, 4),
            "source": source,
            "advisory": advisory,
            "should_clarify": should_clarify,
            "abstain": calibrated < 0.35,
            "reasons": reasons,
        }


class ClarificationClassifier:
    def classify(
        self,
        text: str,
        *,
        intent_prediction: dict[str, Any] | None = None,
        route_choice: dict[str, Any] | None = None,
        request_contract: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        req = dict(request_contract or {})
        intent = dict(intent_prediction or {})
        route = dict(route_choice or {})
        low = str(text or "").strip().lower()
        ambiguous_markers = ("bir şey", "yardım et", "hallet", "bakar mısın", "yardim et", "şunu yap", "sunu yap")
        should_clarify = bool(req.get("needs_clarification")) or bool(intent.get("should_clarify"))
        reasons: list[str] = []
        if bool(req.get("needs_clarification")):
            reasons.append("request_contract")
        if bool(intent.get("should_clarify")):
            reasons.append("low_intent_confidence")
        if any(marker in low for marker in ambiguous_markers):
            should_clarify = True
            reasons.append("ambiguous_user_request")
        confidence = 0.72 if should_clarify else 0.31
        if route.get("score", 0.0):
            confidence = _clamp((confidence + float(route.get("score", 0.0))) / 2.0)
        return {
            "decision": "clarify" if should_clarify else "proceed",
            "should_clarify": should_clarify,
            "confidence": round(confidence, 4),
            "question": str(req.get("clarifying_question") or "").strip(),
            "reasons": reasons,
        }


class ActionRanker:
    def rank(self, intent: dict[str, Any] | str, candidates: list[Any], context: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ctx = dict(context or {})
        intent_label = str(intent.get("label") if isinstance(intent, dict) else intent or "").strip().lower()
        route_decision = ctx.get("route_decision", {}) if isinstance(ctx.get("route_decision"), dict) else {}
        request_contract = ctx.get("request_contract", {}) if isinstance(ctx.get("request_contract"), dict) else {}
        capability_plan = ctx.get("capability_plan", {}) if isinstance(ctx.get("capability_plan"), dict) else {}
        ranked: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in candidates:
            candidate = str(raw.get("candidate") if isinstance(raw, dict) else raw or "").strip().lower()
            if not candidate or candidate in seen:
                continue
            seen.add(candidate)
            score = 0.2
            reasons: list[str] = []
            if intent_label and candidate == intent_label:
                score += 0.45
                reasons.append("intent_match")
            if candidate and candidate == str(route_decision.get("mode") or "").strip().lower():
                score += 0.25
                reasons.append("route_match")
            if candidate and candidate == str(request_contract.get("route_mode") or "").strip().lower():
                score += 0.2
                reasons.append("contract_match")
            if candidate and candidate == str(capability_plan.get("suggested_job_type") or "").strip().lower():
                score += 0.15
                reasons.append("capability_match")
            if candidate in {"chat", "communication"} and not reasons:
                score += 0.05
            ranked.append(
                {
                    "candidate": candidate,
                    "score": round(_clamp(score), 4),
                    "reasons": reasons or ["baseline"],
                }
            )
        ranked.sort(key=lambda item: (-float(item.get("score", 0.0)), str(item.get("candidate") or "")))
        if ranked:
            ranked[0]["selected"] = True
        return ranked


class Verifier:
    def __init__(self) -> None:
        evaluation_cfg = dict(elyan_config.get("evaluation", {}) or {})
        self.threshold = float(evaluation_cfg.get("verifier_threshold", 0.55) or 0.55)

    def score(self, task: Any, result: Any, evidence: Any = None) -> dict[str, Any]:
        task_map = _as_mapping(task)
        result_map = _as_mapping(result)
        evidence_list = list(evidence or [])
        text = _first_non_empty(
            result_map.get("text"),
            result_map.get("summary"),
            result_map.get("message"),
            result,
        )
        errors = list(result_map.get("errors") or [])
        status = str(result_map.get("status") or "").strip().lower()
        artifact_count = int(result_map.get("artifact_count") or 0)
        if artifact_count <= 0:
            artifacts = result_map.get("artifacts")
            if isinstance(artifacts, list):
                artifact_count = len([item for item in artifacts if item])
        evidence_count = len(evidence_list)
        requires_artifact = str(task_map.get("kind") or task_map.get("specialist") or "").strip().lower() in {
            "code",
            "browser",
            "file",
            "research",
            "data",
        }
        score = 0.45
        reasons: list[str] = []
        if status in {"success", "ok", "completed"}:
            score += 0.18
            reasons.append("success_status")
        if text:
            score += min(0.12, math.log(len(text) + 1, 10) * 0.08)
            reasons.append("response_text")
        if evidence_count > 0:
            score += min(0.15, evidence_count * 0.03)
            reasons.append("evidence_present")
        if artifact_count > 0:
            score += min(0.2, artifact_count * 0.06)
            reasons.append("artifacts_present")
        if errors:
            score -= 0.35
            reasons.append("errors_present")
        if "failed" in status:
            score -= 0.4
            reasons.append("failed_status")
        if requires_artifact and artifact_count <= 0 and evidence_count <= 0:
            score -= 0.28
            reasons.append("missing_required_artifact")
        normalized = _clamp(score)
        return {
            "ok": normalized >= self.threshold,
            "score": round(normalized, 4),
            "threshold": self.threshold,
            "reasons": reasons,
            "artifact_count": artifact_count,
            "evidence_count": evidence_count,
            "status": status or ("success" if normalized >= self.threshold else "uncertain"),
            "text_preview": str(text or "")[:220],
            "fallback": True,
        }


class SourceQualityScorer:
    def score(self, url: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        meta = dict(metadata or {})
        low = str(url or "").lower()
        score = 0.45
        if any(domain in low for domain in (".edu", ".gov", ".org")):
            score += 0.25
        if meta.get("citation_count"):
            score += min(0.2, float(meta.get("citation_count", 0) or 0) * 0.02)
        return {"score": round(_clamp(score), 4), "url": str(url or ""), "fallback": True}


class ClaimEvidenceMatcher:
    def score(self, claim: str, evidence: list[str] | None = None) -> dict[str, Any]:
        claim_tokens = set(_tokenize(claim))
        evidence_tokens = set(_tokenize(" ".join(evidence or [])))
        overlap = len(claim_tokens & evidence_tokens)
        denom = max(1, len(claim_tokens))
        return {"score": round(overlap / denom, 4), "fallback": True}


class HallucinationRiskScorer:
    def score(self, text: str, sources: list[str] | None = None) -> dict[str, Any]:
        source_count = len(list(sources or []))
        unsupported_claim = "kesin" in str(text or "").lower() and source_count == 0
        risk = 0.72 if unsupported_claim else (0.48 if source_count == 0 else 0.22)
        return {"risk": round(risk, 4), "fallback": True}


class RepoAwareEditRanker:
    def rank(self, candidates: list[str], query: str) -> list[dict[str, Any]]:
        query_tokens = set(_tokenize(query))
        ranked = []
        for candidate in candidates:
            score = 0.1
            name_tokens = set(_tokenize(candidate))
            score += len(query_tokens & name_tokens) * 0.15
            ranked.append({"candidate": candidate, "score": round(_clamp(score), 4), "fallback": True})
        return sorted(ranked, key=lambda item: (-item["score"], item["candidate"]))


class TestImpactPredictor:
    def predict(self, changed_files: list[str]) -> dict[str, Any]:
        impacted = [path for path in changed_files if "/tests/" in path or path.endswith(".py")]
        return {"impacted_tests": impacted, "confidence": 0.41 if impacted else 0.18, "fallback": True}


class FixSuggestionReranker:
    def rank(self, suggestions: list[str], error_text: str) -> list[dict[str, Any]]:
        error_tokens = set(_tokenize(error_text))
        ranked = []
        for suggestion in suggestions:
            tokens = set(_tokenize(suggestion))
            score = 0.12 + len(tokens & error_tokens) * 0.08
            ranked.append({"suggestion": suggestion, "score": round(_clamp(score), 4), "fallback": True})
        return sorted(ranked, key=lambda item: (-item["score"], item["suggestion"]))


_intent_scorer: IntentScorer | None = None
_clarification_classifier: ClarificationClassifier | None = None
_action_ranker: ActionRanker | None = None
_verifier: Verifier | None = None


def get_intent_scorer() -> IntentScorer:
    global _intent_scorer
    if _intent_scorer is None:
        _intent_scorer = IntentScorer()
    return _intent_scorer


def get_clarification_classifier() -> ClarificationClassifier:
    global _clarification_classifier
    if _clarification_classifier is None:
        _clarification_classifier = ClarificationClassifier()
    return _clarification_classifier


def get_action_ranker() -> ActionRanker:
    global _action_ranker
    if _action_ranker is None:
        _action_ranker = ActionRanker()
    return _action_ranker


def get_verifier() -> Verifier:
    global _verifier
    if _verifier is None:
        _verifier = Verifier()
    return _verifier
