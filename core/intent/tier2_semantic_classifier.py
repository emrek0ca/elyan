"""
Tier 2: Semantic Classifier (< 200ms)

Uses LLM to classify intent with cost/speed optimization.
Default: Groq (fastest, free), fallback to Gemini, then Claude.
Handles ~50% of traffic with 85%+ accuracy.
"""

import json
import time
from typing import Optional, Dict, Any, List
from utils.logger import get_logger
from .models import IntentCandidate, TaskDefinition
from core.nlu import get_phase1_engine

logger = get_logger("tier2_semantic_classifier")

# Tier 2 Semantic Classifier Prompt Template
SEMANTIC_CLASSIFIER_PROMPT = """
Sen bir intent sınıflandırıcısın. Konuşma dilinde Türkçe/İngilizce mesajları anla ve araçlarla eşleştir.

KULLANICI MESSAJı:
{user_input}

MEVCUT ARAÇLAR:
{available_tools}

KURALLAR:
1. Tool listesinde OLMAYAN action ASLA döndürme - başarısızlıkla sonuçlanır
2. Belirsizse "clarify" döndür, tahmin etme
3. Türkçe ekleri analiz et: "-u/-ü/-ı/-i" (nesne), "-de/-da" (konum)
4. Çoklu görev ise "multi_task" döndür, tasks listesini doldur
5. Basit konuşma (selamlaşma, zaman sorgusu) → "chat"
6. Güvenlik riskli işlemler (restart, shutdown) → sor, direkt yapma

ÇIKTI JSON SCHEMA (MUTLAKA UY):
{{
  "intent": "tool_name | multi_task | chat | clarify",
  "confidence": 0.5-1.0,
  "reasoning": "neden bu seçildi (1-2 cümle)",
  "params": {{"key": "value"}},
  "tasks": [
    {{
      "task_id": "t1",
      "action": "tool_name",
      "params": {{"key": "value"}},
      "depends_on": [],
      "output_key": "variable_name"
    }}
  ]
}}

Sadece JSON döndür, başka metin yok.
"""


class SemanticClassifier:
    """LLM-based semantic intent classifier with multi-provider routing."""

    PHASE1_DIRECT_THRESHOLD = 0.30
    PHASE1_CLARIFY_THRESHOLD = 0.20

    def __init__(self, llm_orchestrator=None):
        self.llm = llm_orchestrator
        self.timeout_ms = 200
        self._phase1 = get_phase1_engine()

    def classify(
        self,
        user_input: str,
        available_tools: Dict[str, Any],
        context: Optional[str] = None
    ) -> Optional[IntentCandidate]:
        """
        Classify user intent using LLM.

        Args:
            user_input: User's message
            available_tools: Available tools dict {name: schema}
            context: Conversation context for better understanding

        Returns:
            IntentCandidate with confidence >= 0.7, or None
        """
        start = time.time()

        try:
            phase1_candidate = None
            if self._phase1 is not None:
                phase1_candidate = self._phase1.classify(
                    user_input,
                    context=context,
                    available_tools=available_tools,
                )
                if phase1_candidate is not None:
                    if phase1_candidate.needs_clarification and phase1_candidate.confidence >= self.PHASE1_CLARIFY_THRESHOLD:
                        candidate = phase1_candidate.to_candidate()
                        candidate.execution_time_ms = (time.time() - start) * 1000
                        logger.info(
                            "Tier 2 phase1 clarify (%s) in %.1fms",
                            candidate.action,
                            candidate.execution_time_ms,
                        )
                        return candidate
                    if phase1_candidate.confidence >= self.PHASE1_DIRECT_THRESHOLD:
                        candidate = phase1_candidate.to_candidate()
                        if candidate.action in available_tools or candidate.action in {"chat", "clarify", "multi_task"}:
                            candidate.execution_time_ms = (time.time() - start) * 1000
                            logger.info(
                                "Tier 2 phase1 direct %s (%.2f) in %.1fms",
                                candidate.action,
                                candidate.confidence,
                                candidate.execution_time_ms,
                            )
                            return candidate
                        if candidate.intent in available_tools:
                            candidate.action = candidate.intent
                            candidate.execution_time_ms = (time.time() - start) * 1000
                            logger.info(
                                "Tier 2 phase1 direct intent %s (%.2f) in %.1fms",
                                candidate.intent,
                                candidate.confidence,
                                candidate.execution_time_ms,
                            )
                            return candidate

            # Build tool list for prompt
            tool_list = self._format_tool_list(available_tools)

            # Build prompt
            prompt = SEMANTIC_CLASSIFIER_PROMPT.format(
                user_input=user_input,
                available_tools=tool_list
            )

            if context:
                prompt += f"\n\nKONVERSASYON CONTEXT:\n{context}"
            if phase1_candidate is not None:
                prompt += (
                    "\n\nLOCAL PHASE1 HINT:\n"
                    f"- intent: {phase1_candidate.intent}\n"
                    f"- action: {phase1_candidate.action}\n"
                    f"- confidence: {phase1_candidate.confidence:.2f}\n"
                    f"- reasoning: {phase1_candidate.reasoning}\n"
                )

            # Get LLM response - use best cost/speed provider
            response = self._call_llm(prompt)

            if not response:
                if phase1_candidate is not None:
                    candidate = phase1_candidate.to_candidate()
                    if candidate.action in available_tools or candidate.action in {"chat", "clarify", "multi_task"}:
                        candidate.execution_time_ms = (time.time() - start) * 1000
                        logger.info(
                            "Tier 2 phase1 fallback %s (%.2f) in %.1fms",
                            candidate.action,
                            candidate.confidence,
                            candidate.execution_time_ms,
                        )
                        return candidate
                    if candidate.intent in available_tools:
                        candidate.action = candidate.intent
                        candidate.execution_time_ms = (time.time() - start) * 1000
                        logger.info(
                            "Tier 2 phase1 fallback intent %s (%.2f) in %.1fms",
                            candidate.intent,
                            candidate.confidence,
                            candidate.execution_time_ms,
                        )
                        return candidate
                logger.warning(f"Tier 2: LLM returned empty response for '{user_input}'")
                return None

            # Parse response
            candidate = self._parse_response(response, available_tools)

            elapsed = (time.time() - start) * 1000
            if candidate:
                candidate.execution_time_ms = elapsed
                logger.info(
                    f"Tier 2 {candidate.action} ({candidate.confidence:.2f}) in {elapsed:.1f}ms"
                )

            return candidate

        except Exception as e:
            logger.error(f"Tier 2 classification error: {e}")
            return None

    def _call_llm(self, prompt: str) -> Optional[str]:
        """Call LLM with automatic provider selection and fallback."""
        if not self.llm:
            logger.warning("Tier 2: LLM orchestrator not available")
            return None

        try:
            # Try Groq first (fastest, free)
            response = self.llm.call_groq(
                prompt=prompt,
                temperature=0.3,  # Deterministic
                max_tokens=500,
                timeout_ms=self.timeout_ms
            )
            if response:
                return response

            # Fallback to Gemini (free)
            response = self.llm.call_gemini(
                prompt=prompt,
                temperature=0.3,
                max_tokens=500,
                timeout_ms=self.timeout_ms
            )
            if response:
                return response

            # Last resort: Claude (quality but slower)
            response = self.llm.call_claude(
                prompt=prompt,
                temperature=0.3,
                max_tokens=500,
                timeout_ms=self.timeout_ms
            )
            return response

        except Exception as e:
            logger.error(f"Tier 2 LLM call failed: {e}")
            return None

    def _format_tool_list(self, available_tools: Dict[str, Any]) -> str:
        """Format available tools for LLM prompt."""
        lines = []
        for tool_name, schema in available_tools.items():
            if isinstance(schema, dict):
                params = schema.get("params", {})
                desc = schema.get("description", "")
                lines.append(f"- {tool_name}: {desc} (params: {list(params.keys())})")
            else:
                lines.append(f"- {tool_name}")
        return "\n".join(lines) if lines else "(No tools available)"

    def _parse_response(self, response: str, available_tools: Dict[str, Any]) -> Optional[IntentCandidate]:
        """Parse LLM JSON response and validate."""
        try:
            # Try JSON parse (response should be pure JSON)
            data = json.loads(response.strip())

            intent = data.get("intent", "").strip()
            confidence = float(data.get("confidence", 0.5))
            reasoning = data.get("reasoning", "")
            params = data.get("params", {})
            tasks = data.get("tasks", [])

            # Validate intent
            if not intent:
                logger.warning("Tier 2: No intent in response")
                return None

            # Check if intent is valid
            if intent not in ["multi_task", "chat", "clarify"]:
                if intent not in available_tools:
                    logger.warning(f"Tier 2: Invalid intent '{intent}' not in available tools")
                    return None

            # Validate confidence range
            if not (0.0 <= confidence <= 1.0):
                confidence = max(0.0, min(1.0, confidence))

            # Parse tasks if multi_task
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
                        # Validate task action
                        if task.action not in available_tools:
                            logger.warning(f"Tier 2: Task action '{task.action}' not in available tools")
                            continue
                        task_defs.append(task)
                    except Exception as te:
                        logger.warning(f"Tier 2: Failed to parse task: {te}")
                        continue

            return IntentCandidate(
                action=intent,
                confidence=confidence,
                reasoning=reasoning,
                params=params,
                tasks=task_defs,
                source_tier="tier2"
            )

        except json.JSONDecodeError as e:
            logger.warning(f"Tier 2: JSON parse failed: {e}, response: {response[:200]}")
            return None
        except Exception as e:
            logger.error(f"Tier 2: Parse error: {e}")
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Get classifier statistics."""
        return {
            "tier": "semantic_classifier",
            "timeout_ms": self.timeout_ms,
            "llm_available": self.llm is not None,
            "phase1": self._phase1.describe() if self._phase1 is not None else {},
        }
