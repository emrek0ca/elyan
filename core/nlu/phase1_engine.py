from __future__ import annotations

import json
import math
import re
import time
from typing import TYPE_CHECKING
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterable, Optional

import numpy as np

from core.capability_router import CapabilityRouter, get_capability_router
from core.model_manager import LocalHashingEmbedder
from core.nlu.baseline_intent_model import NaiveBayesIntentModel
from core.turkish_nlp import TurkishNLPAnalyzer
from utils.logger import get_logger

logger = get_logger("phase1_nlu")

if TYPE_CHECKING:
    from core.intent.models import IntentCandidate, TaskDefinition

PHASE1_CORRECTIONS_PATH = Path.home() / ".elyan" / "nlu" / "phase1_corrections.json"


@dataclass(slots=True)
class IntentTaxonomyEntry:
    intent: str
    action: str
    domain: str
    keywords: tuple[str, ...]
    examples: tuple[str, ...]
    route_mode: str = "task"
    content_kind: str = "task"
    output_formats: tuple[str, ...] = ()
    style_profile: str = "balanced"
    source_policy: str = "trusted"
    quality_contract: tuple[str, ...] = ()
    clarifying_question: str = ""
    needs_clarification: bool = False
    evidence_required: bool = True
    learning_tags: tuple[str, ...] = ()


@dataclass(slots=True)
class Phase1Decision:
    intent: str
    action: str
    confidence: float
    reasoning: str
    params: dict[str, Any] = field(default_factory=dict)
    entities: dict[str, list[str]] = field(default_factory=dict)
    clarification_question: str = ""
    needs_clarification: bool = False
    tasks: list[Any] = field(default_factory=list)
    request_contract: dict[str, Any] = field(default_factory=dict)
    candidate_scores: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source: str = "phase1"

    def to_candidate(self) -> "IntentCandidate":
        from core.intent.models import IntentCandidate

        return IntentCandidate(
            action=self.action,
            confidence=float(self.confidence),
            reasoning=self.reasoning,
            params=dict(self.params or {}),
            tasks=list(self.tasks or []),
            source_tier=self.source,
            metadata={
                "phase1_intent": self.intent,
                "phase1_action": self.action,
                "phase1_entities": dict(self.entities or {}),
                "phase1_request_contract": dict(self.request_contract or {}),
                "phase1_candidate_scores": list(self.candidate_scores or []),
                **dict(self.metadata or {}),
            },
        )

    def to_parser_payload(self) -> dict[str, Any]:
        payload = {
            "action": self.intent,
            "params": dict(self.params or {}),
            "reply": self.reply_text(),
            "confidence": float(self.confidence),
        }
        if self.tasks:
            payload["tasks"] = [
                {
                    "id": task.task_id,
                    "action": task.action,
                    "params": dict(task.params or {}),
                    "depends_on": list(task.depends_on or []),
                    "output_key": task.output_key,
                }
                for task in self.tasks
            ]
            payload["action"] = "multi_task"
        payload["metadata"] = {
            "phase1_action": self.action,
            "phase1_entities": dict(self.entities or {}),
            "phase1_request_contract": dict(self.request_contract or {}),
            "phase1_candidate_scores": list(self.candidate_scores or []),
            **dict(self.metadata or {}),
        }
        if self.needs_clarification and self.clarification_question:
            payload["action"] = "clarify"
            payload["params"] = {
                **dict(self.params or {}),
                "question": self.clarification_question,
            }
            payload["reply"] = self.clarification_question
        return payload

    def reply_text(self) -> str:
        if self.needs_clarification and self.clarification_question:
            return self.clarification_question
        if self.intent == "research_document_delivery":
            topic = str(self.params.get("topic") or "").strip()
            if topic:
                return f"'{topic}' için araştırma ve belge paketi hazırlanıyor..."
            return "Araştırma ve belge paketi hazırlanıyor..."
        if self.intent == "create_word_document":
            return f"'{self.params.get('filename') or 'belge.docx'}' Word belgesi hazırlanıyor..."
        if self.intent == "create_excel":
            return f"'{self.params.get('filename') or 'tablo.xlsx'}' Excel dosyası hazırlanıyor..."
        if self.intent == "create_presentation":
            topic = str(self.params.get("topic") or "").strip()
            return f"'{topic or 'sunum'}' sunumu hazırlanıyor..."
        if self.intent == "create_website":
            topic = str(self.params.get("topic") or "").strip()
            return f"'{topic or 'website'}' için web projesi hazırlanıyor..."
        if self.intent == "create_coding_project":
            name = str(self.params.get("project_name") or "").strip()
            return f"'{name or 'proje'}' için kodlama projesi hazırlanıyor..."
        if self.intent == "translate":
            return "Çeviri hazırlanıyor..."
        if self.intent.startswith("summarize"):
            return "Özet hazırlanıyor..."
        if self.intent == "clarify":
            return self.clarification_question or "Çıktı biçimini netleştirir misin?"
        if self.intent == "chat":
            return "Mesajınız işleniyor..."
        return "İstek işleniyor..."


class Phase1NLUEngine:
    """
    Local intent/NLU engine for Phase 1.

    Features:
    - Turkish normalization + entity extraction
    - 30+ intent taxonomy
    - semantic search over examples
    - deterministic fallback learning
    - request contract generation through CapabilityRouter
    """

    DIRECT_THRESHOLD = 0.30
    CLARIFY_THRESHOLD = 0.20
    AMBIGUOUS_MARGIN = 0.05
    QUICK_RESEARCH_HINTS = ("sadece", "yalnızca", "yalnizca", "kısa", "kisa", "özet", "ozet", "hızlı", "hizli")
    RESEARCH_MARKERS = ("araştır", "arastir", "research", "incele", "analiz", "kaynaklı", "kaynakli")
    DELIVERY_MARKERS = ("word", "docx", "excel", "xlsx", "pdf", "sunum", "presentation", "slide", "deck")
    EXPLICIT_DOCUMENT_MARKERS = ("word", "docx", "excel", "xlsx", "pdf", "sunum", "presentation", "slide", "deck")
    REPORT_MARKERS = ("rapor", "doküman", "dokuman")

    def __init__(
        self,
        *,
        taxonomy: Optional[list[IntentTaxonomyEntry]] = None,
        corrections_path: Path | None = None,
        capability_router: CapabilityRouter | None = None,
        embedder: LocalHashingEmbedder | None = None,
        model_path: str | None = None,
    ) -> None:
        self.capability_router = capability_router or get_capability_router()
        self.embedder = embedder or LocalHashingEmbedder()
        self.model_path = str(model_path or "").strip() or None
        self.corrections_path = Path(corrections_path or PHASE1_CORRECTIONS_PATH).expanduser()
        self.entries = list(taxonomy or self._build_taxonomy())
        self._entry_by_intent = {entry.intent: entry for entry in self.entries}
        self._entry_by_action = {entry.action: entry for entry in self.entries}
        self._examples, self._labels = self._build_training_corpus()
        self._nb_model = NaiveBayesIntentModel().fit(self._examples, self._labels)
        self._intent_vectors = self._build_intent_vectors()
        self._learned_examples: list[dict[str, Any]] = []
        self._backend = "local_hashing_nb"
        self._load_corrections()
        if self._learned_examples:
            self._retrain()

    # ------------------------------------------------------------------
    # Taxonomy
    # ------------------------------------------------------------------
    @staticmethod
    def _build_taxonomy() -> list[IntentTaxonomyEntry]:
        return [
            IntentTaxonomyEntry(
                intent="chat",
                action="chat",
                domain="communication",
                keywords=("selam", "merhaba", "hello", "nasılsın", "naber", "sohbet"),
                examples=("merhaba", "nasılsın", "selam", "kısa bir sohbet edelim"),
                route_mode="communication",
                content_kind="communication",
                evidence_required=False,
                quality_contract=("natural_tone", "brief_reply"),
            ),
            IntentTaxonomyEntry(
                intent="clarify",
                action="clarify",
                domain="communication",
                keywords=("hangi", "hangisi", "netleştir", "belirt", "seçenek", "format"),
                examples=("bunu hangi formatta istiyorsun", "çıktı biçimini netleştir"),
                route_mode="communication",
                content_kind="communication",
                needs_clarification=True,
                evidence_required=False,
                clarifying_question="Bunu hangi formatta hazırlayayım: Word, Excel, sunum ya da web?",
            ),
            IntentTaxonomyEntry(
                intent="web_search",
                action="web_search",
                domain="research",
                keywords=("webde ara", "google ara", "internette ara", "web search", "araştır"),
                examples=("internette ara", "web'de ara", "google'da ara", "şunu webde ara"),
                route_mode="research",
                content_kind="research_delivery",
                output_formats=("text",),
                quality_contract=("source_traceability", "search_relevance"),
                learning_tags=("search", "browser"),
            ),
            IntentTaxonomyEntry(
                intent="research",
                action="advanced_research",
                domain="research",
                keywords=("araştır", "arastir", "incele", "analiz", "kaynak", "literatür"),
                examples=("pytorch hakkında araştırma yap", "Fourier serileri hakkında araştırma yap"),
                route_mode="research",
                content_kind="research_delivery",
                output_formats=("text", "report"),
                quality_contract=("source_traceability", "claim_coverage"),
                learning_tags=("research", "analysis"),
            ),
            IntentTaxonomyEntry(
                intent="research_document_delivery",
                action="research_document_delivery",
                domain="research",
                keywords=("rapor", "belge", "word", "docx", "pdf", "excel", "sunum", "araştırma"),
                examples=("araştırma yap ve word dosyası oluştur", "kaynaklı rapor hazırla"),
                route_mode="research_batch",
                content_kind="research_delivery",
                output_formats=("docx", "report"),
                quality_contract=("claim_coverage", "source_traceability", "revision_summary"),
                learning_tags=("research", "document"),
            ),
            IntentTaxonomyEntry(
                intent="summarize_text",
                action="summarize_text",
                domain="research",
                keywords=("özetle", "ozetle", "kısalt", "summary", "sentez"),
                examples=("bu metni özetle", "kısaca anlat"),
                route_mode="research",
                content_kind="summary_pack",
                output_formats=("text",),
                quality_contract=("conciseness", "coverage"),
                learning_tags=("summary",),
            ),
            IntentTaxonomyEntry(
                intent="summarize_url",
                action="summarize_url",
                domain="research",
                keywords=("url", "siteyi özetle", "sayfayı özetle", "web sayfasını özetle"),
                examples=("bu url'i özetle", "sayfayı özetle"),
                route_mode="research",
                content_kind="summary_pack",
                output_formats=("text",),
                quality_contract=("coverage", "source_traceability"),
            ),
            IntentTaxonomyEntry(
                intent="summarize_file",
                action="summarize_file",
                domain="research",
                keywords=("dosyayı özetle", "pdf özetle", "belge özetle"),
                examples=("bu pdf'i özetle", "dosyayı özetle"),
                route_mode="research",
                content_kind="summary_pack",
                output_formats=("text",),
                quality_contract=("coverage", "traceability"),
            ),
            IntentTaxonomyEntry(
                intent="translate",
                action="translate",
                domain="communication",
                keywords=("çevir", "cevir", "translate", "tercüme", "ingilizceye"),
                examples=("bunu ingilizceye çevir", "metni türkçeye çevir"),
                route_mode="communication",
                content_kind="communication",
                output_formats=("text",),
                quality_contract=("translation_fidelity",),
                evidence_required=False,
            ),
            IntentTaxonomyEntry(
                intent="create_word_document",
                action="write_word",
                domain="document",
                keywords=("word", "docx", "belge", "rapor", "word dosyası"),
                examples=("word dosyası oluştur", "word belgesi hazırla"),
                route_mode="document_pack",
                content_kind="document_pack",
                output_formats=("docx",),
                quality_contract=("document_structure", "title_body_clarity"),
                learning_tags=("office", "word"),
            ),
            IntentTaxonomyEntry(
                intent="create_excel",
                action="write_excel",
                domain="document",
                keywords=("excel", "xlsx", "tablo", "spreadsheet", "sheet"),
                examples=("excel dosyası oluştur", "tablo hazırla"),
                route_mode="spreadsheet",
                content_kind="spreadsheet",
                output_formats=("xlsx",),
                quality_contract=("table_structure", "column_clarity"),
                learning_tags=("office", "excel"),
            ),
            IntentTaxonomyEntry(
                intent="create_presentation",
                action="create_presentation",
                domain="document",
                keywords=("sunum", "presentation", "ppt", "pptx", "slide", "deck"),
                examples=("sunum hazırla", "pptx deck oluştur"),
                route_mode="presentation",
                content_kind="presentation",
                output_formats=("pptx", "slides"),
                quality_contract=("slide_outline", "message_clarity", "source_traceability"),
                learning_tags=("office", "presentation"),
            ),
            IntentTaxonomyEntry(
                intent="create_pdf",
                action="generate_document_pack",
                domain="document",
                keywords=("pdf", "pdf oluştur", "pdf yap", "pdf olarak kaydet"),
                examples=("pdf oluştur", "raporu pdf yap"),
                route_mode="document_pack",
                content_kind="document_pack",
                output_formats=("pdf",),
                quality_contract=("pdf_layout", "source_traceability"),
            ),
            IntentTaxonomyEntry(
                intent="create_website",
                action="create_web_project_scaffold",
                domain="website",
                keywords=("website", "web sitesi", "web sayfası", "landing page", "html", "css", "js"),
                examples=("portfolyo websitesi yap", "html css js ile web sitesi oluştur"),
                route_mode="web_project",
                content_kind="web_project",
                output_formats=("html", "css", "js"),
                quality_contract=("responsive_layout", "dom_contract", "style_lock"),
                learning_tags=("web", "frontend"),
            ),
            IntentTaxonomyEntry(
                intent="create_coding_project",
                action="create_coding_project",
                domain="code",
                keywords=("kod", "uygulama", "app", "proje", "debug", "refactor", "script"),
                examples=("python ile bir uygulama yap", "kodlama projesi oluştur"),
                route_mode="code_project",
                content_kind="code_project",
                output_formats=("source", "tests"),
                quality_contract=("correctness", "testability", "readability", "safety"),
                learning_tags=("code", "engineering"),
            ),
            IntentTaxonomyEntry(
                intent="run_code",
                action="run_code",
                domain="code",
                keywords=("kod çalıştır", "script çalıştır", "run code", "execute code", "python çalıştır"),
                examples=("python kodunu çalıştır", "bu kodu çalıştır"),
                route_mode="code_project",
                content_kind="code_project",
                output_formats=("stdout",),
                quality_contract=("execution_safety",),
            ),
            IntentTaxonomyEntry(
                intent="open_app",
                action="open_app",
                domain="browser",
                keywords=("aç", "başlat", "open", "launch", "uygulama"),
                examples=("safari aç", "chrome aç", "terminal aç"),
                route_mode="system",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("deterministic_open",),
            ),
            IntentTaxonomyEntry(
                intent="close_app",
                action="close_app",
                domain="browser",
                keywords=("kapat", "close", "quit", "sonlandır"),
                examples=("chrome kapat", "safariyi kapat"),
                route_mode="system",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("deterministic_close",),
            ),
            IntentTaxonomyEntry(
                intent="open_url",
                action="open_url",
                domain="browser",
                keywords=("http", "www", "site aç", "url aç", "web aç"),
                examples=("google.com aç", "şu linki aç"),
                route_mode="system",
                content_kind="task",
                output_formats=("url",),
                quality_contract=("url_normalization",),
            ),
            IntentTaxonomyEntry(
                intent="take_screenshot",
                action="take_screenshot",
                domain="screen",
                keywords=("ekran görüntüsü", "ss", "screenshot", "görüntü al", "ekran al"),
                examples=("ekran görüntüsü al", "ss atsana"),
                route_mode="system_automation",
                content_kind="task",
                output_formats=("png",),
                quality_contract=("screen_state",),
            ),
            IntentTaxonomyEntry(
                intent="screen_workflow",
                action="screen_workflow",
                domain="screen",
                keywords=("ekrana bak", "ekranı oku", "durum nedir", "screen", "computer use"),
                examples=("ekrana bak ve ne görüyorsun söyle", "durum nedir"),
                route_mode="system_automation",
                content_kind="task",
                output_formats=("analysis",),
                quality_contract=("dom_or_screen_evidence",),
            ),
            IntentTaxonomyEntry(
                intent="set_volume",
                action="set_volume",
                domain="system",
                keywords=("ses", "volume", "kapat", "aç", "kıs", "yükselt"),
                examples=("sesi kapat", "sesi yüzde elli yap"),
                route_mode="system",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("system_control",),
            ),
            IntentTaxonomyEntry(
                intent="set_brightness",
                action="set_brightness",
                domain="system",
                keywords=("parlaklık", "brightness", "ekranı karart", "ışığı aç"),
                examples=("parlaklığı artır", "parlaklığı düşür"),
                route_mode="system",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("system_control",),
            ),
            IntentTaxonomyEntry(
                intent="wifi_toggle",
                action="wifi_toggle",
                domain="system",
                keywords=("wifi", "wi-fi", "kablosuz", "ağ", "internet"),
                examples=("wifi'yi kapat", "wifi aç"),
                route_mode="system",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("network_control",),
            ),
            IntentTaxonomyEntry(
                intent="lock_screen",
                action="lock_screen",
                domain="system",
                keywords=("kilitle", "lock", "ekranı kilitle"),
                examples=("ekranı kilitle", "bilgisayarı kilitle"),
                route_mode="system",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("system_control",),
            ),
            IntentTaxonomyEntry(
                intent="shutdown_system",
                action="shutdown_system",
                domain="system",
                keywords=("kapat", "shutdown", "power off", "bilgisayarı kapat"),
                examples=("bilgisayarı kapat", "shutdown yap"),
                route_mode="system",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("high_risk_refusal",),
            ),
            IntentTaxonomyEntry(
                intent="restart_system",
                action="restart_system",
                domain="system",
                keywords=("yeniden başlat", "restart", "reboot", "tekrar başlat"),
                examples=("bilgisayarı yeniden başlat", "restart et"),
                route_mode="system",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("high_risk_refusal",),
            ),
            IntentTaxonomyEntry(
                intent="create_folder",
                action="create_folder",
                domain="files",
                keywords=("klasör", "folder", "dizin", "yeni klasör"),
                examples=("masaüstünde klasör oluştur", "test klasörü yap"),
                route_mode="file_operations",
                content_kind="task",
                output_formats=("folder",),
                quality_contract=("path_safety",),
            ),
            IntentTaxonomyEntry(
                intent="list_files",
                action="list_files",
                domain="files",
                keywords=("dosyaları listele", "list files", "hangi dosyalar", "ne var"),
                examples=("masaüstündeki dosyaları listele", "dosyaları göster"),
                route_mode="file_operations",
                content_kind="task",
                output_formats=("listing",),
                quality_contract=("path_safety",),
            ),
            IntentTaxonomyEntry(
                intent="read_file",
                action="read_file",
                domain="files",
                keywords=("oku", "read", "içeriğini göster", "dosya içeriği"),
                examples=("bu dosyayı oku", "dosyanın içeriğini göster"),
                route_mode="file_operations",
                content_kind="task",
                output_formats=("text",),
                quality_contract=("path_safety", "content_integrity"),
            ),
            IntentTaxonomyEntry(
                intent="write_file",
                action="write_file",
                domain="files",
                keywords=("yaz", "kaydet", "oluştur", "dosyaya yaz", "save"),
                examples=("not olarak kaydet", "dosyaya yaz"),
                route_mode="file_operations",
                content_kind="task",
                output_formats=("file",),
                quality_contract=("path_safety", "content_integrity"),
            ),
            IntentTaxonomyEntry(
                intent="search_files",
                action="search_files",
                domain="files",
                keywords=("ara", "bul", "search", "dosyada ara"),
                examples=("dosyalarda ara", "şu metni bul"),
                route_mode="file_operations",
                content_kind="task",
                output_formats=("listing",),
                quality_contract=("path_safety",),
            ),
            IntentTaxonomyEntry(
                intent="delete_file",
                action="delete_file",
                domain="files",
                keywords=("sil", "delete", "kaldır", "at"),
                examples=("bu dosyayı sil", "klasörü kaldır"),
                route_mode="file_operations",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("destructive_operation_warning",),
            ),
            IntentTaxonomyEntry(
                intent="send_email",
                action="send_email",
                domain="communication",
                keywords=("mail", "e-posta", "email", "gönder", "mesaj"),
                examples=("mail gönder", "e-posta yaz"),
                route_mode="communication",
                content_kind="task",
                output_formats=("email",),
                quality_contract=("recipient_clarity", "tone"),
            ),
            IntentTaxonomyEntry(
                intent="create_calendar_event",
                action="create_event",
                domain="communication",
                keywords=("takvim", "etkinlik", "randevu", "toplantı"),
                examples=("takvime etkinlik ekle", "toplantı oluştur"),
                route_mode="communication",
                content_kind="task",
                output_formats=("event",),
                quality_contract=("date_clarity", "time_clarity"),
            ),
            IntentTaxonomyEntry(
                intent="create_reminder",
                action="create_reminder",
                domain="communication",
                keywords=("hatırlat", "reminder", "uyar", "alarm"),
                examples=("yarın hatırlat", "bana haber ver"),
                route_mode="communication",
                content_kind="task",
                output_formats=("reminder",),
                quality_contract=("time_clarity",),
            ),
            IntentTaxonomyEntry(
                intent="play_music",
                action="control_music",
                domain="media",
                keywords=("müzik", "şarkı", "çal", "spotify", "play"),
                examples=("müzik çal", "şunu aç"),
                route_mode="communication",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("media_control",),
            ),
            IntentTaxonomyEntry(
                intent="pause_music",
                action="control_music",
                domain="media",
                keywords=("duraklat", "pause", "stop", "durdur"),
                examples=("müziği duraklat", "şarkıyı durdur"),
                route_mode="communication",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("media_control",),
            ),
            IntentTaxonomyEntry(
                intent="resume_music",
                action="control_music",
                domain="media",
                keywords=("devam", "resume", "continue"),
                examples=("müziğe devam et", "çalmaya devam et"),
                route_mode="communication",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("media_control",),
            ),
            IntentTaxonomyEntry(
                intent="next_track",
                action="control_music",
                domain="media",
                keywords=("sonraki", "next", "ileri"),
                examples=("sonraki şarkı", "ileri sar"),
                route_mode="communication",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("media_control",),
            ),
            IntentTaxonomyEntry(
                intent="prev_track",
                action="control_music",
                domain="media",
                keywords=("önceki", "previous", "geri"),
                examples=("önceki şarkı", "geri sar"),
                route_mode="communication",
                content_kind="task",
                output_formats=("action",),
                quality_contract=("media_control",),
            ),
            IntentTaxonomyEntry(
                intent="multi_task",
                action="multi_task",
                domain="automation",
                keywords=("ve sonra", "ardından", "sonra", "aynı anda", "eşzamanlı"),
                examples=("safari aç ve google ara", "dosyayı oku sonra özetle"),
                route_mode="task",
                content_kind="task",
                output_formats=("plan",),
                quality_contract=("task_graph",),
                learning_tags=("automation", "workflow"),
            ),
            IntentTaxonomyEntry(
                intent="create_visual_asset_pack",
                action="create_visual_asset_pack",
                domain="image",
                keywords=("görsel", "logo", "poster", "afiş", "thumbnail"),
                examples=("logo oluştur", "poster tasarla"),
                route_mode="task",
                content_kind="task",
                output_formats=("asset_pack",),
                quality_contract=("style_alignment",),
            ),
        ]

    def _build_training_corpus(self) -> tuple[list[str], list[str]]:
        texts: list[str] = []
        labels: list[str] = []
        for entry in self.entries:
            samples = list(entry.examples) + list(entry.keywords)
            samples.append(entry.intent.replace("_", " "))
            samples.append(entry.action.replace("_", " "))
            for sample in samples:
                sample_text = str(sample or "").strip()
                if not sample_text:
                    continue
                texts.append(sample_text)
                labels.append(entry.intent)
        return texts, labels

    def _build_intent_vectors(self) -> dict[str, np.ndarray]:
        vectors: dict[str, np.ndarray] = {}
        for entry in self.entries:
            samples = list(entry.examples) or [entry.intent.replace("_", " ")]
            encoded = self.embedder.encode(samples, convert_to_numpy=True, normalize_embeddings=True)
            arr = np.asarray(encoded, dtype=np.float32)
            if arr.ndim == 1:
                vectors[entry.intent] = arr
            elif arr.ndim >= 2:
                vectors[entry.intent] = arr.mean(axis=0)
        return vectors

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def classify(
        self,
        text: str,
        *,
        context: Optional[str] = None,
        available_tools: Optional[dict[str, Any]] = None,
        allow_clarify: bool = True,
    ) -> Phase1Decision | None:
        original = str(text or "").strip()
        if not original:
            return None

        normalized = self._normalize(original)
        if not normalized:
            return None

        entities = self.extract_entities(original)
        detected_keywords = TurkishNLPAnalyzer.detect_intent_keywords(original)
        context_text = str(context or "").strip()

        direct_match = self._match_direct(normalized, original, detected_keywords, entities, context_text)
        if direct_match:
            if self._accept_action(direct_match.action, available_tools):
                return direct_match
            if direct_match.intent == "clarify" or direct_match.action == "clarify":
                return direct_match

        if allow_clarify and self._looks_like_generic_document_request(normalized, original):
            return self._build_weak_clarify(original, entities)

        scored = self._score_intents(normalized, original, entities, context_text, detected_keywords)
        if not scored:
            return self._build_weak_clarify(original, entities) if allow_clarify else None

        best = scored[0]
        runner_up = scored[1] if len(scored) > 1 else None
        margin = best["score"] - (runner_up["score"] if runner_up else 0.0)
        entry = best["entry"]

        if best["score"] >= self.DIRECT_THRESHOLD and margin >= self.AMBIGUOUS_MARGIN:
            decision = self._decision_from_entry(
                entry=entry,
                normalized=normalized,
                original=original,
                entities=entities,
                score=best["score"],
                scored=scored,
            )
            if self._accept_action(decision.action, available_tools):
                return decision
            if self._accept_action(decision.intent, available_tools):
                decision.action = decision.intent
                return decision

        if allow_clarify and (
            best["score"] >= self.CLARIFY_THRESHOLD
            or entry.needs_clarification
            or margin < self.AMBIGUOUS_MARGIN
        ):
            clarification = self._clarify(entry, scored, original)
            if clarification:
                clarification.candidate_scores = scored
                return clarification

        return None

    def semantic_search(self, text: str, *, top_k: int = 5) -> list[dict[str, Any]]:
        normalized = self._normalize(text)
        if not normalized:
            return []
        scored = self._score_intents(normalized, text, self.extract_entities(text), "", TurkishNLPAnalyzer.detect_intent_keywords(text))
        out: list[dict[str, Any]] = []
        for row in scored[: max(1, int(top_k))]:
            entry = row["entry"]
            out.append(
                {
                    "intent": entry.intent,
                    "action": entry.action,
                    "domain": entry.domain,
                    "score": round(float(row["score"]), 4),
                    "examples": list(entry.examples[:3]),
                    "quality_contract": list(entry.quality_contract),
                }
            )
        return out

    def learn_from_correction(self, text: str, correct_action: str, params: Optional[dict[str, Any]] = None) -> None:
        normalized_action = self._normalize_action(correct_action)
        sample = {
            "text": str(text or "").strip(),
            "action": normalized_action,
            "params": dict(params or {}),
        }
        if not sample["text"]:
            return
        self._learned_examples.append(sample)
        self._retrain()
        self._save_corrections()

    def describe(self) -> dict[str, Any]:
        return {
            "backend": self._backend,
            "taxonomy_size": len(self.entries),
            "learned_examples": len(self._learned_examples),
            "model_path": self.model_path,
            "corrections_path": str(self.corrections_path),
        }

    def benchmark(self, samples: Iterable[dict[str, Any]]) -> dict[str, Any]:
        sample_list = list(samples)
        if not sample_list:
            return {
                "accuracy": 0.0,
                "coverage": 0.0,
                "clarify_rate": 0.0,
                "avg_latency_ms": 0.0,
                "samples": 0,
            }

        correct = 0
        clarify_count = 0
        latencies: list[float] = []
        covered = 0
        rows: list[dict[str, Any]] = []
        for sample in sample_list:
            text = str(sample.get("text") or "").strip()
            expected_intent = self._normalize_action(str(sample.get("intent") or "").strip())
            start = time.perf_counter()
            decision = self.classify(text, allow_clarify=True)
            elapsed = (time.perf_counter() - start) * 1000
            latencies.append(elapsed)
            pred_intent = decision.intent if decision else ""
            pred_action = decision.action if decision else ""
            if decision:
                covered += 1
            if decision and (pred_intent == expected_intent or pred_action == expected_intent):
                correct += 1
            if decision and decision.needs_clarification:
                clarify_count += 1
            rows.append(
                {
                    "text": text,
                    "expected": expected_intent,
                    "predicted_intent": pred_intent,
                    "predicted_action": pred_action,
                    "confidence": getattr(decision, "confidence", 0.0) if decision else 0.0,
                    "latency_ms": round(elapsed, 2),
                }
            )
        return {
            "accuracy": round(correct / len(sample_list), 4),
            "coverage": round(covered / len(sample_list), 4),
            "clarify_rate": round(clarify_count / len(sample_list), 4),
            "avg_latency_ms": round(sum(latencies) / len(latencies), 2),
            "samples": len(sample_list),
            "rows": rows,
        }

    # ------------------------------------------------------------------
    # Internal scoring
    # ------------------------------------------------------------------
    def _match_direct(
        self,
        normalized: str,
        original: str,
        detected_keywords: dict[str, list[str]],
        entities: dict[str, list[str]],
        context_text: str,
    ) -> Phase1Decision | None:
        if not normalized:
            return None

        if TurkishNLPAnalyzer.is_question(original) and self._looks_like_chat(normalized):
            return self._build_chat_decision(original, context_text, reason="question_like_chat")

        for entry in self.entries:
            if any(kw in normalized for kw in entry.keywords):
                if entry.intent in {"chat", "clarify"}:
                    return self._decision_from_entry(
                        entry=entry,
                        normalized=normalized,
                        original=original,
                        entities=entities,
                        score=0.95,
                        scored=[],
                    )
        return None

    def _score_intents(
        self,
        normalized: str,
        original: str,
        entities: dict[str, list[str]],
        context_text: str,
        detected_keywords: dict[str, list[str]],
    ) -> list[dict[str, Any]]:
        if not normalized:
            return []

        qvec = np.asarray(self.embedder.encode(original, convert_to_numpy=True, normalize_embeddings=True), dtype=np.float32)
        context_bonus = 0.05 if context_text else 0.0
        scores: list[dict[str, Any]] = []
        for entry in self.entries:
            lexical_score = self._lexical_score(normalized, original, entry, detected_keywords)
            semantic_score = self._semantic_score(qvec, entry)
            nb_score = self._nb_score(original, entry)
            domain_bonus = self._domain_bonus(original, entry)
            entity_bonus = self._entity_bonus(entities, entry)
            intent_bias = self._intent_bias(entry, original, normalized, detected_keywords)
            raw = (
                (0.34 * lexical_score)
                + (0.31 * semantic_score)
                + (0.20 * nb_score)
                + (0.10 * domain_bonus)
                + (0.05 * entity_bonus)
                + context_bonus * self._context_bias(entry, context_text)
            )
            raw += self._learning_bonus(original, entry)
            raw += intent_bias
            score = max(0.0, min(1.0, raw))
            if score <= 0.02:
                continue
            scores.append(
                {
                    "entry": entry,
                    "score": score,
                    "lexical_score": lexical_score,
                    "semantic_score": semantic_score,
                    "nb_score": nb_score,
                "domain_bonus": domain_bonus,
                "entity_bonus": entity_bonus,
                "intent_bias": intent_bias,
            }
            )
        scores.sort(key=lambda row: row["score"], reverse=True)
        return scores

    def _decision_from_entry(
        self,
        *,
        entry: IntentTaxonomyEntry,
        normalized: str,
        original: str,
        entities: dict[str, list[str]],
        score: float,
        scored: list[dict[str, Any]],
    ) -> Phase1Decision:
        params = self._build_params(entry.intent, original, normalized, entities)
        request_contract = self._build_request_contract(entry, original, score, params)
        clarification = entry.clarifying_question if entry.needs_clarification else ""
        return Phase1Decision(
            intent=entry.intent,
            action=entry.action,
            confidence=float(score),
            reasoning=self._build_reasoning(entry, scored, entities),
            params=params,
            entities=entities,
            clarification_question=clarification,
            needs_clarification=entry.needs_clarification,
            tasks=self._build_tasks(entry.intent, params),
            request_contract=request_contract.to_dict() if request_contract else {},
            candidate_scores=scored[:5],
            metadata={
                "domain": entry.domain,
                "route_mode": entry.route_mode,
                "content_kind": entry.content_kind,
            },
        )

    def _clarify(
        self,
        entry: IntentTaxonomyEntry,
        scored: list[dict[str, Any]],
        original: str,
    ) -> Phase1Decision | None:
        question = entry.clarifying_question
        if not question:
            if entry.domain in {"document", "research"}:
                question = "Bunu Word, Excel, sunum ya da kaynaklı araştırma olarak mı hazırlayayım?"
            elif entry.domain == "code":
                question = "Bunu kod projesi, tek dosya ya da test eklenmiş bir çözüm olarak mı hazırlayayım?"
            else:
                question = "Çıktı biçimini netleştirir misin?"
        return Phase1Decision(
            intent="clarify",
            action="clarify",
            confidence=float(max(entry_for("score", scored, default=0.58), self.CLARIFY_THRESHOLD)),
            reasoning=f"'{original}' birden fazla çıktı türüne uyuyor.",
            params={"question": question},
            entities=self.extract_entities(original),
            clarification_question=question,
            needs_clarification=True,
            candidate_scores=scored[:5],
            metadata={"ambiguous": True, "domain": entry.domain},
        )

    def _build_chat_decision(self, original: str, context_text: str, *, reason: str) -> Phase1Decision:
        return Phase1Decision(
            intent="chat",
            action="chat",
            confidence=0.92,
            reasoning=f"Basit sohbet/yanıt isteği ({reason}).",
            params={"message": original},
            entities=self.extract_entities(original),
            candidate_scores=[],
            metadata={"context_present": bool(context_text)},
        )

    def _build_request_contract(
        self,
        entry: IntentTaxonomyEntry,
        text: str,
        confidence: float,
        params: dict[str, Any],
    ) -> Any:
        quality = list(entry.quality_contract or [])
        output_artifacts = self._output_artifacts_for(entry.intent, entry.action, params)
        return self.capability_router.build_request_contract(
            text,
            domain=entry.domain,
            confidence=float(confidence),
            route_mode=entry.route_mode,
            output_artifacts=output_artifacts,
            quality_checklist=quality,
            parsed_intent={"action": entry.intent, "params": dict(params or {})},
            metadata={
                "phase1_intent": entry.intent,
                "phase1_action": entry.action,
                "phase1_domain": entry.domain,
            },
        )

    def _build_reasoning(self, entry: IntentTaxonomyEntry, scored: list[dict[str, Any]], entities: dict[str, list[str]]) -> str:
        top_terms = ", ".join(entry.keywords[:4])
        score_info = f"{scored[0]['score']:.2f}" if scored else "0.00"
        entity_bits = []
        for entity_type, values in list(entities.items())[:3]:
            if values:
                entity_bits.append(f"{entity_type}:{values[0]}")
        entity_text = f" | entities: {', '.join(entity_bits)}" if entity_bits else ""
        return f"Taxonomy match '{entry.intent}' ({score_info}) via keywords: {top_terms}{entity_text}"

    def _build_params(
        self,
        intent: str,
        original: str,
        normalized: str,
        entities: dict[str, list[str]],
    ) -> dict[str, Any]:
        text = str(original or "").strip()
        low = normalized.lower()
        params: dict[str, Any] = {}
        if intent in {"research", "research_document_delivery", "web_search"}:
            topic = self._extract_research_topic(text)
            if topic:
                params["topic"] = topic
            if intent == "research_document_delivery":
                params.update(self._build_research_delivery_flags(text))
            if "depth" not in params:
                params["depth"] = self._research_depth(text)
            return params

        if intent == "summarize_url":
            url = self._extract_url(text)
            if url:
                params["url"] = url
            return params

        if intent == "summarize_file":
            path = self._extract_path(text)
            if path:
                params["path"] = path
            return params

        if intent == "translate":
            params["target_lang"] = self._target_language(text)
            params["text"] = self._extract_translation_text(text)
            return params

        if intent == "create_word_document":
            filename = self._extract_filename(text, default="belge.docx")
            params["filename"] = filename
            params["path"] = str(Path.home() / "Desktop" / filename)
            params["content"] = self._extract_inline_content(text)
            return params

        if intent == "create_excel":
            filename = self._extract_filename(text, default="tablo.xlsx")
            params["filename"] = filename
            params["path"] = str(Path.home() / "Desktop" / filename)
            params["content"] = self._extract_inline_content(text)
            headers = self._extract_headers(text)
            if headers:
                params["headers"] = headers
            return params

        if intent == "create_presentation":
            params["topic"] = self._extract_topic(text, default="genel")
            return params

        if intent == "create_website":
            params["topic"] = self._extract_topic(text, default="kisisel")
            slug = re.sub(r"[^a-z0-9]+", "-", params["topic"].lower()).strip("-")
            params["filename"] = f"{slug or 'website'}.html"
            params["output_dir"] = str(Path.home() / "Desktop" / (slug or "website"))
            return params

        if intent == "create_coding_project":
            kind = self._infer_project_kind(text)
            params["project_kind"] = kind
            params["project_name"] = self._extract_project_name(text, kind=kind)
            params["stack"] = self._infer_stack(text, kind)
            params["complexity"] = self._infer_complexity(text)
            params["theme"] = "professional"
            params["output_dir"] = str(Path.home() / "Desktop")
            params["brief"] = text
            return params

        if intent == "open_app":
            app = self._extract_app_name(text)
            if app:
                params["app_name"] = app
            return params

        if intent == "open_url":
            url = self._extract_url(text)
            if url:
                params["url"] = url
            browser = self._extract_browser(text)
            if browser:
                params["browser"] = browser
            return params

        if intent in {"take_screenshot", "screen_workflow"}:
            if intent == "screen_workflow":
                params["mode"] = "inspect_and_control" if self._has_control_signal(text) else "inspect"
            return params

        if intent == "set_volume":
            level = self._extract_numeric_level(text, default=50)
            params["volume"] = level
            return params

        if intent == "set_brightness":
            level = self._extract_numeric_level(text, default=50)
            params["level"] = level
            return params

        if intent == "wifi_toggle":
            if any(k in low for k in ("kapat", "off", "disable", "devre dışı", "devre disi")):
                params["enable"] = False
            elif any(k in low for k in ("aç", "ac", "on", "enable")):
                params["enable"] = True
            return params

        if intent == "send_email":
            params["to"] = self._extract_email(text)
            params["subject"] = self._extract_subject(text)
            params["body"] = self._extract_body(text)
            return params

        if intent == "create_calendar_event":
            params["title"] = self._extract_title(text, default="Etkinlik")
            params["date"] = self._extract_date(text, default="bugün")
            params["time"] = self._extract_time(text)
            return params

        if intent == "create_reminder":
            params["title"] = self._extract_title(text, default="Hatırlatma")
            time_value = self._extract_time(text)
            if time_value:
                params["due_time"] = time_value
            return params

        if intent in {"play_music", "pause_music", "resume_music", "next_track", "prev_track"}:
            if intent == "play_music":
                params["query"] = self._extract_music_query(text)
            return params

        if intent == "multi_task":
            return params

        if intent == "create_visual_asset_pack":
            params["brief"] = text
            params["project_name"] = self._extract_project_name(text, kind="website")
            params["output_dir"] = "~/Desktop"
            return params

        if intent == "write_file":
            path = self._extract_path(text)
            if path:
                params["path"] = path
            content = self._extract_inline_content(text)
            if content:
                params["content"] = content
            return params

        if intent == "read_file":
            path = self._extract_path(text)
            if path:
                params["path"] = path
            return params

        if intent == "search_files":
            params["query"] = self._extract_inline_content(text) or self._extract_topic(text, default="")
            path = self._extract_path(text)
            if path:
                params["path"] = path
            return params

        if intent == "delete_file":
            path = self._extract_path(text)
            if path:
                params["path"] = path
            return params

        return params

    def _build_tasks(self, intent: str, params: dict[str, Any]) -> list[TaskDefinition]:
        if intent != "multi_task":
            return []
        text = str(params.get("text") or "").strip()
        if not text:
            return []
        chunks = self._split_multi_step(text)
        from core.intent.models import TaskDefinition

        tasks: list[TaskDefinition] = []
        for idx, chunk in enumerate(chunks, start=1):
            sub = self.classify(chunk, allow_clarify=False)
            if not sub or sub.intent in {"chat", "clarify"}:
                continue
            tasks.append(
                TaskDefinition(
                    task_id=f"t{idx}",
                    action=sub.action,
                    params=dict(sub.params or {}),
                    depends_on=[f"t{idx-1}"] if idx > 1 and tasks else [],
                    output_key=f"out_{idx}",
                )
            )
        return tasks

    def _output_artifacts_for(self, intent: str, action: str, params: dict[str, Any]) -> list[str]:
        if intent == "research_document_delivery":
            artifacts = ["research_report", "claims_map", "sources"]
            if params.get("include_word"):
                artifacts.append("docx")
            if params.get("include_excel"):
                artifacts.append("xlsx")
            if params.get("include_pdf"):
                artifacts.append("pdf")
            if params.get("include_latex"):
                artifacts.append("latex")
            return artifacts
        if intent == "create_word_document":
            return ["docx"]
        if intent == "create_excel":
            return ["xlsx"]
        if intent == "create_presentation":
            return ["pptx"]
        if intent == "create_website":
            return ["html", "css", "js"]
        if intent == "create_coding_project":
            return ["source_code", "tests"]
        return [action]

    # ------------------------------------------------------------------
    # Signal helpers
    # ------------------------------------------------------------------
    def extract_entities(self, text: str) -> dict[str, list[str]]:
        entities = TurkishNLPAnalyzer.extract_entities(text)
        out: dict[str, list[str]] = {k: list(v) for k, v in dict(entities or {}).items() if v}
        extra: dict[str, list[str]] = {}

        url = self._extract_url(text)
        if url:
            extra.setdefault("url", []).append(url)
        path = self._extract_path(text)
        if path:
            extra.setdefault("file_path", []).append(path)
        email = self._extract_email(text)
        if email:
            extra.setdefault("email", []).append(email)
        title = self._extract_title(text, default="")
        if title and title not in out.get("title", []):
            extra.setdefault("title", []).append(title)

        for key, value in extra.items():
            out.setdefault(key, []).extend([item for item in value if item not in out.get(key, [])])
        return out

    def _lexical_score(
        self,
        normalized: str,
        original: str,
        entry: IntentTaxonomyEntry,
        detected_keywords: dict[str, list[str]],
    ) -> float:
        tokens = set(re.findall(r"[\wçğıöşüÇĞİÖŞÜ]+", normalized.lower()))
        keyword_hits = 0
        for kw in entry.keywords:
            kw_norm = self._normalize(str(kw))
            if kw_norm in normalized:
                keyword_hits += 1
            elif kw_norm in tokens:
                keyword_hits += 1
        keyword_score = min(1.0, keyword_hits / max(1, min(6, len(entry.keywords))))

        example_score = 0.0
        for example in entry.examples:
            example_score = max(example_score, TurkishNLPAnalyzer.similarity_score(original, example))

        detected_score = 0.0
        for category, matches in detected_keywords.items():
            if category in entry.learning_tags or category == entry.domain:
                detected_score = max(detected_score, min(1.0, len(matches) / 3.0))

        prior_bonus = self._intent_prior_bonus(entry, normalized, original)

        return min(1.0, (0.45 * keyword_score) + (0.30 * example_score) + (0.15 * detected_score) + (0.10 * prior_bonus))

    def _semantic_score(self, query_vec: np.ndarray, entry: IntentTaxonomyEntry) -> float:
        target = self._intent_vectors.get(entry.intent)
        if target is None:
            return 0.0
        if query_vec.ndim == 0 or target.ndim == 0:
            return 0.0
        denom = (float(np.linalg.norm(query_vec)) * float(np.linalg.norm(target)))
        if denom <= 0:
            return 0.0
        return float(np.dot(query_vec, target) / denom)

    def _nb_score(self, text: str, entry: IntentTaxonomyEntry) -> float:
        score = float(self._nb_model.predict_proba(text).get(entry.intent, 0.0) or 0.0)
        return max(0.0, min(1.0, score))

    def _domain_bonus(self, text: str, entry: IntentTaxonomyEntry) -> float:
        plan = self.capability_router.route(text)
        if not plan:
            return 0.0
        if plan.domain == entry.domain:
            return 0.18
        if plan.primary_action == entry.action:
            return 0.12
        if plan.content_kind == entry.content_kind and entry.content_kind != "task":
            return 0.10
        return 0.0

    def _intent_prior_bonus(self, entry: IntentTaxonomyEntry, normalized: str, original: str) -> float:
        low = f"{normalized} {original}".lower()
        research_markers = self.RESEARCH_MARKERS
        delivery_markers = self.DELIVERY_MARKERS
        if entry.intent == "research_document_delivery":
            if any(marker in low for marker in research_markers):
                return 1.0
            if any(marker in low for marker in delivery_markers):
                return 1.0
        if entry.intent == "research":
            if any(marker in low for marker in ("sadece", "yalnızca", "yalnizca", "kısa", "kisa", "özet", "ozet")):
                return 0.75
            if any(marker in low for marker in delivery_markers):
                return 0.0
        if entry.intent == "create_word_document" and "word" in low:
            return 0.7
        if entry.intent == "create_excel" and "excel" in low:
            return 0.7
        if entry.intent == "create_website" and any(marker in low for marker in ("website", "web sitesi", "web sayfası", "landing page", "html", "css", "js")):
            return 0.85
        if entry.intent == "create_coding_project" and any(marker in low for marker in ("uygulama", "app", "kod", "proje", "script")):
            return 0.7
        return 0.0

    def _intent_bias(
        self,
        entry: IntentTaxonomyEntry,
        original: str,
        normalized: str,
        detected_keywords: dict[str, list[str]],
    ) -> float:
        low = f"{normalized} {original}".lower()
        has_research = any(marker in low for marker in self.RESEARCH_MARKERS)
        has_delivery = any(marker in low for marker in self.DELIVERY_MARKERS)
        has_quick_hint = any(marker in low for marker in self.QUICK_RESEARCH_HINTS)

        if entry.intent == "research_document_delivery":
            if has_research:
                bonus = 0.28
                if not has_quick_hint:
                    bonus += 0.14
                if has_delivery:
                    bonus += 0.08
                return bonus
            if any(marker in low for marker in self.REPORT_MARKERS) and any(marker in low for marker in ("kaynaklı", "kaynakli", "araştır", "arastir", "research", "incele", "analiz")):
                return 0.24
            if any(marker in low for marker in self.REPORT_MARKERS) and not has_delivery:
                return 0.08
            if has_delivery:
                return -0.16
            return 0.0

        if entry.intent == "research":
            if has_quick_hint:
                return 0.28
            if has_research and not has_delivery:
                return -0.12
            return 0.0

        if entry.intent == "create_word_document":
            if any(marker in low for marker in ("word", "docx")):
                return 0.22
            if any(marker in low for marker in ("belge", "doküman", "dokuman", "rapor")):
                return 0.10
            return 0.0

        if entry.intent == "create_excel":
            if any(marker in low for marker in ("excel", "xlsx")):
                return 0.22
            if any(marker in low for marker in ("tablo", "sheet", "spreadsheet")):
                return 0.10
            return 0.0

        if entry.intent == "create_website":
            if any(marker in low for marker in ("website", "web sitesi", "web sayfası", "landing page", "html", "css", "js")):
                return 0.18
            return 0.0

        if entry.intent == "create_coding_project":
            if any(marker in low for marker in ("uygulama", "app", "kod", "proje", "script")):
                return 0.10
            return 0.0

        return 0.0

    def _looks_like_generic_document_request(self, normalized: str, original: str) -> bool:
        low = f"{normalized} {original}".lower()
        has_generic_doc = any(marker in low for marker in ("belge", "doküman", "dokuman", "rapor", "dosya", "document"))
        explicit = any(marker in low for marker in self.EXPLICIT_DOCUMENT_MARKERS)
        research = any(marker in low for marker in self.RESEARCH_MARKERS)
        return has_generic_doc and not explicit and not research

    def _entity_bonus(self, entities: dict[str, list[str]], entry: IntentTaxonomyEntry) -> float:
        if not entities:
            return 0.0
        if entry.intent in {"summarize_url", "open_url"} and entities.get("url"):
            return 1.0
        if entry.intent in {"summarize_file", "read_file", "write_file", "delete_file"} and entities.get("file_path"):
            return 1.0
        if entry.intent in {"send_email"} and entities.get("email"):
            return 1.0
        if entry.intent in {"create_calendar_event", "create_reminder"} and (entities.get("date") or entities.get("date_word") or entities.get("time")):
            return 1.0
        if entry.intent in {"create_word_document", "create_excel", "create_presentation"} and (entities.get("number") or entities.get("date") or entities.get("title")):
            return 0.5
        return 0.0

    def _context_bias(self, entry: IntentTaxonomyEntry, context_text: str) -> float:
        if not context_text:
            return 0.0
        context_low = context_text.lower()
        if entry.domain == "research" and any(k in context_low for k in ("araştır", "research", "kaynak", "rapor")):
            return 1.0
        if entry.domain == "document" and any(k in context_low for k in ("word", "excel", "sunum", "rapor")):
            return 1.0
        if entry.domain == "code" and any(k in context_low for k in ("kod", "app", "website", "proje")):
            return 1.0
        return 0.0

    def _learning_bonus(self, text: str, entry: IntentTaxonomyEntry) -> float:
        if not self._learned_examples:
            return 0.0
        score = 0.0
        normalized = self._normalize(text)
        for sample in self._learned_examples[-50:]:
            if self._normalize(str(sample.get("text") or "")) == normalized:
                if sample.get("action") == entry.intent or sample.get("action") == entry.action:
                    score = max(score, 0.22)
        return score

    # ------------------------------------------------------------------
    # Learning / persistence
    # ------------------------------------------------------------------
    def _retrain(self) -> None:
        texts = list(self._examples)
        labels = list(self._labels)
        for sample in self._learned_examples:
            text = str(sample.get("text") or "").strip()
            action = self._normalize_action(str(sample.get("action") or "").strip())
            if text and action:
                texts.append(text)
                labels.append(action)
        if texts and labels:
            self._nb_model.fit(texts, labels)
            self._intent_vectors = self._build_intent_vectors()

    def _load_corrections(self) -> None:
        path = self.corrections_path
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        items = payload.get("examples") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            text = str(item.get("text") or "").strip()
            action = self._normalize_action(str(item.get("action") or "").strip())
            if not text or not action:
                continue
            self._learned_examples.append(
                {
                    "text": text,
                    "action": action,
                    "params": dict(item.get("params") or {}) if isinstance(item.get("params"), dict) else {},
                }
            )

    def _save_corrections(self) -> None:
        try:
            self.corrections_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "examples": list(self._learned_examples),
                "updated_at": time.time(),
            }
            self.corrections_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("Phase1 correction save failed: %s", exc)

    # ------------------------------------------------------------------
    # Normalization / mapping helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize(text: str) -> str:
        return TurkishNLPAnalyzer.normalize_turkish_text(text).lower().strip()

    @staticmethod
    def _accept_action(action: str, available_tools: Optional[dict[str, Any]]) -> bool:
        if not available_tools:
            return True
        if action in {"chat", "clarify", "multi_task"}:
            return True
        return action in available_tools

    def _normalize_action(self, action: str) -> str:
        low = str(action or "").strip().lower()
        alias = {
            "research_and_document": "research_document_delivery",
            "research_report_delivery": "research_document_delivery",
            "deliver_research_copy": "research_document_delivery",
            "create_word_document": "create_word_document",
            "write_word": "create_word_document",
            "create_excel": "create_excel",
            "write_excel": "create_excel",
            "create_website": "create_website",
            "create_web_project_scaffold": "create_website",
            "create_coding_project": "create_coding_project",
            "advanced_research": "research",
            "web_search": "web_search",
            "summarize_text": "summarize_text",
            "summarize_url": "summarize_url",
            "summarize_file": "summarize_file",
            "create_presentation": "create_presentation",
            "generate_document_pack": "create_pdf",
            "write_file": "write_file",
            "read_file": "read_file",
            "search_files": "search_files",
            "delete_file": "delete_file",
            "open_app": "open_app",
            "close_app": "close_app",
            "open_url": "open_url",
            "take_screenshot": "take_screenshot",
            "screen_workflow": "screen_workflow",
            "set_volume": "set_volume",
            "set_brightness": "set_brightness",
            "wifi_toggle": "wifi_toggle",
            "lock_screen": "lock_screen",
            "shutdown_system": "shutdown_system",
            "restart_system": "restart_system",
            "send_email": "send_email",
            "create_event": "create_calendar_event",
            "create_reminder": "create_reminder",
            "play_music": "play_music",
            "pause_music": "pause_music",
            "resume_music": "resume_music",
            "next_track": "next_track",
            "prev_track": "prev_track",
            "multi_task": "multi_task",
            "clarify": "clarify",
            "chat": "chat",
        }
        return alias.get(low, low)

    def _looks_like_chat(self, text: str) -> bool:
        low = self._normalize(text)
        return any(k in low for k in ("merhaba", "selam", "naber", "nasılsın", "sohbet", "help"))

    def _extract_url(self, text: str) -> str:
        m = re.search(r'(https?://[^\s]+|www\.[^\s]+)', text, re.IGNORECASE)
        if m:
            url = m.group(1)
            return url if url.startswith("http") else f"https://{url}"
        low = text.lower()
        for marker in ("google", "youtube", "github", "claude", "chatgpt", "drive", "mail"):
            if marker in low and marker in self.capability_router._DOMAIN_KEYWORDS.get("api_integration", []):  # type: ignore[attr-defined]
                break
        return ""

    def _extract_path(self, text: str) -> str:
        m = re.search(r'(?:~\/|\/|\.\.\/)[^\s]+', text)
        if m:
            return m.group(0)
        if "desktop" in text.lower() or "masaüst" in text.lower():
            filename = self._extract_filename(text, default="")
            if filename:
                return str(Path.home() / "Desktop" / filename)
            return str(Path.home() / "Desktop")
        return ""

    def _extract_email(self, text: str) -> str:
        m = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
        return m.group(0) if m else ""

    def _extract_subject(self, text: str) -> str:
        m = re.search(r"(?:konu|subject)\s*[:\-]\s*(.+?)(?:\s+içerik|\s+body|$)", text, re.IGNORECASE)
        return (m.group(1) or "").strip() if m else ""

    def _extract_body(self, text: str) -> str:
        m = re.search(r"(?:içerik|body|mesaj)\s*[:\-]\s*(.+)$", text, re.IGNORECASE)
        return (m.group(1) or "").strip() if m else ""

    def _extract_title(self, text: str, default: str = "") -> str:
        m = re.search(r"(?:başlık|title)\s*[:\-]\s*(.+?)(?:\s+(?:tarih|date|saat|time)|$)", text, re.IGNORECASE)
        if m:
            return (m.group(1) or "").strip()
        m = re.search(r"(.+?)\s+(?:etkinliği|toplantısı|randevusu|hatırlatma)", text, re.IGNORECASE)
        if m:
            return (m.group(1) or "").strip()
        return default

    def _extract_date(self, text: str, default: str = "") -> str:
        m = re.search(r"\b(\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?)\b", text)
        if m:
            return m.group(1)
        for word in ("bugün", "yarın", "dün", "pazartesi", "salı", "çarşamba", "perşembe", "cuma", "cumartesi", "pazar"):
            if word in text.lower():
                return word
        return default

    def _extract_time(self, text: str) -> str:
        m = re.search(r"\b(\d{1,2}[:.]\d{2})\b", text)
        if m:
            return m.group(1).replace(".", ":")
        m = re.search(r"\b(\d{1,2})\s*(?:de|da|te|ta)?\b", text, re.IGNORECASE)
        if m:
            hour = int(m.group(1))
            if 0 <= hour <= 23:
                return f"{hour:02d}:00"
        return ""

    def _extract_numeric_level(self, text: str, default: int = 50) -> int:
        m = re.search(r"\b(\d{1,3})\b", text)
        if m:
            return max(0, min(100, int(m.group(1))))
        if any(k in text.lower() for k in ("kapat", "sıfır", "sifir", "mute")):
            return 0
        if any(k in text.lower() for k in ("aç", "ac", "yükselt", "artır", "arttir", "increase")):
            return 100
        return default

    def _extract_filename(self, text: str, default: str) -> str:
        quoted = re.search(r"[\"']([^\"']{2,120})[\"']", text)
        if quoted:
            candidate = quoted.group(1).strip()
            if candidate:
                return candidate
        m = re.search(r"(?:adı|adi|isim|name)\s*[:\-\s]*([A-Za-z0-9çğıöşüÇĞİÖŞÜ_\-]+)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return default

    def _extract_inline_content(self, text: str) -> str:
        patterns = [
            r"(?:içine|icine|içeriğine|icerigine)\s+(.+?)(?:\s+yaz|$)",
            r"(?:metin|içerik|icerik|konu)\s*[:\-]\s*(.+)$",
            r"(?:şunu|sunu|bunu)\s+yaz\s*[:\-]?\s*(.+)$",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if not m:
                continue
            candidate = str(m.group(1) or "").strip()
            candidate = re.sub(r"\b(word|excel|belge|dosya|tablo|oluştur|olustur|kaydet)\b", " ", candidate, flags=re.IGNORECASE)
            candidate = re.sub(r"\s+", " ", candidate).strip(" .,:;-")
            if len(candidate) >= 3:
                return candidate
        return ""

    def _extract_headers(self, text: str) -> list[str]:
        hm = re.search(r"(?:kolonlar|sütunlar|sutunlar)\s*[:\-]\s*(.+)$", text, re.IGNORECASE)
        if not hm:
            return []
        raw = hm.group(1).strip()
        raw = re.split(r"\b(?:içine|icine|içeri|iceri|içerik|icerik)\b", raw, maxsplit=1, flags=re.IGNORECASE)[0].strip()
        cols = [c.strip() for c in re.split(r"[;,|]", raw) if c.strip()]
        return cols[:20]

    def _extract_topic(self, text: str, default: str = "") -> str:
        topic = text.strip()
        topic = re.sub(r"\b(araştır|arastir|araştırma|arastirma|incele|research|write|oluştur|olustur|hazırla|hazirla|yap)\b", " ", topic, flags=re.IGNORECASE)
        topic = re.sub(r"\b(word|excel|pdf|sunum|presentation|website|web sitesi|web sayfası|html|css|js|docx|xlsx)\b", " ", topic, flags=re.IGNORECASE)
        topic = re.sub(r"\s+", " ", topic).strip(" .,:;-")
        return topic if len(topic) >= 2 else default

    def _extract_research_topic(self, text: str) -> str:
        patterns = [
            r"(.+?)\s+hakkında\s+(?:\w+\s+)*(?:araştırma|araştır|inceleme)",
            r"(.+?)\s+inceleme\s+(?:yapılsın|yap\b)?",
            r"(.+?)\s+(?:araştırma|research)(?:\s+yap\w*)?$",
            r"(?:araştırma|inceleme|araştır)\s+yap\w*\s+(.+)",
        ]
        low = text.strip()
        for pat in patterns:
            m = re.search(pat, low, re.IGNORECASE)
            if m:
                topic = (m.group(1) or "").strip()
                topic = self._strip_command_noise(topic)
                if len(topic) >= 2:
                    return topic
        return self._strip_command_noise(self._extract_topic(text))

    def _strip_command_noise(self, topic: str) -> str:
        topic = re.sub(r"\b(aç|ac|başlat|baslat|çalıştır|calistir|open|launch|safari|chrome|tarayıcı|tarayici|browser)\b", " ", topic, flags=re.IGNORECASE)
        topic = re.sub(r"\b(kaydet|yaz|oluştur|olustur|dosya|belge|word|excel|tablo|içine|icine)\b", " ", topic, flags=re.IGNORECASE)
        topic = re.sub(r"\b(kopyala|copy|clipboard|pano|panoya)\b", " ", topic, flags=re.IGNORECASE)
        topic = re.sub(r"\s+", " ", topic).strip(" .,:;-")
        return topic

    def _extract_translation_text(self, text: str) -> str:
        low = text
        for trigger in ("çevir", "cevir", "translate", "tercüme", "tercume", "çeviri yap"):
            low = re.sub(trigger, " ", low, flags=re.IGNORECASE)
        low = re.sub(r"\b(ingilizceye|türkçeye|turkceye|almancaya|fransızcaya|ispanyolcaya|japoncaya|çinceye|rusçaya|arapçaya)\b", " ", low, flags=re.IGNORECASE)
        low = re.sub(r"\b(ye|e|a|ya|dan|den|na|ne)\b", " ", low, flags=re.IGNORECASE)
        return re.sub(r"\s+", " ", low).strip(" .,:;-")

    def _target_language(self, text: str) -> str:
        lang_map = {
            "ingilizce": "en", "english": "en",
            "türkçe": "tr", "turkce": "tr",
            "almanca": "de", "german": "de",
            "fransızca": "fr", "fransizca": "fr",
            "ispanyolca": "es", "spanish": "es",
            "italyanca": "it", "italian": "it",
            "japonca": "ja", "japanese": "ja",
            "çince": "zh", "cince": "zh",
            "rusça": "ru", "rusca": "ru",
            "arapça": "ar", "arapca": "ar",
        }
        low = text.lower()
        for key, code in lang_map.items():
            if key in low:
                return code
        return "en"

    def _extract_music_query(self, text: str) -> str:
        m = re.search(r"(?:çal|cal|play|aç)\s+(.+)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        m = re.search(r"(.+?)\s+(?:çal|cal|play)", text, re.IGNORECASE)
        if m:
            return m.group(1).strip()
        return ""

    def _extract_browser(self, text: str) -> str:
        low = text.lower()
        if "safari" in low:
            return "Safari"
        if "chrome" in low or "krom" in low:
            return "Google Chrome"
        if "firefox" in low:
            return "Firefox"
        return ""

    def _extract_app_name(self, text: str) -> str:
        low = text.lower()
        app_map = {
            "safari": "Safari",
            "chrome": "Google Chrome",
            "krom": "Google Chrome",
            "terminal": "Terminal",
            "finder": "Finder",
            "word": "Microsoft Word",
            "excel": "Microsoft Excel",
            "powerpoint": "Microsoft PowerPoint",
            "notlar": "Notes",
            "notes": "Notes",
            "spotify": "Spotify",
            "photos": "Photos",
            "preview": "Preview",
        }
        for marker, app in app_map.items():
            if marker in low:
                return app
        return ""

    def _extract_project_name(self, text: str, *, kind: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return "elyan-project"
        quoted = re.search(r"[\"']([^\"']{2,80})[\"']", raw)
        if quoted:
            return quoted.group(1).strip()
        before_target = re.search(r"([a-zA-Z0-9çğıöşüÇĞİÖŞÜ _\-]{2,80})\s+(?:website|web sitesi|web sayfası|uygulama|app|proje)", raw, re.IGNORECASE)
        if before_target:
            candidate = re.sub(r"\b(bir|new|yeni|ile|using|ve|the|a|an|için|icin)\b", " ", before_target.group(1), flags=re.IGNORECASE)
            candidate = re.sub(r"\b(python|react|next|nextjs|node|express|django|flask|fastapi|flutter|js|javascript|typescript|ts)\b", " ", candidate, flags=re.IGNORECASE)
            candidate = re.sub(r"\s+", " ", candidate).strip(" .,:;-")
            if len(candidate) >= 2:
                return candidate
        return "web-projesi" if kind == "website" else ("oyun-projesi" if kind == "game" else "uygulama-projesi")

    def _infer_project_kind(self, text: str) -> str:
        low = text.lower()
        if any(k in low for k in ("website", "web sitesi", "web sayfası", "landing page", "frontend")):
            return "website"
        if any(k in low for k in ("oyun", "game", "pygame", "unity")):
            return "game"
        return "app"

    def _infer_stack(self, text: str, kind: str) -> str:
        low = text.lower()
        if kind == "website":
            if "next" in low:
                return "nextjs"
            if "react" in low:
                return "react"
            return "vanilla"
        if kind == "game":
            return "unity" if "unity" in low else "pygame"
        if "flutter" in low:
            return "flutter"
        if "react native" in low:
            return "react-native"
        if "node" in low or "express" in low:
            return "node"
        if "django" in low:
            return "django"
        if "flask" in low:
            return "flask"
        if "fastapi" in low:
            return "fastapi"
        return "python"

    def _infer_complexity(self, text: str) -> str:
        low = text.lower()
        if any(k in low for k in ("karmaşık", "enterprise", "production", "profesyonel", "full-featured", "eksiksiz")):
            return "expert"
        if any(k in low for k in ("basit", "simple", "minimal", "demo", "örnek", "ornek")):
            return "standard"
        return "advanced"

    def _build_research_delivery_flags(self, text: str) -> dict[str, Any]:
        low = text.lower()
        include_pdf = "pdf" in low
        include_latex = any(k in low for k in ("latex", "tex"))
        include_excel = any(k in low for k in ("excel", "xlsx", "tablo", "csv"))
        explicit_word = any(k in low for k in ("word", "docx", "dokuman", "doküman"))
        generic_doc = any(k in low for k in ("rapor", "belge"))
        include_word = explicit_word or (generic_doc and not include_excel and not include_pdf and not include_latex)
        if not include_word and not include_excel and not include_latex:
            include_word = True
        return {
            "include_word": include_word,
            "include_excel": include_excel,
            "include_pdf": include_pdf,
            "include_latex": include_latex,
            "include_report": True,
        }

    def _research_depth(self, text: str) -> str:
        low = text.lower()
        if any(w in low for w in ("detaylı", "kapsamlı", "derin", "derinlemesine")):
            return "deep"
        if any(w in low for w in ("kısa", "hızlı", "özet")):
            return "quick"
        return "standard"

    def _has_control_signal(self, text: str) -> bool:
        return any(k in text.lower() for k in ("tıkla", "tikla", "click", "yaz", "type", "gir", "seç", "sec", "gönder", "gonder"))

    def _build_weak_clarify(self, original: str, entities: dict[str, list[str]]) -> Phase1Decision:
        question = "Bunu Word, Excel, sunum, web sitesi ya da araştırma olarak mı hazırlayayım?"
        return Phase1Decision(
            intent="clarify",
            action="clarify",
            confidence=self.CLARIFY_THRESHOLD,
            reasoning="Yeterli ayrıştırıcı sinyal yok.",
            params={"question": question},
            entities=entities,
            clarification_question=question,
            needs_clarification=True,
        )

    def _split_multi_step(self, text: str) -> list[str]:
        normalized = re.sub(r"\baçıp\b", "aç sonra", text, flags=re.IGNORECASE)
        normalized = re.sub(r"\bacip\b", "aç sonra", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\bçalıştırıp\b", "çalıştır sonra", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\bcalistirip\b", "çalıştır sonra", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\bgidip\b", "git sonra", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\bgirip\b", "gir sonra", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\byazıp\b", "yaz sonra", normalized, flags=re.IGNORECASE)
        normalized = re.sub(r"\byazip\b", "yaz sonra", normalized, flags=re.IGNORECASE)
        parts = [p.strip() for p in re.split(r"\s*(?:[,;]+\s*|\s+(?:ve sonra|ardından|ardindan|sonra|sonrasında|sonrasinda|then|açıp|acip|çalıştırıp|calistirip|gidip|girip|yazıp|yazip)\s+)\s*", normalized, flags=re.IGNORECASE) if p.strip()]
        if len(parts) < 2 and " ve " in text.lower():
            raw_parts = [p.strip() for p in re.split(r"\s+ve\s+", text, flags=re.IGNORECASE) if p.strip()]
            if len(raw_parts) >= 2:
                parts = raw_parts
        return parts


def entry_for(field: str, scored: list[dict[str, Any]], default: float = 0.0) -> float:
    if not scored:
        return default
    return float(scored[0].get(field, default) or default)


_phase1_engine: Phase1NLUEngine | None = None


def get_phase1_engine() -> Phase1NLUEngine:
    global _phase1_engine
    if _phase1_engine is None:
        _phase1_engine = Phase1NLUEngine()
    return _phase1_engine


__all__ = [
    "IntentTaxonomyEntry",
    "Phase1Decision",
    "Phase1NLUEngine",
    "get_phase1_engine",
]
