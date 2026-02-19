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
        m = re.search(r'hatırlat[:\s]+(.+)|beni\s+(.+?)\s+için\s+uyar', text, re.IGNORECASE)
        content = ""
        if m:
            content = (m.group(1) or m.group(2) or "").strip()
        time_m = re.search(r'(\d{1,2}:\d{2}|\d+\s*(?:dakika|saat|gün|dk|sn))', text)
        time_val = time_m.group() if time_m else ""
        return {"action": "create_reminder",
                "params": {"message": content, "time": time_val},
                "reply": f"Hatırlatıcı oluşturuluyor{': ' + content if content else ''}..."}

    # ── Music ─────────────────────────────────────────────────────────────────
    def _parse_music(self, text: str, text_norm: str, original: str) -> dict | None:
        if not any(t in text for t in ["müzik", "muzik", "şarkı", "sarki", "çal", "cal",
                                        "music", "play", "spotify", "apple music"]):
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
        triggers = ["python kodu", "kod çalıştır", "kodu çalıştır", "script çalıştır",
                    "run code", "execute code", "python script"]
        if not any(t in text for t in triggers):
            return None
        m = re.search(r'```python\n(.+?)```|kod[:\s]+(.+)', text, re.DOTALL | re.IGNORECASE)
        code = ""
        if m:
            code = (m.group(1) or m.group(2) or "").strip()
        return {"action": "run_python", "params": {"code": code}, "reply": "Python kodu çalıştırılıyor..."}

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
    def _parse_help(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["yardım", "yardim", "help", "ne yapabilirsin", "neler yapabilirsin",
                    "komutlar", "nasıl kullanırım", "özellikler", "kabiliyetler"]
        if not any(t in text for t in triggers):
            return None
        return {"action": "show_help", "params": {}, "reply": "Yardım bilgileri gösteriliyor..."}

    # ── Unknown / Chat ────────────────────────────────────────────────────────
    def _parse_chat_fallback(self, text: str, text_norm: str, original: str) -> dict:
        return {"action": "chat", "params": {"message": original},
                "reply": "Mesajınız işleniyor..."}
