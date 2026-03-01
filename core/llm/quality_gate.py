"""
Elyan Response Quality Gate — Validates LLM outputs for consistency and safety.
"""

from typing import Dict, Any, List, Optional
import re
from utils.logger import get_logger

logger = get_logger("quality_gate")

class ResponseQualityGate:
    """Checks LLM response for common failure modes."""

    def __init__(self):
        # Patterns that indicate a failed or low-quality response
        self.fail_patterns = [
            r"i apologize, but i cannot",
            r"as an ai language model",
            r"i'm sorry, i can't assist",
            r"i am unable to provide",
            r"^$", # Empty response
        ]

    def validate(self, response: str) -> Dict[str, Any]:
        """Return quality metrics for a response."""
        if not response or not response.strip():
            return {"valid": False, "score": 0.0, "reason": "empty_response"}

        # Check for placeholder/error patterns
        for pattern in self.fail_patterns:
            if re.search(pattern, response.lower()):
                return {"valid": False, "score": 0.1, "reason": "refusal_pattern"}

        # Basic length check
        length = len(response)
        if length < 5:
            return {"valid": False, "score": 0.2, "reason": "too_short"}

        # Check for repetition (self-echo)
        # (Simple heuristic: look for triplets of words repeated)
        words = response.split()
        if len(words) > 20:
            for i in range(len(words)-10):
                chunk = " ".join(words[i:i+5])
                if response.count(chunk) > 3:
                     return {"valid": False, "score": 0.3, "reason": "repetitive_content"}

        return {"valid": True, "score": 1.0, "reason": "passed"}

# Global instance
quality_gate = ResponseQualityGate()
