"""
LLM Response Quality Evaluator

Comprehensive response quality assessment:
- Syntax validation (JSON, markdown, code)
- Semantic validation (meaning, correctness)
- Compliance checking (schema, format)
- Confidence estimation
- Quality scoring

Turkish/English support.
"""

import re
import json
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

from utils.logger import get_logger

logger = get_logger("llm_response_quality")


class ResponseFormat(Enum):
    """Expected response format"""
    TEXT = "text"
    JSON = "json"
    MARKDOWN = "markdown"
    CODE = "code"
    CSV = "csv"
    XML = "xml"


@dataclass
class ValidationResult:
    """Result of validation check"""
    passed: bool
    score: float  # 0.0-1.0
    message: str
    severity: str  # "error", "warning", "info"


@dataclass
class QualityScore:
    """Composite quality score"""
    syntax_score: float
    semantic_score: float
    compliance_score: float
    completeness_score: float
    overall_score: float
    confidence: float
    issues: List[str]
    recommendations: List[str]


class SyntaxValidator:
    """Validate response syntax"""

    @staticmethod
    def validate_json(text: str) -> ValidationResult:
        """Validate JSON syntax"""
        try:
            json.loads(text)
            return ValidationResult(
                passed=True,
                score=1.0,
                message="Valid JSON",
                severity="info"
            )
        except json.JSONDecodeError as e:
            return ValidationResult(
                passed=False,
                score=0.0,
                message=f"Invalid JSON: {str(e)}",
                severity="error"
            )

    @staticmethod
    def validate_markdown(text: str) -> ValidationResult:
        """Validate markdown structure"""
        if not text.strip():
            return ValidationResult(
                passed=False,
                score=0.0,
                message="Empty markdown",
                severity="error"
            )

        # Check for basic markdown markers
        has_headers = bool(re.search(r'^#+\s', text, re.MULTILINE))
        has_lists = bool(re.search(r'^[-*+]\s', text, re.MULTILINE))
        has_emphasis = bool(re.search(r'\*\*.*?\*\*|__.*?__', text))

        score = 0.3  # Baseline for valid markdown text
        if has_headers:
            score += 0.3
        if has_lists:
            score += 0.2
        if has_emphasis:
            score += 0.2

        return ValidationResult(
            passed=True,
            score=min(1.0, score),
            message=f"Valid markdown (headers: {has_headers}, lists: {has_lists})",
            severity="info"
        )

    @staticmethod
    def validate_code(text: str, language: str = "python") -> ValidationResult:
        """Validate code syntax"""
        if not text.strip():
            return ValidationResult(
                passed=False,
                score=0.0,
                message="Empty code",
                severity="error"
            )

        if language == "python":
            try:
                compile(text, "<string>", "exec")
                return ValidationResult(
                    passed=True,
                    score=1.0,
                    message="Valid Python code",
                    severity="info"
                )
            except SyntaxError as e:
                return ValidationResult(
                    passed=False,
                    score=0.0,
                    message=f"Python syntax error: {str(e)}",
                    severity="error"
                )

        # For other languages, do basic checks
        if language in ["javascript", "typescript"]:
            if text.count("{") != text.count("}"):
                return ValidationResult(
                    passed=False,
                    score=0.3,
                    message="Unmatched braces",
                    severity="warning"
                )

        return ValidationResult(
            passed=True,
            score=0.7,
            message=f"Likely valid {language}",
            severity="info"
        )


class SemanticValidator:
    """Validate response semantics"""

    @staticmethod
    def check_completeness(text: str, min_length: int = 10) -> ValidationResult:
        """Check if response is complete"""
        stripped = text.strip()
        if len(stripped) < min_length:
            return ValidationResult(
                passed=False,
                score=0.0,
                message=f"Response too short ({len(stripped)} chars, min {min_length})",
                severity="warning"
            )

        # Check for common truncation patterns
        if any(text.endswith(x) for x in ["...", "incomplete", "more", "not complete"]):
            return ValidationResult(
                passed=False,
                score=0.5,
                message="Response appears truncated",
                severity="warning"
            )

        return ValidationResult(
            passed=True,
            score=1.0,
            message="Response appears complete",
            severity="info"
        )

    @staticmethod
    def check_coherence(text: str) -> ValidationResult:
        """Check if response is coherent"""
        lines = text.strip().split('\n')
        if len(lines) < 2:
            return ValidationResult(
                passed=True,
                score=0.5,
                message="Single line response",
                severity="info"
            )

        # Check for very short lines (might be corrupted)
        short_lines = sum(1 for line in lines if len(line.strip()) < 3)
        short_ratio = short_lines / len(lines)

        if short_ratio > 0.5:
            return ValidationResult(
                passed=False,
                score=0.4,
                message=f"Many very short lines ({short_ratio:.0%})",
                severity="warning"
            )

        return ValidationResult(
            passed=True,
            score=0.9,
            message="Response appears coherent",
            severity="info"
        )

    @staticmethod
    def check_relevance(text: str, keywords: List[str]) -> ValidationResult:
        """Check if response is relevant to keywords"""
        if not keywords:
            return ValidationResult(
                passed=True,
                score=0.5,
                message="No keywords provided",
                severity="info"
            )

        text_lower = text.lower()
        matches = sum(1 for kw in keywords if kw.lower() in text_lower)
        relevance_score = matches / len(keywords) if keywords else 0.5

        if relevance_score < 0.3:
            return ValidationResult(
                passed=False,
                score=relevance_score,
                message=f"Low relevance: only {matches}/{len(keywords)} keywords found",
                severity="warning"
            )

        return ValidationResult(
            passed=True,
            score=relevance_score,
            message=f"Relevant: {matches}/{len(keywords)} keywords found",
            severity="info"
        )


class ComplianceChecker:
    """Check response compliance with schema"""

    @staticmethod
    def validate_against_schema(response: Any, schema: Dict[str, Any]) -> ValidationResult:
        """Validate response against JSON schema"""
        if not isinstance(response, dict):
            return ValidationResult(
                passed=False,
                score=0.0,
                message="Response is not a dictionary",
                severity="error"
            )

        required_fields = schema.get("required", [])
        missing_fields = [f for f in required_fields if f not in response]

        if missing_fields:
            return ValidationResult(
                passed=False,
                score=0.5,
                message=f"Missing required fields: {missing_fields}",
                severity="error"
            )

        # Check field types
        properties = schema.get("properties", {})
        type_errors = []
        for field, field_schema in properties.items():
            if field in response:
                expected_type = field_schema.get("type")
                actual_type = type(response[field]).__name__
                if expected_type and not ComplianceChecker._type_matches(
                    response[field], expected_type
                ):
                    type_errors.append(
                        f"{field}: expected {expected_type}, got {actual_type}"
                    )

        if type_errors:
            return ValidationResult(
                passed=False,
                score=0.7,
                message=f"Type mismatches: {'; '.join(type_errors)}",
                severity="warning"
            )

        return ValidationResult(
            passed=True,
            score=1.0,
            message="Complies with schema",
            severity="info"
        )

    @staticmethod
    def _type_matches(value: Any, expected_type: str) -> bool:
        """Check if value matches expected type"""
        type_map = {
            "string": str,
            "number": (int, float),
            "integer": int,
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        expected = type_map.get(expected_type.lower())
        return isinstance(value, expected) if expected else True


class ConfidenceEstimator:
    """Estimate confidence in response"""

    @staticmethod
    def estimate_confidence(
        text: str,
        format_type: ResponseFormat = ResponseFormat.TEXT
    ) -> float:
        """Estimate confidence in response quality"""
        confidence = 0.5  # Baseline

        # Length confidence
        if 20 < len(text) < 5000:
            confidence += 0.1
        elif len(text) >= 5000:
            confidence += 0.15

        # Format-specific confidence
        if format_type == ResponseFormat.JSON:
            try:
                json.loads(text)
                confidence += 0.2
            except:
                confidence -= 0.3

        elif format_type == ResponseFormat.CODE:
            if any(kw in text for kw in ["def ", "class ", "import ", "function "]):
                confidence += 0.15
            if text.count("\n") > 3:
                confidence += 0.05

        elif format_type == ResponseFormat.MARKDOWN:
            if re.search(r'^#+\s', text, re.MULTILINE):
                confidence += 0.1
            if text.count("\n") > 5:
                confidence += 0.05

        # Check for uncertainty markers
        uncertainty_phrases = [
            "i'm not sure", "i don't know", "unclear", "uncertain",
            "might be", "probably", "possibly", "maybe",
            "i think", "i believe", "seems like"
        ]
        if any(phrase in text.lower() for phrase in uncertainty_phrases):
            confidence -= 0.1

        # Check for error indicators
        if any(indicator in text.lower() for indicator in ["error", "failed", "incorrect"]):
            confidence -= 0.05

        return max(0.0, min(1.0, confidence))


class ResponseEvaluator:
    """Comprehensive response quality evaluator"""

    def __init__(self):
        self.syntax_validator = SyntaxValidator()
        self.semantic_validator = SemanticValidator()
        self.compliance_checker = ComplianceChecker()
        self.confidence_estimator = ConfidenceEstimator()

    def evaluate(
        self,
        response: str,
        format_type: ResponseFormat = ResponseFormat.TEXT,
        schema: Optional[Dict[str, Any]] = None,
        keywords: Optional[List[str]] = None,
        min_length: int = 10
    ) -> QualityScore:
        """Evaluate response quality comprehensively"""
        scores = []
        issues = []
        recommendations = []

        # Syntax validation
        syntax_result = self._validate_syntax(response, format_type)
        scores.append(("syntax", syntax_result.score))
        if not syntax_result.passed:
            issues.append(syntax_result.message)
            recommendations.append("Check response syntax")

        # Semantic validation
        completeness_result = self.semantic_validator.check_completeness(
            response, min_length
        )
        scores.append(("completeness", completeness_result.score))
        if not completeness_result.passed:
            issues.append(completeness_result.message)

        coherence_result = self.semantic_validator.check_coherence(response)
        scores.append(("coherence", coherence_result.score))
        if not coherence_result.passed:
            issues.append(coherence_result.message)
            recommendations.append("Response structure needs improvement")

        # Relevance check
        if keywords:
            relevance_result = self.semantic_validator.check_relevance(response, keywords)
            scores.append(("relevance", relevance_result.score))
            if relevance_result.score < 0.7:
                issues.append(relevance_result.message)
                recommendations.append("Response may not be relevant to query")

        # Schema compliance
        compliance_score = 0.7
        if schema:
            try:
                response_obj = json.loads(response)
                compliance_result = self.compliance_checker.validate_against_schema(
                    response_obj, schema
                )
                compliance_score = compliance_result.score
                if not compliance_result.passed:
                    issues.append(compliance_result.message)
                    recommendations.append("Response doesn't match expected schema")
            except:
                compliance_score = 0.5

        scores.append(("compliance", compliance_score))

        # Calculate composite scores
        syntax_score = next((s for k, s in scores if k == "syntax"), 0.7)
        semantic_score = (
            next((s for k, s in scores if k == "completeness"), 0.5) +
            next((s for k, s in scores if k == "coherence"), 0.5) +
            next((s for k, s in scores if k == "relevance"), 0.7)
        ) / 3

        compliance_score = next((s for k, s in scores if k == "compliance"), 0.7)
        completeness_score = next((s for k, s in scores if k == "completeness"), 0.7)

        overall_score = (syntax_score + semantic_score + compliance_score + completeness_score) / 4
        confidence = self.confidence_estimator.estimate_confidence(response, format_type)

        return QualityScore(
            syntax_score=syntax_score,
            semantic_score=semantic_score,
            compliance_score=compliance_score,
            completeness_score=completeness_score,
            overall_score=overall_score,
            confidence=confidence,
            issues=issues,
            recommendations=recommendations
        )

    def _validate_syntax(self, response: str, format_type: ResponseFormat) -> ValidationResult:
        """Validate syntax based on format type"""
        if format_type == ResponseFormat.JSON:
            return self.syntax_validator.validate_json(response)
        elif format_type == ResponseFormat.MARKDOWN:
            return self.syntax_validator.validate_markdown(response)
        elif format_type == ResponseFormat.CODE:
            return self.syntax_validator.validate_code(response)
        else:
            # Text format always passes
            return ValidationResult(
                passed=True,
                score=0.8,
                message="Valid text response",
                severity="info"
            )

    def is_acceptable(self, quality_score: QualityScore, threshold: float = 0.6) -> bool:
        """Check if response is acceptable quality"""
        return quality_score.overall_score >= threshold

    def get_recommendations(self, quality_score: QualityScore) -> List[str]:
        """Get improvement recommendations"""
        if quality_score.overall_score < 0.5:
            return ["Consider using a different provider"] + quality_score.recommendations
        elif quality_score.overall_score < 0.7:
            return quality_score.recommendations
        else:
            return []


# Singleton instance
_evaluator: Optional[ResponseEvaluator] = None


def get_response_evaluator() -> ResponseEvaluator:
    """Get or create response evaluator instance"""
    global _evaluator
    if _evaluator is None:
        _evaluator = ResponseEvaluator()
    return _evaluator
