"""Semantik anlama katmanı — desen eşleştirmenin yerine geçer.

NEDEN
-----
"Şu kelime geçerse şunu yap" yaklaşımı yapısal olarak çıkmazdır: her yeni cümle
kalıbı yeni bir desen, her desen yeni bir kenar durum doğurur. Türkçe gibi
eklemeli ve serbest sıralı bir dilde bu hiç kapanmaz.

Bu katman niyeti **anlamlandırır**: metni yapılandırılmış bir anlama zarfına
çevirir (niyet, varlıklar, teslimatlar, kısıtlar, risk, güven). Desenler yalnız
model erişilemediğinde devreye giren *bozulmuş mod* yedeğidir ve bu durum
``source``/``degraded`` alanlarıyla açıkça işaretlenir — sessizce kalite
düşmez, izlenebilir.

İZLENEBİLİRLİK
--------------
Her zarf; kaynağını, güvenini, gerekçesini ve hangi sinyallerin tetiklendiğini
taşır. Böylece "neden bu karar verildi" sorusu loglardan cevaplanabilir.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Callable

UNDERSTANDING_CONTRACT = "elyan.understanding.v1"

# Niyet sınıfları — kapalı küme; model buna uymak zorundadır.
INTENT_CHAT = "chat"
INTENT_TASK = "task"
INTENT_TASK_CONTROL = "task_control"
INTENT_CLARIFY = "clarify"

_VALID_INTENTS = {INTENT_CHAT, INTENT_TASK, INTENT_TASK_CONTROL, INTENT_CLARIFY}


@dataclass(slots=True)
class Entity:
    """Metinden çıkarılan somut varlık (dosya, uygulama, kişi, tarih, URL…)."""

    type: str
    value: str
    role: str = ""  # "target" | "source" | "constraint" | ""

    def to_dict(self) -> dict[str, str]:
        payload = {"type": self.type, "value": self.value}
        if self.role:
            payload["role"] = self.role
        return payload


@dataclass(slots=True)
class SemanticUnderstanding:
    """Bir kullanıcı mesajının yapılandırılmış anlaması."""

    intent: str
    confidence: float
    source: str  # "model" | "deterministic_fallback"
    reasoning: str = ""
    task_type: str = ""
    entities: list[Entity] = field(default_factory=list)
    deliverables: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    risk: str = "low"
    degraded: bool = False
    signals: list[str] = field(default_factory=list)
    # İşlenecek içeriğin kaynağı NEREDE:
    #   user_private    — kullanıcının kendi içeriği (notları, dosyası) → SOR
    #   public_external — kamuya açık/güncel bilgi → GETİR (web/Compound), sorma
    #   none            — işin kaynağa ihtiyacı yok
    source_kind: str = "none"

    @property
    def is_task(self) -> bool:
        return self.intent == INTENT_TASK

    @property
    def is_chat(self) -> bool:
        return self.intent == INTENT_CHAT

    @property
    def needs_clarification(self) -> bool:
        return self.intent == INTENT_CLARIFY or bool(self.missing_information)

    def targets(self) -> list[Entity]:
        return [item for item in self.entities if item.role == "target"]

    def artifact_subject(self) -> str:
        """Üretilecek dosyanın KONUSU — komut cümlesi değil.

        Canlı arıza: "Ceza hukuku 3.sınıf ders notlarını özetle ve masaüstünde
        belge oluştur" isteği, tüm cümle slug'lanarak
        `ceza-hukuku-3-sinif-ders-notlarini-ozetle-ve-masaustunde-belge-o.docx`
        adıyla kaydedilmişti. Dosya adı komutu değil İÇERİĞİ anlatmalı.

        Konu, anlaşılan varlıklardan çıkarılır (önce hedef, sonra konu/kaynak);
        hiçbiri yoksa boş döner ve çağıran mevcut davranışını sürdürür — uydurma
        başlık atılmaz."""
        preferred_roles = ("target", "source", "")
        for role in preferred_roles:
            for entity in self.entities:
                if entity.role != role:
                    continue
                # Dosya/URL gibi teknik varlıklar başlık olmaz; konu olanları al.
                if entity.type in {"topic", "person", "date"} or role == "target":
                    value = entity.value.strip()
                    # Tek kelimelik jenerik hedefler ("belge", "dosya") konu değildir.
                    if value and value.lower() not in {
                        "belge", "dosya", "rapor", "not", "notlar", "document", "file",
                    }:
                        return value[:120]
        return ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract": UNDERSTANDING_CONTRACT,
            "intent": self.intent,
            "confidence": round(float(self.confidence), 3),
            "source": self.source,
            "degraded": self.degraded,
            "taskType": self.task_type,
            "entities": [item.to_dict() for item in self.entities],
            "deliverables": self.deliverables,
            "constraints": self.constraints,
            "missingInformation": self.missing_information,
            "risk": self.risk,
            "sourceKind": self.source_kind,
            "reasoning": self.reasoning[:480],
            "signals": self.signals,
        }


_SYSTEM_CONTRACT = (
    "Kullanıcı mesajını ANLAMLANDIR. Kelime eşleştirme yapma; ne demek istediğini çöz.\n"
    "NIYET SINIFLARI:\n"
    "  chat         — sohbet, soru, açıklama isteği, selamlama, senin hakkında soru. "
    "Bilgi vermek EYLEM DEĞİLDİR.\n"
    "  task         — bilgisayarda somut bir iş yapılmasını istiyor (dosya, uygulama, "
    "mesaj, arama+üretim, kod). Gerçek dünyada bir DEĞİŞİKLİK ya da ÜRETİM bekleniyor.\n"
    "  task_control — yürüyen işe müdahale (iptal, onay, durum sorma).\n"
    "  clarify      — iş istiyor ama kritik bilgi eksik (hangi dosya? kime?).\n"
    "KURALLAR:\n"
    "1) Emin değilsen 'chat' seç. Yanlışlıkla iş çalıştırmak, gereksiz soru sormaktan pahalıdır.\n"
    "2) entities: somut varlıkları çıkar (file/app/url/person/date/topic). "
    "İşin uygulanacağı şeye role='target' ver.\n"
    "3) deliverables: kullanıcının elinde ne kalmalı (ör. 'masaüstünde rapor.docx').\n"
    "4) missingInformation: iş için ŞART olan ama verilmemiş bilgiler.\n"
    "5) risk: low|medium|high — geri alınamaz/dışa gönderim/silme varsa yüksek.\n"
    "6) DURUMU KULLAN. 'currentSituation' verildiyse (takvim, konum, aktif uygulama, "
    "son dosyalar) niyeti onunla çöz: 'toplantı notu hazırla' derken hangi toplantı "
    "olduğunu takvim söyler. Bağlamdan çıkarılabilecek şeyi missingInformation'a YAZMA — "
    "iyi bir asistan bariz olanı sormaz, makul varsayar. Yalnız GERÇEKTEN belirsiz ve "
    "kritik olanı sor (ör. kime gönderilecek).\n"
    "7) Varsayımların sinyale DAYANSIN. Durum verisi yoksa uydurma; sessizce genel kal.\n"
    "8) KAYNAĞI SINIFLA, sonra karar ver — 'sourceKind' alanını doldur:\n"
    "   • user_private → içerik KULLANICIYA ait ve elimizde yok ('benim notlarım', "
    "'şu dosyayı', 'attığım rapor'). Bunu uydurmak yasak: intent='clarify' seç, "
    "missingInformation'a neyin gerektiğini yaz.\n"
    "   • public_external → içerik KAMUYA AÇIK bilgi ('2026 KDV oranları', 'X "
    "şirketinin son bilançosu', 'Python asyncio nasıl çalışır'). Bunu SORMA — "
    "araştırılıp getirilebilir. intent='task' seç; araştırma adımı kaynağı sağlar.\n"
    "   • none → işin dış kaynağa ihtiyacı yok.\n"
    "   Ayrım şu: kullanıcının ÖZEL verisi mi (soramazsan uydurursun), yoksa "
    "herkesin erişebileceği bilgi mi (araştırılabilir)? Kamuya açık bilgi için soru "
    "sormak gereksiz sürtünmedir; özel içerik için sormamak uydurmadır.\n"
    "   Kaynağı olmayan belgeyi ASLA genel bilgiyle doldurup 'task' deme.\n"
    "9) SADECE tek JSON nesnesi döndür."
)

_SCHEMA_HINT = (
    '{"intent":"chat|task|task_control|clarify","confidence":0.0,'
    '"taskType":"<kısa etiket>","reasoning":"<neden>",'
    '"entities":[{"type":"file|app|url|person|date|topic","value":"","role":"target|source|constraint"}],'
    '"deliverables":[],"constraints":[],"missingInformation":[],"risk":"low|medium|high",'
    '"sourceKind":"user_private|public_external|none"}'
)


def build_understanding_prompt(
    text: str,
    *,
    dispatch_active: bool = False,
    has_pending_plan: bool = False,
    recent_turns: list[str] | None = None,
    situational_context: dict[str, Any] | None = None,
) -> str:
    situation: dict[str, Any] = {
        "message": str(text or "")[:2_000],
        "dispatchActive": bool(dispatch_active),
        "hasPendingPlan": bool(has_pending_plan),
    }
    # DURUMSAL BAĞLAM: takvim/konum/aktif uygulama/son dosyalar. Bunlar niyeti
    # çözerken kullanılır — "sunum hazırla" derken hangi sunum olduğunu bağlam
    # söyler. Bariz olanı sormak yerine varsaymayı mümkün kılar.
    if isinstance(situational_context, dict) and situational_context:
        situation["currentSituation"] = situational_context
    if recent_turns:
        situation["recentTurns"] = [str(item)[:240] for item in recent_turns[-4:]]
    if dispatch_active:
        situation["note"] = (
            "Bir iş ZATEN yürüyor. Kullanıcı çalışan işe müdahale etmek istemiyorsa "
            "bu mesaj büyük olasılıkla sohbettir."
        )
    return (
        f"{_SYSTEM_CONTRACT}\n\n"
        f"DURUM:\n{json.dumps(situation, ensure_ascii=False)}\n\n"
        f"ÇIKTI ŞEMASI:\n{_SCHEMA_HINT}"
    )


def _coerce_entities(value: Any) -> list[Entity]:
    if not isinstance(value, list):
        return []
    entities: list[Entity] = []
    for item in value[:16]:
        if not isinstance(item, dict):
            continue
        entity_value = str(item.get("value", "") or "").strip()[:240]
        if not entity_value:
            continue
        entities.append(
            Entity(
                type=str(item.get("type", "") or "topic").strip()[:32],
                value=entity_value,
                role=str(item.get("role", "") or "").strip()[:16],
            )
        )
    return entities


def _coerce_texts(value: Any, limit: int = 8) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip()[:240] for item in value if str(item or "").strip()][:limit]


def parse_understanding(payload: Any) -> SemanticUnderstanding | None:
    """Model çıktısını doğrulanmış bir anlama zarfına çevirir."""
    if not isinstance(payload, dict):
        return None
    intent = str(payload.get("intent", "") or "").strip().lower()
    if intent not in _VALID_INTENTS:
        return None
    try:
        confidence = float(payload.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        confidence = 0.0
    risk = str(payload.get("risk", "") or "low").strip().lower()
    source_kind = str(
        payload.get("sourceKind", "") or payload.get("source_kind", "") or "none"
    ).strip().lower()
    if source_kind not in {"user_private", "public_external", "none"}:
        source_kind = "none"
    return SemanticUnderstanding(
        intent=intent,
        confidence=max(0.0, min(1.0, confidence)),
        source="model",
        reasoning=str(payload.get("reasoning", "") or "").strip(),
        task_type=str(payload.get("taskType", "") or payload.get("task_type", "") or "").strip()[:64],
        entities=_coerce_entities(payload.get("entities")),
        deliverables=_coerce_texts(payload.get("deliverables")),
        constraints=_coerce_texts(payload.get("constraints")),
        missing_information=_coerce_texts(payload.get("missingInformation")),
        risk=risk if risk in {"low", "medium", "high"} else "low",
        source_kind=source_kind,
    )


def analyze(
    text: str,
    *,
    send_prompt: Callable[[str], str] | None = None,
    dispatch_active: bool = False,
    has_pending_plan: bool = False,
    recent_turns: list[str] | None = None,
    situational_context: dict[str, Any] | None = None,
    fallback: Callable[[], SemanticUnderstanding] | None = None,
) -> SemanticUnderstanding:
    """Mesajı anlamlandırır.

    Model erişilebilirse semantik anlama kullanılır. Erişilemez ya da geçersiz
    çıktı verirse ``fallback`` (deterministik yedek) devreye girer ve sonuç
    ``degraded=True`` ile işaretlenir — çağıran kalitenin düştüğünü BİLİR.
    """
    if send_prompt is not None:
        prompt = build_understanding_prompt(
            text,
            dispatch_active=dispatch_active,
            has_pending_plan=has_pending_plan,
            recent_turns=recent_turns,
            situational_context=situational_context,
        )
        try:
            raw = send_prompt(prompt)
        except Exception:
            raw = ""
        if raw:
            from runtime.agent_decider import extract_json_object

            parsed = parse_understanding(extract_json_object(raw))
            if parsed is not None:
                return parsed

    if fallback is not None:
        try:
            degraded = fallback()
        except Exception:
            degraded = None
        if degraded is not None:
            degraded.degraded = True
            degraded.source = "deterministic_fallback"
            return degraded

    return SemanticUnderstanding(
        intent=INTENT_CHAT,
        confidence=0.3,
        source="deterministic_fallback",
        degraded=True,
        reasoning="Anlama katmanı kullanılamadı; güvenli varsayılan sohbet.",
    )
