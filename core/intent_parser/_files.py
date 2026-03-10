"""
_files.py — Dosya sistemi parser'ları
Kapsam: create_folder, list_files, write_file, search_files, read_file, delete_file
"""
import re
from pathlib import Path
from config.settings import HOME_DIR
from ._base import BaseParser, _RE_FOLDER_NAME_PATTERNS


class FileParser(BaseParser):
    @staticmethod
    def _extract_create_folder_name(original: str) -> str:
        raw = str(original or "").strip()
        if not raw:
            return ""

        quoted = re.findall(r"[\"“”'`](.+?)[\"“”'`]", raw)
        for item in quoted:
            candidate = str(item or "").strip(" .,:;-_/")
            if re.fullmatch(r"[\w\- ]{1,80}", candidate, re.IGNORECASE):
                return candidate.replace(" ", "-")

        patterns = (
            r"\b([a-zA-Z0-9][\w\-]{0,80})\s+adında\s+klas[öo]r(?:ü|u)?\b",
            r"\b([a-zA-Z0-9][\w\-]{0,80})\s+adinda\s+klasor(?:u)?\b",
            r"\b(?:adında|adli|isimli|named)\s+([a-zA-Z0-9][\w\-]{0,80})\s+klas[öo]r\b",
            r"\b(?:adinda|adli|isimli|named)\s+([a-zA-Z0-9][\w\-]{0,80})\s+klasor\b",
            r"(?:masaüst(?:üne|ünde)?|masaust(?:une|unde)?|desktop(?:a|e|ta|te)?|belgeler(?:de)?|documents(?:ta|te)?|indirilenler(?:de)?|downloads(?:ta|te)?)\s+([a-zA-Z0-9][\w\-]{0,80})\s+klas[öo]r(?:ü|u)?\s+(?:oluştur|olustur|kur|aç|ac|yap|ekle)\b",
            r"\b([a-zA-Z0-9][\w\-]{0,80})\s+klas[öo]r(?:ü|u)?\s+(?:oluştur|olustur|kur|aç|ac|yap|ekle)\b",
        )
        for pattern in patterns:
            match = re.search(pattern, raw, re.IGNORECASE)
            if match:
                return str(match.group(1) or "").strip(" .,:;-_/")
        return ""

    @staticmethod
    def _extract_write_content(original: str) -> str:
        raw = str(original or "").strip()
        if not raw:
            return ""

        quoted = re.findall(r"[\"“”'`](.+?)[\"“”'`]", raw)
        if quoted:
            candidate = str(quoted[0] or "").strip()
            if len(candidate) >= 2:
                return candidate

        patterns = (
            r"(?:masaüstüne|masaustune|desktop(?:a|e)?)(?:\s+bir)?\s+not(?:\s+olarak)?\s+(.+?)\s+yaz\b",
            r"(?:masaüstüne|masaustune|desktop(?:a|e)?)(?:\s+bir)?\s+not(?:\s+olarak)?\s+(.+?)\s+kaydet\b",
            r"\bnot(?:\s+olarak)?\s+(.+?)\s+yaz\b",
            r"\bnot(?:\s+olarak)?\s+(.+?)\s+kaydet\b",
            r"\byaz[:\s]+(.+)$",
            r"\bkaydet[:\s]+(.+)$",
            r"\boluştur[:\s]+(.+)$",
            r"\bolustur[:\s]+(.+)$",
            r"\biçeriği[:\s]+(.+)$",
            r"\bicerigi[:\s]+(.+)$",
        )
        for pattern in patterns:
            match = re.search(pattern, raw, re.IGNORECASE)
            if not match:
                continue
            content = str(match.group(1) or "").strip()
            content = re.sub(r"\s+", " ", content).strip(" .,:;-")
            if len(content) >= 2:
                return content
        return ""

    # ── Create Folder ─────────────────────────────────────────────────────────
    def _parse_create_folder(self, text: str, text_norm: str, original: str) -> dict | None:
        if not any(t in text for t in ["klasör", "klasor", "folder"]):
            return None
        if not any(v in text for v in ["olustur", "oluştur", "kur", "ac", "aç", "yap", "ekle"]):
            return None
        name = self._extract_create_folder_name(original)
        for pat in _RE_FOLDER_NAME_PATTERNS:
            if name:
                break
            m = pat.search(original)
            if m:
                name = m.group(1)
                break
        if not name or len(name) < 1:
            name = "yeni_klasor"
        base = "Desktop"
        for alias, real in self.path_aliases.items():
            if alias in text:
                base = real or "Desktop"
                break
        return {"action": "create_folder", "params": {"path": f"~/{base}/{name}"},
                "reply": f"{base} konumunda '{name}' klasoru olusturuluyor..."}

    # ── List Files ────────────────────────────────────────────────────────────
    def _parse_list_files(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["ne var", "neler var", "göster", "listele", "bak", "içeriği",
                    "hangi dosya", "hangi klasör", "dosyalar neler", "klasörler neler",
                    "içindekiler", "neleri var", "dosyaları göster"]
        if not any(t in text for t in triggers):
            return None
        # Dosya içeriği isteklerini read_file parser'ına bırak.
        if re.search(
            r"[\w\-.]+\.[a-z0-9]{2,8}\s+(?:içinde ne var|icinde ne var|içeriğini göster|icerigini goster|oku|ne yazıyor)",
            text,
            re.IGNORECASE,
        ):
            return None
        if re.search(
            r"\b([a-z0-9][\w\-]{0,80})\s+dosya\w*\s+(?:içinde ne var|icinde ne var|içeriğini göster|icerigini goster|oku|ne yazıyor)\b",
            text,
            re.IGNORECASE,
        ):
            return None
        path = self._extract_path(text)
        fs_context_tokens = [
            "dosya", "file", "klasör", "klasor", "folder", "dizin", "directory",
            "masaüst", "desktop", "indirilen", "download", "belgeler", "documents",
            "resimler", "pictures", "music", "müzik", "movies", "filmler",
            "ana klasör", "home", "ev dizini",
        ]
        has_fs_context = bool(path) or any(tok in text for tok in fs_context_tokens)
        if not has_fs_context:
            # "takvimde ne var" gibi dosya sistemi dışı cümleleri yanlış yakalama.
            return None

        path = path or str(HOME_DIR / "Desktop")
        folder_name = Path(path).name or "Ana klasör"
        return {"action": "list_files", "params": {"path": path},
                "reply": f"{folder_name} klasörü listeleniyor..."}

    # ── Write File ────────────────────────────────────────────────────────────
    def _parse_write_file(self, text: str, text_norm: str, original: str) -> dict | None:
        triggers = ["not yaz", "dosya oluştur", "kaydet", "yaz:", "not oluştur",
                    "liste yaz", "dosya yaz", "metin kaydet", "not al",
                    "bunu kaydet", "dosya olarak kaydet", "masaüstüne kaydet",
                    "masaüstüne not", "masaustune not", "not olarak", "desktop note"]
        if not any(t in text for t in triggers):
            return None
        content = self._extract_write_content(original)
        filename = "not.txt"
        fm = re.search(r'([\w\-.]+\.[a-z0-9]{2,8})', text, re.IGNORECASE)
        if fm:
            filename = fm.group(1)
        else:
            nm = re.search(r'adı\s*[:\s]*([\w\-]+)|([\w\-]+)\s*dosyası|([\w\-]+)\s*olarak', text)
            if nm:
                n = nm.group(1) or nm.group(2) or nm.group(3)
                if n and n not in ["yaz", "oluştur", "kaydet", "dosya", "not"]:
                    filename = n + ".txt"

        base_dir = self._extract_path(text) or str(HOME_DIR / "Desktop")
        return {"action": "write_file",
                "params": {"path": str(Path(base_dir) / filename), "content": content},
                "reply": f"{filename} oluşturuluyor..."}

    # ── Search Files ──────────────────────────────────────────────────────────
    def _parse_search_files(self, text: str, text_norm: str, original: str) -> dict | None:
        if not any(t in text for t in ["ara", "bul", "search", "find", "tara"]):
            return None
        research_markers = [
            "araştır", "arastir", "araştırma", "arastirma", "hakkında", "hakkinda",
            "internette", "webde", "web'de", "kaynak", "özet", "ozet",
        ]
        file_context_markers = [
            "dosya", "file", "klasör", "klasor", "folder", "dizin", "uzant",
            "masaüst", "masaust", "desktop", "indirilen", "documents",
        ]
        if any(k in text for k in research_markers) and not any(k in text for k in file_context_markers):
            return None
        m = re.search(r'\*\.(\w+)', text)
        if m:
            pattern = f"*.{m.group(1)}"
        else:
            ext_map = {"pdf": "*.pdf", "resim": "*.{jpg,png,gif}", "foto": "*.{jpg,png}",
                       "video": "*.{mp4,mov}", "müzik": "*.{mp3,m4a}", "python": "*.py",
                       "belge": "*.{doc,docx,pdf,txt}", "excel": "*.xlsx", "word": "*.docx"}
            pattern = None
            for kw, pat in ext_map.items():
                if kw in text:
                    pattern = pat
                    break
            if not pattern:
                wm = re.search(r'(\w+)\s*(dosya|file)', text)
                if wm:
                    pattern = f"*{wm.group(1)}*"
                else:
                    return None
        directory = self._extract_path(text) or str(HOME_DIR)
        return {"action": "search_files", "params": {"pattern": pattern, "directory": directory},
                "reply": f"{pattern} dosyaları aranıyor..."}

    # ── Read File ─────────────────────────────────────────────────────────────
    def _parse_read_file(self, text: str, text_norm: str, original: str) -> dict | None:
        if not any(t in text for t in ["oku", "içeriğini göster", "ne yazıyor", "aç ve göster", "içeriği", "içinde ne var", "icinde ne var"]):
            return None
        m = re.search(r'[\w\-]+\.\w+', text)
        if m:
            filename = m.group()
            path = self._extract_path(text)
            full = str(Path(path) / filename) if path else str(HOME_DIR / "Desktop" / filename)
            return {"action": "read_file", "params": {"path": full}, "reply": f"{filename} okunuyor..."}
        m2 = re.search(
            r"\b([a-z0-9][\w\-]{0,80})\s+dosya\w*\s*(?:içinde ne var|icinde ne var|içeriğini göster|icerigini goster|oku|ne yazıyor)?\b",
            text,
            re.IGNORECASE,
        )
        if m2:
            filename = str(m2.group(1) or "").strip()
            if filename and filename.lower() not in {"bu", "bunu", "şunu", "sunu", "onu", "dosya", "klasor", "klasör"}:
                path = self._extract_path(text)
                full = str(Path(path) / filename) if path else str(HOME_DIR / "Desktop" / filename)
                return {"action": "read_file", "params": {"path": full}, "reply": f"{filename} okunuyor..."}
        if any(p in text for p in ["bunu oku", "şunu oku", "sunu oku", "onu oku"]):
            return {"action": "read_file", "params": {"path": ""}, "reply": "Dosya okunuyor..."}
        return None

    # ── Delete File ───────────────────────────────────────────────────────────
    def _parse_delete_file(self, text: str, text_norm: str, original: str) -> dict | None:
        if not any(t in text for t in ["sil", "kaldir", "kaldır", "delete", "remove"]):
            return None
        if any(w in text for w in ["silme işlemi", "silinmesini", "silinir"]):
            return None
        m = re.search(r'[\w\-]+\.\w+', text)
        if m:
            filename = m.group()
            path = self._extract_path(text)
            full = str(Path(path) / filename) if path else str(HOME_DIR / "Desktop" / filename)
            return {"action": "delete_file", "params": {"path": full, "force": False},
                    "reply": f"{filename} siliniyor..."}
        m2 = re.search(
            r"\b([a-z0-9][\w\-]{0,80})\s+dosya\w*\s*(?:sil|kald[ıi]r|delete|remove)\b",
            text,
            re.IGNORECASE,
        )
        if m2:
            filename = str(m2.group(1) or "").strip()
            if filename and filename.lower() not in {"bu", "bunu", "şunu", "sunu", "onu", "dosya", "klasor", "klasör"}:
                path = self._extract_path(text)
                full = str(Path(path) / filename) if path else str(HOME_DIR / "Desktop" / filename)
                return {"action": "delete_file", "params": {"path": full, "force": False},
                        "reply": f"{filename} siliniyor..."}
        if any(p in text for p in ["bunu sil", "şunu sil", "sunu sil", "onu sil"]):
            return {"action": "delete_file", "params": {"path": "", "force": False}, "reply": "Dosya siliniyor..."}
        return None
