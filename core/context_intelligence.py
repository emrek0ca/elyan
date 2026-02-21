"""
core/context_intelligence.py
─────────────────────────────────────────────────────────────────────────────
Detects the active operational domain and technology stack from user input 
and environment. Enables the agent to pivot its behavior dynamically.
"""

from __future__ import annotations
import re
from typing import Dict, Any, List, Optional

class ContextIntelligence:
    def __init__(self):
        self.domains = {
            "coding": [r"kod", r"yazılım", r"program", r"script", r"debug", r"hata", r"fonksiyon"],
            "web_dev": [r"website", r"html", r"css", r"react", r"nextjs", r"js", r"javascript", r"frontend", r"backend"],
            "research": [r"araştır", r"bilgi topla", r"kaynak", r"rapor", r"analiz", r"incele"],
            "system": [r"dosya", r"klasör", r"terminal", r"bash", r"mac", r"sistem", r"ekran", r"wifi", r"pil"],
            "office": [r"word", r"excel", r"xlsx", r"docx", r"tablo", r"belge", r"döküman"],
        }
        
        self.stacks = {
            "python": [r"python", r"py", r"pip", r"pytest", r"fastapi", r"flask"],
            "javascript": [r"js", r"javascript", r"node", r"npm", r"react", r"vue", r"nextjs"],
            "shell": [r"bash", r"zsh", r"terminal", r"komut", r"sh"],
        }

    def detect(self, user_input: str) -> Dict[str, Any]:
        low_input = user_input.lower()
        
        detected_domain = "general"
        for domain, patterns in self.domains.items():
            if any(re.search(p, low_input) for p in patterns):
                detected_domain = domain
                break
        
        detected_stack = "none"
        for stack, patterns in self.stacks.items():
            if any(re.search(p, low_input) for p in patterns):
                detected_stack = stack
                break
                
        return {
            "domain": detected_domain,
            "stack": detected_stack,
            "is_creative": any(k in low_input for k in ["şiir", "hikaye", "yaratıcı", "fikir bul"]),
            "needs_automation": any(k in low_input for k in ["rutin", "otomatik", "her gün", "zamanla"]),
        }

    def get_specialized_prompt(self, context: Dict[str, Any]) -> str:
        prompts = {
            "web_dev": f"Şu an bir Senior Frontend Architect rolündesin. Modern, erişilebilir ve responsive {context['stack'].upper() if context['stack'] != 'none' else ''} web yapılarına odaklan. CSS'te Tailwind veya modern Flex/Grid yapılarını tercih et.",
            "coding": f"Şu an bir Senior {context['stack'].upper() if context['stack'] != 'none' else ''} Developer rolündesin. Temiz kod (Clean Code), SOLID prensipleri ve kapsamlı test yazımı senin için önceliktir.",
            "research": "Şu an bir Deep Research Analyst rolündesin. Veriye dayalı, kaynak gösteren ve tarafsız raporlar üretmeye odaklan. Bilgi kirliliğinden kaçın.",
            "system": "Şu an bir System Administrator rolündesin. Güvenlik, performans ve stabilite en büyük önceliğin. Terminal komutlarında dikkatli ve kesin ol.",
            "office": "Şu an bir Data & Document Specialist rolündesin. Profesyonel raporlama formatlarına, veri doğruluğuna ve kurumsal dile sadık kal."
        }
        return prompts.get(context["domain"], "")

    def get_preferred_tools(self, domain: str) -> List[str]:
        mapping = {
            "web_dev": ["create_web_project_scaffold", "verify_web_project_smoke_test", "open_url"],
            "coding": ["run_code", "execute_python_code", "open_project_in_ide", "debug_code"],
            "research": ["advanced_research", "web_search", "research_document_delivery", "generate_document_pack"],
            "office": ["write_word", "write_excel", "read_word", "read_excel", "summarize_document"],
            "system": ["get_system_info", "run_safe_command", "list_files", "take_screenshot"]
        }
        return mapping.get(domain, [])

_intelligence = ContextIntelligence()

def get_context_intelligence() -> ContextIntelligence:
    return _intelligence
