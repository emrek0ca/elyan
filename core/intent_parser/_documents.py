"""
_documents.py — Belge ve web sitesi parser'ları
Kapsam: create_word, create_excel, create_pdf, create_website
"""
import re
from pathlib import Path
from config.settings import HOME_DIR
from ._base import (BaseParser, _RE_WEBSITE_DIRECT_TOPIC, _RE_WEBSITE_TOPIC,
                    _RE_WEBSITE_ALT, _RE_WEBSITE_CLEAN, _RE_WEBSITE_FILENAME,
                    _RE_WEBSITE_FOLDER, _RE_WEBSITE_SLUGIFY)


class DocumentParser(BaseParser):

    @staticmethod
    def _extract_inline_content(text: str) -> str:
        patterns = [
            r"(?:içine|icine|içeriğine|icerigine)\s+(.+?)(?:\s+yaz|$)",
            r"(?:metin|içerik|icerik|konu)\s*[:\-]\s*(.+)$",
            r"(?:şunu|sunu|bunu)\s+yaz\s*[:\-]?\s*(.+)$",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.IGNORECASE)
            if not m:
                continue
            candidate = str(m.group(1) or "").strip()
            candidate = re.sub(
                r"\b(word|excel|belge|dosya|tablo|oluştur|olustur|kaydet)\b",
                " ",
                candidate,
                flags=re.IGNORECASE,
            )
            candidate = re.sub(r"\s+", " ", candidate).strip(" .,:;-")
            if len(candidate) >= 3:
                return candidate
        return ""

    # ── Word Document ─────────────────────────────────────────────────────────
    def _parse_create_word(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["word belgesi", "word dosyası", "docx", "word oluştur",
                    "word yaz", "belge oluştur", "belge yaz", "rapor yaz", "word olarak kaydet", "word kaydet"]
        if not any(t in text for t in triggers):
            if not ("word" in text and "kaydet" in text):
                return None
        if any(t in text for t in ["word aç", "word ac", "wordu aç", "word'u aç", "microsoft word aç"]):
            return None
        m = re.search(r'adı\s*[:\s]*(\w+)|(\w+)\s*(?:adında|adlı)\s*(?:word|belge)', text)
        filename = "belge.docx"
        if m:
            n = m.group(1) or m.group(2)
            if n:
                filename = n + ".docx"
        content = self._extract_inline_content(text)
        if not content:
            cm = re.search(r'içerik[:\s]+(.+)|konu[:\s]+(.+)', text, re.IGNORECASE)
            if cm:
                content = (cm.group(1) or cm.group(2) or "").strip()
        if not content:
            topic_m = re.search(
                r"(.+?)\s+hakkında\s+(?:rapor|belge|word|docx)(?:\s+oluştur|\s+yaz|\s+kaydet|$)",
                text,
                re.IGNORECASE,
            )
            if topic_m:
                content = topic_m.group(1).strip()
        return {"action": "create_word_document",
                "params": {"filename": filename, "content": content,
                           "path": str(HOME_DIR / "Desktop" / filename)},
                "reply": f"'{filename}' Word belgesi oluşturuluyor..."}

    # ── Excel Spreadsheet ─────────────────────────────────────────────────────
    def _parse_create_excel(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["excel", "xlsx", "tablo oluştur", "tablo yap", "spreadsheet",
                    "veri tablosu", "excel dosyası", "excel belgesi"]
        if not any(t in text for t in triggers):
            return None
        if any(t in text for t in ["excel aç", "excel ac", "exceli aç", "excel'i aç", "microsoft excel aç"]):
            return None
        m = re.search(r'adı\s*[:\s]*(\w+)|(\w+)\s*(?:adında|adlı)\s*(?:excel|tablo)', text)
        filename = "tablo.xlsx"
        if m:
            n = m.group(1) or m.group(2)
            if n:
                filename = n + ".xlsx"
        content = self._extract_inline_content(text)
        if not content:
            topic_m = re.search(
                r"(.+?)\s+hakkında\s+(?:excel|xlsx|tablo)(?:\s+oluştur|\s+yap|\s+kaydet|$)",
                text,
                re.IGNORECASE,
            )
            if topic_m:
                content = topic_m.group(1).strip()

        headers = None
        hm = re.search(r"(?:kolonlar|sütunlar|sutunlar)\s*[:\-]\s*(.+)$", text, re.IGNORECASE)
        if hm:
            raw = hm.group(1).strip()
            raw = re.split(r"\b(?:içine|icine|içeri|iceri|içerik|icerik)\b", raw, maxsplit=1, flags=re.IGNORECASE)[0].strip()
            cols = [c.strip() for c in re.split(r"[;,|]", raw) if c.strip()]
            if cols:
                headers = cols[:20]

        params = {"filename": filename, "path": str(HOME_DIR / "Desktop" / filename)}
        if content:
            params["content"] = content
        if headers:
            params["headers"] = headers
        return {"action": "create_excel", "params": params,
                "reply": f"'{filename}' Excel dosyası oluşturuluyor..."}

    # ── PDF ───────────────────────────────────────────────────────────────────
    def _parse_pdf_operations(self, text: str, text_norm: str, original: str) -> dict | None:
        if "pdf" not in text:
            return None
        if any(t in text for t in ["birleştir", "merge", "birlestir"]):
            return {"action": "merge_pdfs", "params": {}, "reply": "PDF dosyaları birleştiriliyor..."}
        if any(t in text for t in ["böl", "bol", "ayır", "split"]):
            return {"action": "split_pdf", "params": {}, "reply": "PDF bölünüyor..."}
        if any(t in text for t in ["sıkıştır", "sikistir", "compress", "küçült"]):
            return {"action": "compress_pdf", "params": {}, "reply": "PDF sıkıştırılıyor..."}
        if any(t in text for t in ["oluştur", "olustur", "yap", "convert", "dönüştür"]):
            return {"action": "create_pdf", "params": {}, "reply": "PDF oluşturuluyor..."}
        return None

    @staticmethod
    def _infer_project_kind(text: str) -> str:
        low = str(text or "").lower()
        if any(k in low for k in ["oyun", "game", "pygame", "unity", "three.js", "threejs"]):
            return "game"
        if any(k in low for k in ["website", "web sitesi", "web sayfas", "landing page", "frontend", "saas", "dashboard", "panel"]):
            return "website"
        return "app"

    @staticmethod
    def _infer_ide(text: str) -> str:
        low = str(text or "").lower()
        if any(k in low for k in ["cursor"]):
            return "cursor"
        if any(k in low for k in ["windsurf", "codeium windsurf"]):
            return "windsurf"
        if any(k in low for k in ["antigravity", "anti gravity", "gravity"]):
            return "antigravity"
        return "vscode"

    @staticmethod
    def _infer_stack(text: str, kind: str) -> str:
        low = str(text or "").lower()
        if kind == "website":
            if "next" in low:
                return "nextjs"
            if "react" in low:
                return "react"
            return "vanilla"
        if kind == "game":
            if "unity" in low:
                return "unity"
            return "python"

        if "flutter" in low:
            return "flutter"
        if "react native" in low:
            return "react-native"
        if "node" in low or "express" in low:
            return "node"
        if "django" in low:
            return "django"
        if "flask" in low:
            return "flask"
        if "fastapi" in low:
            return "fastapi"
        return "python"

    @staticmethod
    def _infer_complexity(text: str) -> str:
        low = str(text or "").lower()
        expert_markers = (
            "karmaşık",
            "karmasik",
            "çok karmaşık",
            "cok karmasik",
            "enterprise",
            "production",
            "ölçeklenebilir",
            "olceklenebilir",
            "profesyonel",
            "tam kapsamlı",
            "full-featured",
            "eksiksiz",
        )
        standard_markers = ("basit", "simple", "minimal", "demo", "örnek", "ornek")
        if any(k in low for k in expert_markers):
            return "expert"
        if any(k in low for k in standard_markers):
            return "standard"
        return "advanced"

    @staticmethod
    def _extract_project_name(text: str, kind: str) -> str:
        raw = str(text or "").strip()
        if not raw:
            return "elyan-project"

        quoted = re.search(r"[\"']([^\"']{2,80})[\"']", raw)
        if quoted:
            return quoted.group(1).strip()

        named = re.search(
            r"([a-zA-Z0-9çğıöşüÇĞİÖŞÜ _\-]{2,80})\s+(?:adında|adli|isimli)\s+(?:website|web sitesi|web sayfas[ıi]|uygulama|app|proje)",
            raw,
            re.IGNORECASE,
        )
        if named:
            return named.group(1).strip()

        topic = re.search(r"(.+?)\s+hakkında\s+(?:website|web sitesi|uygulama|app|proje)", raw, re.IGNORECASE)
        if topic:
            return topic.group(1).strip()

        before_target = re.search(
            r"([a-zA-Z0-9çğıöşüÇĞİÖŞÜ _\-]{2,80})\s+(?:website|web sitesi|web sayfas[ıi]|uygulama(?:s[ıi])?|app|proje)\b",
            raw,
            re.IGNORECASE,
        )
        if before_target:
            candidate = str(before_target.group(1) or "").strip()
            candidate = re.sub(
                r"\b(bir|new|yeni|ile|using|ve|the|a|an|için|icin)\b",
                " ",
                candidate,
                flags=re.IGNORECASE,
            )
            candidate = re.sub(
                r"\b(python|react|next|nextjs|node|express|django|flask|fastapi|flutter|js|javascript|typescript|ts)\b",
                " ",
                candidate,
                flags=re.IGNORECASE,
            )
            candidate = re.sub(r"\s+", " ", candidate).strip(" .,:;-")
            if len(candidate) >= 2:
                return candidate

        return "web-projesi" if kind == "website" else ("oyun-projesi" if kind == "game" else "uygulama-projesi")

    # ── Coding Project ───────────────────────────────────────────────────────
    def _parse_create_coding_project(self, text: str, text_norm: str, original: str) -> dict | None:
        low = str(text or "").lower()
        create_kw = [
            "yap", "oluştur", "olustur", "geliştir", "gelistir", "kodla", "planla", "tasarla",
            "build", "develop", "create", "kur",
        ]
        target_kw = [
            "website", "web sitesi", "web sayfas", "landing page", "frontend",
            "uygulama", "app", "mobil", "desktop app", "masaüstü uygulama", "masaustu uygulama", "backend",
            "api", "saas", "dashboard", "panel", "mvp", "oyun", "game",
            "hesap makinesi", "calculator", "todo", "yapılacak", "yapilacak",
            "not defteri", "takvim uygulaması", "chat uygulaması",
        ]
        if not any(k in low for k in create_kw):
            return None
        if not any(k in low for k in target_kw):
            return None
        if any(k in low for k in ["word", "excel", "pdf", "sunum", "presentation"]):
            return None
        if any(k in low for k in ["klasör", "klasor", "folder", "dosya", "file"]) and not any(
            k in low for k in ["uygulama", "app", "website", "web sitesi", "web sayfas", "api", "oyun", "game"]
        ):
            return None
        if any(k in low for k in ["araştır", "arastir", "araştırma", "arastirma", "hakkında", "hakkinda"]) and any(
            k in low for k in ["rapor", "belge", "docx", "word", "excel", "xlsx", "tablo"]
        ):
            return None

        kind = self._infer_project_kind(low)
        stack = self._infer_stack(low, kind=kind)
        ide = self._infer_ide(low)
        complexity = self._infer_complexity(low)
        project_name = self._extract_project_name(original, kind=kind)
        output_dir = str(HOME_DIR / "Desktop")

        params = {
            "project_kind": kind,
            "project_name": project_name,
            "stack": stack,
            "output_dir": output_dir,
            "open_ide": True,
            "ide": ide,
            "complexity": complexity,
            "theme": "professional",
            "brief": original,
        }
        return {
            "action": "create_coding_project",
            "params": params,
            "reply": f"'{project_name}' için {kind} projesi hazırlanıyor ({stack}) ve {ide} açılıyor...",
        }

    # ── Website ───────────────────────────────────────────────────────────────
    def _parse_create_website(self, text: str, text_norm: str, original: str) -> dict | None:
        website_kw = ["website", "web sitesi", "web sayfası", "html", "portfolyo", "portfolio"]
        create_kw  = ["yap", "oluştur", "olustur", "hazırla", "hazirla", "kur", "oluşturur musun",
                      "yapabilir misin", "yapabilirmisin", "yazar mısın"]
        if not any(w in text.lower() for w in website_kw):
            return None
        if not any(v in text.lower() for v in create_kw):
            return None
        topic = None
        m = _RE_WEBSITE_DIRECT_TOPIC.search(text)
        if m:
            topic = m.group(1).strip()
        if not topic:
            m2 = _RE_WEBSITE_TOPIC.search(text)
            if m2:
                topic = m2.group(1).strip()
        if not topic:
            m3 = _RE_WEBSITE_ALT.search(text)
            if m3:
                topic = m3.group(1).strip()
        if topic:
            topic = _RE_WEBSITE_CLEAN.sub("", topic).strip()
        if not topic or len(topic) < 2:
            topic = "kisisel"
        filename_m = _RE_WEBSITE_FILENAME.search(text)
        filename = filename_m.group(1) if filename_m else None
        if not filename:
            slug = _RE_WEBSITE_SLUGIFY.sub("-", topic.lower().strip()).strip("-")
            filename = f"{slug}.html"
        folder_m = _RE_WEBSITE_FOLDER.search(text)
        folder = folder_m.group(1) if folder_m else None
        if not folder:
            slug = _RE_WEBSITE_SLUGIFY.sub("-", topic.lower().strip()).strip("-")
            folder = slug
        output_dir = str(HOME_DIR / "Desktop" / folder)
        return {"action": "create_website",
                "params": {"topic": topic, "filename": filename, "output_dir": output_dir},
                "reply": f"'{topic}' konulu web sitesi oluşturuluyor..."}

    # ── Presentation ──────────────────────────────────────────────────────────
    def _parse_create_presentation(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["sunum", "presentation", "powerpoint", "pptx", "slayt", "slide"]
        if not any(t in text for t in triggers):
            return None
        m = re.search(r'(.+?)\s+(?:hakkında|konulu|için)\s+sunum', text)
        topic = m.group(1).strip() if m else "genel"
        return {"action": "create_presentation", "params": {"topic": topic},
                "reply": f"'{topic}' sunumu oluşturuluyor..."}
