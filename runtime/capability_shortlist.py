"""P0 — Deterministik capability shortlist.

Planlayıcıya her görevde 77 aracın tamamını göndermek payload'ı şişiriyor ve
backend'in 48.000 karakter sınırını zorluyordu. Bu modül, görev metninden
DETERMİNİSTİK (LLM'siz, rastgelesiz) bir kısa liste çıkarır:

- Anahtar kelime → yetenek grubu eşlemesi (Türkçe + İngilizce).
- Çekirdek yetenekler her listede bulunur (chat-benzeri görevler de plan
  üretebilsin).
- Sonuç her zaman [MIN_SHORTLIST, MAX_SHORTLIST] aralığında tutulur; eşleşme
  azsa deterministik dolgu sırasıyla tamamlanır.
- Kullanıcıya özel öğrenme (learning_store) yalnız SIRALAMAYI etkiler, kümeyi
  genişletmez; yeterli örnek yoksa hiç kullanılmaz.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

MIN_SHORTLIST = 8
MAX_SHORTLIST = 15

# Görev metni olmadan da anlamlı plan üretilebilsin diye her listede bulunan
# çekirdek yetenekler (okuma ağırlıklı, zararsız).
_CORE_CAPABILITIES: tuple[str, ...] = (
    "web_research",
    "document_read",
    "file_search",
    "open_app",
    "sys_info",
)

# Eşleşme azsa listeyi MIN_SHORTLIST'e tamamlayan deterministik dolgu sırası.
_FILL_ORDER: tuple[str, ...] = (
    "document_write",
    "file_read",
    "directory_tree",
    "browser_control",
    "retrieve_context",
    "close_app",
    "spreadsheet_write",
    "make_directory",
)

# Türkçe karakter katlama — anahtar kelimeler katlanmış halde tutulur.
def _fold(value: str) -> str:
    value = str(value or "").lower()
    for src, dst in (("ı", "i"), ("ğ", "g"), ("ü", "u"), ("ş", "s"), ("ö", "o"), ("ç", "c")):
        value = value.replace(src, dst)
    return " ".join(re.sub(r"[^a-z0-9ığüşöç\s]", " ", value).split())


# (anahtar kelime kökleri) → önerilen yetenekler. Kökler substring olarak
# aranır; Türkçe ekler sorun olmaz ("tabloyu", "tablosunu" → "tablo").
_KEYWORD_GROUPS: tuple[tuple[tuple[str, ...], tuple[str, ...]], ...] = (
    (("avukat", "hukuk", "dava", "savunma", "dilekce", "mevzuat", "itiraz", "sozlesme"), ("document_read", "web_research", "text_analyze", "document_write")),
    (("doktor", "hekim", "tahlil", "tetkik", "laboratuvar", "kan sonucu", "rapor cikar", "yorumla"), ("document_read", "ocr_read", "text_analyze", "document_write")),
    (("muhasebe", "muhasebeci", "kdv", "vergi", "fatura", "tevkifat", "beyanname", "tutar", "yuzde"), ("math_solve", "spreadsheet_write", "web_research", "document_write")),
    (("ogrenci", "odev", "ders", "proje", "sunum hazirla", "calisma notu"), ("web_research", "text_analyze", "document_write", "presentation_write")),
    (("muhendis", "teknik", "tasarim", "simulasyon", "analiz et", "raporla"), ("data_analyze", "text_analyze", "chart_generate", "document_write")),
    (("optimizasyon", "karar degisken", "amac fonksiyon", "kisıt", "kisit", "kapasite", "qubo", "knapsack", "rota optimizasyon"), ("quantum_model_problem", "quantum_run_experiment", "quantum_compare_classical", "quantum_generate_report", "math_solve")),
    (("mail", "eposta", "e posta", "email", "gmail"), ("email_draft", "email_send")),
    (("takvim", "calendar", "toplanti", "meeting", "etkinlik", "randevu"), ("get_calendar_events", "add_calendar_event", "delete_calendar_event")),
    (("hatirlat", "remind", "yapilacak"), ("get_reminders", "add_reminder")),
    (("whatsapp", "wp mesaj"), ("send_whatsapp_message", "save_whatsapp_contact")),
    (("tablo", "excel", "xlsx", "csv", "spreadsheet", "hesap tablosu", "veri analiz", "satir", "sutun"), ("spreadsheet_write", "data_analyze", "chart_generate")),
    (("grafik", "chart", "histogram", "plot"), ("chart_generate", "data_analyze")),
    (("sunum", "slayt", "pptx", "presentation", "slide"), ("presentation_write", "document_read")),
    (("belge", "rapor", "docx", "word", "yazi yaz", "makale", "ozet cikar", "not al"), ("document_write", "document_read", "canvas_write")),
    (("pdf",), ("canvas_write", "document_read", "ocr_read")),
    (("oku", "ozetle", "summarize", "read"), ("document_read", "ocr_read", "image_read")),
    (("gorsel olustur", "resim olustur", "image generate", "gorsel uret", "ciz"), ("image_generate", "image_edit")),
    (("gorsel", "resim", "foto", "image", "png", "jpg"), ("image_read", "image_fetch", "image_edit")),
    (("ekran", "screenshot", "screen"), ("analyze_screen", "desktop_operator.observe_screen")),
    (("dosya", "klasor", "file", "folder", "directory", "dizin", "tasi", "kopyala", "yeniden adlandir"), ("file_search", "file_read", "file_write", "file_move", "make_directory", "directory_tree")),
    (("git", "commit", "branch", "diff", "repo"), ("git_status", "git_diff", "git_commit", "git_branch", "file_patch", "file_read")),
    (("kod", "code", "python", "script", "fonksiyon", "bug", "hata ayikla"), ("file_search", "file_read", "file_patch", "file_write", "shell_run")),
    (("komut", "terminal", "shell", "calistir komut"), ("shell_run", "sys_info")),
    (("tarayici", "browser", "site", "url", "http", "web sayfa", "sekme"), ("browser_control", "browser_agent.run", "browser_session.goto", "browser_session.extract")),
    (("indir", "download"), ("browser_session.download", "image_fetch", "web_research")),
    (("youtube", "video ac", "muzik", "spotify", "cal", "sarki", "dinle"), ("play_media", "browser_control", "get_youtube_channel_report")),
    (("arastir", "research", "haber", "guncel", "bul ve ozetle", "search"), ("web_research", "retrieve_context")),
    (("hava", "weather", "sicaklik"), ("get_weather",)),
    (("uygulama", "app ", "ac ", "baslat", "launch", "kapat", "quit", "close"), ("open_app", "close_app", "desktop_os.processes")),
    (("matematik", "math", "denklem", "integral", "turev", "hesapla"), ("math_solve", "latex_parse")),
    (("kuantum", "quantum", "qiskit"), ("quantum_model_problem", "quantum_run_experiment", "quantum_compare_classical", "quantum_generate_report")),
    (("ses", "konus", "speech", "sesli", "mikrofon", "dinleyip yaz"), ("speech_to_text", "text_to_speech", "speech_capture")),
    (("pano", "clipboard", "kopyalanan"), ("clipboard_read", "clipboard_write")),
    (("hafiza", "hatirla bunu", "memory", "kaydet bunu"), ("save_memory", "delete_memory")),
    (("surec", "process", "pid", "pencere", "window"), ("desktop_os.processes", "desktop_os.active_window", "close_app")),
    (("otomasyon", "tikla", "operator", "form doldur"), ("desktop_operator.run", "desktop_operator.observe_screen", "browser_agent.run")),
)


def shortlist_capabilities(
    text: str,
    *,
    known_capabilities: Iterable[str] | None = None,
    extra_capabilities: Iterable[str] | None = None,
    success_rate_provider: Any = None,
    min_size: int = MIN_SHORTLIST,
    max_size: int = MAX_SHORTLIST,
) -> list[str]:
    """Görev metni için deterministik yetenek kısa listesi (8–15 ad).

    `extra_capabilities`: iş emri/route kararının açıkça istediği yetenekler —
    her zaman listeye girer (bütçe içinde önceliklidir).
    `success_rate_provider(capability) -> float | None`: kullanıcıya özel
    öğrenilmiş başarı oranı; yalnız eşleşen adaylar arasındaki SIRAYI etkiler.
    """
    folded = _fold(text)
    known = {str(item or "").strip() for item in (known_capabilities or ()) if str(item or "").strip()}

    scored: dict[str, int] = {}

    def _add(name: str, score: int) -> None:
        name = str(name or "").strip()
        if not name:
            return
        if known and name not in known:
            return
        scored[name] = max(scored.get(name, 0), score)

    for name in extra_capabilities or ():
        _add(str(name), 100)
    for keywords, capabilities in _KEYWORD_GROUPS:
        hits = sum(1 for keyword in keywords if keyword in folded)
        if hits <= 0:
            continue
        for position, name in enumerate(capabilities):
            _add(name, 10 * hits - position)
    for name in _CORE_CAPABILITIES:
        _add(name, 1)

    def _success(name: str) -> float:
        if not callable(success_rate_provider):
            return 0.5
        try:
            rate = success_rate_provider(name)
        except Exception:
            return 0.5
        if rate is None:
            return 0.5
        return max(0.0, min(1.0, float(rate)))

    ordered = sorted(
        scored.items(),
        key=lambda item: (-item[1], -_success(item[0]), item[0]),
    )
    result = [name for name, _ in ordered[: max(1, max_size)]]

    if len(result) < min_size:
        for name in _FILL_ORDER + _CORE_CAPABILITIES:
            if len(result) >= min_size:
                break
            if name in result:
                continue
            if known and name not in known:
                continue
            result.append(name)
    return result[: max(1, max_size)]
