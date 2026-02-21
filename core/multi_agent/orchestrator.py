"""
core/multi_agent/orchestrator.py
─────────────────────────────────────────────────────────────────────────────
Lead Orchestrator that manages task delegation between specialist agents.
"""

from __future__ import annotations
import asyncio
from typing import List, Dict, Any, Optional
from utils.logger import get_logger
from .specialists import get_specialist_registry, SpecialistIdentity

logger = get_logger("multi_agent.orchestrator")

class AgentOrchestrator:
    def __init__(self, agent_instance):
        self.main_agent = agent_instance
        self.registry = get_specialist_registry()

    async def delegate_subtask(self, subtask: Any, context: Dict[str, Any]) -> tuple[str, bool]:
        """Bir alt görevi en uygun uzmana delege eder ve QA denetiminden geçirir."""
        action = str(getattr(subtask, "action", "") or "")
        name = str(getattr(subtask, "name", "") or "")
        
        # 1. Uzmanı seç ve görevi yaptır
        specialist = self.registry.select_for_input(f"{name} {action}")
        logger.info(f"Delegating '{name}' to {specialist.name} ({specialist.role})")
        
        result_text, ok = await self.main_agent._execute_planned_step_with_recovery(
            subtask, 
            user_input=context.get("original_input", "")
        )

        # 2. Kritik görevler için QA Denetimi (Reflection)
        if ok and action in ["run_code", "write_file", "write_word", "advanced_research", "create_web_project_scaffold"]:
            qa_specialist = self.registry.get("qa_expert")
            logger.info(f"QA Review starting for: {name}")
            
            # QA'ya çıktıyı incelet (LLM Reflection)
            qa_prompt = (
                f"Sistem Rolün: {qa_specialist.system_prompt}\n\n"
                f"Kullanıcı İsteği: {context.get('original_input')}\n"
                f"Uzman Çıktısı: {result_text}\n\n"
                "Görev: Yukarıdaki çıktıyı incele. Eğer görev tam ve doğru yapılmışsa sadece 'ONAY' yaz. "
                "Eğer bir hata, eksiklik veya kalite sorunu varsa, nedenini ve nasıl düzeltileceğini teknik bir dille açıkla."
            )
            
            try:
                # Ana ajanın LLM'ini kullanarak QA yorumu al
                qa_review = await self.main_agent.llm.generate(qa_prompt, role="qa", user_id="system")
                is_verified = "ONAY" in qa_review.upper() and len(qa_review.strip()) < 10
                
                if not is_verified:
                    logger.warning(f"QA rejected the output. Reason: {qa_review}")
                    # Düzeltme için tekrar uzmana gönder
                    refined_result, refined_ok = await self.main_agent._execute_planned_step_with_recovery(
                        subtask,
                        user_input=f"{context.get('original_input')} (KALİTE DENETİMİ GERİ BİLDİRİMİ: {qa_review})"
                    )
                    return f"[Refined after QA] {refined_result}", refined_ok
                else:
                    logger.info(f"QA approved: {name}")
            except Exception as e:
                logger.error(f"QA process error: {e}")

        return result_text, ok

    async def manage_flow(self, plan: Any, original_input: str) -> str:
        """Tüm planın uzmanlar arasındaki akışını yönetir (Bağımlılık bazlı paralel yürütme)."""
        results = []
        executed_steps = set()
        subtasks = getattr(plan, "subtasks", []) or []
        
        # Basit bir bağımlılık çözücü (Dependency Resolver)
        while len(executed_steps) < len(subtasks):
            # O an çalıştırılabilir olanlar (bağımlılığı tamamlanmış adımlar)
            runnable = [
                s for s in subtasks 
                if s.task_id not in executed_steps and 
                all(d in executed_steps for d in (getattr(s, "dependencies", []) or []))
            ]
            
            if not runnable:
                # Deadlock durumu (veya dairesel bağımlılık)
                logger.error("Pipeline deadlock detected. Check subtask dependencies.")
                break
                
            # Paralel yürütme (Aynı "seviyedeki" adımlar)
            tasks = []
            for step in runnable:
                tasks.append(self.delegate_subtask(step, {"original_input": original_input}))
            
            # Tüm "seviye" adımlarının bitmesini bekle
            level_results = await asyncio.gather(*tasks)
            
            for i, (res_text, ok) in enumerate(level_results):
                results.append(res_text)
                if ok:
                    executed_steps.add(runnable[i].task_id)
                
        return "\n\n".join(results)

def get_orchestrator(agent_instance) -> AgentOrchestrator:
    return AgentOrchestrator(agent_instance)
