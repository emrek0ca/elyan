"""
_media.py — Medya ve iletişim parser'ları
Kapsam: email, calendar, reminder, music, video, code_run
"""
import re
from ._base import BaseParser


class MediaParser(BaseParser):

    # ── Email ─────────────────────────────────────────────────────────────────
    def _parse_email(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["mail gönder", "e-posta gönder", "eposta gönder", "mail at",
                    "email gönder", "mail yaz", "e-posta yaz", "mail oluştur"]
        if not any(t in text for t in triggers):
            return None
        to = ""
        m = re.search(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', text)
        if m:
            to = m.group()
        subject = ""
        sm = re.search(r'konu[:\s]+(.+?)(?:\s+içerik|\s+mesaj|$)', text, re.IGNORECASE)
        if sm:
            subject = sm.group(1).strip()
        body = ""
        bm = re.search(r'içerik[:\s]+(.+)|mesaj[:\s]+(.+)', text, re.IGNORECASE)
        if bm:
            body = (bm.group(1) or bm.group(2) or "").strip()
        return {"action": "send_email",
                "params": {"to": to, "subject": subject, "body": body},
                "reply": f"E-posta hazırlanıyor{' → ' + to if to else ''}..."}

    # ── Calendar ──────────────────────────────────────────────────────────────
    def _parse_calendar(self, text: str, text_norm: str, original: str) -> dict | None:
        if not any(t in text for t in ["takvim", "etkinlik", "toplantı", "randevu",
                                        "calendar", "event", "meeting"]):
            return None
        if any(v in text for v in ["ekle", "oluştur", "olustur", "koy", "yaz", "planla", "ayarla"]):
            m = re.search(r'(.+?)\s+(?:etkinliği|toplantısı|randevusu|için)', text)
            title = m.group(1).strip() if m else "Etkinlik"
            date_m = re.search(r'(\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?|\w+\s+\d{1,2})', text)
            date = date_m.group() if date_m else "bugün"
            time_m = re.search(r'(\d{1,2}:\d{2}|\d{1,2}\s*(?:de|da|te|ta))', text)
            time_val = time_m.group() if time_m else ""
            return {"action": "create_calendar_event",
                    "params": {"title": title, "date": date, "time": time_val},
                    "reply": f"'{title}' etkinliği ekleniyor..."}
        return {"action": "get_calendar", "params": {}, "reply": "Takvim etkinlikleri getiriliyor..."}

    # ── Reminder ──────────────────────────────────────────────────────────────
    def _parse_reminder(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["hatırlat", "hatirlatici", "hatırlatıcı", "reminder", "alarm", "uyar"]
        if not any(t in text for t in triggers):
            return None
        content = ""
        patterns = [
            r'saat\s*\d{1,2}(?::\d{2})?\s*(?:de|da|te|ta)?\s+(.+?)(?:\s+hatırlat|\s+uyar|$)',
            r'hatırlat[:\s]+(.+)',
            r'beni\s+(.+?)\s+için\s+uyar',
            r'(.+?)\s+hatırlat$',
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                content = (m.group(1) or "").strip()
                if content:
                    break

        content = re.sub(r'\b(bana|beni|lütfen|lutfen)\b', ' ', content, flags=re.IGNORECASE)
        content = re.sub(r'\s+', ' ', content).strip(" .,:;-")

        time_val = ""
        tm = re.search(r'\b(\d{1,2})[:.](\d{2})\b', text, re.IGNORECASE)
        if tm:
            time_val = f"{int(tm.group(1)):02d}:{int(tm.group(2)):02d}"
        else:
            tm2 = re.search(r'saat\s*(\d{1,2})\s*(?:de|da|te|ta)?', text, re.IGNORECASE)
            if tm2:
                time_val = f"{int(tm2.group(1)):02d}:00"

        title = content or "Hatırlatma"
        params = {"title": title}
        if time_val:
            params["due_time"] = time_val

        return {"action": "create_reminder",
                "params": params,
                "reply": f"Hatırlatıcı oluşturuluyor{': ' + title if title else ''}..."}

    # ── Music ─────────────────────────────────────────────────────────────────
    def _parse_music(self, text: str, text_norm: str, original: str) -> dict | None:
        import re as _re_music
        # BUGFIX: "çal" substring match was catching "çalıştır" (run/execute)
        # Use word-boundary aware check for "çal" and "cal"
        has_music_kw = any(t in text for t in ["müzik", "muzik", "şarkı", "sarki",
                                                 "music", "spotify", "apple music"])
        has_play_kw = any(t in text for t in ["play"])
        # Word-boundary check for "çal/cal" to avoid matching "çalıştır/calıştır"
        has_cal = bool(_re_music.search(r'\bçal\b|\bcal\b', text))
        if not (has_music_kw or has_play_kw or has_cal):
            return None
        # Extra guard: if code/run context is present, don't match as music
        code_ctx = any(k in text for k in ["python", "kod", "script", "çalıştır", "calistir",
                                             "execute", "run", "program", "hesap"])
        if code_ctx and not has_music_kw:
            return None
        if "youtube" in text:
            return None
        if any(t in text for t in ["durdur", "dur", "pause", "stop"]):
            return {"action": "pause_music", "params": {}, "reply": "Müzik duraklatılıyor..."}
        if any(t in text for t in ["devam", "resume", "continue"]):
            return {"action": "resume_music", "params": {}, "reply": "Müzik devam ettiriliyor..."}
        if any(t in text for t in ["sonraki", "next", "ileri"]):
            return {"action": "next_track", "params": {}, "reply": "Sonraki parçaya geçiliyor..."}
        if any(t in text for t in ["önceki", "previous", "geri"]):
            return {"action": "prev_track", "params": {}, "reply": "Önceki parçaya geçiliyor..."}
        m = re.search(r'(?:çal|cal|play|aç)\s+(.+)|(.+?)\s+(?:çal|cal|play)', text, re.IGNORECASE)
        song = ""
        if m:
            song = (m.group(1) or m.group(2) or "").strip()
        return {"action": "play_music", "params": {"query": song},
                "reply": f"{'Müzik çalınıyor...' if not song else f'{song} çalınıyor...'}"}

    # ── Code Run ──────────────────────────────────────────────────────────────
    def _parse_code_run(self, text: str, text_norm: str, original: str) -> dict | None:
        exec_triggers = [
            "kod çalıştır", "kodu çalıştır", "kodu calistir", "kod calistir",
            "script çalıştır", "script calistir",
            "run code", "execute code",
            "python çalıştır", "python calistir",
            "python ile çalıştır", "python ile calistir",
        ]
        # "python kodu" tek başına tetikleyici OLMASIN; sadece exec_trigger ile birlikte geçerliyse veya
        # açıkça kod bloğu (``` ...) varsa çalıştır
        has_code_block = bool(re.search(r'```', text))
        has_exec = any(t in text for t in exec_triggers) or any(t in text_norm for t in exec_triggers)
        if not has_exec and not has_code_block:
            return None
        # "yaz" var ama "çalıştır" yoksa → code_write'a bırak
        has_write_only = any(t in text for t in ["yaz", "yazdir", "yazar misin", "yazabilir misin"]) and not has_exec
        if has_write_only:
            return None
        m = re.search(r'```python\n(.+?)```|kod[:\s]+(.+)', text, re.DOTALL | re.IGNORECASE)
        code = ""
        if m:
            code = (m.group(1) or m.group(2) or "").strip()
        return {"action": "run_code", "params": {"code": code, "language": "python"},
                "reply": "Python kodu çalıştırılıyor..."}

    # ── Code Write ────────────────────────────────────────────────────────────
    def _parse_code_write(self, text: str, text_norm: str, original: str) -> dict | None:
        """'Bana X kodu yaz' tarzı istekleri yakala → LLM ile kod üretimi."""
        # Triggers: code writing without execution
        write_triggers = [
            "kodu yaz", "kod yaz", "python yaz", "python kodu yaz",
            "javascript yaz", "js yaz", "html yaz", "css yaz",
            "fonksiyon yaz", "class yaz", "algoritma yaz", "script yaz",
            "write code", "write a", "kod oluştur",
        ]
        # Execution triggers — if both write AND execute, skip here (handled by multi_task)
        exec_triggers = ["çalıştır", "calistir", "execute", "run", "koştur", "kostir"]

        has_write = any(t in text for t in write_triggers)
        has_exec = any(t in text for t in exec_triggers)

        if not has_write:
            return None
        if has_exec:
            # "yaz ve çalıştır" → multi_task will handle it
            return None

        # Extract what kind of code
        topic = ""
        m = re.search(r'(?:bana\s+|bir\s+)?(.+?)\s+(?:kodu?\s*)?yaz|write\s+(.+?)\s+code', text, re.IGNORECASE)
        if m:
            topic = (m.group(1) or m.group(2) or "").strip()
        topic = re.sub(r'\b(bana|bir|lütfen|lutfen)\b', ' ', topic, flags=re.IGNORECASE).strip()
        if not topic or len(topic) < 2:
            topic = original

        return {
            "action": "chat",
            "params": {"message": original, "_code_request": True, "topic": topic},
            "reply": f"'{topic}' için kod yazılıyor...",
            "_route_to_llm": True,
        }

    # ── Visual Generation ─────────────────────────────────────────────────────
    def _parse_visual_generation(self, text: str, text_norm: str, original: str) -> dict | None:
        create_triggers = [
            "görsel oluştur", "gorsel olustur", "görsel üret", "gorsel uret",
            "logo oluştur", "logo olustur", "logo tasarla", "afiş tasarla",
            "poster tasarla", "image generate", "generate image", "create image",
        ]
        if not any(t in text for t in create_triggers):
            return None

        cleaned = re.sub(
            r"\b(görsel|gorsel|image|logo|afiş|afis|poster|oluştur|olustur|üret|uret|tasarla|create|generate)\b",
            " ",
            original,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,:;-")
        project_name = cleaned[:64] if cleaned else "elyan-visual"

        return {
            "action": "create_visual_asset_pack",
            "params": {
                "project_name": project_name,
                "brief": original,
                "output_dir": "~/Desktop",
            },
            "reply": "Görsel üretim paketi hazırlanıyor...",
        }

    # ── Help ──────────────────────────────────────────────────────────────────
    def _parse_scheduled_tasks(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = [
            "planlanmış görevler", "planlanmis gorevler", "planlı görevler",
            "planli gorevler", "zamanlanmış görevler", "zamanlanmis gorevler",
            "aktif planlar", "planları göster", "planlari goster",
        ]
        if any(t in text for t in triggers):
            return {"action": "list_plans", "params": {}, "reply": "Planlanmış görevler listeleniyor..."}
        return None

    def _parse_help(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["yardım", "yardim", "help", "ne yapabilirsin", "neler yapabilirsin",
                    "komutlar", "nasıl kullanırım", "özellikler", "kabiliyetler"]
        if not any(t in text for t in triggers):
            return None
        return {"action": "show_help", "params": {}, "reply": "Yardım bilgileri gösteriliyor..."}

    # ── Dropped File (Dashboard) ─────────────────────────────────────────────
    def _parse_dropped_file(self, text: str, text_norm: str, original: str) -> dict | None:
        if not text.startswith("dropped file:"):
            return None
        
        # Extract path: dropped file: /path/to/file. extension
        match = re.search(r'dropped file:\s*([^\s\.]+[\.][a-zA-Z0-9]{1,8})', text, re.IGNORECASE)
        if not match:
            # Fallback for paths with spaces if they are absolute
            match = re.search(r'dropped file:\s*(/.+?\.[a-zA-Z0-9]{1,8})', text, re.IGNORECASE)
            
        if not match:
            return None
            
        file_path = match.group(1).strip()
        ext = file_path.split('.')[-1].lower()
        
        image_exts = {'jpg', 'jpeg', 'png', 'webp', 'gif', 'bmp'}
        doc_exts = {'pdf', 'doc', 'docx', 'txt', 'csv', 'xlsx', 'xls'}
        audio_exts = {'mp3', 'wav', 'ogg', 'm4a', 'flac', 'aac'}
        
        if ext in image_exts:
            return {
                "action": "analyze_image",
                "params": {"image_path": file_path, "prompt": "Bu görselde ne görüyorsun? Detaylı açıkla."},
                "reply": f"Görsel analiz ediliyor: {re.sub(r'.+/', '', file_path)}..."
            }
        elif ext in audio_exts:
            return {
                "action": "transcribe_audio_file",
                "params": {"audio_file": file_path, "language": "tr"},
                "reply": f"Ses dosyası deşifre ediliyor: {re.sub(r'.+/', '', file_path)}..."
            }
        elif ext in doc_exts:
            return {
                "action": "read_file",
                "params": {"path": file_path},
                "reply": f"Dosya okunuyor: {re.sub(r'.+/', '', file_path)}..."
            }
            
        return None

    # ── Unknown / Chat ────────────────────────────────────────────────────────
    def _parse_chat_fallback(self, text: str, text_norm: str, original: str) -> dict:
        return {"action": "chat", "params": {"message": original},
                "reply": "Mesajınız işleniyor..."}
