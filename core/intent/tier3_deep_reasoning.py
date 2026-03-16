"""
Tier 3: Deep Reasoning (< 2s)

Best-quality LLM reasoning for ambiguous/complex intents (confidence < 0.7).
Uses Claude 3.5 Sonnet or Gemini 2.0 Flash.
Handles ~10% of traffic with 95%+ accuracy.
"""

import json
import time
from typing import Optional, Dict, Any, List
from utils.logger import get_logger
from .models import IntentCandidate, TaskDefinition

logger = get_logger("tier3_deep_reasoning")

# Deep Reasoning Prompt Template
DEEP_REASONING_PROMPT = """
DÜŞÜN: Kullanıcı şu mesajı yazdı:
"{user_input}"

Tier 2 Semantic Classifier bu önerileri sundu (güven: {tier2_confidence}):
{tier2_candidates}

Ama emin değil. Daha derinlemesine analiz yap:

1. Kullanıcı TAM OLARAK ne yapmak istiyor?
2. Alternatif interpretasyonlar var mı?
3. Çok adımlı görev mi? Birbirini takip eden işler mi?
4. Kullanıcıya soru sorması gerekir mi (belirsizlik)?
5. Tool listesindeki araçlar yeterli mi?
6. Güvenlik riskli mi?

MEVCUT ARAÇLAR:
{available_tools}

KESIN SONUÇ VER (JSON, başka metin yok):
{{
  "intent": "tool_name | multi_task | chat | clarify",
  "confidence": 0.7-1.0,
  "reasoning": "Derin analiz: neden bu karar verdik (2-3 cümle)",
  "params": {{"key": "value"}},
  "tasks": [
    {{
      "task_id": "t1",
      "action": "tool_name",
      "params": {{"key": "value"}},
      "depends_on": [],
      "output_key": "variable_name"
    }}
  ],
  "analysis": {{
    "alternatives_considered": ["...", "..."],
    "reasoning_depth": "complex | multi_step | ambiguous | etc",
    "user_clarification_needed": false
  }}
}}
"""


class DeepReasoner:
    """High-quality LLM reasoning for complex/ambiguous intents."""

    def __init__(self, llm_orchestrator=None):
        self.llm = llm_orchestrator
        self.timeout_ms = 2000

    def reason(
        self,
        user_input: str,
        tier2_candidates: List[IntentCandidate],
        available_tools: Dict[str, Any],
        context: Optional[str] = None
    ) -> Optional[IntentCandidate]:
        """
        Perform deep reasoning for ambiguous intents.

        Args:
            user_input: User's message
            tier2_candidates: Candidates from Tier 2
            available_tools: Available tools dict
            context: Conversation context

        Returns:
            IntentCandidate with high confidence, or None
        """
        start = time.time()

        if not tier2_candidates:
            logger.warning("Tier 3: No candidates from Tier 2")
            return None

        try:
            # Select best candidate(s) to reason about
            best_candidate = max(tier2_candidates, key=lambda c: c.confidence)

            # Build candidates summary for prompt
            candidates_summary = self._format_candidates(tier2_candidates)

            # Build tool list
            tool_list = self._format_tool_list(available_tools)

            # Build prompt
            prompt = DEEP_REASONING_PROMPT.format(
                user_input=user_input,
                tier2_confidence=f"{best_candidate.confidence:.2f}",
                tier2_candidates=candidates_summary,
                available_tools=tool_list
            )

            if context:
                prompt += f"\n\nKONVERSASYON CONTEXT:\n{context}"

            # Call best-quality LLM
            response = self._call_best_llm(prompt)

            if not response:
                logger.warning(f"Tier 3: LLM returned empty response for '{user_input}'")
                return None

            # Parse response
            candidate = self._parse_response(response, available_tools)

            elapsed = (time.time() - start) * 1000
            if candidate:
                candidate.execution_time_ms = elapsed
                logger.info(
                    f"Tier 3 {candidate.action} ({candidate.confidence:.2f}) in {elapsed:.1f}ms"
                )

            return candidate

        except Exception as e:
            logger.error(f"Tier 3 reasoning error: {e}")
            return None

    def _call_best_llm(self, prompt: str) -> Optional[str]:
        """Call best-quality LLM."""
        if not self.llm:
            logger.warning("Tier 3: LLM orchestrator not available")
            return None

        try:
            # Prefer Claude 3.5 Sonnet for quality
            response = self.llm.call_claude(
                prompt=prompt,
                temperature=0.5,  # Allow reasoning
                max_tokens=2000,
                timeout_ms=self.timeout_ms
            )
            if response:
                return response

            # Fallback to Gemini 2.0 Flash
            response = self.llm.call_gemini(
                prompt=prompt,
                temperature=0.5,
                max_tokens=2000,
                timeout_ms=self.timeout_ms
            )
            return response

        except Exception as e:
            logger.error(f"Tier 3 LLM call failed: {e}")
            return None

    def _format_candidates(self, candidates: List[IntentCandidate]) -> str:
        """Format Tier 2 candidates for prompt."""
        lines = []
        for i, c in enumerate(candidates[:3], 1):  # Top 3
            lines.append(f"{i}. {c.action} (confidence: {c.confidence:.2f})")
            lines.append(f"   Reasoning: {c.reasoning}")
            if c.params:
                lines.append(f"   Params: {c.params}")
        return "\n".join(lines)

    def _format_tool_list(self, available_tools: Dict[str, Any]) -> str:
        """Format available tools for LLM prompt."""
        lines = []
        for tool_name, schema in available_tools.items():
            if isinstance(schema, dict):
                desc = schema.get("description", "")
                params = schema.get("params", {})
                lines.append(f"- {tool_name}: {desc}")
                if params:
                    for param_name, param_schema in params.items():
                        param_desc = param_schema.get("description", "") if isinstance(param_schema, dict) else ""
                        lines.append(f"  - {param_name}: {param_desc}")
            else:
                lines.append(f"- {tool_name}")
        return "\n".join(lines) if lines else "(No tools available)"

    def _parse_response(self, response: str, available_tools: Dict[str, Any]) -> Optional[IntentCandidate]:
        """Parse LLM JSON response and validate."""
        try:
            data = json.loads(response.strip())

            intent = data.get("intent", "").strip()
            confidence = float(data.get("confidence", 0.5))
            reasoning = data.get("reasoning", "")
            params = data.get("params", {})
            tasks = data.get("tasks", [])
            analysis = data.get("analysis", {})

            # Validate intent
            if not intent:
                logger.warning("Tier 3: No intent in response")
                return None

            if intent not in ["multi_task", "chat", "clarify"]:
                if intent not in available_tools:
                    logger.warning(f"Tier 3: Invalid intent '{intent}'")
                    return None

            # Ensure confidence is in valid range
            if not (0.0 <= confidence <= 1.0):
                confidence = max(0.0, min(1.0, confidence))

            # Parse tasks
            task_defs = []
            if intent == "multi_task" and tasks:
                for t in tasks:
                    try:
                        task = TaskDefinition(
                            task_id=t.get("task_id", ""),
                            action=t.get("action", ""),
                            params=t.get("params", {}),
                            depends_on=t.get("depends_on", []),
                            output_key=t.get("output_key", "")
                        )
                        if task.action not in available_tools:
                            logger.warning(f"Tier 3: Task action '{task.action}' not in available tools")
                            continue
                        task_defs.append(task)
                    except Exception as te:
                        logger.warning(f"Tier 3: Failed to parse task: {te}")
                        continue

            candidate = IntentCandidate(
                action=intent,
                confidence=confidence,
                reasoning=reasoning,
                params=params,
                tasks=task_defs,
                source_tier="tier3",
                metadata={
                    "alternatives": analysis.get("alternatives_considered", []),
                    "reasoning_depth": analysis.get("reasoning_depth", ""),
                    "user_clarification_needed": analysis.get("user_clarification_needed", False)
                }
            )

            return candidate

        except json.JSONDecodeError as e:
            logger.warning(f"Tier 3: JSON parse failed: {e}")
            return None
        except Exception as e:
            logger.error(f"Tier 3: Parse error: {e}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get reasoning statistics."""
        return {
            "tier": "deep_reasoner",
            "timeout_ms": self.timeout_ms,
            "llm_available": self.llm is not None
        }
