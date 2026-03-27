"""
core/multi_agent/specialists.py
─────────────────────────────────────────────────────────────────────────────
Agent Team: Specialized AI agents with distinct roles, capabilities, and
behavior prompts. Each specialist operates autonomously within its domain.
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
    preferred_model: str = "gpt-4o"
    preferred_providers: List[str] = field(default_factory=list)
    capabilities: List[str] = field(default_factory=list)
    llm_role: str = "reasoning"
    local_first: bool = True
    cloud_allowed: bool = False
    secret_access: bool = False
    tool_scope: List[str] = field(default_factory=list)
    handoff_template: str = ""
    emoji: str = "🤖"

class SpecialistChain:
    """
    Defines a sequence of specialists to handle a specific workflow.
    """
    def __init__(self, name: str, steps: List[str]):
        self.name = name
        self.steps = steps # List of specialist keys

class SpecialistRegistry:
    def __init__(self):
        self.protocol_rules = """
CEVAP FORMATI (STRICT):
<thought>
Görevi analiz et. Neyi, neden yapacağını, olası hataları ve çözüm planını detaylıca açıkla.
Kullanıcının asıl niyetini anla — sıradan konuşma diliyle söylenen teknik görevleri de yakala.
</thought>

{
  "outputs": ["üretilen dosyalar veya sonuçlar"],
  "assumptions": ["varsayımlar"],
  "risks": ["olası sorunlar"],
  "next_actions": ["takip edici adım"]
}
"""

        self.specialists = {
            # ─── LEADER: Task Coordinator ───
            "lead": SpecialistIdentity(
                name="Koordinatör",
                role="Görev Koordinatörü ve Takım Lideri",
                emoji="🎯",
                preferred_model="gpt-4o",
                preferred_providers=["ollama", "openai", "anthropic"],
                capabilities=["task_decomposition", "llm_reasoning", "coordination"],
                llm_role="planning",
                cloud_allowed=False,
                secret_access=False,
                tool_scope=["planning", "coordination"],
                handoff_template="Görevi alt işlere böl, sahipleri ata ve kritik riskleri açıkla.",
                system_prompt=(
                    "Sen takımın liderisin. Gelen görevi analiz edip doğru uzmanlara yönlendirirsin. "
                    "Doğal dilde söylenen her talebi anlayıp teknik görevlere çevirirsin.\n\n"
                    "KURALLAR:\n"
                    "1. Kullanıcı 'bi araştır' derse → researcher'a yönlendir\n"
                    "2. Kullanıcı 'yaz/oluştur/kod' derse → builder'a yönlendir\n"
                    "3. Kullanıcı 'dosya/klasör/temizle' derse → ops'a yönlendir\n"
                    "4. Genel sohbet ise → kendın yanıtla\n"
                    "5. Karmaşık görevleri adımlara böl ve paralel çalıştır\n"
                ),
                preferred_tools=["create_plan"],
                domain="coordination"
            ),

            # ─── RESEARCHER: Deep Research & Analysis ───
            "researcher": SpecialistIdentity(
                name="Araştırmacı",
                role="Derin Araştırma ve Analiz Uzmanı",
                emoji="🔬",
                preferred_model="google/gemini-pro",
                preferred_providers=["google", "groq", "openai"],
                capabilities=["web_search", "summarization", "fact_extraction"],
                llm_role="research_worker",
                cloud_allowed=True,
                secret_access=False,
                tool_scope=["web_search", "web_fetch", "grounding"],
                handoff_template="Kaynakları topla, iddiaları doğrula ve belirsizlikleri not et.",
                system_prompt=(
                    "Sen bir araştırma uzmanısın. Konuyu derinlemesine araştırır, "
                    "birden fazla kaynaktan veri toplar, çapraz doğrulama yapar ve "
                    "bulgularını profesyonel raporlar halinde sunarsin.\n\n"
                    "KURALLAR:\n"
                    "1. Her iddiayı en az 2 kaynakla doğrula\n"
                    "2. Bulguları Markdown raporuna yaz\n"
                    "3. Riskleri ve belirsizlikleri açıkça belirt\n"
                    "4. Kaynak URL'leri ve referansları mutlaka ekle\n"
                    f"{self.protocol_rules}"
                ),
                preferred_tools=["advanced_research", "web_search", "web_fetch", "write_file"],
                domain="research"
            ),

            # ─── BUILDER: Code & Content Creation ───
            "builder": SpecialistIdentity(
                name="Yazılımcı",
                role="Full-Stack Geliştirici ve İçerik Üretici",
                emoji="🏗️",
                preferred_model="claude-3-5-sonnet",
                preferred_providers=["ollama", "deepseek", "anthropic", "openai"],
                capabilities=["code_execution", "file_write", "testing"],
                llm_role="code_worker",
                cloud_allowed=True,
                secret_access=False,
                tool_scope=["code", "workspace_files", "tests"],
                handoff_template="Değişikliği üret, doğrulama adımlarını ve kalan riskleri açıkla.",
                system_prompt=(
                    "Sen kıdemli bir yazılımcısın. Temiz, hatasız, production-ready kod yazarsın. "
                    "Her dosyayı [FILE: /yol] formatında tam ve eksiksiz verirsin.\n\n"
                    "KURALLAR:\n"
                    "1. Kodu çalıştırmadan ÖNCE test et\n"
                    "2. Error handling her zaman ekle\n"
                    "3. Dosya yollarını kesinlikle doğru ver\n"
                    "4. Bağımlılıkları kontrol et\n"
                    f"{self.protocol_rules}"
                ),
                preferred_tools=["write_file", "edit_file", "run_code", "create_coding_project", "create_web_project_scaffold"],
                domain="building"
            ),

            # ─── OPS: System Operations ───
            "ops": SpecialistIdentity(
                name="Operasyon",
                role="Sistem ve Dosya Operasyon Uzmanı",
                emoji="⚙️",
                preferred_model="gpt-4o-mini",
                preferred_providers=["ollama", "groq", "openai"],
                capabilities=["filesystem", "network", "ui_automation"],
                llm_role="worker",
                cloud_allowed=False,
                secret_access=True,
                tool_scope=["filesystem", "runtime", "desktop"],
                handoff_template="İşlem sonucunu, etkilenen yolları ve geri dönüş adımını yaz.",
                system_prompt=(
                    "Sen operasyon uzmanısın. Dosya işlemleri, sistem yönetimi, "
                    "terminal komutları ve otomasyon görevlerini yürütürsün.\n\n"
                    "KURALLAR:\n"
                    "1. Tehlikeli komutlardan önce onay al\n"
                    "2. Dosya silme işlemlerinde çift kontrol et\n"
                    "3. Hata durumunda anlaşılır açıklama yap\n"
                    "4. İşlem sonuçlarını net raporla\n"
                ),
                preferred_tools=["run_code", "list_files", "read_file", "write_file", "take_screenshot",
                                 "get_system_info", "get_battery_status"],
                domain="operations"
            ),

            # ─── QA: Quality Assurance ───
            "qa": SpecialistIdentity(
                name="Kalite Kontrol",
                role="Test ve Kalite Güvence Uzmanı",
                emoji="🔍",
                preferred_model="gpt-4o",
                preferred_providers=["ollama", "openai", "anthropic"],
                capabilities=["testing", "verification", "review"],
                llm_role="qa",
                cloud_allowed=False,
                secret_access=False,
                tool_scope=["verification", "review", "tests"],
                handoff_template="Başarısız kapıları, doğrulama kanıtlarını ve önerilen düzeltmeyi yaz.",
                system_prompt=(
                    "Sen kalite kontrol uzmanısın. Üretilen her çıktıyı titizlikle inceler, "
                    "hataları bulur ve düzeltme önerileri sunarsın.\n\n"
                    "KURALLAR:\n"
                    "1. Kod çalışıyor mu kontrol et\n"
                    "2. Dosya boyutu ve bütünlüğünü doğrula\n"
                    "3. Güvenlik açıklarını tara\n"
                    "4. En ufak hatada 'FAIL' ver ve sebep açıkla\n"
                    f"{self.protocol_rules}"
                ),
                preferred_tools=["read_file", "list_files", "run_code", "verify_visual_quality"],
                domain="qa"
            ),

            # ─── COMMUNICATOR: User Interaction ───
            "communicator": SpecialistIdentity(
                name="İletişimci",
                role="Kullanıcı İletişim ve Raporlama Uzmanı",
                emoji="💬",
                preferred_model="gpt-4o",
                preferred_providers=["openai", "anthropic", "google"],
                capabilities=["summarization", "reporting"],
                llm_role="creative",
                local_first=False,
                cloud_allowed=True,
                secret_access=False,
                tool_scope=["summary", "reporting"],
                handoff_template="Teknik sonucu sakin, kısa ve karar verilebilir biçimde özetle.",
                system_prompt=(
                    "Sen iletişim uzmanısın. Teknik sonuçları kullanıcının anlayacağı "
                    "dilde, net ve öz şekilde aktarırsın. Türkçe yanıt verirsin.\n\n"
                    "KURALLAR:\n"
                    "1. Teknik jargondan kaçın\n"
                    "2. Sonuçları madde madde özetle\n"
                    "3. Başarılı işlemleri ✅, hataları ❌ ile işaretle\n"
                    "4. Gerektiğinde sonraki adımları öner\n"
                ),
                preferred_tools=["chat"],
                domain="communication"
            ),
            "code_agent": SpecialistIdentity(
                name="CodeAgent",
                role="Kod yazma, debug ve refactor uzmanı",
                emoji="⌘",
                preferred_model="ollama/llama3.1:8b",
                preferred_providers=["ollama", "deepseek", "groq", "anthropic"],
                capabilities=["code_execution", "ast_analysis", "testing", "file_write"],
                llm_role="code_worker",
                cloud_allowed=True,
                secret_access=False,
                tool_scope=["code", "workspace_files", "tests"],
                handoff_template="Kod değişikliğini, test sonucunu ve açık kalan riskleri teslim et.",
                system_prompt=(
                    "Sen Elyan'ın CodeAgent'isin. Kod yazma, debug, refactor ve patch işlerinde uzmanlaşmışsın. "
                    "Önce yerel modeli kullan, gerekirse daha güçlü modele yüksel. "
                    "Çıktın uygulanabilir, doğrulanabilir ve üretim kalitesinde olmalı."
                ),
                preferred_tools=["write_file", "edit_file", "run_code", "run_safe_command", "create_coding_project"],
                domain="coding",
            ),
            "research_agent": SpecialistIdentity(
                name="ResearchAgent",
                role="Web araştırma, kaynak toplama ve grounding uzmanı",
                emoji="🌐",
                preferred_model="google/gemini-2.0-flash",
                preferred_providers=["google", "groq", "openai"],
                capabilities=["web_search", "summarization", "fact_extraction", "evidence_collection"],
                llm_role="research_worker",
                local_first=False,
                cloud_allowed=True,
                secret_access=False,
                tool_scope=["web_search", "grounding", "evidence"],
                handoff_template="Kaynak listesini, ana bulguları ve belirsizlikleri teslim et.",
                system_prompt=(
                    "Sen Elyan'ın ResearchAgent'isin. Web araştırması yapar, kaynakları toplar, doğrular ve "
                    "kanıt merkezli özet üretirsin. Tahmin yerine kaynak göster."
                ),
                preferred_tools=["advanced_research", "web_search", "web_fetch", "open_url", "write_file"],
                domain="research",
            ),
            "document_agent": SpecialistIdentity(
                name="DocumentAgent",
                role="Rapor, sunum ve uzun biçimli döküman üretim uzmanı",
                emoji="🗂️",
                preferred_model="anthropic/claude-3-5-sonnet-latest",
                preferred_providers=["anthropic", "openai", "google"],
                capabilities=["document_generation", "summarization", "file_write", "presentation_generation"],
                llm_role="creative",
                local_first=False,
                cloud_allowed=True,
                secret_access=False,
                tool_scope=["documents", "presentations", "reports"],
                handoff_template="Final dökümanı, kaynak dayanaklarını ve yayın risklerini teslim et.",
                system_prompt=(
                    "Sen Elyan'ın DocumentAgent'isin. Uzun context ile çalışan, rafine rapor, sunum ve dökümanlar üreten uzmansın. "
                    "Biçim, yapı ve teslim kalitesine odaklan."
                ),
                preferred_tools=["write_file", "write_word", "write_excel", "research_document_delivery"],
                domain="documentation",
            ),
            "thinking_agent": SpecialistIdentity(
                name="ThinkingAgent",
                role="Derin düşünme, planlama ve problem çözme uzmanı",
                emoji="🧠",
                preferred_model="deepseek/deepseek-chat",
                preferred_providers=["ollama", "deepseek", "anthropic", "openai"],
                capabilities=["llm_reasoning", "task_decomposition", "planning", "synthesis"],
                llm_role="reasoning",
                cloud_allowed=False,
                secret_access=False,
                tool_scope=["planning", "reasoning", "synthesis"],
                handoff_template="Planı, varsayımları, karar noktalarını ve sonraki en iyi eylemi teslim et.",
                system_prompt=(
                    "Sen Elyan'ın ThinkingAgent'isin. Karmaşık görevleri parçalara ayırır, belirsizliği azaltır ve "
                    "adım adım plan üretirsin. Gereksiz konuşma yok, net muhakeme var."
                ),
                preferred_tools=["chat", "create_plan", "advanced_research"],
                domain="reasoning",
            ),
        }
        
        # ─── Definition of standard chains ───
        self.chains = {
            "RESEARCH_WORKFLOW": SpecialistChain("Research & Report", ["lead", "researcher", "qa", "communicator"]),
            "CODING_WORKFLOW": SpecialistChain("Build & Deploy", ["lead", "builder", "ops", "qa", "communicator"]),
            "FIX_WORKFLOW": SpecialistChain("Analyze & Patch", ["lead", "ops", "builder", "qa", "communicator"]),
            "NEXTGEN_OPERATOR_WORKFLOW": SpecialistChain("Next-Gen Operator", ["thinking_agent", "research_agent", "code_agent", "document_agent"]),
        }

        # Set legacy aliases
        self.specialists["pm_agent"] = self.specialists["lead"]
        self.specialists["executor"] = self.specialists["builder"]
        self.specialists["tool_runner"] = self.specialists["ops"]
        self.specialists["qa_expert"] = self.specialists["qa"]
        self.specialists["automation_expert"] = self.specialists["ops"]
        self.specialists["coder"] = self.specialists["builder"]
        self.specialists["codeagent"] = self.specialists["code_agent"]
        self.specialists["researchagent"] = self.specialists["research_agent"]
        self.specialists["documentagent"] = self.specialists["document_agent"]
        self.specialists["thinkingagent"] = self.specialists["thinking_agent"]
        self.specialists["executive"] = self.specialists["lead"]
        self.specialists["planner"] = self.specialists["thinking_agent"]
        self.specialists["research"] = self.specialists["research_agent"]
        self.specialists["artifact"] = self.specialists["document_agent"]
        self.specialists["code"] = self.specialists["code_agent"]
        self.specialists["review"] = self.specialists["qa"]
        self.specialists["security"] = self.specialists["ops"]

    def get(self, key: str) -> Optional[SpecialistIdentity]:
        return self.specialists.get(key)

    def get_chain(self, key: str) -> Optional[SpecialistChain]:
        return self.chains.get(key)

    def get_team(self) -> Dict[str, SpecialistIdentity]:
        """Return all non-alias specialists."""
        core = ["lead", "researcher", "builder", "ops", "qa", "communicator"]
        return {k: self.specialists[k] for k in core}

    def get_nextgen_team(self) -> Dict[str, SpecialistIdentity]:
        keys = ["thinking_agent", "research_agent", "code_agent", "document_agent"]
        return {key: self.specialists[key] for key in keys}

    def get_provider_chain(self, key: str) -> List[str]:
        specialist = self.get(key)
        if specialist is None:
            return ["ollama", "groq", "google", "openai", "anthropic"]
        ordered: List[str] = []
        if specialist.local_first:
            ordered.append("ollama")
        for provider in specialist.preferred_providers or []:
            token = str(provider or "").strip().lower()
            if token and token not in ordered:
                ordered.append(token)
        for provider in ["groq", "google", "openai", "anthropic", "deepseek", "mistral", "ollama"]:
            if provider not in ordered:
                ordered.append(provider)
        return ordered

    def sync_contract_net(self, contract_net: Any) -> None:
        if contract_net is None or not hasattr(contract_net, "register_agent"):
            return
        concurrency = {
            "thinking_agent": 2,
            "research_agent": 3,
            "code_agent": 3,
            "document_agent": 2,
        }
        for agent_id, specialist in self.get_nextgen_team().items():
            contract_net.register_agent(
                agent_id,
                list(specialist.capabilities or []),
                max_concurrent=int(concurrency.get(agent_id, 2)),
            )

    def select_for_input(self, user_input: str) -> SpecialistIdentity:
        """Smart agent selection based on user input analysis."""
        low = user_input.lower()
        words = low.split()

        # ── Chat/Greeting patterns (highest priority for casual messages) ──
        chat_kw = [
            "merhaba", "selam", "naber", "nasılsın", "nasilsin", "hey",
            "günaydın", "gunaydin", "iyi geceler", "iyi akşamlar",
            "sağol", "teşekkür", "tesekkur", "eyvallah", "tamam",
            "hello", "hi", "thanks", "thank you", "bye", "hoşça kal",
        ]
        # Only match if the entire message is short/casual
        if len(words) <= 4 and any(k in low for k in chat_kw):
            return self.specialists["communicator"]

        # ── Research patterns (TR + EN) ──
        research_kw = [
            "araştır", "arastir", "research", "incele", "analiz",
            "karşılaştır", "compare", "ne olmuş", "haber",
            "trend", "piyasa", "market", "report", "rapor",
        ]
        if any(k in low for k in research_kw):
            return self.specialists["researcher"]

        # ── Building patterns ──
        build_kw = [
            "yaz", "oluştur", "olustur", "kod", "code", "build",
            "geliştir", "develop", "program", "uygulama", "website",
            "script", "create", "generate", "proje", "project",
            "düzenle", "refactor", "implement",
        ]
        if any(k in low for k in build_kw):
            return self.specialists["builder"]

        # ── Operations patterns ──
        ops_kw = [
            "dosya", "file", "klasör", "folder", "sil", "delete",
            "taşı", "move", "kopyala", "copy", "temizle", "clean",
            "kur", "install", "sistem", "system", "terminal",
            "çalıştır", "run", "execute", "ekran", "screenshot",
            "listele", "list", "göster", "aç", "kapat",
        ]
        if any(k in low for k in ops_kw):
            return self.specialists["ops"]

        # ── QA patterns ──
        qa_kw = ["test", "kontrol", "doğrula", "verify", "check", "hata", "bug", "debug"]
        if any(k in low for k in qa_kw):
            return self.specialists["qa"]

        # ── Context intelligence fallback ──
        try:
            from core.context_intelligence import get_context_intelligence
            ctx = get_context_intelligence().detect(user_input)
            domain_map = {
                "coding": "builder",
                "web_dev": "builder",
                "research": "researcher",
                "system": "ops",
                "office": "builder",
                "automation": "ops",
                "communication": "communicator",
            }
            key = domain_map.get(ctx["domain"], "communicator")
            return self.specialists[key]
        except Exception:
            return self.specialists["communicator"]

    def format_team_status(self) -> str:
        """Format team overview for display."""
        lines = ["🏢 Elyan Ajan Takımı", "═" * 40]
        for key, spec in self.get_team().items():
            lines.append(f"  {spec.emoji} {spec.name} ({spec.role})")
        return "\n".join(lines)


_registry = SpecialistRegistry()

def get_specialist_registry() -> SpecialistRegistry:
    return _registry
