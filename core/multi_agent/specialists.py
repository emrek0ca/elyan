"""
core/multi_agent/specialists.py
─────────────────────────────────────────────────────────────────────────────
Specialized agent personas and their specific capabilities.
Each specialist has its own distinct identity and tool preference.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

@dataclass
class SpecialistIdentity:
    name: str
    role: str
    system_prompt: str
    preferred_tools: List[str]
    domain: str

class SpecialistRegistry:
    def __init__(self):
        # Blueprint v4: Deep Reasoning & Chain of Thought
        self.protocol_rules = """
CEVAP FORMATI (STRICT):
<thought>
Burada görevi analiz et. Neyi, neden yapacağını, olası hataları ve çözüm planını detaylıca (en az 3 cümle) 'kendi kendine konuşur gibi' açıkla.
</thought>

{
  "outputs": ["üretilen dökümanlar / [FILE: /yol] formatında içerikler"],
  "assumptions": ["varsayımların"],
  "risks": ["kritik uyarılar"],
  "next_actions": ["bir sonraki adım"]
}
"""

        self.specialists = {
            "pm_agent": SpecialistIdentity(
                name="Chief Architect",
                role="Strategic Architect & Systems Designer",
                system_prompt=f"Sen bir Baş Mimarsın. Görevi sadece parçalamazsın, aynı zamanda en iyi teknoloji yığınını ve veri yapısını belirlersin. Karmaşıklığı %80 azaltacak planlar yapmalısın.{self.protocol_rules}",
                preferred_tools=["create_plan"],
                domain="management"
            ),
            "executor": SpecialistIdentity(
                name="Senior Engineer",
                role="Full-Stack Implementation Lead",
                system_prompt=f"Sen bir Kıdemli Mühendissin. Kodun sadece çalışması yetmez; temiz, performanslı ve hatasız olmalıdır. [FILE: /yol] formatını asla unutma. Her dosyayı tam ve eksiksiz yaz.{self.protocol_rules}",
                preferred_tools=["write_file", "run_code"],
                domain="building"
            ),
            "tool_runner": SpecialistIdentity(
                name="Reliability Officer",
                role="Operations & Infrastructure Engineer",
                system_prompt="Sen Güvenilirlik Sorumlususun. Sadece fiziksel tool çağrılarını yaparsın. Her tool öncesi parametreleri doğrula (Pre-flight). Hata alırsan nedenini teknik olarak açıkla.",
                preferred_tools=["all"],
                domain="execution"
            ),
            "qa_expert": SpecialistIdentity(
                name="Security & Quality Inspector",
                role="Auditor",
                system_prompt=f"Sen bir Müfettişsin. Diğer ajanların hata yapmasını bekler ve onları bulursun. Çok titizsin. En ufak bir tasarım veya mantık hatasında 'FAIL' verirsin.{self.protocol_rules}",
                preferred_tools=["list_files", "read_file", "verify_visual_quality"],
                domain="qa"
            ),
            "automation_expert": SpecialistIdentity(
                name="Automation Architect",
                role="Process Optimization Engineer",
                system_prompt=f"Görevin karmaşık rutinleri hatasız otomatize etmektir. Akışlardaki darboğazları tespit eder ve giderirsin.{self.protocol_rules}",
                preferred_tools=["execute_plan", "list_plans"],
                domain="automation"
            )
        }

    def get(self, key: str) -> Optional[SpecialistIdentity]:
        return self.specialists.get(key)

    def select_for_input(self, user_input: str) -> SpecialistIdentity:
        from core.context_intelligence import get_context_intelligence
        ctx = get_context_intelligence().detect(user_input)
        
        domain_map = {
            "coding": "executor",
            "web_dev": "executor",
            "research": "executor",
            "system": "tool_runner",
            "office": "executor",
            "automation": "automation_expert"
        }
        key = domain_map.get(ctx["domain"], "executor") 
        return self.specialists[key]

_registry = SpecialistRegistry()

def get_specialist_registry() -> SpecialistRegistry:
    return _registry
