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
    emoji: str = "🤖"


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

            # Legacy aliases
            "pm_agent": None,  # → lead
            "executor": None,  # → builder
            "tool_runner": None,  # → ops
            "qa_expert": None,  # → qa
            "automation_expert": None,  # → ops
        }
        # Set legacy aliases
        self.specialists["pm_agent"] = self.specialists["lead"]
        self.specialists["executor"] = self.specialists["builder"]
        self.specialists["tool_runner"] = self.specialists["ops"]
        self.specialists["qa_expert"] = self.specialists["qa"]
        self.specialists["automation_expert"] = self.specialists["ops"]

    def get(self, key: str) -> Optional[SpecialistIdentity]:
        return self.specialists.get(key)

    def get_team(self) -> Dict[str, SpecialistIdentity]:
        """Return all non-alias specialists."""
        core = ["lead", "researcher", "builder", "ops", "qa", "communicator"]
        return {k: self.specialists[k] for k in core}

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
