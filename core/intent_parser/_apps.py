"""
_apps.py — Uygulama ve URL parser'ları
Kapsam: open_app, close_app, open_url, greeting, spotlight
"""
import re
from urllib.parse import quote_plus
from ._base import BaseParser, _RE_BROWSER_SEARCH_VERB, _RE_SEARCH_BEFORE, _RE_SEARCH_AFTER
from ._base import _RE_YOUTUBE_QUERY, _RE_YOUTUBE_FALLBACK, _RE_YOUTUBE_CLEANUP1, _RE_YOUTUBE_CLEANUP2


def _looks_like_image_search_request(text: str) -> bool:
    low = str(text or "").lower()
    if not low:
        return False
    explicit_image_markers = (
        "resim",
        "resimleri",
        "görsel",
        "gorsel",
        "foto",
        "fotoğraf",
        "fotograf",
        "image",
        "images",
        "wallpaper",
    )
    if any(marker in low for marker in explicit_image_markers):
        return True
    if any(
        marker in low
        for marker in (
            "resmi kaynak",
            "resmi site",
            "resmi kurum",
            "resmi gazete",
            "resmi belge",
            "resmi rapor",
            "official",
            ".gov",
        )
    ):
        return False
    return bool(re.search(r"\b[\wçğıöşü]+\s+resmi\b", low, re.IGNORECASE))


class AppParser(BaseParser):

    def _infer_browser_app(self, text: str, text_norm: str) -> str:
        candidates = (
            ("google chrome", "Google Chrome"),
            ("chrome", "Google Chrome"),
            ("krom", "Google Chrome"),
            ("firefox", "Firefox"),
            ("arc", "Arc"),
            ("safari", "Safari"),
            ("tarayıcı", "Safari"),
            ("tarayici", "Safari"),
            ("browser", "Safari"),
        )
        low = str(text or "").lower()
        norm = str(text_norm or "")
        for alias, app_name in candidates:
            alias_norm = self._normalize(alias)
            if alias in low or alias_norm in norm:
                return app_name
        return ""

    def _browser_request_payload(self, text: str, text_norm: str) -> str:
        norm = str(text_norm or self._normalize(str(text or "").lower()))
        payload = re.sub(r"([0-9a-zçğıöşü]+)'([0-9a-zçğıöşü]+)", r"\1 \2", norm, flags=re.IGNORECASE)
        cleanup_tokens = {
            "safari", "safariyi", "safariden", "safaride", "safariye", "safariya",
            "chrome", "chromedan", "chromede", "chromeye", "krom", "kromdan", "kromda", "kroma",
            "firefox", "firefoxda", "firefoxdan",
            "arc", "arcda", "arcdan",
            "tarayici", "tarayicida", "tarayicidan", "tarayiciya",
            "tarayıcı", "tarayıcıda", "tarayıcıdan", "tarayıcıya",
            "browser", "browserda", "browserdan", "browsera",
            "ac", "aç", "open", "git", "gir", "goto", "go", "to",
            "den", "dan", "de", "da", "ye", "ya", "a", "e",
            "ve", "sonra", "ardindan", "ardından", "ile", "icin", "için",
            "lütfen", "lutfen",
        }
        return " ".join(part for part in payload.split() if part not in cleanup_tokens).strip(" ,.;:-")

    def _parse_browser_tab_control(self, text: str, text_norm: str, original: str) -> dict | None:
        low = str(text or "").lower()
        norm = text_norm or self._normalize(low)
        if not any(token in low for token in ("sekme", "tab")):
            return None
        if not any(token in low for token in ("aç", "ac", "open", "yenı", "yeni", "new")):
            return None

        browser_aliases = {
            "safari": "Safari",
            "chrome": "Google Chrome",
            "google chrome": "Google Chrome",
            "krom": "Google Chrome",
            "firefox": "Firefox",
            "arc": "Arc",
            "tarayıcı": "Safari",
            "tarayici": "Safari",
            "browser": "Safari",
        }

        def _alias_match(raw_alias: str) -> bool:
            alias = str(raw_alias or "").strip()
            if not alias:
                return False
            alias_norm = self._normalize(alias)
            suffixes_raw = r"(?:[' ]?(?:yi|yı|yu|yü|i|ı|u|ü|ya|ye|a|e|da|de|dan|den))?"
            suffixes_norm = r"(?:[' ]?(?:yi|yu|i|u|ya|ye|a|e|da|de|dan|den))?"
            pat_raw = rf"(?<!\w){re.escape(alias)}{suffixes_raw}(?!\w)"
            pat_norm = rf"(?<!\w){re.escape(alias_norm)}{suffixes_norm}(?!\w)"
            return bool(re.search(pat_raw, low, re.IGNORECASE) or re.search(pat_norm, norm, re.IGNORECASE))

        target_browser = ""
        for alias, app in browser_aliases.items():
            if _alias_match(alias):
                target_browser = app
                break

        if not target_browser:
            return None

        return {
            "action": "multi_task",
            "tasks": [
                {
                    "id": "task_1",
                    "action": "open_app",
                    "params": {"app_name": target_browser},
                    "description": f"{target_browser} odaga aliniyor...",
                },
                {
                    "id": "task_2",
                    "action": "key_combo",
                    "params": {"combo": "cmd+t", "target_app": target_browser},
                    "description": "Yeni sekme aciliyor...",
                    "depends_on": ["task_1"],
                },
            ],
            "reply": f"{target_browser} icinde yeni sekme aciliyor...",
        }

    # ── Open App ──────────────────────────────────────────────────────────────
    def _parse_open_app(self, text: str, text_norm: str, original: str) -> dict | None:
        open_t = ["aç", "ac", "başlat", "çalıştır", "open", "run", "start", "launch"]
        focus_t = ["geç", "gec", "dön", "don", "odaklan", "göster", "goster", "switch", "focus"]
        if any(w in text for w in ["dosya", "klasör", "http", ".com", ".org"]):
            return None
        # "terminalden ssh root komutunu çalıştır" gibi komut-yürütme cümlelerini
        # open_app'e düşürmeyip terminal command parser'ına bırak.
        if (
            "terminal" in text_norm
            and re.search(r"\bkomut\w*\b", text, re.IGNORECASE)
            and re.search(r"\b(çalıştır|calistir|run|execute)\b", text, re.IGNORECASE)
        ):
            return None
        # Intent disambiguation: browser content/query requests should not degrade to plain open_app.
        browser_aliases = ("safari", "chrome", "krom", "tarayıcı", "tarayici", "browser")
        content_hints = (
            "resim", "resimleri", "resmi", "görsel", "gorsel", "foto", "fotograf", "fotoğraf",
            "image", "images", "video", "haber", "makale",
        )
        query_hints = ("ara", "arat", "search", "için", "icin", "hakkında", "hakkinda")
        if any(k in text for k in browser_aliases) and any(k in text for k in content_hints) and any(k in text for k in query_hints):
            return None
        if any(k in text for k in browser_aliases):
            payload = self._browser_request_payload(text, text_norm)
            if len(payload.split()) >= 2 or any(
                marker in payload for marker in ("wikipedia", "vikipedi", "wiki", "youtube", "yt", "google", "github", "reddit", "gmail")
            ):
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

        has_open_or_focus_verb = any(re.search(rf"\b{re.escape(t)}\b", text, re.IGNORECASE) for t in open_t) or any(
            re.search(rf"\b{re.escape(t)}\b", text, re.IGNORECASE) for t in focus_t
        )
        has_focus_verb = any(re.search(rf"\b{re.escape(t)}\b", text, re.IGNORECASE) for t in focus_t)

        if has_open_or_focus_verb:
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
                    reply = f"{app} öne alınıyor..." if has_focus_verb else f"{app} açılıyor..."
                    return {"action": "open_app", "params": {"app_name": app}, "reply": reply}
            for alias, url in self.url_aliases.items():
                if alias in text_norm:
                    return {"action": "open_url", "params": {"url": url},
                            "reply": f"{alias.capitalize()} açılıyor..."}

        # Ultra-short app invocation support: "safari a.", "chrome'a", "terminale"
        compact = " ".join(str(original or text or "").strip().split()).strip().rstrip(".,;:!?")
        if compact:
            compact_low = compact.lower()
            compact_norm = self._normalize(compact_low)
            for alias, app in self.app_aliases.items():
                alias_low = str(alias or "").strip().lower()
                alias_norm = self._normalize(alias_low)
                short_patterns = (
                    rf"^{re.escape(alias_low)}(?:[' ]?(?:a|e|ya|ye|da|de|dan|den))?$",
                    rf"^{re.escape(alias_norm)}(?:[' ]?(?:a|e|ya|ye|da|de|dan|den))?$",
                )
                if any(re.match(pattern, compact_low, re.IGNORECASE) or re.match(pattern, compact_norm, re.IGNORECASE) for pattern in short_patterns):
                    return {"action": "open_app", "params": {"app_name": app}, "reply": f"{app} açılıyor..."}
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
                    alias_norm = self._normalize(alias)
                    stripped = re.sub(rf"\b{re.escape(alias_norm)}\b", " ", text_norm, flags=re.IGNORECASE)
                    stripped = re.sub(r"\b(aç|ac|git|gir|gitmek|gotur|götür|open|go|to|ve|sonra|lütfen|lutfen)\b", " ", stripped, flags=re.IGNORECASE)
                    stripped = " ".join(stripped.split())
                    has_topic_marker = ("icin" in text_norm) or ("hakkinda" in text_norm)
                    has_content_intent = any(k in text_norm for k in ("resim", "gorsel", "foto", "image", "video", "haber", "news", "makale"))
                    browser_context = bool(self._infer_browser_app(text, text_norm))
                    remaining = self._browser_request_payload(stripped, stripped)
                    # If command carries extra topic/query words, let browser_search handle it.
                    if has_topic_marker and (len(stripped.split()) >= 1 or has_content_intent):
                        continue
                    if browser_context and remaining:
                        continue
                    return {"action": "open_url", "params": {"url": url},
                            "reply": f"{alias.capitalize()} açılıyor..."}
        return None

    # ── Browser Search ────────────────────────────────────────────────────────
    def _parse_browser_search(self, text: str, text_norm: str, original: str) -> dict | None:
        lower = text.lower()
        has_search_verb = bool(_RE_BROWSER_SEARCH_VERB.search(text))
        browser_context_tokens = (
            "safari", "safariyi", "safariden", "safaride", "safariye", "safariya",
            "chrome", "chromedan", "chromede", "krom", "kromdan", "kromda",
            "tarayici", "tarayıcı", "tarayicida", "tarayıcıda", "tarayicidan", "tarayıcıdan",
            "browser", "browsers", "webde", "internette",
        )
        browser_context = any(k in lower for k in browser_context_tokens)
        target_browser = self._infer_browser_app(text, text_norm) or "Safari"
        browser_payload = self._browser_request_payload(text, text_norm)
        images_mode = _looks_like_image_search_request(lower)
        info_mode = any(k in lower for k in ("video", "haber", "makale", "article", "news"))
        research_mode = any(k in lower for k in ("araştır", "arastir", "araştırma", "arastirma", "research", "incele", "inceleme"))
        has_open_verb = bool(re.search(r"\b(aç|ac)\b", lower))
        has_topic_marker = ("için" in lower) or ("icin" in lower) or ("hakkında" in lower) or ("hakkinda" in lower)
        site_mode = any(marker in browser_payload for marker in ("wikipedia", "vikipedi", "wiki", "youtube", "yt", "google", "github", "reddit", "gmail"))
        implicit_browser_search = browser_context and has_open_verb and (
            images_mode or info_mode or has_topic_marker or site_mode or len(browser_payload.split()) >= 2
        )

        if not has_search_verb and not implicit_browser_search:
            return None
        if any(k in lower for k in ["website", "web sitesi", "web sayfas", "portfolyo", "portfolio"]) and \
           any(v in lower for v in ["yap", "oluştur", "olustur", "hazırla", "hazirla"]):
            return None

        query = None
        if implicit_browser_search:
            for pattern in (
                r"(.+?)\s+için\s+(?:resim|resimleri|resmi|görsel|gorsel|foto|image|images)\s+(?:aç|ac)\b",
                r"(.+?)\s+icin\s+(?:resim|resimleri|resmi|gorsel|foto|image|images)\s+(?:aç|ac)\b",
                r"(.+?)\s+hakkında\s+(?:resim|resimleri|resmi|görsel|gorsel|foto|image|images)\s+(?:aç|ac)\b",
                r"(.+?)\s+hakkinda\s+(?:resim|resimleri|resmi|gorsel|foto|image|images)\s+(?:aç|ac)\b",
            ):
                m_implicit = re.search(pattern, lower, re.IGNORECASE)
                if m_implicit:
                    query = m_implicit.group(1).strip()
                    break
        m = _RE_SEARCH_BEFORE.search(lower)
        if m and not query:
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
            "lütfen", "lutfen", "ara", "arat", "search", "den", "dan", "de", "da", "için", "icin",
        }
        if images_mode:
            cleanup_tokens.update({"resim", "resimleri", "resmi", "görsel", "gorsel", "foto", "image", "images", "wallpaper"})
        query = " ".join(p for p in (query or "").replace(".", " ").split() if p not in cleanup_tokens).strip(" ,.;:-")
        if len(query) < 2:
            return None
        copy_top_result = any(
            marker in lower
            for marker in (
                "en üsttekini kopyala",
                "en usttekini kopyala",
                "ilk sonucu kopyala",
                "ilk sonucu panoya kopyala",
                "ilkini kopyala",
                "en üstteki sonucu kopyala",
                "en ustteki sonucu kopyala",
            )
        )

        if research_mode and implicit_browser_search:
            topic = re.sub(
                r"\b(araştır|arastir|araştırma|arastirma|research|incele|inceleme|yap|yapin|yapın)\b",
                " ",
                query,
                flags=re.IGNORECASE,
            )
            topic = " ".join(topic.split()).strip() or query

            wants_browser_open = browser_context
            tasks = []
            if wants_browser_open:
                tasks.append(
                    {
                        "id": "task_1",
                        "action": "open_app",
                        "params": {"app_name": target_browser},
                        "description": f"{target_browser} aç",
                    }
                )
            tasks.append(
                {
                    "id": "task_2",
                    "action": "research",
                    "params": {"topic": topic, "depth": "standard"},
                    "description": f"Arastirma: {topic}",
                    "depends_on": ["task_1"] if wants_browser_open else [],
                }
            )
            if wants_browser_open:
                return {"action": "multi_task", "tasks": tasks, "reply": f"{target_browser} açılıyor ve '{topic}' araştırılıyor..."}
            return {"action": "research", "params": {"topic": topic, "depth": "standard"}, "reply": f"'{topic}' arastiriliyor..."}

        video_mode = any(
            marker in lower
            for marker in (
                "video",
                "videosu",
                "videosunu",
                "videoları",
                "videolari",
                "izle",
                "oynat",
                "play",
            )
        )

        wiki_mode = any(marker in query for marker in ("wikipedia", "vikipedi", "wiki"))
        youtube_mode = video_mode or any(marker in query for marker in ("youtube", "yt"))

        if wiki_mode:
            wiki_query = re.sub(r"\b(wikipedia|vikipedi|wiki)\b", " ", query, flags=re.IGNORECASE)
            wiki_query = " ".join(wiki_query.split()).strip()
            if wiki_query:
                url = f"https://tr.wikipedia.org/wiki/Special:Search?search={quote_plus(wiki_query)}"
            else:
                url = "https://tr.wikipedia.org"
        elif images_mode:
            url = f"https://www.google.com/search?tbm=isch&q={quote_plus(query)}"
        elif youtube_mode:
            yt_query = re.sub(r"\b(youtube|yt)\b", " ", query, flags=re.IGNORECASE)
            yt_query = " ".join(yt_query.split()).strip()
            if yt_query:
                url = f"https://www.youtube.com/results?search_query={quote_plus(yt_query)}"
            else:
                url = "https://www.youtube.com"
        else:
            url = f"https://www.google.com/search?q={quote_plus(query)}"

        wants_browser_open = browser_context
        tasks = []
        if wants_browser_open:
            tasks.append({"id": "task_1", "action": "open_app", "params": {"app_name": target_browser},
                          "description": f"{target_browser} aç"})
        open_url_params = {"url": url}
        if wants_browser_open:
            open_url_params["browser"] = target_browser
        tasks.append({"id": "task_2", "action": "open_url", "params": open_url_params,
                      "description": f"{'Video araması' if youtube_mode else 'Arama'}: {query}",
                      "depends_on": ["task_1"] if wants_browser_open else []})
        if copy_top_result and not wiki_mode and not youtube_mode:
            search_dep = str(tasks[-1].get("id") or "task_2")
            tasks.append(
                {
                    "id": "task_3",
                    "action": "web_search",
                    "params": {"query": query, "num_results": 5},
                    "description": f"Arama sonuçlarını çıkar: {query}",
                    "depends_on": [search_dep] if search_dep else [],
                }
            )
            tasks.append(
                {
                    "id": "task_4",
                    "action": "write_clipboard",
                    "params": {"text": ""},
                    "description": "İlk sonucu panoya kopyala",
                    "depends_on": ["task_3"],
                }
            )
        if wants_browser_open:
            if copy_top_result and not wiki_mode and not youtube_mode:
                return {"action": "multi_task", "tasks": tasks, "reply": f"{target_browser}'de '{query}' aranıyor ve ilk sonuç panoya kopyalanıyor..."}
            if wiki_mode:
                return {"action": "multi_task", "tasks": tasks, "reply": f"{target_browser}'de Wikipedia için '{query}' açılıyor..."}
            if youtube_mode:
                return {"action": "multi_task", "tasks": tasks, "reply": f"{target_browser}'de '{query}' videosu açılıyor..."}
            return {"action": "multi_task", "tasks": tasks, "reply": f"{target_browser}'de '{query}' aranıyor..."}
        if copy_top_result and not wiki_mode and not youtube_mode:
            return {"action": "multi_task", "tasks": tasks, "reply": f"Tarayıcıda '{query}' aranıyor ve ilk sonuç panoya kopyalanıyor..."}
        if youtube_mode:
            return {"action": "open_url", "params": open_url_params, "reply": f"Tarayıcıda '{query}' videosu açılıyor..."}
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
        target_browser = self._infer_browser_app(text, text_norm)
        if query:
            url = f"{base}/results?search_query={quote_plus(query)}"
            if target_browser:
                return {
                    "action": "multi_task",
                    "tasks": [
                        {"id": "task_1", "action": "open_app", "params": {"app_name": target_browser}, "description": f"{target_browser} aç"},
                        {"id": "task_2", "action": "open_url", "params": {"url": url, "browser": target_browser}, "description": f"YouTube'da '{query}' aç", "depends_on": ["task_1"]},
                    ],
                    "reply": f"{target_browser}'de YouTube için '{query}' açılıyor...",
                }
            return {"action": "open_url", "params": {"url": url},
                    "reply": f"YouTube'da '{query}' açılıyor..."}
        if target_browser:
            return {
                "action": "multi_task",
                "tasks": [
                    {"id": "task_1", "action": "open_app", "params": {"app_name": target_browser}, "description": f"{target_browser} aç"},
                    {"id": "task_2", "action": "open_url", "params": {"url": base, "browser": target_browser}, "description": "YouTube'u aç", "depends_on": ["task_1"]},
                ],
                "reply": f"{target_browser}'de YouTube açılıyor...",
            }
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
    def _normalize_terminal_command(self, command: str) -> str:
        cmd = str(command or "").strip()
        if not cmd:
            return ""
        cmd = re.sub(r"\s+", " ", cmd).strip(" \t\r\n.,;:!?")
        cmd = re.sub(r"\s+\b(?:komut(?:u|unu|un)?|command)\b\s*$", "", cmd, flags=re.IGNORECASE).strip(" \t\r\n.,;:!?")
        cmd = re.sub(r"\s+(?:çalıştır|calistir|run|execute)\b\s*$", "", cmd, flags=re.IGNORECASE).strip(" \t\r\n.,;:!?")

        cd_match = re.match(r"^\s*cd\s+(.+?)\s*$", cmd, re.IGNORECASE)
        if not cd_match:
            return cmd
        raw_target = str(cd_match.group(1) or "").strip().strip("\"'")
        if not raw_target:
            return "cd ~"

        if re.match(r"^(desktop|masaüstü|masaustu|masa ustu)$", raw_target, re.IGNORECASE):
            return "cd ~/Desktop"

        subpath = re.match(r"^(desktop|masaüstü|masaustu|masa ustu)([/\\].+)$", raw_target, re.IGNORECASE)
        if subpath:
            suffix = str(subpath.group(2) or "").replace("\\", "/")
            return f"cd ~/Desktop{suffix}"

        return cmd

    def _parse_terminal_command(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["terminal", "komut", "çalıştır", "calistir", "run", "execute", "bash", "shell"]
        if not any(t in text for t in triggers):
            return None
        command = ""
        patterns = [
            r"terminal(?:den|dan|de)?\b\s+(.+?)\s+komut\w*\s+(?:çalıştır|calistir)\b",
            r"terminal(?:den|dan|de)?\b\s+(.+?)\s+(?:çalıştır|calistir)\b",
            r"(.+?)\s+komut\w*\s+(?:çalıştır|calistir)\b",
            r"(?:run|execute)\s+(.+)",
            r"(?:çalıştır|calistir)\s+(.+)",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                command = str(m.group(1) or "").strip()
                break
        if not command:
            words = text.split()
            for i, w in enumerate(words):
                lw = str(w or "").lower()
                if (lw in triggers or lw.startswith("terminal")) and i + 1 < len(words):
                    command = " ".join(words[i+1:])
                    break
        command = re.sub(r"^(?:terminal(?:den|dan|de)?\b\s+)", "", str(command or ""), flags=re.IGNORECASE).strip(" .,:;-")
        command = re.sub(r"^(?:komut(?:u|unu|un)?\s+)", "", command, flags=re.IGNORECASE).strip(" .,:;-")
        command = re.sub(r"^(?:ve|sonra|ardından|ardindan|açıp|acip|çalıştırıp|calistirip|gidip|girip)\s+", "", command, flags=re.IGNORECASE).strip(" .,:;-")
        command = self._normalize_terminal_command(command)
        if not command or command.lower() in {
            "terminal", "komut", "bunu", "şunu", "sunu",
            "aç", "ac", "open", "start", "başlat", "baslat",
            "çalıştır", "calistir", "run", "execute",
        }:
            return None

        wants_terminal_open = bool(re.search(r"\bterminal(?:den|dan|de)?\b", text, re.IGNORECASE))
        if wants_terminal_open:
            return {
                "action": "multi_task",
                "tasks": [
                    {
                        "id": "task_1",
                        "action": "open_app",
                        "params": {"app_name": "Terminal"},
                        "description": "Terminal açılıyor...",
                    },
                    {
                        "id": "task_2",
                        "action": "type_text",
                        "params": {"text": command, "press_enter": True},
                        "description": "Komut terminalde çalıştırılıyor...",
                        "depends_on": ["task_1"],
                    },
                ],
                "reply": f"Terminal açılıp komut çalıştırılıyor: {command}",
            }
        if command:
            return {
                "action": "run_safe_command",
                "params": {"command": command},
                "reply": f"Terminal komutu çalıştırılıyor: {command}",
            }
        return None
