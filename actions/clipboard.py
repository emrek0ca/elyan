"""
Pano (clipboard) araçları — macOS pbpaste/pbcopy sarmalayıcısı.

Jarvis akışları için: "panodakini oku/özetle", "şunu panoya kopyala".
Yan etki düşük (metin panosu); okuma read-only, yazma iyi huylu bir yerel işlem.
"""

import subprocess


_MAX_READ_CHARS = 20000
_MAX_WRITE_CHARS = 100000


def clipboard_read(query: str = "") -> str:
    """Panodaki metni döndürür. `query` yok sayılır (gelecekte format seçimi
    için ayrılmıştır)."""
    try:
        result = subprocess.run(
            ["pbpaste"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except FileNotFoundError:
        return "Pano okunamadı: bu sistemde pbpaste yok (yalnız macOS)."
    except subprocess.TimeoutExpired:
        return "Pano okunamadı: zaman aşımı."
    if result.returncode != 0:
        return "Pano okunamadı."
    text = result.stdout or ""
    if not text.strip():
        return "Pano boş."
    truncated = text[:_MAX_READ_CHARS]
    suffix = "\n… (kırpıldı)" if len(text) > _MAX_READ_CHARS else ""
    return f"Panodaki metin:\n{truncated}{suffix}"


def clipboard_write(text: str = "") -> str:
    """Verilen metni panoya kopyalar."""
    payload = str(text or "")
    if not payload.strip():
        return "Panoya yazılamadı: metin boş."
    if len(payload) > _MAX_WRITE_CHARS:
        return f"Panoya yazılamadı: metin çok uzun (>{_MAX_WRITE_CHARS} karakter)."
    try:
        subprocess.run(
            ["pbcopy"],
            input=payload,
            text=True,
            check=True,
            timeout=5,
        )
    except FileNotFoundError:
        return "Panoya yazılamadı: bu sistemde pbcopy yok (yalnız macOS)."
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return "Panoya yazılamadı."
    preview = payload[:80].replace("\n", " ")
    return f"Panoya kopyalandı: {preview}" + ("…" if len(payload) > 80 else "")
