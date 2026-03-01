"""
_system.py — Sistem kontrol parser'ları
Kapsam: screenshot, volume, brightness, dark mode, wifi, power, clipboard, notification
"""
import re
from ._base import BaseParser, _RE_SCREENSHOT_NAME


class SystemParser(BaseParser):

    # ── Screenshot ──────────────────────────────────────────────────────────
    def _parse_screenshot(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = [
            "ekran görüntüsü", "screenshot", "ekran resmi",
            "ekranı kaydet", "ekranı yakala", "ekran al", "görüntü al",
            "ekranın resmini", "ekran yakala", "screen capture",
            "ss al", " ss ", "ss?", " ss,",
            "ss gönder", "ss gonder", "ss yolla", "ss at",
            "ekran görüntüsü gönder", "ekran goruntusu gonder",
        ]
        matched = False
        for trigger in triggers:
            if trigger in text:
                if trigger.strip() == "ss" and ("ssh" in text or "@" in text):
                    continue
                matched = True
                break
        if not matched and "ekran goruntusu" not in text_norm and "ekran resmi" not in text_norm:
            return None
        filename = None
        m = _RE_SCREENSHOT_NAME.search(text)
        if m:
            filename = m.group(1) or m.group(2) or m.group(3)
        return {"action": "take_screenshot", "params": {"filename": filename}, "reply": "Ekran görüntüsü alınıyor..."}

    def _parse_status_snapshot(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["durum nedir", "durum ne", "ne yapiyorsun", "ne yapıyorsun",
                    "su an ne yapiyorsun", "şu an ne yapıyorsun",
                    "durumu goster", "durumu göster", "ekranda ne var"]
        if not any(t in text for t in triggers) and \
           not any(t in text_norm for t in ["durum nedir", "ne yapiyorsun", "durumu goster"]):
            return None
        exclusions = ["wifi", "bluetooth", "hava durumu", "plan durumu", "araştırma durumu",
                      "sistem durumu", "pil", "batarya", "status", "/status"]
        if any(e in text for e in exclusions):
            return None
        return {"action": "take_screenshot", "params": {"filename": "elyan_durum"},
                "reply": "Anlik durumu gostermek icin ekran goruntusu aliyorum..."}

    # ── Volume ───────────────────────────────────────────────────────────────
    def _parse_volume(self, text: str, text_norm: str, original: str) -> dict | None:
        if any(t in text for t in ["sesi kapat", "sessize al", "sessiz yap", "mute", "sesi kıs", "ses kapat"]):
            return {"action": "set_volume", "params": {"mute": True}, "reply": "Ses kapatılıyor..."}
        if any(t in text for t in ["sesi aç", "sessizden çık", "unmute", "ses aç"]):
            return {"action": "set_volume", "params": {"mute": False}, "reply": "Ses açılıyor..."}
        if any(t in text for t in ["ses", "volume", "ses seviyesi", "sesi"]):
            _word_nums = {
                "sıfır": 0, "bir": 1, "iki": 2, "üç": 3, "dört": 4, "bes": 5, "beş": 5,
                "alti": 6, "altı": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10,
                "yirmi": 20, "otuz": 30, "kirk": 40, "kırk": 40, "elli": 50,
                "altmis": 60, "altmış": 60, "yetmis": 70, "yetmiş": 70,
                "seksen": 80, "doksan": 90, "yuz": 100, "yüz": 100,
            }
            m = re.search(r'%\s*(\d+)|(\d+)\s*%|yüzde\s*(\d+)|yuzde\s*(\d+)|(\d+)\s*yap', text)
            if m:
                level = int(next(g for g in m.groups() if g is not None))
                return {"action": "set_volume", "params": {"level": min(100, max(0, level))},
                        "reply": f"Ses seviyesi %{level} yapılıyor..."}
            # Sözcüksel sayı: "yüzde elli" → 50
            word_m = re.search(r'yüzde\s+(\w+)|yuzde\s+(\w+)', text)
            if word_m:
                word = (word_m.group(1) or word_m.group(2) or "").lower()
                if word in _word_nums:
                    level = _word_nums[word]
                    return {"action": "set_volume", "params": {"level": level},
                            "reply": f"Ses seviyesi %{level} yapılıyor..."}
            if any(w in text for w in ["arttır", "artır", "yükselt", "aç"]):
                return {"action": "set_volume", "params": {"level": 70}, "reply": "Ses yükseltiliyor..."}
            if any(w in text for w in ["azalt", "düşür", "kıs"]):
                return {"action": "set_volume", "params": {"level": 30}, "reply": "Ses kısılıyor..."}
        return None

    # ── Brightness ───────────────────────────────────────────────────────────
    def _parse_brightness(self, text: str, text_norm: str, original: str) -> dict | None:
        if "parlakl" not in text_norm and "brightness" not in text_norm:
            return None
        if "kapat" in text_norm:
            return {"action": "set_brightness", "params": {"level": 10}, "reply": "Parlaklık düşürülüyor..."}
        if any(w in text_norm for w in [" ac", "artir", "yukselt"]):
            return {"action": "set_brightness", "params": {"level": 75}, "reply": "Parlaklık artırılıyor..."}
        if any(w in text_norm for w in ["azalt", "dusur", " kis"]):
            return {"action": "set_brightness", "params": {"level": 30}, "reply": "Parlaklık azaltılıyor..."}
        m = re.search(r'%\s*(\d+)|(\d+)\s*%|yuzde\s*(\d+)|(\d+)\s*yap', text_norm)
        if m:
            level = int(m.group(1) or m.group(2) or m.group(3) or m.group(4))
            return {"action": "set_brightness", "params": {"level": min(100, max(0, level))},
                    "reply": f"Parlaklık %{level} yapılıyor..."}
        return {"action": "get_brightness", "params": {}, "reply": "Parlaklık okunuyor..."}

    # ── Dark Mode ─────────────────────────────────────────────────────────────
    def _parse_dark_mode(self, text: str, text_norm: str, original: str) -> dict | None:
        dark = ["karanlık mod", "karanlik mod", "dark mode", "gece modu", "karanlık tema", "dark tema"]
        light = ["aydınlık mod", "aydinlik mod", "light mode", "gündüz modu", "açık tema", "acik tema"]
        if any(t in text for t in dark) or "karanlik mod" in text_norm:
            return {"action": "toggle_dark_mode", "params": {}, "reply": "Karanlık mod değiştiriliyor..."}
        if any(t in text for t in light):
            return {"action": "toggle_dark_mode", "params": {}, "reply": "Aydınlık moda geçiliyor..."}
        return None

    # ── WiFi ──────────────────────────────────────────────────────────────────
    def _parse_wifi(self, text: str, text_norm: str, original: str) -> dict | None:
        status_t = ["wifi durumu", "wifi durum", "wifi ne durumda", "wifi bagli mi",
                    "wifi bağlı mı", "internet durumu", "wifi status"]
        if any(t in text for t in status_t) or "wifi bagli" in text_norm:
            return {"action": "wifi_status", "params": {}, "reply": "WiFi durumu kontrol ediliyor..."}
        off_t = ["wifi kapat", "wifi'yı kapat", "wifi'yi kapat", "interneti kapat", "wifi off"]
        on_t  = ["wifi aç", "wifi'yı aç", "wifi'yi aç", "interneti aç", "wifi on"]
        if any(t in text for t in off_t) or "wifi kapat" in text_norm:
            return {"action": "wifi_toggle", "params": {"enable": False}, "reply": "WiFi kapatılıyor..."}
        if any(t in text for t in on_t) or "wifi ac" in text_norm:
            return {"action": "wifi_toggle", "params": {"enable": True}, "reply": "WiFi açılıyor..."}
        return None

    # ── Power ─────────────────────────────────────────────────────────────────
    def _parse_power_control(self, text: str, text_norm: str, original: str) -> dict | None:
        if any(k in text for k in ["ekranı kilitle", "ekrani kilitle", "lock screen"]):
            return {"action": "lock_screen", "params": {}, "reply": "Ekran kilitleniyor..."}
        # Restart/reboot recognised regardless of subject word
        if any(k in text for k in ["yeniden başlat", "yeniden baslat", "restart", "reboot"]):
            return {"action": "restart_system", "params": {}, "reply": "Sistem yeniden başlatılıyor..."}
        subjects = ["bilgisayar", "sistem", "mac", "macbook", "cihaz", "computer", "laptop"]
        if not any(s in text for s in subjects):
            return None
        if any(k in text for k in ["uykuya al", "uyku modu", "sleep"]):
            return {"action": "sleep_system", "params": {}, "reply": "Sistem uyku moduna alınıyor..."}
        if any(k in text for k in ["kilitle", "lock"]):
            return {"action": "lock_screen", "params": {}, "reply": "Ekran kilitleniyor..."}
        if any(k in text for k in ["kapat", "shut down", "shutdown", "power off"]):
            return {"action": "shutdown_system", "params": {}, "reply": "Sistem kapatılıyor..."}
        return None

    # ── Clipboard ─────────────────────────────────────────────────────────────
    def _parse_clipboard(self, text: str, text_norm: str, original: str) -> dict | None:
        read_t = ["panoda ne var", "panodaki", "clipboard", "panoyu oku",
                  "pano içeriği", "kopyalanan", "panoda ne", "pano göster"]
        if any(t in text for t in read_t):
            return {"action": "read_clipboard", "params": {}, "reply": "Pano içeriği okunuyor..."}
        write_t = ["panoya yaz", "panoya kopyala", "kopyala:", "bunu kopyala",
                   "şunu kopyala", "metni kopyala", "clipboard'a"]
        if any(t in text for t in write_t):
            m = re.search(r'kopyala[:\s]+(.+)|yaz[:\s]+(.+)', text, re.IGNORECASE)
            if m:
                content = (m.group(1) or m.group(2)).strip()
                return {"action": "write_clipboard", "params": {"text": content},
                        "reply": "Metin panoya kopyalanıyor..."}
            # "bunu kopyala" gibi içeriksiz cümlelerde agent son çıktıyı doldurur.
            return {"action": "write_clipboard", "params": {"text": ""},
                    "reply": "Son yanıt panoya kopyalanıyor..."}
        return None

    # ── Notification ──────────────────────────────────────────────────────────
    def _parse_notification(self, text: str, text_norm: str, original: str) -> dict | None:
        if not any(t in text for t in ["bildirim", "bildir", "notification", "hatırlat", "uyar", "notify"]):
            return None
        # Zamanlı hatırlatma cümlelerini media/reminder parser'a bırak.
        if "hatırlat" in text and any(k in text for k in ["saat", "dakika", "yarın", "bugün", "aksam", "akşam"]):
            return None
        m = re.search(r'bildirim[:\s]+(.+)|bildir[:\s]+(.+)|gönder[:\s]+(.+)|hatırlat[:\s]+(.+)',
                      text, re.IGNORECASE)
        if m:
            content = next((g for g in m.groups() if g), "").strip()
            return {"action": "send_notification",
                    "params": {"title": "Bot Bildirimi", "message": content},
                    "reply": "Bildirim gönderiliyor..."}
        tail = re.search(r'(.+?)\s+hatırlat$', text, re.IGNORECASE)
        if tail and tail.group(1).strip():
            content = tail.group(1).strip()
            return {"action": "send_notification",
                    "params": {"title": "Bot Bildirimi", "message": content},
                    "reply": "Bildirim gönderiliyor..."}
        return {"action": "send_notification",
                "params": {"title": "Bot Bildirimi", "message": "Bildirim"},
                "reply": "Bildirim gönderiliyor..."}

    # ── System Info ───────────────────────────────────────────────────────────
    def _parse_system_info(self, text: str, text_norm: str, original: str) -> dict | None:
        norm = text_norm or self._normalize(text)
        battery_patterns = [
            r"\bpil\w*\b",
            r"\bbatarya\w*\b",
            r"\bsarj\w*\b",
            r"\bşarj\w*\b",
            r"\bbattery\w*\b",
            r"\bcharge\w*\b",
            r"\bcharging\w*\b",
        ]
        if any(re.search(pat, norm, re.IGNORECASE) for pat in battery_patterns):
            if "dosya" in norm or "klasor" in norm:
                return None
            return {
                "action": "get_battery_status",
                "params": {},
                "reply": "Pil durumu kontrol ediliyor...",
            }

        trigger_patterns = [
            r"\bsistem\b",
            r"\bcpu\b",
            r"\bram\b",
            r"\bbellek\b",
            r"\bdisk\b",
            r"\bpil\b",
            r"\bbatarya\b",
            r"\bislemci\b",
            r"\bhafiza\b",
            r"\bdepolama\b",
            r"\bsystem\s+info\b",
            r"\bperformans\b",
        ]
        if any(re.search(pat, norm, re.IGNORECASE) for pat in trigger_patterns):
            if "dosya" in norm or "klasor" in norm:
                return None
            return {"action": "get_system_info", "params": {}, "reply": "Sistem bilgileri getiriliyor..."}
        return None

    # ── Process Control ───────────────────────────────────────────────────────
    def _parse_process_control(self, text: str, text_norm: str, original: str) -> dict | None:
        if "hangi" in text and "uygulamalar" in text and "çalışıyor" in text:
            return {"action": "get_running_apps", "params": {}, "reply": "Çalışan uygulamalar listeleniyor..."}
        list_t = ["process", "çalışan", "uygulamalar", "memory", "cpu"]
        query_w = ["kaç", "neler", "hangileri", "listele", "göster", "hangi", "what", "which"]
        if any(t in text for t in list_t) and any(w in text for w in query_w):
            return {"action": "get_running_apps", "params": {}, "reply": "Çalışan uygulamalar listeleniyor..."}
        kill_t = ["sonlandır", "terminate", "kill", "exit", "quit"]
        if any(t in text for t in kill_t):
            for alias, app in [("chrome", "Chrome"), ("safari", "Safari"), ("python", "Python")]:
                if alias in text:
                    return {"action": "kill_process", "params": {"process_name": alias},
                            "reply": f"{app} process'i sonlandırılıyor..."}
        return None

    # ── Weather ───────────────────────────────────────────────────────────────
    def _parse_weather(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["hava durumu", "hava nasıl", "sıcaklık", "sicaklik", "hava kac derece",
                    "hava kaç derece", "gökyüzü", "goksuzu", "yağmur yağacak mı", "weather",
                    "bugün hava", "yarın hava", "hava tahmini"]
        if not (any(t in text for t in triggers) or "hava nasil" in text_norm):
            return None
        # Şehir adı çıkarımı — soru sözcüklerini ve hava kelimelerini dışla
        city = ""
        _stop_words = {"hava", "durumu", "nasıl", "nasil", "kaç", "kac", "derece", "bugün",
                       "bugun", "yarın", "yarin", "weather", "tahmini", "için", "icin", "sicaklik", "sıcaklık"}
        import re as _re_w
        m = _re_w.search(r"([A-ZÇĞİÖŞÜa-zçğışöşü]{2,}(?:\s+[A-ZÇĞİÖŞÜa-zçğışöşü]{2,})?)\s+(?:hava|sıcaklık|sicaklik|weather)\b", original, _re_w.IGNORECASE)
        if m:
            candidate = m.group(1).strip().lower()
            if candidate not in _stop_words and len(candidate) > 2:
                city = m.group(1).strip().title()
        if not city:
            m2 = _re_w.search(r"\b(in|için)\s+([A-ZÇĞİÖŞÜa-zçğışöşü]{3,})", original, _re_w.IGNORECASE)
            if m2:
                candidate = m2.group(2).strip().lower()
                if candidate not in _stop_words:
                    city = m2.group(2).strip()
        params = {}
        if city:
            params["city"] = city
        city_str = f" ({city})" if city else ""
        return {"action": "get_weather", "params": params, "reply": f"Hava durumu bilgileri getiriliyor{city_str}..."}

    # ── UI Input Control (Keyboard/Mouse) ───────────────────────────────────
    def _parse_input_control(self, text: str, text_norm: str, original: str) -> dict | None:
        low = text.lower()
        norm = text_norm or self._normalize(text)

        # key combo: "cmd+l bas", "command + shift + 4"
        combo_match = re.search(
            r"\b(cmd|command|ctrl|control|alt|option|shift)\s*(?:\+\s*[a-z0-9]+)+",
            low,
            re.IGNORECASE,
        )
        if combo_match and any(k in low for k in ["bas", "press", "tuş", "tus", "kısayol", "kisayol"]):
            raw_combo = combo_match.group(0)
            raw_combo = re.sub(r"\s+", "", raw_combo)
            raw_combo = raw_combo.replace("command", "cmd").replace("control", "ctrl").replace("option", "alt")
            return {
                "action": "key_combo",
                "params": {"combo": raw_combo},
                "reply": f"Klavye kısayolu uygulanıyor: {raw_combo}",
            }

        # "enter bas", "esc bas"
        key_match = re.search(
            r"\b(enter|return|tab|space|esc|escape|left|right|up|down|delete|backspace)\b.*\b(bas|press|tuş|tus)\b",
            norm,
            re.IGNORECASE,
        )
        if key_match:
            key = str(key_match.group(1) or "").strip().lower()
            return {
                "action": "press_key",
                "params": {"key": key},
                "reply": f"{key} tuşuna basılıyor...",
            }

        # "500,300 tıkla"
        click_match = re.search(r"\b(\d{1,4})\s*[,x]\s*(\d{1,4})\b.*\b(tıkla|tikla|click)\b", low, re.IGNORECASE)
        if click_match:
            x = int(click_match.group(1))
            y = int(click_match.group(2))
            return {
                "action": "mouse_click",
                "params": {"x": x, "y": y, "button": "left"},
                "reply": f"Mouse tıklaması yapılıyor ({x},{y})...",
            }

        # "mouse'u 500,300 taşı"
        move_match = re.search(
            r"\b(mouse|imlec|cursor)\b.*\b(\d{1,4})\s*[,x]\s*(\d{1,4})\b.*\b(taşı|tasi|git|move)\b",
            low,
            re.IGNORECASE,
        )
        if move_match:
            x = int(move_match.group(2))
            y = int(move_match.group(3))
            return {
                "action": "mouse_move",
                "params": {"x": x, "y": y},
                "reply": f"Mouse imleci taşınıyor ({x},{y})...",
            }

        # "şunu yaz: ...", "yaz ..."
        write_match = re.search(r"(?:şunu yaz|sunu yaz|yaz)\s*[:\\-]?\s*(.+)", original, re.IGNORECASE)
        if write_match:
            payload = str(write_match.group(1) or "").strip()
            payload = re.sub(r"\s+(?:ve\s+|sonra\s+)?(?:enter|return)\s+bas.*$", "", payload, flags=re.IGNORECASE)
            if payload:
                press_enter = bool(re.search(r"\b(enter|return)\b", low, re.IGNORECASE))
                return {
                    "action": "type_text",
                    "params": {"text": payload, "press_enter": press_enter},
                    "reply": "Metin yazılıyor...",
                }

        return None
