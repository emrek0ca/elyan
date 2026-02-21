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
        self.specialists = {
            "coder": SpecialistIdentity(
                name="Elyan Code",
                role="Senior Software Engineer",
                system_prompt="Sen bir yazılım uzmanısın. Kod kalitesi, mimari ve test edilebilirlik senin için kutsaldır. Sadece çalışan ve optimize edilmiş kod üretirsin.",
                preferred_tools=["run_code", "execute_python_code", "open_project_in_ide", "debug_code"],
                domain="coding"
            ),
            "researcher": SpecialistIdentity(
                name="Elyan Research",
                role="Lead Research Analyst",
                system_prompt="Sen bir araştırma uzmanısın. İnternetteki bilgileri tarar, doğrular ve yapılandırılmış raporlar haline getirirsin. Kaynak göstermek zorunludur.",
                preferred_tools=["advanced_research", "web_search", "fetch_page", "summarize_document"],
                domain="research"
            ),
            "sysadmin": SpecialistIdentity(
                name="Elyan System",
                role="System Administrator",
                system_prompt="Sen bir sistem yöneticisisin. Terminal komutları, dosya sistemi yönetimi ve donanım sağlığı senin uzmanlık alanındır. Güvenlikten taviz vermezsin.",
                preferred_tools=["run_safe_command", "get_system_info", "list_files", "get_process_info"],
                domain="system"
            ),
            "officer": SpecialistIdentity(
                name="Elyan Office",
                role="Document & Data Specialist",
                system_prompt="Sen profesyonel bir dökümantasyon ve veri uzmanısın. Word, Excel ve raporlama formatlarında mükemmel çıktılar üretirsin.",
                preferred_tools=["write_word", "write_excel", "read_word", "read_excel", "generate_document_pack"],
                domain="office"
            ),
            "qa_expert": SpecialistIdentity(
                name="Elyan QA",
                role="Senior Quality Assurance Engineer",
                system_prompt="Sen bir kalite denetçisisin. Diğer uzmanların çıktılarını doğruluk, tamlık ve profesyonellik açısından incelersin. Hataları acımasızca bulur ve yapıcı çözüm önerileri sunarsın. Onay vermediğin hiçbir iş teslim edilemez.",
                preferred_tools=["analyze_document", "run_code", "verify_web_project_smoke_test"],
                domain="qa"
            )
        }

    def get(self, key: str) -> Optional[SpecialistIdentity]:
        return self.specialists.get(key)

    def select_for_input(self, user_input: str) -> SpecialistIdentity:
        from core.context_intelligence import get_context_intelligence
        ctx = get_context_intelligence().detect(user_input)
        
        domain_map = {
            "coding": "coder",
            "web_dev": "coder",
            "research": "researcher",
            "system": "sysadmin",
            "office": "officer"
        }
        key = domain_map.get(ctx["domain"], "researcher") # Default to researcher for unknown
        return self.specialists[key]

_registry = SpecialistRegistry()

def get_specialist_registry() -> SpecialistRegistry:
    return _registry
