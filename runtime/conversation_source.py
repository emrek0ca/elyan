"""Konuşmanın kendisini birinci sınıf İÇERİK KAYNAĞI yapar.

NEDEN
-----
Canlı akış: kullanıcı bir şey sorar, Elyan cevaplar, sonra "bunu belge yap" der.
Bu ana kadar o "bunu" hiçbir yerde çözülemiyordu:

* Anlama katmanı yalnız TEK mesajı görüyordu. `recent_turns` parametresi
  ``intent_gate.understand`` ve ``understanding.analyze`` imzalarında YILLARDIR
  vardı, prompt'ta ``recentTurns`` olarak işleniyordu — ama **hiçbir çağıran
  onu doldurmuyordu**. Yani alan ölüydü (aynı sınıf hata: `recentOutputs`).
* Yazıcı araçlar (document/spreadsheet/presentation/canvas) yalnız AYNI PLAN
  içindeki önceki adımın çıktısını görebiliyordu (`_dependencyResults`).
  Turlar arası içerik hiç taşınmıyordu.

Sonuç: ya "hangi içeriği belgeleyeyim?" diye soruluyor (elde içerik varken —
gereksiz sürtünme), ya da yazıcı, kullanıcının KOMUT cümlesini belgenin gövdesi
sanıp onu yazıyordu.

DEĞİŞMEZ
--------
Bu katman **içerik uydurmaz**: yalnız konuşmada GERÇEKTEN söylenmiş metni
taşır. Taşınacak metin yoksa ``None`` döner ve çağıran mevcut davranışını
(sorma) sürdürür. Yani "kaynak yoksa sor" kuralı korunur; ortadan kaldırılan
şey yalnız kaynak VARKEN sormaktır.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CONVERSATION_SOURCE_CONTRACT = "elyan.conversation_source.v1"

# Bir cevabın "belgelenebilir içerik" sayılması için asgari uzunluk. Amaç
# kelime avı değil hacim eşiği: "Tamam." / "Oluşturuldu." gibi teyitler bir
# belgenin gövdesi olamaz. Eşik altındaki metin YOK sayılır (uydurmaya değil,
# soruya düşer).
_MIN_SUBSTANTIVE_CHARS = 120

# Modele referans çözümü için verilecek tur özeti sınırı.
_TURN_PREVIEW_CHARS = 240

# Yazıcıya aktarılacak gövde sınırı — writer katmanı zaten 12k'da kırpıyor.
_MAX_BODY_CHARS = 12_000


@dataclass(slots=True)
class ConversationSource:
    """Konuşmadan çıkarılmış, gerçekten var olan içerik."""

    text: str
    role: str = "assistant"
    # Kullanıcının bu içeriği doğuran sorusu — belge başlığı/konusu için.
    prompt_text: str = ""

    @property
    def is_usable(self) -> bool:
        return len(self.text.strip()) >= _MIN_SUBSTANTIVE_CHARS


def _message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    for key in ("text", "content"):
        value = str(message.get(key, "") or "").strip()
        if value:
            return value
    return ""


def _is_reference_candidate(message: Any) -> bool:
    """Bir asistan mesajının içerik olarak taşınabilir olup olmadığı.

    Netleştirme soruları ve durum bildirimleri elenir: bunlar Elyan'ın kendi
    süreç cümleleridir, kullanıcının belgelemek istediği bilgi değil. Eleme
    KELİMEYE değil, mesajın kendi METADATA'sına bakar — o metadata'yı zaten
    üreten katman yazıyor (`clarificationNeeded`), dolayısıyla desen değil
    kanıttır.
    """
    if not isinstance(message, dict):
        return False
    if str(message.get("role", "") or "") != "assistant":
        return False
    if message.get("clarificationNeeded"):
        return False
    return len(_message_text(message)) >= _MIN_SUBSTANTIVE_CHARS


def latest_reference_content(
    messages: list[dict[str, Any]] | None,
) -> ConversationSource | None:
    """Konuşmadaki en son taşınabilir asistan içeriğini döndürür.

    Yoksa ``None`` — çağıran o zaman SORAR. Uydurma üretilmez.
    """
    if not isinstance(messages, list) or not messages:
        return None
    ordered = [item for item in messages if isinstance(item, dict)]
    for index in range(len(ordered) - 1, -1, -1):
        message = ordered[index]
        if not _is_reference_candidate(message):
            continue
        # İçeriği doğuran kullanıcı sorusu: belgenin konusu genelde odur.
        prompt_text = ""
        for back in range(index - 1, -1, -1):
            previous = ordered[back]
            if str(previous.get("role", "") or "") == "user":
                prompt_text = _message_text(previous)[:_TURN_PREVIEW_CHARS]
                break
        return ConversationSource(
            text=_message_text(message)[:_MAX_BODY_CHARS],
            prompt_text=prompt_text,
        )
    return None


def recent_turns(
    messages: list[dict[str, Any]] | None,
    *,
    limit: int = 6,
) -> list[str]:
    """Anlama katmanına verilecek tur özetleri ("rol: metin").

    Amaç içerik taşımak değil GÖNDERME ÇÖZMEK: "bunu belge yap" derken
    "bunu"nun neye işaret ettiğini modelin görebilmesi. Bu yüzden her tur
    kısa kırpılır — gövdenin tamamı ayrı yoldan (``latest_reference_content``)
    yazıcıya gider.
    """
    if not isinstance(messages, list):
        return []
    turns: list[str] = []
    for message in messages[-limit:]:
        text = _message_text(message)
        if not text:
            continue
        role = str((message or {}).get("role", "") or "user")
        speaker = "kullanıcı" if role == "user" else "Elyan"
        turns.append(f"{speaker}: {text[:_TURN_PREVIEW_CHARS]}")
    return turns


def describe_for_context(source: ConversationSource | None) -> dict[str, Any] | None:
    """Durumsal bağlama girecek özet — İÇERİĞİN KENDİSİ DEĞİL, VARLIĞI.

    Modelin bilmesi gereken tek şey: "elimde hazır bir içerik VAR, dolayısıyla
    'hangi içerik?' diye sormaya gerek yok." Gövdeyi buraya koymak ÖZNEYİ
    ÇALIYOR: ölçüldü — içeriğin ilk 240 karakteri bağlama konduğunda model
    "bunu belge yap" mesajını değil o metni sınıflamaya başladı ve 5/5 'chat'
    dedi ("mesaj bilgi veriyor, eylem talebi yok"). Bu, mesajı zarfa gömmenin
    yarattığı özne karışıklığının aynısıdır.

    Bu yüzden burada yalnız ölçü ve KONU taşınır. Gövdenin tamamı ayrı yoldan
    (yürütme hunisi → yazıcının ``sourceContext``i) gider; modelin onu okuması
    gerekmez.
    """
    if source is None or not source.is_usable:
        return None
    payload: dict[str, Any] = {
        "available": True,
        "chars": len(source.text),
    }
    if source.prompt_text:
        # Konu başlığı: "ne hakkında" bilgisi niyeti çözmeye yeter, gövde değil.
        payload["topic"] = source.prompt_text
    return payload
