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

    # ── Word Document ─────────────────────────────────────────────────────────
    def _parse_create_word(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["word belgesi", "word dosyası", "docx", "word oluştur",
                    "word yaz", "belge oluştur", "belge yaz", "rapor yaz"]
        if not any(t in text for t in triggers):
            return None
        m = re.search(r'adı\s*[:\s]*(\w+)|(\w+)\s*(?:adında|adlı)\s*(?:word|belge)', text)
        filename = "belge.docx"
        if m:
            n = m.group(1) or m.group(2)
            if n:
                filename = n + ".docx"
        content = ""
        cm = re.search(r'içerik[:\s]+(.+)|konu[:\s]+(.+)', text, re.IGNORECASE)
        if cm:
            content = (cm.group(1) or cm.group(2) or "").strip()
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
        m = re.search(r'adı\s*[:\s]*(\w+)|(\w+)\s*(?:adında|adlı)\s*(?:excel|tablo)', text)
        filename = "tablo.xlsx"
        if m:
            n = m.group(1) or m.group(2)
            if n:
                filename = n + ".xlsx"
        return {"action": "create_excel",
                "params": {"filename": filename, "path": str(HOME_DIR / "Desktop" / filename)},
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
