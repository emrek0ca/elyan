"""
core/result_aggregator.py
─────────────────────────────────────────────────────────────────────────────
PHASE 4: Result Aggregation & Validation (~400 lines)
Aggregate sub-task results, validate, and format for unified output.
─────────────────────────────────────────────────────────────────────────────
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum
import json
from utils.logger import get_logger

logger = get_logger("result_aggregator")


class AggregationMode(Enum):
    """Result aggregation modes."""
    SEQUENTIAL = "sequential"  # Chain results (A→B→C)
    PARALLEL = "parallel"  # Combine independent results
    CONDITIONAL = "conditional"  # Use A if success, else B
    HIERARCHICAL = "hierarchical"  # Organize by importance
    FUSION = "fusion"  # Merge conflicting results


@dataclass
class ResultValidation:
    """Validation result for aggregated data."""
    is_valid: bool
    completeness: float  # 0.0-1.0, what % of expected fields present
    consistency: float  # 0.0-1.0, how consistent are values
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class ResultValidator:
    """Validate aggregated results."""

    def __init__(self):
        self.type_checks = self._build_type_checks()

    def _build_type_checks(self) -> Dict[type, callable]:
        """Build type validation functions."""
        return {
            dict: self._validate_dict,
            list: self._validate_list,
            str: self._validate_string,
            int: self._validate_number,
            float: self._validate_number,
            bool: self._validate_boolean,
        }

    def validate(self, data: Any, schema: Optional[Dict[str, Any]] = None) -> ResultValidation:
        """Validate result against schema."""
        errors = []
        warnings = []
        completeness = 1.0
        consistency = 1.0

        # Type validation
        if not self._validate_type(data, errors):
            return ResultValidation(is_valid=False, completeness=0.0, consistency=0.0, errors=errors)

        # Schema validation
        if schema:
            completeness, consistency = self._validate_schema(data, schema, errors, warnings)

        # Content validation
        self._validate_content(data, errors, warnings)

        is_valid = len(errors) == 0
        return ResultValidation(
            is_valid=is_valid,
            completeness=completeness,
            consistency=consistency,
            errors=errors,
            warnings=warnings,
        )

    def _validate_type(self, data: Any, errors: List[str]) -> bool:
        """Check basic type validity."""
        if data is None:
            errors.append("Result is None")
            return False
        return True

    def _validate_schema(self, data: Any, schema: Dict[str, Any], errors: List[str], warnings: List[str]) -> Tuple[float, float]:
        """Validate against schema."""
        if not isinstance(data, dict):
            errors.append(f"Expected dict, got {type(data).__name__}")
            return 0.0, 0.0

        required_fields = set(schema.keys())
        provided_fields = set(data.keys())
        missing_fields = required_fields - provided_fields
        extra_fields = provided_fields - required_fields

        if missing_fields:
            errors.append(f"Missing fields: {missing_fields}")

        if extra_fields:
            warnings.append(f"Extra fields: {extra_fields}")

        # Calculate completeness
        completeness = 1.0 - (len(missing_fields) / len(required_fields)) if required_fields else 1.0

        # Consistency check - verify types
        consistency = 1.0
        for field, expected_type in schema.items():
            if field in data:
                if not isinstance(data[field], expected_type):
                    consistency -= 0.1
                    warnings.append(f"Field '{field}': expected {expected_type.__name__}, got {type(data[field]).__name__}")

        return completeness, max(0.0, consistency)

    def _validate_content(self, data: Any, errors: List[str], warnings: List[str]) -> None:
        """Validate content sanity."""
        if isinstance(data, dict):
            for key, value in data.items():
                if value == "" or value == []:
                    warnings.append(f"Field '{key}' is empty")
                elif isinstance(value, (int, float)) and value < 0:
                    warnings.append(f"Field '{key}' has negative value")

        elif isinstance(data, list):
            if len(data) == 0:
                warnings.append("Result list is empty")
            if len(data) > 10000:
                warnings.append("Result list is very large (>10k items)")

    def _validate_dict(self, data: dict) -> bool:
        """Validate dictionary."""
        return len(data) > 0

    def _validate_list(self, data: list) -> bool:
        """Validate list."""
        return len(data) > 0

    def _validate_string(self, data: str) -> bool:
        """Validate string."""
        return len(data) > 0

    def _validate_number(self, data: int | float) -> bool:
        """Validate number."""
        return not (data is None)

    def _validate_boolean(self, data: bool) -> bool:
        """Validate boolean."""
        return isinstance(data, bool)


class ResultTransformer:
    """Transform results between formats."""

    def __init__(self):
        self.transformers: Dict[str, callable] = {
            "json": self._to_json,
            "csv": self._to_csv,
            "markdown": self._to_markdown,
            "plain_text": self._to_plain_text,
        }

    def transform(self, data: Any, target_format: str) -> str:
        """Transform result to target format."""
        transformer = self.transformers.get(target_format, self._to_json)
        return transformer(data)

    def _to_json(self, data: Any) -> str:
        """Convert to JSON."""
        return json.dumps(data, indent=2, default=str)

    def _to_csv(self, data: Any) -> str:
        """Convert to CSV."""
        if isinstance(data, list) and all(isinstance(item, dict) for item in data):
            if not data:
                return ""

            keys = list(data[0].keys())
            lines = [",".join(keys)]
            for item in data:
                values = [str(item.get(k, "")) for k in keys]
                lines.append(",".join(values))
            return "\n".join(lines)
        else:
            return str(data)

    def _to_markdown(self, data: Any) -> str:
        """Convert to Markdown."""
        if isinstance(data, dict):
            lines = []
            for key, value in data.items():
                lines.append(f"**{key}**: {value}")
            return "\n\n".join(lines)
        elif isinstance(data, list):
            lines = []
            for item in data:
                lines.append(f"- {item}")
            return "\n".join(lines)
        else:
            return str(data)

    def _to_plain_text(self, data: Any) -> str:
        """Convert to plain text."""
        return str(data)


class ResultAggregator:
    """Main result aggregation engine."""

    def __init__(self):
        self.validator = ResultValidator()
        self.transformer = ResultTransformer()
        self.aggregation_log: List[Dict[str, Any]] = []

    def aggregate(
        self,
        results: Dict[str, Any],
        mode: AggregationMode = AggregationMode.PARALLEL,
        order: Optional[List[str]] = None,
    ) -> Any:
        """Aggregate results from multiple sources."""
        logger.info(f"Aggregating {len(results)} results using {mode.name} mode")

        if mode == AggregationMode.SEQUENTIAL:
            aggregated = self._aggregate_sequential(results, order)
        elif mode == AggregationMode.PARALLEL:
            aggregated = self._aggregate_parallel(results)
        elif mode == AggregationMode.CONDITIONAL:
            aggregated = self._aggregate_conditional(results)
        elif mode == AggregationMode.HIERARCHICAL:
            aggregated = self._aggregate_hierarchical(results)
        elif mode == AggregationMode.FUSION:
            aggregated = self._aggregate_fusion(results)
        else:
            aggregated = self._aggregate_parallel(results)

        # Log aggregation
        self.aggregation_log.append({
            "mode": mode.name,
            "source_count": len(results),
            "result_type": type(aggregated).__name__,
        })

        return aggregated

    def _aggregate_sequential(self, results: Dict[str, Any], order: Optional[List[str]]) -> Any:
        """Sequential aggregation - chain results."""
        if not order:
            order = list(results.keys())

        aggregated = None
        for key in order:
            if key in results:
                if aggregated is None:
                    aggregated = results[key]
                else:
                    # Chain: use previous result as input to next
                    if isinstance(aggregated, dict) and isinstance(results[key], dict):
                        aggregated.update(results[key])
                    else:
                        aggregated = results[key]

        return aggregated

    def _aggregate_parallel(self, results: Dict[str, Any]) -> Dict[str, Any] | List[Any]:
        """Parallel aggregation - combine independent results."""
        if not results:
            return {}

        # Determine aggregation strategy based on result types
        result_types = set(type(v).__name__ for v in results.values())

        if len(result_types) == 1:
            first_type = result_types.pop()

            if first_type == "dict":
                # Merge dictionaries
                merged = {}
                for result in results.values():
                    if isinstance(result, dict):
                        merged.update(result)
                return merged

            elif first_type == "list":
                # Concatenate lists
                merged = []
                for result in results.values():
                    if isinstance(result, list):
                        merged.extend(result)
                return merged

        # Mixed types - return as dict
        return results

    def _aggregate_conditional(self, results: Dict[str, Any]) -> Any:
        """Conditional aggregation - use A if success, else B."""
        for result in results.values():
            if isinstance(result, dict) and result.get("success", True):
                return result
        return next(iter(results.values())) if results else None

    def _aggregate_hierarchical(self, results: Dict[str, Any]) -> Dict[str, Any]:
        """Hierarchical aggregation - organize by importance."""
        aggregated = {}
        importance_order = ["error", "warning", "info", "debug", "data"]

        for category in importance_order:
            matching = {k: v for k, v in results.items() if k.startswith(category)}
            if matching:
                aggregated[category] = matching

        return aggregated

    def _aggregate_fusion(self, results: Dict[str, Any]) -> Any:
        """Fusion aggregation - merge conflicting results."""
        if not results:
            return None

        # Simple voting mechanism for conflicting values
        merged = {}
        all_keys = set()
        for result in results.values():
            if isinstance(result, dict):
                all_keys.update(result.keys())

        for key in all_keys:
            values = [v[key] for v in results.values() if isinstance(v, dict) and key in v]
            if len(set(str(v) for v in values)) == 1:
                # All values agree
                merged[key] = values[0]
            else:
                # Values conflict - use majority
                from collections import Counter
                counter = Counter(str(v) for v in values)
                merged[key] = counter.most_common(1)[0][0]

        return merged

    def validate_and_aggregate(
        self,
        results: Dict[str, Any],
        mode: AggregationMode = AggregationMode.PARALLEL,
        schema: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Any, ResultValidation]:
        """Validate results, then aggregate."""
        # Validate each result
        validations = []
        for key, result in results.items():
            validation = self.validator.validate(result, schema)
            validations.append(validation)
            if not validation.is_valid:
                logger.warning(f"Result {key} validation failed: {validation.errors}")

        # Aggregate
        aggregated = self.aggregate(results, mode)

        # Final validation
        final_validation = self.validator.validate(aggregated, schema)

        return aggregated, final_validation

    def format_result(self, data: Any, format: str) -> str:
        """Format aggregated result."""
        return self.transformer.transform(data, format)
