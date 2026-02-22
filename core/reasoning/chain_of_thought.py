"""
core/reasoning/chain_of_thought.py
─────────────────────────────────────────────────────────────────────────────
Chain-of-Thought Reasoning Engine (Phase 30).
Instead of single-shot LLM calls, complex tasks are processed through a 
structured multi-step pipeline: Understand → Plan → Execute → Verify.
Each step builds on the previous step's output, creating cumulative reasoning.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from utils.logger import get_logger

logger = get_logger("reasoning")

class ThinkingPhase(Enum):
    UNDERSTAND = "understand"
    PLAN = "plan"
    EXECUTE = "execute"
    VERIFY = "verify"

@dataclass
class ThoughtStep:
    phase: ThinkingPhase
    prompt: str
    result: str = ""
    confidence: float = 0.0
    elapsed_ms: float = 0.0

@dataclass
class ReasoningResult:
    original_request: str
    steps: List[ThoughtStep] = field(default_factory=list)
    final_answer: str = ""
    overall_confidence: float = 0.0
    total_elapsed_ms: float = 0.0
    required_clarification: bool = False
    clarification_question: str = ""

class ReasoningChain:
    CONFIDENCE_THRESHOLD = 0.7

    def __init__(self, agent_instance):
        self.agent = agent_instance
    
    async def reason(self, user_request: str, context: str = "") -> ReasoningResult:
        """Multi-step reasoning pipeline for complex tasks."""
        result = ReasoningResult(original_request=user_request)
        total_start = time.time()
        
        logger.info(f"🧠 ReasoningChain STARTED for: {user_request[:80]}...")
        
        # Step 1: UNDERSTAND — Parse what the user actually wants
        understand = await self._think(
            ThinkingPhase.UNDERSTAND,
            f"""Kullanıcının isteğini analiz et. Asıl amacı, gizli gereksinimleri ve olası zorlukları belirle.
Bağlam: {context}
İstek: {user_request}

JSON formatında döndür:
{{"intent": "ana amaç", "hidden_needs": ["gizli gereksinim1"], "risks": ["risk1"], "confidence": 0.0-1.0}}"""
        )
        result.steps.append(understand)
        
        if understand.confidence < self.CONFIDENCE_THRESHOLD:
            result.required_clarification = True
            result.clarification_question = await self._generate_clarification(user_request, understand.result)
            result.overall_confidence = understand.confidence
            logger.warning(f"⚠️ Low confidence ({understand.confidence:.0%}). Requesting clarification.")
            return result
        
        # Step 2: PLAN — Create step-by-step execution plan
        plan = await self._think(
            ThinkingPhase.PLAN,
            f"""Önceki analiz sonuçlarına göre adım adım bir uygulama planı oluştur.
Analiz: {understand.result}
Orijinal İstek: {user_request}

Her adım için bağımlılıkları ve sıralamayı düşün. JSON formatında döndür:
{{"steps": [{{"id": 1, "action": "yapılacak", "depends_on": [], "tool": "araç adı"}}], "estimated_complexity": "low/medium/high"}}"""
        )
        result.steps.append(plan)
        
        # Step 3: EXECUTE — Run each planned step
        execute = await self._think(
            ThinkingPhase.EXECUTE,
            f"""Aşağıdaki planı uygula ve her adımın sonucunu detaylı olarak raporla.
Plan: {plan.result}
Orijinal İstek: {user_request}
Önceki Analiz: {understand.result}

Her adımın çıktısını açıkla. Eğer bir adım başarısız olursa durma, alternatif yol öner."""
        )
        result.steps.append(execute)
        
        # Step 4: VERIFY — Check the result makes sense
        verify = await self._think(
            ThinkingPhase.VERIFY,
            f"""Üretilen sonucu doğrula. Tasarım hataları, eksik edge case'ler veya mantık açıkları var mı?
Orijinal İstek: {user_request}
Üretilen Sonuç: {execute.result}

Sorun varsa düzeltilmiş hali döndür. Yoksa "VERIFIED" yaz ve güven skorunu belirt."""
        )
        result.steps.append(verify)
        
        result.final_answer = verify.result
        result.overall_confidence = min(s.confidence for s in result.steps)
        result.total_elapsed_ms = (time.time() - total_start) * 1000
        
        logger.info(
            f"🧠 ReasoningChain COMPLETE: {len(result.steps)} steps, "
            f"Confidence={result.overall_confidence:.0%}, "
            f"Time={result.total_elapsed_ms:.0f}ms"
        )
        return result
    
    async def _think(self, phase: ThinkingPhase, prompt: str) -> ThoughtStep:
        """Execute a single thinking step via the LLM."""
        step = ThoughtStep(phase=phase, prompt=prompt)
        start = time.time()
        
        try:
            from core.multi_agent.orchestrator import AgentOrchestrator
            orch = AgentOrchestrator(self.agent)
            
            system_prefix = f"[REASONING PHASE: {phase.value.upper()}]\n"
            step.result = await orch._run_specialist("executor", system_prefix + prompt)
            
            # Extract confidence from result if present
            import re
            conf_match = re.search(r'"confidence"\s*:\s*([\d.]+)', step.result)
            step.confidence = float(conf_match.group(1)) if conf_match else 0.75
            step.confidence = max(0.0, min(1.0, step.confidence))
            
        except Exception as e:
            step.result = f"Error in {phase.value}: {str(e)}"
            step.confidence = 0.0
            
        step.elapsed_ms = (time.time() - start) * 1000
        logger.debug(f"  → {phase.value}: conf={step.confidence:.0%}, time={step.elapsed_ms:.0f}ms")
        return step
    
    async def _generate_clarification(self, request: str, analysis: str) -> str:
        """Generate a clarification question when confidence is too low."""
        from core.multi_agent.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator(self.agent)
        
        return await orch._run_specialist("qa", f"""
Kullanıcının isteği yeterince net değil. Analiz sonuçlarına bakarak,
devam etmeden önce sorulması gereken EN ÖNEMLİ soruyu tek cümle ile oluştur.
İstek: {request}
Analiz: {analysis}
""")
