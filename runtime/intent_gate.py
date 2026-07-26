"""Görev / sohbet ayrım kapısı.

NEDEN VAR
---------
Eski yol (`_requires_tool_capable_route`) 100+ desenlik bir keyword listesiydi ve
mantığı TERSTİ: *herhangi bir* kelime eşleşirse istek "görev" sayılıyordu. Türkçede
"yaz" (fiil/mevsim), "ara" (fiil/"arada"), "aç" (fiil/"açık") gibi çakışmalar
yüzünden düz sohbet sürekli araç çağrısına dönüşüyordu — canlıda görülen
"dispatch aktifken 'adım ne benim' → desktop_operator.run" hatası bunun sonucu.
Her yeni cümle kalıbı için desen eklemek dipsiz kuyuydu.

BU MODÜLÜN KURALI
-----------------
**Varsayılan SOHBET; görev için pozitif kanıt şarttır.** Kanıt = eylem fiili
*ve* bir hedef (nesne/dosya/uygulama/URL). Tek başına fiil yetmez. Belirsizlik
sohbete düşer: en kötü ihtimalle kullanıcı isteğini netleştirir — yanlışlıkla
yan etkili bir iş çalıştırmaktan çok daha ucuzdur (fail-safe).

Ayrıca görev YÜRÜRKEN gelen mesajlar varsayılan olarak sohbettir; yalnız açık
görev kontrolü ("iptal", "onayla", "ne durumda") kontrol sayılır.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INTENT_GATE_CONTRACT = "elyan.intent_gate.v1"

# ── Sınıflar ────────────────────────────────────────────────────────────────
CHAT = "chat"
TASK = "task"
TASK_CONTROL = "task_control"


@dataclass(frozen=True, slots=True)
class IntentDecision:
    kind: str
    confidence: float
    reason: str

    @property
    def is_task(self) -> bool:
        return self.kind == TASK

    @property
    def is_chat(self) -> bool:
        return self.kind == CHAT


def _normalize(value: str) -> str:
    text = str(value or "").strip().lower()
    for source, target in (
        ("ı", "i"), ("ğ", "g"), ("ü", "u"), ("ş", "s"), ("ö", "o"), ("ç", "c"),
        ("â", "a"), ("î", "i"), ("û", "u"),
    ):
        text = text.replace(source, target)
    return re.sub(r"\s+", " ", text)


# ── Sohbet sinyalleri (görev kanıtından ÖNCE bakılır, kesin kes) ────────────
# Asistanın kendisine / duruma dair sorular, selamlama, sohbet, meta.
_CHAT_PATTERNS = (
    # Kimlik ve durum soruları: "adım ne", "sen kimsin", "napıyorsun"
    r"\b(adim|ismim|adin|ismin)\s+(ne|nedir|neydi)\b",
    r"\bben\s+kimim\b",
    r"\bsen\s+(kimsin|nesin|kim)\b",
    r"\bkimsin\b",
    r"\bne\s?(yapiyorsun|apiyorsun|yapiyosun)\b",
    r"\bnasilsin\b",
    r"\bnaber\b",
    # Selamlama / nezaket
    r"^\s*(merhaba|selam|gunaydin|iyi\s?(gunler|aksamlar|geceler)|hey|hi|hello)\b",
    r"^\s*(tesekkur|sagol|sag\s?ol|eyvallah|tamam|peki|ok|okey)\b",
    # Görüş/açıklama istekleri — eylem değil
    r"\b(ne\s?dusunuyorsun|fikrin\s+ne|sence|nedir|ne\s?demek|aciklar\s?misin|anlat)\b",
    r"\bnasil\s+(calisir|oluyor|yapiliyor)\b",
    # Yetenek sorusu (yapabilir misin?) — istek değil, soru
    r"\b(yapabilir|edebilir|acabilir|yazabilir)\s?misin\b",
    r"\bneler\s+yapabilirsin\b",
)

# ── Görev kontrolü (görev yürürken anlamlı) ────────────────────────────────
_TASK_CONTROL_PATTERNS = (
    r"\b(iptal|vazgec|durdur|dur|kes)\b",
    r"\b(onayla|onay|kabul|evet\s+devam|devam\s+et)\b",
    r"\b(ne\s?durumda|durum\s+ne|nerede\s+kaldi|bitti\s?mi|hazir\s?mi|ilerleme)\b",
)

# ── Eylem fiilleri (tek başına YETMEZ; hedef de gerekir) ───────────────────
_ACTION_VERBS = (
    "ac", "acar", "baslat", "calistir", "kur", "yukle", "indir", "kaydet",
    "olustur", "yarat", "uret", "hazirla", "yaz", "duzenle", "degistir",
    "sil", "kopyala", "tasi", "gonder", "paylas", "ara", "bul", "arastir",
    "analiz", "ozetle", "cevir", "hesapla", "coz", "planla", "ekle",
    "guncelle", "tikla", "goster", "listele", "kontrol", "test",
    "optimize", "duzelt", "temizle", "derle", "deploy", "commit",
)

# ── Hedef sinyalleri (eylemin üzerine uygulanacağı somut nesne) ────────────
_TARGET_PATTERNS = (
    r"[\w\-/]+\.(txt|md|pdf|docx?|xlsx?|pptx?|csv|json|png|jpe?g|py|ts|js|html|css|zip|sh)\b",
    r"\b(https?://|www\.)\S+",
    r"[~/][\w\-./]+",                       # dosya yolu
    # NOT: Türkçe eklemeli bir dildir ("rapor" → "rapora", "dosyayı", "ekranda").
    # Bu yüzden hedef adlarında sondaki sınır yerine ek toleransı (\w*) kullanılır;
    # aksi halde "rapora yaz" gibi apaçık görevler hedefsiz görünüp sohbete düşer.
    r"\b(masaustu|desktop|indirilenler|downloads|belgeler|documents|klasor|dizin)\w*",
    r"\b(dosya|belge|rapor|tablo|sunum|grafik|not|liste|mail|e?posta|mesaj|takvim|randevu|hatirlatici|toplanti)\w*",
    r"\b(chrome|safari|firefox|finder|terminal|vscode|spotify|whatsapp|slack|excel|word|powerpoint|uygulama)\w*",
    r"\b(ekran|pencere|sekme|pano|clipboard)\w*",
    r"\b(kod|repo|proje|test|branch|commit|pull\s?request)\w*",
)


def _has_action_verb(text: str) -> bool:
    for verb in _ACTION_VERBS:
        if re.search(rf"\b{re.escape(verb)}\w*\b", text):
            return True
    return False


def _has_target(text: str) -> bool:
    return any(re.search(pattern, text) for pattern in _TARGET_PATTERNS)


def _is_question_about_state(text: str) -> bool:
    """'X ne', 'X kim', 'X nedir' gibi bilgi soruları — eylem talebi değil."""
    return bool(
        re.search(r"\b(ne|nedir|kim|kimdir|hangi|neden|nicin|nasil)\b", text)
        and not _has_target(text)
    )


def classify_message(
    text: str,
    *,
    dispatch_active: bool = False,
    has_pending_plan: bool = False,
) -> IntentDecision:
    """Bir kullanıcı mesajını sohbet / görev / görev-kontrolü olarak sınıflar.

    ``dispatch_active`` — masaüstünde bir görev yürüyor. Bu durumda gelen mesaj
    VARSAYILAN OLARAK SOHBETTİR; kullanıcı çalışan işe müdahale etmek istiyorsa
    bunu açıkça söyler (iptal/onayla/ne durumda). Böylece "görev sürerken normal
    sohbet edilemiyor" hatası kökten biter.
    """
    normalized = _normalize(text)
    if not normalized:
        return IntentDecision(CHAT, 1.0, "empty_message")

    # 1) Görev kontrolü — yalnız bir iş yürüyor ya da onay bekliyorsa anlamlı.
    if dispatch_active or has_pending_plan:
        for pattern in _TASK_CONTROL_PATTERNS:
            if re.search(pattern, normalized):
                return IntentDecision(TASK_CONTROL, 0.9, "explicit_task_control")

    # 2) Sohbet sinyalleri — görev kanıtından ÖNCE ve kesin.
    for pattern in _CHAT_PATTERNS:
        if re.search(pattern, normalized):
            return IntentDecision(CHAT, 0.95, "conversational_signal")

    # 3) Görev yürürken: açık ve güçlü kanıt yoksa sohbet kal.
    if dispatch_active:
        if _has_action_verb(normalized) and _has_target(normalized):
            return IntentDecision(TASK, 0.8, "explicit_task_during_dispatch")
        return IntentDecision(CHAT, 0.85, "chat_during_dispatch")

    # 4) Bilgi sorusu (hedefsiz "ne/kim/nasil") → sohbet.
    if _is_question_about_state(normalized):
        return IntentDecision(CHAT, 0.8, "informational_question")

    # 5) POZİTİF KANIT: eylem fiili + hedef.
    has_verb = _has_action_verb(normalized)
    has_target = _has_target(normalized)
    if has_verb and has_target:
        return IntentDecision(TASK, 0.9, "action_verb_with_target")
    if has_verb and len(normalized.split()) <= 4:
        # Kısa ve emir kipi: "chrome ac", "ekrani goster" gibi.
        return IntentDecision(TASK, 0.75, "short_imperative")

    # 6) Belirsiz → SOHBET (fail-safe: yanlışlıkla yan etki üretme).
    return IntentDecision(CHAT, 0.6, "insufficient_task_evidence")


def should_run_task(
    text: str,
    *,
    dispatch_active: bool = False,
    has_pending_plan: bool = False,
) -> bool:
    """Kısa yol: mesaj görev yürütmeyi hak ediyor mu?"""
    return classify_message(
        text,
        dispatch_active=dispatch_active,
        has_pending_plan=has_pending_plan,
    ).is_task


def assemble_situational_context(
    state: dict | None = None,
    *,
    calendar_events: list | None = None,
    extra: dict | None = None,
) -> dict | None:
    """Anlama katmanına gidecek durumsal bağlamı kurar.

    TEK KAYNAK: canlı yol da, eval de bu payload'ı kullanır. Ayrı kurulursa
    eval production'ı değil kendi kurgusunu ölçer — nitekim ölçtü: ``environment``
    hiç enjekte edilmediği için "projedeki testleri çalıştır" isteği 5 koşunun
    3'ünde "hangi proje dizini?" diye sorulup ``clarify``ye düşüyordu; canlı
    yolda o bilgi zaten vardı.

    ``extra`` sentetik/çağıran-tarafı bağlamı üstüne bindirir (eval senaryoları
    kendi takvim/recentOutputs kurgularını böyle verir); üretimde boştur.
    """
    # Durumsal bağlam: takvim/konum/aktif uygulama. Niyeti bununla çözmek,
    # "hangi toplantı?" gibi bariz soruları ortadan kaldırır.
    situational: dict | None = None
    try:
        from runtime.situational_context import gather_situation

        moment = gather_situation(state, calendar_events=calendar_events)
        if not moment.is_empty:
            situational = moment.to_prompt_context()
    except Exception:
        situational = None

    # ÖZ-MODEL + DÜNYA MODELİ: "ben neyim / bu makinede ne var" bilgisi koddan
    # türetilir. İkisi de niyet çözümünü doğrudan etkiler: izni kapalı bir işi
    # "yaparım" diye görev sayma; bu makinede olmayan aracı varsayma.
    try:
        from runtime.self_model import build_self_card, self_card_is_informative

        card = build_self_card(state)
        if self_card_is_informative(card):
            situational = dict(situational or {})
            situational["selfModel"] = card
    except Exception:
        pass
    try:
        from runtime import environment_model

        facts = environment_model.to_prompt_context(
            environment_model.environment_facts(state)
        )
        if facts:
            situational = dict(situational or {})
            situational["environment"] = facts
    except Exception:
        pass
    # EKOSİSTEM: Elyan üç yüzeyli tek organizmadır (mobil/backend/masaüstü).
    # Hangi yüzeyin ŞU AN açık olduğunu bilmek, "yaptım" uydurmasının ve
    # "yapamam" gereksiz reddinin ortak panzehiridir.
    try:
        from runtime import ecosystem_model

        topology = ecosystem_model.to_prompt_context(ecosystem_model.assess(state))
        if topology:
            situational = dict(situational or {})
            situational["ecosystem"] = topology
    except Exception:
        pass
    if isinstance(extra, dict) and extra:
        situational = {**(situational or {}), **extra}
    return situational


def understand(
    text: str,
    *,
    send_prompt=None,
    dispatch_active: bool = False,
    has_pending_plan: bool = False,
    recent_turns: list[str] | None = None,
    state: dict | None = None,
    calendar_events: list | None = None,
    situational_extra: dict | None = None,
):
    """Semantik anlama (birincil) + desen tabanlı yedek.

    OTORİTE MODELDEDİR. Bu dosyadaki desenler yalnız model erişilemediğinde
    devreye girer ve sonuç ``degraded=True`` ile işaretlenir. Yani "şu kelime
    geçerse şu" mantığı artık ana karar yolu DEĞİL, yalnız bozulmuş mod
    emniyet ağıdır.
    """
    from runtime import understanding as understanding_module

    def _pattern_fallback():
        decision = classify_message(
            text,
            dispatch_active=dispatch_active,
            has_pending_plan=has_pending_plan,
        )
        mapping = {
            CHAT: understanding_module.INTENT_CHAT,
            TASK: understanding_module.INTENT_TASK,
            TASK_CONTROL: understanding_module.INTENT_TASK_CONTROL,
        }
        return understanding_module.SemanticUnderstanding(
            intent=mapping.get(decision.kind, understanding_module.INTENT_CHAT),
            confidence=decision.confidence,
            source="deterministic_fallback",
            reasoning=decision.reason,
            signals=[decision.reason],
        )

    situational = assemble_situational_context(
        state, calendar_events=calendar_events, extra=situational_extra
    )

    return understanding_module.analyze(
        text,
        send_prompt=send_prompt,
        dispatch_active=dispatch_active,
        has_pending_plan=has_pending_plan,
        recent_turns=recent_turns,
        situational_context=situational,
        fallback=_pattern_fallback,
    )
