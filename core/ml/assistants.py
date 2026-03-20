from __future__ import annotations

from pathlib import Path
from typing import Any


def _token_overlap(left: str, right: str) -> float:
    left_tokens = {tok for tok in str(left or "").lower().split() if tok}
    right_tokens = {tok for tok in str(right or "").lower().split() if tok}
    if not left_tokens or not right_tokens:
        return 0.0
    return len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))


class SourceQualityScorer:
    _TRUSTED_DOMAINS = {"openai.com", "pytorch.org", "python.org", "docs.python.org", "developer.mozilla.org", "wikipedia.org", "who.int"}

    def score(self, source: dict[str, Any]) -> dict[str, Any]:
        url = str(source.get("url") or "")
        reliability = float(source.get("reliability_score", 0.0) or 0.0)
        domain = url.split("/")[2].lower() if "://" in url else url.lower()
        score = reliability
        if any(domain.endswith(trusted) for trusted in self._TRUSTED_DOMAINS):
            score = max(score, 0.9)
        if domain.endswith(".gov") or domain.endswith(".edu"):
            score = max(score, 0.88)
        return {"domain": domain, "score": round(max(0.0, min(1.0, score or 0.35)), 4)}


class ClaimEvidenceMatcher:
    def match(self, claim: str, evidence_items: list[dict[str, Any]]) -> dict[str, Any]:
        ranked = []
        for item in evidence_items or []:
            text = str(item.get("text") or item.get("summary") or item.get("content") or "")
            ranked.append({"score": round(_token_overlap(claim, text), 4), "item": dict(item)})
        ranked.sort(key=lambda row: (-float(row["score"]), str(row["item"].get("id") or "")))
        return {"best_match": ranked[0] if ranked else None, "matches": ranked[:5]}


class HallucinationRiskScorer:
    def score(self, text: str, *, sources: list[dict[str, Any]] | None = None, evidence_matches: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        source_count = len(sources or [])
        best_match = max((float(item.get("score", 0.0) or 0.0) for item in evidence_matches or []), default=0.0)
        uncertainty_markers = sum(1 for marker in ("maybe", "possibly", "muhtemelen", "sanırım", "I think") if marker in str(text or "").lower())
        risk = 0.7
        if source_count > 0:
            risk -= min(0.25, source_count * 0.05)
        risk -= min(0.25, best_match * 0.4)
        risk += min(0.2, uncertainty_markers * 0.05)
        return {"risk_score": round(max(0.0, min(1.0, risk)), 4), "source_count": source_count, "best_match": round(best_match, 4)}


class RepoAwareEditRanker:
    def rank(self, request: str, files: list[str], *, workspace_hints: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        hints = dict(workspace_hints or {})
        preferred_dirs = {str(item).lower() for item in list(hints.get("preferred_dirs") or [])}
        ranked = []
        for file_path in files or []:
            path = Path(str(file_path))
            score = _token_overlap(request, path.name)
            if any(part.lower() in preferred_dirs for part in path.parts):
                score += 0.2
            ranked.append({"path": str(file_path), "score": round(min(1.0, score), 4)})
        ranked.sort(key=lambda row: (-float(row["score"]), str(row["path"])))
        return ranked


class TestImpactPredictor:
    def predict(self, changed_files: list[str], available_tests: list[str]) -> list[dict[str, Any]]:
        ranked = []
        changed_tokens = " ".join(Path(str(item)).stem for item in changed_files or [])
        for test_file in available_tests or []:
            score = _token_overlap(changed_tokens, Path(str(test_file)).stem)
            ranked.append({"test": str(test_file), "score": round(score, 4)})
        ranked.sort(key=lambda row: (-float(row["score"]), str(row["test"])))
        return ranked


class FixSuggestionReranker:
    def rank(self, issue: str, suggestions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        ranked = []
        for suggestion in suggestions or []:
            summary = str(suggestion.get("summary") or suggestion.get("text") or suggestion.get("title") or "")
            confidence = float(suggestion.get("confidence", 0.0) or 0.0)
            score = (_token_overlap(issue, summary) * 0.7) + (confidence * 0.3)
            ranked.append({"suggestion": dict(suggestion), "score": round(min(1.0, score), 4)})
        ranked.sort(key=lambda row: (-float(row["score"]), str(row["suggestion"].get("summary") or "")))
        return ranked
