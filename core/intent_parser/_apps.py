"""
_apps.py — Uygulama ve URL parser'ları
Kapsam: open_app, close_app, open_url, greeting, spotlight
"""
import re
from urllib.parse import quote_plus
from ._base import BaseParser, _RE_BROWSER_SEARCH_VERB, _RE_SEARCH_BEFORE, _RE_SEARCH_AFTER
from ._base import _RE_YOUTUBE_QUERY, _RE_YOUTUBE_FALLBACK, _RE_YOUTUBE_CLEANUP1, _RE_YOUTUBE_CLEANUP2


class AppParser(BaseParser):

    # ── Open App ──────────────────────────────────────────────────────────────
    def _parse_open_app(self, text: str, text_norm: str, original: str) -> dict | None:
        open_t = ["aç", "ac", "başlat", "çalıştır", "open", "run", "start", "launch"]
        if any(w in text for w in ["dosya", "klasör", "http", ".com", ".org"]):
            return None
        wants_research = any(k in text for k in ["araştır", "arastir", "araştırma", "arastirma", "research", "incele", "inceleme"])

        def _alias_match(raw_alias: str) -> bool:
            alias = str(raw_alias or "").strip()
            if not alias:
                return False
            alias_norm = self._normalize(alias)
            suffixes_raw = r"(?:yi|yı|yu|yü|i|ı|u|ü|ya|ye|a|e|da|de|dan|den)?"
            suffixes_norm = r"(?:yi|yu|i|u|ya|ye|a|e|da|de|dan|den)?"
            pat_raw = rf"(?<!\w){re.escape(alias)}{suffixes_raw}(?!\w)"
            pat_norm = rf"(?<!\w){re.escape(alias_norm)}{suffixes_norm}(?!\w)"
            return bool(
                re.search(pat_raw, text, re.IGNORECASE)
                or re.search(pat_norm, text_norm, re.IGNORECASE)
            )

        if any(t in text for t in open_t):
            for alias, app in self.app_aliases.items():
                if _alias_match(alias):
                    if wants_research:
                        topic = ""
                        m_topic = re.search(
                            r"(.+?)\s+hakkında\s+(?:araştır|arastir|araştırma|arastirma|research|incele)",
                            text,
                            re.IGNORECASE,
                        )
                        if m_topic:
                            topic = m_topic.group(1).strip()
                        if not topic:
                            m_topic2 = re.search(r"(?:araştır|arastir|research|incele)\s+(.+)", text, re.IGNORECASE)
                            if m_topic2:
                                topic = m_topic2.group(1).strip()
                        if not topic:
                            # Fallback: remove app-open phrase and keep the remainder.
                            topic = re.sub(
                                rf"\b{re.escape(alias)}(?:yi|yı|yu|yü|i|ı|u|ü)?\b",
                                " ",
                                text,
                                flags=re.IGNORECASE,
                            )
                        topic = re.sub(
                            rf"\b{re.escape(alias)}(?:yi|yı|yu|yü|i|ı|u|ü)?\b",
                            " ",
                            topic,
                            flags=re.IGNORECASE,
                        )
                        topic = re.sub(r"\b(aç|ac|ve|sonra|ardından|ardindan|lütfen|lutfen)\b", " ", topic, flags=re.IGNORECASE)
                        topic = re.sub(
                            r"\b(araştır|arastir|araştırma|arastirma|research|incele|inceleme)\b",
                            " ",
                            topic,
                            flags=re.IGNORECASE,
                        )
                        topic = " ".join(topic.split()).strip() or "genel konu"
                        return {
                            "action": "multi_task",
                            "tasks": [
                                {
                                    "id": "task_1",
                                    "action": "open_app",
                                    "params": {"app_name": app},
                                    "description": f"{app} açılıyor...",
                                },
                                {
                                    "id": "task_2",
                                    "action": "research",
                                    "params": {"topic": topic, "depth": "standard"},
                                    "description": f"'{topic}' hakkında araştırma yapılıyor...",
                                    "depends_on": ["task_1"],
                                },
                            ],
                            "reply": f"{app} açılıyor ve '{topic}' araştırılıyor...",
                        }
                    return {"action": "open_app", "params": {"app_name": app},
                            "reply": f"{app} açılıyor..."}
            for alias, url in self.url_aliases.items():
                if alias in text_norm:
                    return {"action": "open_url", "params": {"url": url},
                            "reply": f"{alias.capitalize()} açılıyor..."}
        return None

    # ── Close App ─────────────────────────────────────────────────────────────
    def _parse_close_app(self, text: str, text_norm: str, original: str) -> dict | None:
        if "sesi" in text or "ses" in text:
            return None
        if any(k in text for k in ["bilgisayar", "sistem", "mac", "macbook", "cihaz"]):
            return None
        close_t = ["kapat", "sonlandır", "durdur", "quit", "close", "kill"]
        if any(t in text for t in close_t):
            for alias, app in self.app_aliases.items():
                if alias in text or self._normalize(alias) in text_norm:
                    return {"action": "close_app", "params": {"app_name": app},
                            "reply": f"{app} kapatılıyor..."}
            m = re.search(r'([\w\s]+?)(?:\'?[ıiyuü]?\s*kapat|\'?[ıiyuü]?\s*sonlandır)', text)
            if m:
                app_name = m.group(1).strip()
                if len(app_name) > 1:
                    return {"action": "close_app", "params": {"app_name": app_name.title()},
                            "reply": f"{app_name.title()} kapatılıyor..."}
        return None

    # ── Open URL ──────────────────────────────────────────────────────────────
    def _parse_open_url(self, text: str, text_norm: str, original: str) -> dict | None:
        m = re.search(r'(https?://[^\s]+|www\.[^\s]+|\w+\.(com|org|net|io|ai|co|tr)[^\s]*)', text)
        if m:
            url = m.group()
            if not url.startswith("http"):
                url = "https://" + url
            return {"action": "open_url", "params": {"url": url}, "reply": "URL açılıyor..."}
        goto_t = ["aç", "git", "gir", "gitmek", "götür", "open", "go to"]
        if any(t in text for t in goto_t):
            for alias, url in self.url_aliases.items():
                if alias in text_norm or alias in text:
                    return {"action": "open_url", "params": {"url": url},
                            "reply": f"{alias.capitalize()} açılıyor..."}
        return None

    # ── Browser Search ────────────────────────────────────────────────────────
    def _parse_browser_search(self, text: str, text_norm: str, original: str) -> dict | None:
        if not _RE_BROWSER_SEARCH_VERB.search(text):
            return None
        if any(k in text.lower() for k in ["website", "web sitesi", "web sayfas", "portfolyo", "portfolio"]) and \
           any(v in text.lower() for v in ["yap", "oluştur", "olustur", "hazırla", "hazirla"]):
            return None
        lower = text.lower()
        query = None
        m = _RE_SEARCH_BEFORE.search(lower)
        if m:
            query = m.group(1).strip()
        if not query:
            m2 = _RE_SEARCH_AFTER.search(lower)
            if m2:
                query = m2.group(1).strip()

        # Fallback extraction from full command when regex capture is weak.
        if not query:
            query = lower

        # Turkish suffix normalization: "safari'den" -> "safari den"
        query = re.sub(r"([0-9a-zçğıöşü]+)'([0-9a-zçğıöşü]+)", r"\1 \2", query, flags=re.IGNORECASE)

        cleanup_tokens = {
            "safari", "safariyi", "safariden", "safaride", "safariye", "safariya",
            "chrome", "chromedan", "chromede", "krom", "kromdan", "kromda",
            "tarayici", "tarayıcı", "tarayicida", "tarayıcıda", "tarayicidan", "tarayıcıdan",
            "browser", "browsers", "webde", "internette",
            "aç", "ac", "git", "gir", "ve", "sonra", "ardından", "ardindan",
            "lütfen", "lutfen", "ara", "arat", "search", "den", "dan", "de", "da",
        }
        query = " ".join(p for p in (query or "").replace(".", " ").split() if p not in cleanup_tokens).strip(" ,.;:-")
        if len(query) < 2:
            return None

        images_mode = any(k in lower for k in ("resim", "resimleri", "görsel", "gorsel", "foto", "image", "images", "wallpaper"))
        if images_mode:
            url = f"https://www.google.com/search?tbm=isch&q={quote_plus(query)}"
        else:
            url = f"https://www.google.com/search?q={quote_plus(query)}"

        wants_safari = "safari" in text or "safari" in text_norm
        tasks = []
        if wants_safari:
            tasks.append({"id": "task_1", "action": "open_app", "params": {"app_name": "Safari"},
                          "description": "Safari'yi aç"})
        open_url_params = {"url": url}
        if wants_safari:
            open_url_params["browser"] = "Safari"
        tasks.append({"id": "task_2", "action": "open_url", "params": open_url_params,
                      "description": f"Arama: {query}",
                      "depends_on": ["task_1"] if wants_safari else []})
        if wants_safari:
            return {"action": "multi_task", "tasks": tasks, "reply": f"Safari'de '{query}' aranıyor..."}
        return {"action": "open_url", "params": open_url_params, "reply": f"Tarayıcıda '{query}' aranıyor..."}

    # ── YouTube ───────────────────────────────────────────────────────────────
    def _parse_media_play(self, text: str, text_norm: str, original: str) -> dict | None:
        import re as _re2
        # BUGFIX: "yt" substring check caused "python" to match (py-t-hon contains "yt")
        # Use word-boundary aware matching instead of substring check
        has_youtube = "youtube" in text
        has_yt = bool(_re2.search(r'\byt\b', text))
        if not has_youtube and not has_yt:
            return None
        query = None
        m = _RE_YOUTUBE_QUERY.search(text)
        if m:
            query = m.group(1).strip()
        if not query:
            m2 = _RE_YOUTUBE_FALLBACK.search(text)
            if m2:
                query = m2.group(1).strip()
        query = " ".join((query or "").split())
        query = _RE_YOUTUBE_CLEANUP1.sub("", query)
        query = _RE_YOUTUBE_CLEANUP2.sub("", query).strip()
        if query.lower() in {"youtube", "yt"}:
            query = ""
        base = "https://www.youtube.com"
        if query:
            return {"action": "open_url", "params": {"url": f"{base}/results?search_query={quote_plus(query)}"},
                    "reply": f"YouTube'da '{query}' açılıyor..."}
        return {"action": "open_url", "params": {"url": base}, "reply": "YouTube açılıyor..."}

    # ── Random Image ──────────────────────────────────────────────────────────
    def _random_image_url(self, text_lower: str) -> str | None:
        if not any(k in text_lower for k in ["rastgele", "random"]):
            return None
        if not any(k in text_lower for k in ["resim", "resmi", "foto", "fotograf", "fotoğraf",
                                               "gorsel", "görsel", "image", "pic"]):
            return None
        if any(k in text_lower for k in ["kedi", "cat"]):
            return "https://cataas.com/cat"
        if any(k in text_lower for k in ["kopek", "köpek", "dog"]):
            return "https://random.dog"
        return "https://picsum.photos/1200/800"

    def _parse_random_image(self, text: str, text_norm: str, original: str) -> dict | None:
        url = self._random_image_url(text.lower())
        if not url:
            return None
        if "safari" in text.lower():
            return {"action": "multi_task",
                    "tasks": [
                        {"id": "task_1", "action": "open_app", "params": {"app_name": "Safari"},
                         "description": "Safari'yi ac"},
                        {"id": "task_2", "action": "open_url", "params": {"url": url},
                         "description": "Rastgele gorsel ac", "depends_on": ["task_1"]}
                    ], "reply": "Rastgele gorsel aciliyor..."}
        return {"action": "open_url", "params": {"url": url}, "reply": "Rastgele gorsel aciliyor..."}

    # ── Greeting ──────────────────────────────────────────────────────────────
    def _parse_greeting(self, text: str, text_norm: str, original: str) -> dict | None:
        words = text.split()
        if len(words) > 5:
            return None
        first = words[0] if words else ""
        if first in self.greetings or text in self.greetings:
            return {"action": "chat", "params": {},
                    "reply": "Merhaba, ben Elyan. Stratejik kararlarınızda ve günlük görevlerinizde "
                             "size yardımcı olmaya hazırım. Size nasıl yardımcı olabilirim?"}
        return None

    # ── Spotlight ─────────────────────────────────────────────────────────────
    def _parse_spotlight(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["bilgisayarda ara", "sistemde ara", "spotlight",
                    "dosya bul", "bul:", "search:", "mdfind", "bilgisayarımda", "sistemde bul"]
        if not any(t in text for t in triggers):
            return None
        query = ""
        m = re.search(r'ara[:\s]+(.+)|bul[:\s]+(.+)|search[:\s]+(.+)', text, re.IGNORECASE)
        if m:
            query = (m.group(1) or m.group(2) or m.group(3) or "").strip()
        if not query:
            for t in triggers:
                if t in text:
                    parts = text.split(t)
                    if len(parts) > 1 and parts[1].strip():
                        query = parts[1].strip()
                        break
        file_type = None
        type_kw = {"pdf": ["pdf"], "word": ["word", "docx"], "excel": ["excel", "xlsx"],
                   "image": ["resim", "foto", "jpg", "png"], "video": ["video", "mp4"],
                   "audio": ["müzik", "mp3"]}
        for ftype, kws in type_kw.items():
            if any(kw in text for kw in kws):
                file_type = ftype
                for kw in kws:
                    query = query.replace(kw, "").strip()
                break
        if query:
            return {"action": "spotlight_search", "params": {"query": query, "file_type": file_type},
                    "reply": f"'{query}' aranıyor..."}
        return None

    # ── Terminal Command ──────────────────────────────────────────────────────
    def _parse_terminal_command(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["terminal", "komut", "çalıştır", "run", "execute", "bash", "shell"]
        patterns = [
            r"(?:terminal|komut|çalıştır|run|execute)\s+(?:komutunu?|bunu|şunu)\s*[:\-]?\s*(.+)",
            r"(.+?)\s+(?:komutunu?|çalıştır)",
            r"run\s+(.+)", r"execute\s+(.+)",
        ]
        if not any(t in text for t in triggers):
            return None
        command = None
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                command = m.group(1).strip()
                break
        if not command:
            words = text.split()
            for i, w in enumerate(words):
                if w in triggers and i + 1 < len(words):
                    command = " ".join(words[i+1:])
                    break
        if command:
            safe = ["date", "uptime", "whoami", "pwd", "ls", "df", "du", "ping", "python", "node", "git"]
            return {"action": "run_safe_command", "params": {"command": command},
                    "reply": f"Terminal komutu çalıştırılıyor: {command}"}
        return None
