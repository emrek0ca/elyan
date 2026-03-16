"""
JSON Repair - Robust JSON parser that can recover from common malformations

Handles LLM-generated JSON that may have:
- Missing/extra commas and quotes
- Trailing commas
- Unquoted keys
- Single quotes instead of double quotes
- Incomplete structures
- Mixed encodings
- Comments

Part of RELIABILITY FOUNDATION (Hafta 1-2)
"""

import json
import re
import ast
from typing import Any, Dict, Optional, Tuple, List
from utils.logger import get_logger

logger = get_logger("json_repair")


class JSONRepair:
    """Robust JSON parser and repair utility"""

    @staticmethod
    def repair_and_parse(text: str, fallback_to_python: bool = True) -> Tuple[bool, Any, Optional[str]]:
        """
        Attempt to parse JSON, with automatic repair

        Returns:
            (success, parsed_value, error_message)
        """
        if not text or not isinstance(text, str):
            return False, None, "Metin girişi boş veya geçersiz (Text input is empty or invalid)"

        text = text.strip()

        # Try standard JSON parsing first
        try:
            result = json.loads(text)
            logger.debug(f"Başarılı JSON ayrıştırma (Successfully parsed JSON): {len(text)} chars")
            return True, result, None
        except json.JSONDecodeError as e:
            logger.debug(f"JSON hata: {e}")

        # Try repair strategies
        repair_strategies = [
            JSONRepair._fix_single_quotes,
            JSONRepair._fix_trailing_commas,
            JSONRepair._fix_unquoted_keys,
            JSONRepair._fix_missing_quotes,
            JSONRepair._fix_incomplete_structure,
            JSONRepair._fix_comments,
            JSONRepair._fix_mixed_quotes,
            JSONRepair._extract_json_object,
        ]

        for strategy in repair_strategies:
            try:
                repaired = strategy(text)
                if repaired != text:
                    result = json.loads(repaired)
                    logger.debug(f"JSON onarım başarılı: {strategy.__name__} (JSON repair successful)")
                    return True, result, None
            except (json.JSONDecodeError, Exception) as e:
                logger.debug(f"Strateji {strategy.__name__} başarısız: {e}")
                continue

        # Fallback to Python literal eval
        if fallback_to_python:
            try:
                result = ast.literal_eval(text)
                logger.debug("Python literal_eval başarılı (Python literal_eval successful)")
                return True, result, None
            except (ValueError, SyntaxError) as e:
                logger.debug(f"Python literal_eval başarısız: {e}")

        logger.warning(f"JSON ayrıştırma başarısız (JSON parsing failed): {text[:100]}")
        return False, None, f"JSON ayrıştırılamadı (Failed to parse JSON): {text[:100]}..."

    @staticmethod
    def _fix_single_quotes(text: str) -> str:
        """Replace single quotes with double quotes (carefully)"""
        # This is risky - only do it for obvious cases
        # Pattern: 'key': or 'value'
        text = re.sub(r"'([^']*)'(\s*:)", r'"\1"\2', text)  # Keys
        text = re.sub(r":\s*'([^']*)'", r': "\1"', text)  # String values
        return text

    @staticmethod
    def _fix_trailing_commas(text: str) -> str:
        """Remove trailing commas before } and ]"""
        text = re.sub(r",(\s*[}\]])", r"\1", text)
        return text

    @staticmethod
    def _fix_unquoted_keys(text: str) -> str:
        """Add quotes around unquoted keys"""
        # Pattern: word: value (not preceded by quote)
        # First for dict start: {key:
        text = re.sub(r'\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r'{"\1":', text)
        # Then for after comma: ,key:
        text = re.sub(r',\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*:', r',"\1":', text)
        return text

    @staticmethod
    def _fix_missing_quotes(text: str) -> str:
        """Add quotes around unquoted string values"""
        # This is very risky, skip for now
        return text

    @staticmethod
    def _fix_incomplete_structure(text: str) -> str:
        """Fix incomplete JSON structures"""
        # Count braces and brackets
        open_braces = text.count("{") - text.count("}")
        open_brackets = text.count("[") - text.count("]")

        # Close unclosed structures
        text += "}" * open_braces + "]" * open_brackets
        return text

    @staticmethod
    def _fix_comments(text: str) -> str:
        """Remove JSON comments (// and /* */)"""
        # Remove single-line comments
        text = re.sub(r"//.*?$", "", text, flags=re.MULTILINE)
        # Remove multi-line comments
        text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
        return text

    @staticmethod
    def _fix_mixed_quotes(text: str) -> str:
        """Fix mixed quote styles"""
        # Normalize to double quotes
        lines = []
        for line in text.split("\n"):
            # Skip if line looks like it has string content with quotes
            if ":" in line and not line.strip().startswith("{"):
                # Try to fix key-value pairs
                match = re.match(r"^(\s*)'([^']*)'(\s*:\s*)", line)
                if match:
                    line = match.group(1) + '"' + match.group(2) + '"' + match.group(3)
            lines.append(line)
        return "\n".join(lines)

    @staticmethod
    def _extract_json_object(text: str) -> str:
        """Extract JSON object from text with surrounding content"""
        # Find first { or [ and match it to the end
        start = -1
        for i, char in enumerate(text):
            if char in "{[":
                start = i
                break

        if start == -1:
            return text

        end = JSONRepair._find_matching_bracket(text, start)
        if end != -1:
            return text[start : end + 1]

        return text

    @staticmethod
    def _find_matching_bracket(text: str, start: int) -> int:
        """Find matching closing bracket"""
        if start >= len(text):
            return -1

        opening = text[start]
        closing = "}" if opening == "{" else "]"
        depth = 0

        for i in range(start, len(text)):
            char = text[i]
            if char == opening:
                depth += 1
            elif char == closing:
                depth -= 1
                if depth == 0:
                    return i

        return -1

    @staticmethod
    def parse_with_fallback(text: str, fallback_value: Any = None) -> Any:
        """
        Parse JSON with fallback value on failure

        Args:
            text: JSON string to parse
            fallback_value: Value to return if parsing fails

        Returns:
            Parsed JSON or fallback_value
        """
        success, result, error = JSONRepair.repair_and_parse(text)
        if success:
            return result
        return fallback_value

    @staticmethod
    def safe_extract_json(text: str) -> Optional[Dict[str, Any]]:
        """
        Safely extract JSON from text that may contain other content

        Returns:
            Parsed JSON dict or None if not found
        """
        # Try to find JSON in the text
        patterns = [
            r"\{[^{}]*\}",  # Simple objects
            r"\{[\s\S]*?\}(?=[^}]*$)",  # Objects to end
        ]

        for pattern in patterns:
            matches = re.finditer(pattern, text)
            for match in matches:
                success, result, _ = JSONRepair.repair_and_parse(match.group())
                if success and isinstance(result, dict):
                    return result

        return None

    @staticmethod
    def validate_structure(text: str) -> bool:
        """Check if text looks like valid JSON structure"""
        text = text.strip()
        if not text:
            return False

        # Must start with { or [
        if not text[0] in "{[":
            return False

        # Must end with } or ]
        if not text[-1] in "}]":
            return False

        # Basic bracket matching
        open_braces = text.count("{")
        close_braces = text.count("}")
        open_brackets = text.count("[")
        close_brackets = text.count("]")

        return open_braces == close_braces and open_brackets == close_brackets


def repair_json(text: str) -> Tuple[bool, Any]:
    """
    Convenience function to repair and parse JSON

    Returns:
        (success, result_or_error_message)
    """
    success, result, error = JSONRepair.repair_and_parse(text)
    return success, result if success else error


def safe_json_loads(text: str, default: Any = None) -> Any:
    """
    Safely load JSON with automatic repair

    Returns:
        Parsed JSON or default value
    """
    success, result, _ = JSONRepair.repair_and_parse(text)
    return result if success else default


def extract_json_from_text(text: str) -> Optional[Dict[str, Any]]:
    """
    Extract JSON object from text containing other content

    Returns:
        Parsed JSON dict or None
    """
    return JSONRepair.safe_extract_json(text)
