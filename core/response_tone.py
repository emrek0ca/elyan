"""
Response Tone - Natural, Human-like Responses

Wiqo asistan gibi konusur, bot gibi degil.
Her yanit dogal, samimi ve zeki.
"""

import random
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path


# === TEMPLATES ===

TONE_TEMPLATES = {
    "success": [
        "Tamamladım.",
        "İşlem hazır.",
        "İstediğiniz gibi düzenlendi.",
        "Dosya hazırlandı.",
        "Hemen hallettim.",
        "Stratejik düzenleme tamamlandı.",
        "Tamamdır, bitti.",
    ],
    "error": [
        "Maalesef bu işlemi gerçekleştiremedim. {reason}",
        "Bir aksilik oluştu: {reason}",
        "Şu an buna erişemiyorum: {reason}",
        "İşlem başarısız oldu: {reason}",
    ],
    "working": [
        "Hemen bakıyorum...",
        "Üzerinde çalışıyorum...",
        "Analiz ediyorum...",
        "Verileri kontrol ediyorum...",
    ],
    "not_found": [
        "Aradığınızı bulamadım.",
        "Böyle bir sonuç çıkmadı.",
        "Kayıtlarda görünmüyor.",
    ],
    "empty": [
        "İçerik boş görünüyor.",
        "Burada herhangi bir veri yok.",
    ],
    "info": [
        "İşte istediğiniz bilgiler.",
        "Buyurun, sonuçlar hazır.",
        "Veriler getirildi.",
    ],
    "thanks_reply": [
        "Rica ederim, her zaman.",
        "Memnuniyetle.",
        "Başka bir talebiniz var mı?",
    ],
    "farewell": [
        "Görüşmek üzere.",
        "İyi çalışmalar dilerim.",
        "Kendinize iyi bakın.",
    ],
    "acknowledge": [
        "Anladım.",
        "Peki.",
        "Üzerine alıyorum.",
        "Başka bir şey var mı?",
    ],
}

# === GREETINGS ===

def conversational_greeting(hour: Optional[int] = None) -> str:
    if hour is None:
        hour = datetime.now().hour

    if 5 <= hour < 12:
        greetings = ["Günaydın.", "Günaydın, hoş geldiniz.", "İyi sabahlar."]
    elif 12 <= hour < 18:
        greetings = ["Merhaba.", "Hoş geldiniz.", "İyi günler."]
    elif 18 <= hour < 22:
        greetings = ["İyi akşamlar.", "Hoş geldiniz.", "Merhaba."]
    else:
        greetings = ["İyi geceler.", "Merhaba.", "Selamlar."]

    return random.choice(greetings)


def get_varied_greeting() -> str:
    """Samuel-style professional varied greeting"""
    hour = datetime.now().hour
    base = conversational_greeting(hour)

    suffixes = [
        " Size nasıl yardımcı olabilirim?",
        " Stratejik asistanınız hazır. Buyurun.",
        " Bugün ne yapalım?",
        " Sizi dinliyorum.",
    ]
    return base + random.choice(suffixes)


# === NATURAL RESPONSE GENERATORS ===

def natural_response(response_type: str, data: Optional[Dict[str, Any]] = None) -> str:
    templates = TONE_TEMPLATES.get(response_type, ["Tamam."])
    template = random.choice(templates)
    if data:
        try:
            return template.format(**data)
        except KeyError:
            return template
    return template


def format_error_natural(error_msg: str) -> str:
    """Teknik hatayi insani dile cevir"""
    error_lower = error_msg.lower()

    if "not found" in error_lower or "bulunamad" in error_lower:
        return "Dosya veya klasor bulunamadi."
    if "permission" in error_lower or "izin" in error_lower:
        return "Bu isleme iznim yok."
    if "timeout" in error_lower or "zaman" in error_lower:
        return "Islem cok uzun surdu, zaman asimina ugradi."
    if "connection" in error_lower or "baglanti" in error_lower:
        return "Baglanti kurulamadi."
    if "invalid" in error_lower or "gecersiz" in error_lower:
        return "Gecersiz bir deger var."
    if "disk" in error_lower or "space" in error_lower:
        return "Disk alani yetersiz."
    if "memory" in error_lower:
        return "Bellek yetersiz."
    if "tool" in error_lower and "not found" in error_lower:
        return "Bu islemi yapacak arac bulunamadi."

    # Kisa tut
    if len(error_msg) > 100:
        return f"Bir sorun olustu: {error_msg[:80]}..."
    return f"Bir sorun olustu: {error_msg}"


def format_tool_result(tool_name: str, result: dict) -> str:
    """Her tool icin dogal Turkce sonuc uret"""
    if not result.get("success", True):
        error = result.get("error", "Bilinmeyen hata")
        return format_error_natural(error)

    # --- File Operations ---
    if tool_name == "list_files":
        items = result.get("items", [])
        if not items:
            return "Klasor bos."
        dirs = [i for i in items if i.get("type") == "dir"]
        files = [i for i in items if i.get("type") == "file"]
        path = result.get("path", "")
        folder = Path(path).name or "Klasor"

        out = f"{folder}\n"
        if dirs:
            out += f"\nKlasorler ({len(dirs)}):\n"
            for d in dirs[:12]:
                out += f"  {d['name']}\n"
            if len(dirs) > 12:
                out += f"  ... +{len(dirs)-12} klasor\n"
        if files:
            out += f"\nDosyalar ({len(files)}):\n"
            for f in files[:15]:
                size = _format_size(f.get('size', 0))
                out += f"  {f['name']} ({size})\n"
            if len(files) > 15:
                out += f"  ... +{len(files)-15} dosya\n"
        return out.strip()

    if tool_name == "write_file":
        name = Path(result.get("path", "dosya")).name
        return f"{name} olusturuldu."

    if tool_name == "read_file":
        content = result.get("content", "")[:2500]
        name = Path(result.get("path", "dosya")).name
        return f"{name}:\n\n{content}"

    if tool_name in ("delete_file", "remove_file"):
        name = Path(result.get("path", "")).name
        return f"{name} silindi."

    if tool_name in ("move_file", "copy_file", "rename_file", "create_folder"):
        return result.get("message", "Tamamlandi.")

    # --- App Control ---
    if tool_name == "open_app":
        return f"{result.get('app', 'Uygulama')} acildi."

    if tool_name == "open_url":
        url = result.get('url', '')
        domain = url.replace("https://", "").replace("http://", "").split("/")[0]
        return f"{domain} acildi."

    if tool_name in ("close_app", "quit_app"):
        return f"{result.get('app', 'Uygulama')} kapatildi."
    if tool_name == "shutdown_system":
        return result.get("message", "Sistem kapatma komutu gönderildi.")
    if tool_name == "restart_system":
        return result.get("message", "Sistem yeniden başlatma komutu gönderildi.")
    if tool_name == "sleep_system":
        return result.get("message", "Sistem uyku moduna alınıyor.")
    if tool_name == "lock_screen":
        return result.get("message", "Ekran kilitlendi.")

    # --- System ---
    if tool_name == "get_system_info":
        s = result.get("system", {})
        c = result.get("cpu", {})
        m = result.get("memory", {})
        d = result.get("disk", {})
        b = result.get("battery")
        out = (f"OS: {s.get('os')} {s.get('os_version','')}\n"
               f"CPU: %{c.get('percent')} ({c.get('cores')} cekirdek)\n"
               f"RAM: {m.get('used_gb')}/{m.get('total_gb')} GB (%{m.get('percent')})\n"
               f"Disk: {d.get('free_gb')} GB bos")
        if b:
            status = "sarj oluyor" if b.get('charging') else ""
            out += f"\nPil: %{b.get('percent')} {status}"
        return out

    if tool_name == "take_screenshot":
        return f"Ekran goruntusu alindi: {result.get('filename', '')}"

    if tool_name == "read_clipboard":
        content = result.get("content", "")
        if not content:
            return "Pano bos."
        return f"Panoda:\n{content[:500]}"

    if tool_name == "write_clipboard":
        return "Panoya kopyalandi."

    if tool_name == "set_volume":
        if result.get("muted") is True:
            return "Ses kapatildi."
        if result.get("muted") is False:
            return "Ses acildi."
        return f"Ses seviyesi: %{result.get('level', 0)}"

    if tool_name == "send_notification":
        return f"Bildirim gonderildi: {result.get('title', '')}"

    if tool_name == "kill_process":
        return f"{result.get('process', 'Process')} sonlandirildi."

    if tool_name == "get_process_info":
        processes = result.get("processes", [])
        if not processes:
            return "Calisan uygulama bulunamadi."
        out = f"Calisan uygulamalar ({len(processes)}):\n"
        for p in processes[:15]:
            out += f"  {p['name'][:40]} (CPU: {p['cpu']}, RAM: {p['memory']}%)\n"
        if len(processes) > 15:
            out += f"  ... +{len(processes)-15} uygulama"
        return out.strip()

    if tool_name == "run_safe_command":
        output = result.get("output", "").strip()
        error = result.get("error", "").strip()
        rc = result.get("return_code", 0)
        if rc != 0:
            return f"Komut basarisiz ({rc}):\n{error}"
        if not output:
            return f"Komut calistirildi: {result.get('command', '')}"
        if len(output) > 1000:
            output = output[:1000] + "\n... (kisaltildi)"
        return output

    # --- macOS ---
    if tool_name in ("set_brightness", "get_brightness"):
        level = result.get("level", 0)
        if level == -1:
            return result.get("note", "Parlaklik bilgisi alinamadi.")
        return f"Parlaklik: %{level}"

    if tool_name == "toggle_dark_mode":
        return f"{result.get('mode', 'Bilinmiyor').capitalize()} mod aktif."

    if tool_name == "get_appearance":
        return f"Gorunum: {result.get('mode', 'bilinmiyor').capitalize()} mod"

    if tool_name == "wifi_status":
        if not result.get("wifi_on"):
            return "WiFi kapali."
        net = result.get("network", "")
        if result.get("connected") and net:
            return f"WiFi acik, bagli: {net}"
        return "WiFi acik (bagli degil)."

    if tool_name == "wifi_toggle":
        return f"WiFi {result.get('action', 'degistirildi')}."

    if tool_name == "bluetooth_status":
        return f"Bluetooth: {result.get('status', 'bilinmiyor')}"

    # --- Calendar & Reminders ---
    if tool_name == "get_today_events":
        events = result.get("events", [])
        if not events:
            return "Bugun etkinlik yok."
        out = f"Bugunun etkinlikleri ({len(events)}):\n"
        for e in events[:10]:
            out += f"  {e['title']}"
            if e.get('time'):
                out += f" - {e['time']}"
            out += "\n"
        return out.strip()

    if tool_name == "create_event":
        return f"Etkinlik olusturuldu: {result.get('title', '')}"

    if tool_name == "get_reminders":
        reminders = result.get("reminders", [])
        if not reminders:
            return "Animsatici yok."
        out = f"Animsaticilar ({len(reminders)}):\n"
        for r in reminders[:15]:
            out += f"  {r['title']}\n"
        return out.strip()

    if tool_name == "create_reminder":
        return f"Animsatici olusturuldu: {result.get('title', '')}"

    # --- Spotlight ---
    if tool_name == "spotlight_search":
        results = result.get("results", [])
        if not results:
            return f"'{result.get('query', '')}' icin sonuc bulunamadi."
        out = f"{len(results)} sonuc bulundu:\n"
        for r in results[:15]:
            prefix = "[Klasor]" if r.get("type") == "folder" else ""
            out += f"  {prefix} {r['name']}\n"
        return out.strip()

    # --- Search ---
    if tool_name == "search_files":
        matches = result.get("matches", [])
        if not matches:
            return "Dosya bulunamadi."
        out = f"{len(matches)} dosya bulundu:\n"
        for m in matches[:15]:
            out += f"  {Path(m).name}\n"
        return out.strip()

    # --- Office ---
    if tool_name == "read_word":
        content = result.get("content", "")[:3000]
        name = result.get("filename", "belge.docx")
        return f"{name}:\n\n{content}"

    if tool_name == "write_word":
        return f"Word dosyasi olusturuldu: {result.get('filename', '')}"

    if tool_name == "read_excel":
        text_output = result.get("text_output", "")
        name = result.get("filename", "tablo.xlsx")
        rows = result.get("row_count", 0)
        return f"{name} ({rows} satir):\n\n{text_output}"

    if tool_name == "write_excel":
        return f"Excel olusturuldu: {result.get('filename', '')} ({result.get('row_count', 0)} satir)"

    if tool_name == "read_pdf":
        content = result.get("content", "")[:3000]
        name = result.get("filename", "belge.pdf")
        pages = result.get("pages_read", 0)
        return f"{name} ({pages} sayfa):\n\n{content}"

    if tool_name in ("get_pdf_info", "pdf_info"):
        name = result.get("filename", "belge.pdf")
        out = f"{name}\n"
        out += f"Sayfa: {result.get('total_pages', '?')}\n"
        out += f"Boyut: {result.get('file_size', '?')}"
        if result.get("title"):
            out += f"\nBaslik: {result['title']}"
        return out

    if tool_name in ("summarize_document", "smart_summarize"):
        summary = result.get("summary", "")
        if not summary:
            return "Ozet olusturulamadi."
        return f"Ozet:\n\n{summary[:1500]}"

    # --- Web ---
    if tool_name == "web_search":
        results_list = result.get("results", [])
        query = result.get("query", "")
        if not results_list:
            return f"'{query}' icin sonuc bulunamadi."
        out = f"'{query}' icin {len(results_list)} sonuc:\n\n"
        for i, r in enumerate(results_list[:5], 1):
            out += f"{i}. {r.get('title', 'Basliksiz')}\n"
            if r.get('snippet'):
                out += f"   {r['snippet'][:150]}\n"
            out += f"   {r.get('display_url', r.get('url', ''))}\n\n"
        return out.strip()

    if tool_name == "fetch_page":
        title = result.get("title", "")
        content = result.get("content", "")[:2000]
        return f"{title}\n\n{content}"

    if tool_name in ("start_research", "research"):
        task_id = result.get("task_id", "")
        topic = result.get("topic", "")
        return f"Arastirma baslatildi: {topic}\nID: {task_id}"

    if tool_name == "get_research_status":
        status = result.get("status", "bilinmiyor")
        progress = result.get("progress", 0)
        out = f"Arastirma: {status} (%{progress})"
        if status == "completed" and result.get("results"):
            out += f"\n\n{result['results'].get('summary', '')}"
        return out

    # --- Notes ---
    if tool_name == "create_note":
        return f"Not olusturuldu: {result.get('title', '')}"

    if tool_name == "list_notes":
        notes = result.get("notes", [])
        if not notes:
            return "Hic not yok."
        out = f"{len(notes)} not:\n"
        for n in notes[:15]:
            out += f"  {n.get('title', 'Basliksiz')}\n"
        return out.strip()

    if tool_name == "search_notes":
        notes = result.get("results", [])
        if not notes:
            return "Not bulunamadi."
        out = f"{len(notes)} sonuc:\n"
        for n in notes[:10]:
            out += f"  {n.get('title', 'Basliksiz')}\n"
        return out.strip()

    if tool_name == "get_note":
        title = result.get("title", "")
        content = result.get("content", "")[:2000]
        return f"{title}:\n\n{content}" if content else f"{title} (bos)"

    if tool_name in ("update_note", "delete_note"):
        return result.get("message", "Tamam.")

    # --- Plans ---
    if tool_name == "create_plan":
        return f"Plan olusturuldu: {result.get('name', '')} ({result.get('task_count', 0)} gorev)"

    if tool_name == "list_plans":
        plans = result.get("plans", [])
        if not plans:
            return "Aktif plan yok."
        out = f"{len(plans)} plan:\n"
        for p in plans[:5]:
            out += f"  {p.get('name', '?')} - {p.get('status', '?')}\n"
        return out.strip()

    # --- Advanced Research ---
    if tool_name in ("advanced_research", "deep_research"):
        topic = result.get("topic", "")
        summary = result.get("summary", "")
        key_insights = result.get("key_insights", [])
        stats = result.get("statistics", {})

        out = f"Arastirma sonucu: {topic}\n\n"
        if stats:
            out += f"Kaynak: {stats.get('total_sources', 0)}, "
            out += f"Bulgu: {stats.get('total_findings', 0)}\n\n"
        if summary:
            out += f"{summary[:1500]}\n"
        if key_insights:
            out += "\nTemel icgoruler:\n"
            for i, ins in enumerate(key_insights[:5], 1):
                out += f"  {i}. {ins[:200]}\n"
        return out.strip()

    if tool_name == "create_research_report":
        return f"Rapor olusturuldu: {result.get('filename', '')}"

    if tool_name == "generate_research_document":
        return f"Belge olusturuldu: {result.get('filename', '')} ({result.get('format', '')})"

    # --- Document Editing ---
    if tool_name == "edit_text_file":
        changes = result.get("changes", [])
        if not result.get("modified"):
            return "Degisiklik yapilmadi."
        return f"{result.get('filename', 'Dosya')} duzenlendi ({len(changes)} islem)."

    if tool_name == "batch_edit_text":
        return f"{result.get('modified_count', 0)} dosya duzenlendi."

    if tool_name in ("edit_word_document",):
        return f"{result.get('filename', 'Word')} duzenlendi."

    # --- Document Merging ---
    if tool_name == "merge_pdfs":
        return f"PDF birlestirildi: {result.get('filename', '')} ({result.get('total_pages', 0)} sayfa)"

    if tool_name in ("merge_documents", "merge_word_documents"):
        return f"Belgeler birlestirildi: {result.get('filename', '')}"

    # --- Source Evaluation ---
    if tool_name == "evaluate_source":
        score = result.get("reliability_score", 0)
        return f"Kaynak guvenilirligi: %{score*100:.0f} ({result.get('reliability_level', '')})"

    if tool_name == "quick_research":
        return f"Hizli arastirma tamamlandi: {result.get('topic', '')}"

    if tool_name == "synthesize_findings":
        synthesis = result.get("synthesis", "")
        return f"Sentez:\n\n{synthesis[:1500]}"

    # --- Generic fallback ---
    msg = result.get("message", "")
    return msg if msg else "Tamamlandi."


def _format_size(b: int) -> str:
    if b < 1024:
        return f"{b}B"
    if b < 1024**2:
        return f"{b/1024:.1f}KB"
    if b < 1024**3:
        return f"{b/1024**2:.1f}MB"
    return f"{b/1024**3:.1f}GB"


def acknowledge_command(command_type: str) -> str:
    acks = {
        "screenshot": "Ekran goruntusu aliyorum.",
        "file": "Dosya islemi yapiyorum.",
        "research": "Arastirma baslatiyorum.",
        "default": "Anliyorum.",
    }
    return acks.get(command_type, acks["default"])
