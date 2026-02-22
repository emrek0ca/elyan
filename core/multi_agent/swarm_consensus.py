"""
core/multi_agent/swarm_consensus.py
─────────────────────────────────────────────────────────────────────────────
Swarm Orchestration - Tribunal System
Instead of a single QA Validator, a tribunal of specialized agents evaluates
the Artifacts in parallel and debates until consensus is met.
"""

import asyncio
from typing import List, Tuple, Dict
from utils.logger import get_logger

logger = get_logger("swarm_consensus")

class SwarmConsensus:
    def __init__(self, agent_instance):
        self.agent = agent_instance
        self.tribunal_personas = {
            "security": "SEN BİR SİBER GÜVENLİK UZMANISIN (SecOps). SADECE güvenlik zafiyetleri ve data sızıntılarını, yetki aşımını ara.",
            "performance": "SEN BİR PERFORMANS MÜHENDİSİSİN. Big-O karmaşıklığı, gereksiz döngüler ve yavaşlatıcı memory/cpu sızıntılarını denetle.",
            "ux": "SEN UX VE PRODUCT MÜHENDİSİSİN. Sistem kullanıcının gerçekte istediği faydayı sunuyor mu buna bak.",
            "risk_manager": "SEN BİR FİNANSAL RİSK YÖNETİCİSİSİSİN (RiskOps). İşlemde (eğer varsa) yüksek drawdown riski, bakiye sıfırlama veya hatalı token ticareti risklerini bloke et."
        }
        
    async def _evaluate_persona(self, persona: str, prompt: str, artifact_dump: str) -> Tuple[bool, str]:
        """A single swarm node evaluating the payload."""
        eval_prompt = f"""
{self.tribunal_personas[persona]}
GÖREV BAĞLAMI: {prompt}

ÜRETİLEN ARTIFACTS:
{artifact_dump}

GÖREV:
1. Sadece kendi uzmanlık alanına giren riskleri değerlendir.
2. PASS veya FAIL kararı ver.
3. Çıktı formatın:
KARAR: [PASS veya FAIL]
GEREKÇE: [Tek Cümle]
RİSKLER: [Eğer varsa liste]
"""
        from core.multi_agent.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator(self.agent)
        try:
            report = await orch._run_specialist("executor", eval_prompt)
            # Circuit Breaker Budget Check
            if "BÜTÇE LİMİT AŞILDI" in report: return False, "Budget"
            
            passed = "KARAR: PASS" in report.upper()
            return passed, report.strip()
        except Exception as e:
            logger.error(f"Swarm Node ({persona}) failed: {e}")
            return False, f"Crash: {e}"

    async def run_tribunal_debate(self, intent: str, artifacts: dict) -> Tuple[bool, List[str]]:
        """Spawns 3 specialized QA agents concurrently."""
        if not artifacts:
            return False, ["Hiç artifact üretilmedi."]

        # Flatten artifact contents
        dump = "\n---\n".join([f"[{k}]\n{v.content[:1000]}..." for k, v in artifacts.items()])
        
        logger.info(f"⚖️ Swarm Tribunal starting debate across {len(self.tribunal_personas)} domains...")
        
        tasks = [
            self._evaluate_persona(persona, intent, dump)
            for persona in self.tribunal_personas.keys()
        ]
        
        # Parallel Execution Map/Reduce
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        issues = []
        pass_count = 0
        total = len(self.tribunal_personas)
        
        for i, (persona, (success, report)) in enumerate(zip(self.tribunal_personas.keys(), results)):
            if success:
                pass_count += 1
                logger.info(f"  ✔ {persona.upper()}: PASSED")
            else:
                logger.warning(f"  ❌ {persona.upper()}: FAILED -> {report}")
                issues.append(f"[{persona.upper()} TRIBUNAL REDDİ]: {report}")
                
        # Consensus Rules: 100% agreement required
        final_verdict = pass_count == total
        
        if final_verdict:
            logger.info("🏛️ Tribunal Consensus Reached: APPROVED")
        else:
            logger.warning(f"🏛️ Tribunal Consensus Denied: {pass_count}/{total} Passed.")
            
        return final_verdict, issues
