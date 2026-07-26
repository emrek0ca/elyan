from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from actions._read_only_common import content_type_for, is_explicit_path_value, preview_text, workspace_root
from runtime.capability_registry import SafeCapabilityError


DEFAULT_OUTPUT_DIRNAME = "elyan_output"


def output_root(root_resolver=workspace_root) -> Path:
    return root_resolver() / DEFAULT_OUTPUT_DIRNAME


def _linux_desktop_dir(home: Path) -> Path | None:
    """Linux'ta XDG kullanıcı dizinlerinden masaüstünü çözer (yerelleştirilmiş
    klasör adlarını da destekler). ~/.config/user-dirs.dirs içindeki
    `XDG_DESKTOP_DIR="$HOME/Masaüstü"` gibi bir satırdan okur."""
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    config_path = (Path(config_home) if config_home else home / ".config") / "user-dirs.dirs"
    try:
        for line in config_path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped.startswith("XDG_DESKTOP_DIR"):
                continue
            _, _, value = stripped.partition("=")
            value = value.strip().strip('"').strip("'")
            value = value.replace("$HOME", str(home)).replace("${HOME}", str(home))
            if value:
                return Path(value).expanduser()
    except OSError:
        pass
    return None


def desktop_dir() -> Path:
    """Tüm işletim sistemlerinde kullanıcı masaüstü klasörü.

    macOS / Windows: ``~/Desktop`` (Windows'ta USERPROFILE\\Desktop). Linux:
    XDG_DESKTOP_DIR (yerelleştirilmiş) ya da ``~/Desktop``. Ev dizini
    çözülemezse çalışma alanı ``elyan_output`` klasörüne düşülür (fail-safe).
    """
    try:
        home = Path.home()
    except (RuntimeError, OSError):
        return output_root()
    if sys.platform.startswith("linux"):
        xdg = _linux_desktop_dir(home)
        if xdg is not None:
            return xdg
    return home / "Desktop"


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def slugify_filename(value: str, *, fallback: str = "untitled") -> str:
    cleaned = " ".join(str(value or "").strip().split()).lower()
    cleaned = (
        cleaned.replace("ı", "i")
        .replace("ğ", "g")
        .replace("ü", "u")
        .replace("ş", "s")
        .replace("ö", "o")
        .replace("ç", "c")
    )
    cleaned = re.sub(r"[^a-z0-9]+", "-", cleaned).strip("-")
    return cleaned[:64] or fallback


def unique_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    for index in range(2, 1000):
        candidate = parent / f"{stem}-{index}{suffix}"
        if not candidate.exists():
            return candidate
    return parent / f"{stem}-{int(path.stat().st_mtime)}{suffix}"


def sanitize_xml_text(value: str, *, max_chars: int | None = None) -> str:
    text = str(value or "")
    cleaned = "".join(
        char
        if char in {"\n", "\r", "\t"} or ord(char) >= 32
        else " "
        for char in text
    )
    cleaned = re.sub(r"[\ufffd]+", " ", cleaned)
    cleaned = "\n".join(" ".join(line.split()) for line in cleaned.splitlines())
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
    if max_chars is not None and max_chars > 0:
        return cleaned[:max_chars]
    return cleaned


def ensure_allowed_output_path(
    raw_path: str,
    *,
    extension: str,
    overwrite: bool = False,
    hint: str = "",
    root_resolver=workspace_root,
    desktop_resolver=None,
) -> Path:
    """Çıktı yolunu çözer. Kullanıcı AÇIK bir yol verdiyse (``~``, ``/``, ``C:\\``)
    oraya yazılır. Göreli yollar çalışma alanı köküne çözülür; hedef verilmezse
    platformun masaüstü klasöründe güvenli bir ad üretilir."""
    suffix = extension.lower() if extension.startswith(".") else f".{extension.lower()}"
    candidate = str(raw_path or "").strip()
    workspace_base = root_resolver().resolve()
    default_base = output_root(root_resolver).resolve()
    if candidate:
        resolved = Path(candidate).expanduser()
        if not resolved.suffix:
            resolved = resolved.with_suffix(suffix)
        if not resolved.is_absolute():
            resolved = (workspace_base / resolved).resolve()
        else:
            resolved = resolved.resolve()
        if not is_explicit_path_value(candidate):
            desktop_base = (desktop_resolver or desktop_dir)().resolve()
            allowed_roots = [workspace_base, default_base, desktop_base]
            if not any(_is_within(resolved, root) for root in allowed_roots):
                raise SafeCapabilityError(
                    "ACCESS_DENIED",
                    "Dosya yalnızca açık yol, masaüstü veya izinli çalışma alanı içine yazılabilir.",
                )
    else:
        default_base = (desktop_resolver or desktop_dir)().resolve()
        filename = f"{slugify_filename(hint or 'elyan-output')}{suffix}"
        resolved = unique_output_path((default_base / filename).resolve())

    if resolved.suffix.lower() != suffix:
        resolved = resolved.with_suffix(suffix)

    resolved.parent.mkdir(parents=True, exist_ok=True)
    if resolved.exists() and not overwrite:
        raise SafeCapabilityError(
            "FILE_EXISTS",
            "Hedef dosya zaten var. Üzerine yazmak için açık onay ve overwrite=true gerekiyor.",
        )
    return resolved


def normalize_source_context(value: str, *, max_chars: int = 320) -> str:
    return preview_text(" ".join(sanitize_xml_text(value).split()), limit=max_chars)


def artifact_payload(path: Path) -> dict[str, str]:
    return {
        "kind": "file",
        "name": path.name,
        "path": str(path),
        "contentType": content_type_for(path),
    }
