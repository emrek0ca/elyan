"""
Pano (clipboard) araçları — çapraz platform.

macOS: pbpaste/pbcopy · Windows: PowerShell Get/Set-Clipboard ·
Linux: wl-paste/wl-copy (Wayland) → xclip → xsel sırasıyla ilk bulunan.

Jarvis akışları için: "panodakini oku/özetle", "şunu panoya kopyala".
Yan etki düşük (metin panosu); okuma read-only, yazma iyi huylu bir yerel işlem.
"""

import shutil
import subprocess
import sys


_MAX_READ_CHARS = 20000
_MAX_WRITE_CHARS = 100000

# PowerShell'de Unicode stdin güvenilir aksın diye encoding açıkça UTF-8'e
# sabitlenir (konsol codepage'ine bırakılmaz).
_PS_READ = "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-Clipboard -Raw"
_PS_WRITE = "[Console]::InputEncoding=[Text.Encoding]::UTF8; Set-Clipboard -Value ([Console]::In.ReadToEnd())"


def _read_command() -> list[str] | None:
    if sys.platform == "darwin":
        return ["pbpaste"] if shutil.which("pbpaste") else None
    if sys.platform == "win32":
        return ["powershell", "-NoProfile", "-Command", _PS_READ]
    if shutil.which("wl-paste"):
        return ["wl-paste", "--no-newline"]
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard", "-o"]
    if shutil.which("xsel"):
        return ["xsel", "--clipboard", "--output"]
    return None


def _write_command() -> list[str] | None:
    if sys.platform == "darwin":
        return ["pbcopy"] if shutil.which("pbcopy") else None
    if sys.platform == "win32":
        return ["powershell", "-NoProfile", "-Command", _PS_WRITE]
    if shutil.which("wl-copy"):
        return ["wl-copy"]
    if shutil.which("xclip"):
        return ["xclip", "-selection", "clipboard", "-i"]
    if shutil.which("xsel"):
        return ["xsel", "--clipboard", "--input"]
    return None


def clipboard_read(query: str = "") -> str:
    """Panodaki metni döndürür. `query` yok sayılır (gelecekte format seçimi
    için ayrılmıştır)."""
    command = _read_command()
    if command is None:
        return "Pano okunamadı: bu sistemde pano aracı yok (Linux için xclip/xsel/wl-clipboard kurun)."
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
        )
    except FileNotFoundError:
        return "Pano okunamadı: pano aracı bulunamadı."
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
    command = _write_command()
    if command is None:
        return "Panoya yazılamadı: bu sistemde pano aracı yok (Linux için xclip/xsel/wl-clipboard kurun)."
    try:
        subprocess.run(
            command,
            input=payload,
            text=True,
            encoding="utf-8",
            check=True,
            timeout=8,
        )
    except FileNotFoundError:
        return "Panoya yazılamadı: pano aracı bulunamadı."
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        return "Panoya yazılamadı."
    preview = payload[:80].replace("\n", " ")
    return f"Panoya kopyalandı: {preview}" + ("…" if len(payload) > 80 else "")
