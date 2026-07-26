"""Turlar arası içerik zincirinin sözleşmesi.

Kapatılan canlı arıza: kullanıcı bir şey sorar, Elyan cevaplar, sonra "bunu
belge yap" der. O ana kadar "bunu" hiçbir yerde çözülemiyordu — anlama katmanı
tek mesaj görüyor, yazıcı yalnız aynı plan içindeki adımları görüyordu. Sonuç
ya gereksiz soru ya da kullanıcının KOMUT cümlesini gövde sanan bir belgeydi.

Değişmez: bu katman içerik UYDURMAZ. Taşınacak gerçek metin yoksa hiçbir şey
değişmez ve "kaynak yoksa sor" kuralı yürürlükte kalır.
"""

from __future__ import annotations

from runtime import bridge, conversation_source

_ANSWER = (
    "Pomodoro tekniği 25 dakikalık odak bloklarına dayanır. Her bloğun ardından "
    "5 dakikalık kısa bir mola verilir; dört blok sonunda 15-30 dakikalık uzun "
    "mola alınır. Yöntemin amacı dikkati tüketmeden sürdürmektir."
)


def _conversation() -> list[dict[str, str]]:
    return [
        {"role": "user", "text": "pomodoro tekniği nasıl çalışıyor?"},
        {"role": "assistant", "text": _ANSWER},
    ]


def test_latest_reference_content_carries_the_previous_answer() -> None:
    source = conversation_source.latest_reference_content(_conversation())
    assert source is not None
    assert source.is_usable
    assert source.text == _ANSWER
    # Belgenin konusu genelde içeriği doğuran sorudur.
    assert "pomodoro" in source.prompt_text.lower()


def test_clarification_questions_are_not_carried_as_content() -> None:
    """Elyan'ın kendi süreç cümlesi kullanıcının içeriği değildir.

    Eleme KELİMEYE değil mesajın kendi metadata'sına bakar (`clarificationNeeded`
    alanını zaten üreten katman yazar) — bu yüzden desen değil kanıttır.
    """
    messages = [
        {"role": "user", "text": "onu belge yap"},
        {
            "role": "assistant",
            "text": "Hangi dosyayı kastettiğini tam çıkaramadım, adını yazar mısın? " * 3,
            "clarificationNeeded": True,
        },
    ]
    assert conversation_source.latest_reference_content(messages) is None


def test_short_acknowledgements_are_not_documentable_content() -> None:
    messages = [
        {"role": "user", "text": "klasörü oluştur"},
        {"role": "assistant", "text": "Oluşturuldu."},
    ]
    assert conversation_source.latest_reference_content(messages) is None


def test_no_conversation_content_yields_nothing_rather_than_invention() -> None:
    assert conversation_source.latest_reference_content([]) is None
    assert conversation_source.latest_reference_content(None) is None
    assert conversation_source.describe_for_context(None) is None


def test_recent_turns_are_labelled_and_bounded() -> None:
    turns = conversation_source.recent_turns(_conversation())
    assert len(turns) == 2
    assert turns[0].startswith("kullanıcı: ")
    assert turns[1].startswith("Elyan: ")
    assert all(len(turn) <= 260 for turn in turns)


def test_writer_with_no_content_receives_the_conversation_body() -> None:
    token = bridge._CURRENT_CONVERSATION_SOURCE.set(_ANSWER)
    try:
        filled = bridge._fill_writer_source_from_conversation(
            "document_write", {"title": "Pomodoro"}
        )
    finally:
        bridge._CURRENT_CONVERSATION_SOURCE.reset(token)
    assert filled["sourceContext"] == _ANSWER
    assert filled["_sourceContextOrigin"] == "conversation_turn"


def test_existing_content_is_never_overwritten() -> None:
    """Plan içi zincirleme ve kullanıcının verdiği içerik korunur."""
    token = bridge._CURRENT_CONVERSATION_SOURCE.set(_ANSWER)
    try:
        explicit = bridge._fill_writer_source_from_conversation(
            "document_write", {"sourceContext": "araştırma çıktısı"}
        )
        chained = bridge._fill_writer_source_from_conversation(
            "document_write", {"_dependencyResults": {"s1": {"kind": "web_research"}}}
        )
        structured = bridge._fill_writer_source_from_conversation(
            "spreadsheet_write", {"rows": [["a", "b"]]}
        )
        from_file = bridge._fill_writer_source_from_conversation(
            "document_write", {"sourcePath": "/tmp/rapor.docx"}
        )
    finally:
        bridge._CURRENT_CONVERSATION_SOURCE.reset(token)
    assert explicit["sourceContext"] == "araştırma çıktısı"
    assert "sourceContext" not in chained
    assert "sourceContext" not in structured
    assert "sourceContext" not in from_file


def test_non_writer_capabilities_are_untouched() -> None:
    token = bridge._CURRENT_CONVERSATION_SOURCE.set(_ANSWER)
    try:
        args = bridge._fill_writer_source_from_conversation("shell_run", {})
    finally:
        bridge._CURRENT_CONVERSATION_SOURCE.reset(token)
    assert args == {}


def test_writer_is_untouched_when_conversation_has_nothing() -> None:
    token = bridge._CURRENT_CONVERSATION_SOURCE.set("")
    try:
        args = bridge._fill_writer_source_from_conversation("document_write", {})
    finally:
        bridge._CURRENT_CONVERSATION_SOURCE.reset(token)
    assert args == {}
