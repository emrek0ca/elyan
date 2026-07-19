"""Yerel Ayarlar penceresi — menü çubuğu/tepsideki "Ayarlar…" öğesinden açılır.

SwiftUI görünümlü native pencere, Python'da: customtkinter ile büyük başlık,
yuvarlatılmış inset-grouped kartlar, iOS tarzı switch'ler, adaçayı vurgu.
Sistem görünümüne uyar — açık modda mobil uygulamanın krem teması, koyu modda
orman-adaçayı paleti (her renk light/dark çifti). Üç işletim sisteminde aynı
kod, aynı görünüm. pystray macOS'ta AppKit run loop'unu ana thread'de
tuttuğu için pencere AYRI SÜREÇTE çalışır (`python -m runtime.settings_ui`).
Pencere kurulum bitene dek gizli tutulur (titremesiz açılış).

Kimlik: pencere hiçbir yerde "Python" olarak görünmez — macOS'ta bundle adı
ve Dock ikonu Elyan/logo.png; Windows'ta AppUserModelID; Linux'ta iconphoto;
süreç adı setproctitle ile `elyan-settings`.

Pencere STATE dosyasını okur/yazar (state_store); servis işlemleri
(yeniden başlat / eşleşmeyi kopar) mevcut `elyan` CLI komutlarına delege
edilir. Değişiklikler anında kaydedilir.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parent.parent
_LOGO_PATH = _REPO_ROOT / "logo.png"
_LOCK_PATH = Path.home() / ".elyan" / "settings-ui.pid"

# Her renk (açık, koyu) çifti — customtkinter tuple'ı sistem görünümüne göre
# kendisi seçer. Açık: mobil uygulamanın krem teması; koyu: mobilin
# orman-adaçayı paleti (mobile_preferences.dart: elyan accent).
_BG = ("#F2EEE5", "#1C2820")
_CARD = ("#FBF9F3", "#2A3A2E")
_PRIMARY = ("#6A8A68", "#86AA84")
_PRIMARY_HOVER = ("#50694F", "#688A66")
_ON_PRIMARY = ("#FFFFFF", "#16211A")
_TEXT = ("#262B24", "#E9EDE7")
_MUTED = ("#8B9084", "#9AA896")
_ACCENT_TEXT = ("#50694F", "#A8C4A6")
_DANGER = ("#B3564C", "#C96A5F")
_DANGER_HOVER = ("#F3E4E1", "#3D2E2A")
_OUTLINE = ("#E4E0D4", "#3A4A3E")
_FIELD = ("#F1EDE2", "#344538")
_SWITCH_OFF = ("#D9D5C9", "#3A4A3E")
_SWITCH_KNOB = ("#FFFFFF", "#E9EDE7")


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def open_settings() -> None:
    """Ayar penceresini ayrı süreçte açar; zaten açıksa ikinci pencere açmaz."""
    try:
        existing = int(_LOCK_PATH.read_text().strip() or "0")
        if _pid_alive(existing):
            return
    except Exception:
        pass
    subprocess.Popen(
        [sys.executable, "-m", "runtime.settings_ui"],
        cwd=str(_REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# ---------------------------------------------------------------------------
# Pencere süreci


def _summary() -> dict[str, Any]:
    try:
        from runtime.daemon import runtime_status_summary

        return runtime_status_summary()
    except Exception:
        return {}


def _elyan_cli(*args: str) -> None:
    subprocess.Popen(
        [sys.executable, "-m", "cli.main", *args],
        cwd=str(_REPO_ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _apply_elyan_identity(root: Any) -> None:
    """Uygulama hiçbir yüzeyde "Python" görünmesin: ad Elyan, ikon logo.png."""
    if sys.platform == "darwin":
        try:
            from AppKit import NSApplication, NSImage
            from Foundation import NSBundle

            info = NSBundle.mainBundle().infoDictionary()
            if isinstance(info, object):
                info["CFBundleName"] = "Elyan"
            if _LOGO_PATH.exists():
                image = NSImage.alloc().initWithContentsOfFile_(str(_LOGO_PATH))
                if image is not None:
                    NSApplication.sharedApplication().setApplicationIconImage_(image)
        except Exception:
            pass
        return
    if sys.platform.startswith("win"):
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("dev.elyan.desktop")  # type: ignore[attr-defined]
        except Exception:
            pass
    try:
        import tkinter as tk

        if _LOGO_PATH.exists():
            icon = tk.PhotoImage(file=str(_LOGO_PATH))
            root.iconphoto(True, icon)
            root._elyan_icon_ref = icon  # GC koruması
    except Exception:
        pass


def _run_window() -> int:
    try:
        import setproctitle

        setproctitle.setproctitle("elyan-settings")
    except Exception:
        pass

    import customtkinter as ctk
    from tkinter import messagebox

    from runtime import state_store

    # Tek örnek kilidi
    try:
        _LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LOCK_PATH.write_text(str(os.getpid()))
    except Exception:
        pass

    state = state_store.snapshot()
    pairing = state.get("pairing", {}) if isinstance(state.get("pairing"), dict) else {}
    privacy = state.get("privacy", {}) if isinstance(state.get("privacy"), dict) else {}

    ctk.set_appearance_mode("system")

    root = ctk.CTk(fg_color=_BG)
    root.withdraw()  # kurulum bitene dek gizle — titremesiz açılış
    root.title("Elyan Ayarları")
    root.resizable(False, False)
    _apply_elyan_identity(root)
    try:  # pencereyi öne getir
        root.attributes("-topmost", True)
        root.after(400, lambda: root.attributes("-topmost", False))
    except Exception:
        pass

    family = (
        "SF Pro Text"
        if sys.platform == "darwin"
        else "Segoe UI Variable" if sys.platform.startswith("win") else "Cantarell"
    )
    font_large_title = ctk.CTkFont(family=family, size=28, weight="bold")
    font_subtitle = ctk.CTkFont(family=family, size=12)
    font_section = ctk.CTkFont(family=family, size=11, weight="bold")
    font_body = ctk.CTkFont(family=family, size=13)
    font_pill = ctk.CTkFont(family=family, size=11, weight="bold")

    outer = ctk.CTkFrame(root, fg_color=_BG, corner_radius=0)
    outer.pack(fill="both", expand=True, padx=22, pady=(18, 16))

    # SwiftUI "large title" başlık; sağında sessiz kayıt rozeti
    header = ctk.CTkFrame(outer, fg_color="transparent")
    header.pack(fill="x", pady=(0, 14))
    ctk.CTkLabel(header, text="Elyan", font=font_large_title, text_color=_TEXT, anchor="w").pack(side="left")

    saved_var = ctk.StringVar(value="")
    ctk.CTkLabel(
        header,
        textvariable=saved_var,
        font=font_subtitle,
        text_color=_ACCENT_TEXT,
        anchor="e",
    ).pack(side="right", pady=(10, 0))

    def _flash_saved(text: str = "Kaydedildi ✓") -> None:
        saved_var.set(text)
        root.after(1600, lambda: saved_var.set(""))

    def _apply(patch: dict[str, Any]) -> None:
        try:
            state_store.update_state(patch)
            _flash_saved()
        except Exception:
            _flash_saved("Kaydedilemedi!")

    def _section(title: str) -> ctk.CTkFrame:
        """SwiftUI inset-grouped bölüm: küçük büyük-harf başlık + yuvarlak kart."""
        ctk.CTkLabel(
            outer,
            text=title.upper(),
            font=font_section,
            text_color=_MUTED,
            anchor="w",
        ).pack(fill="x", padx=6, pady=(2, 4))
        card = ctk.CTkFrame(
            outer,
            fg_color=_CARD,
            corner_radius=16,
            border_width=1,
            border_color=_OUTLINE,
        )
        card.pack(fill="x", pady=(0, 12))
        return card

    def _row(card: ctk.CTkFrame, *, first: bool = False, last: bool = False) -> ctk.CTkFrame:
        row = ctk.CTkFrame(card, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(12 if first else 5, 12 if last else 5))
        return row

    def _pill(row: ctk.CTkFrame, var: ctk.StringVar, *, accent: bool = False) -> None:
        ctk.CTkLabel(
            row,
            textvariable=var,
            font=font_pill,
            text_color=_ACCENT_TEXT if accent else _MUTED,
            fg_color=_FIELD,
            corner_radius=99,
            padx=10,
            pady=2,
        ).pack(side="right")

    def _switch(card: ctk.CTkFrame, label: str, var: ctk.BooleanVar, command: Any, **row_kw: Any) -> None:
        row = _row(card, **row_kw)
        ctk.CTkLabel(row, text=label, font=font_body, text_color=_TEXT, anchor="w").pack(side="left")
        ctk.CTkSwitch(
            row,
            text="",
            variable=var,
            command=command,
            onvalue=True,
            offvalue=False,
            width=44,
            switch_width=42,
            switch_height=24,
            corner_radius=12,
            progress_color=_PRIMARY,
            fg_color=_SWITCH_OFF,
            button_color=_SWITCH_KNOB,
            button_hover_color=_SWITCH_KNOB,
        ).pack(side="right")

    # --- Durum -------------------------------------------------------------
    status_card = _section("Durum")
    conn_var = ctk.StringVar(value="…")
    account_var = ctk.StringVar(value="…")
    device_var = ctk.StringVar(value="…")
    tasks_var = ctk.StringVar(value="…")
    rows = (
        ("Bağlantı", conn_var, True),
        ("Hesap", account_var, False),
        ("Kimlik", device_var, False),
        ("Görevler", tasks_var, False),
    )
    for index, (label, var, accent) in enumerate(rows):
        row = _row(status_card, first=index == 0, last=index == len(rows) - 1)
        ctk.CTkLabel(row, text=label, font=font_body, text_color=_TEXT, anchor="w").pack(side="left")
        _pill(row, var, accent=accent)

    lifecycle_labels = {
        "ready": "Bağlı",
        "online": "Bağlı",
        "connected": "Bağlı",
        "reconnecting": "Yeniden bağlanıyor…",
        "offline": "Çevrimdışı",
        "stopped": "Durduruldu",
        "degraded": "Kısıtlı",
    }

    def _refresh_status() -> None:
        summary = _summary()
        runtime = state_store.snapshot().get("runtime", {})
        runtime = runtime if isinstance(runtime, dict) else {}
        connected = bool(summary.get("websocketConnected", False))
        lifecycle = str(summary.get("lifecycleState", "") or "stopped")
        conn_var.set("● Bağlı" if connected else lifecycle_labels.get(lifecycle, lifecycle))
        email = str(summary.get("email", "") or "")
        paired = bool(str(runtime.get("runtimeToken", "") or "").strip())
        account_var.set(email or ("Telefon eşleşmesi" if paired else "Bağlı değil"))
        device_id = str(runtime.get("deviceId", "") or "")
        device_var.set(device_id[:8] + "…" if device_id else "—")
        active = summary.get("activeTasks", []) or []
        tasks_var.set(str(len(active)) if active else "Yok")
        root.after(3000, _refresh_status)

    # --- Cihaz -------------------------------------------------------------
    device_card = _section("Cihaz")
    name_row = _row(device_card, first=True)
    ctk.CTkLabel(name_row, text="Cihaz adı", font=font_body, text_color=_TEXT, anchor="w").pack(side="left")
    name_var = ctk.StringVar(value=str(pairing.get("deviceName", "") or ""))
    name_entry = ctk.CTkEntry(
        name_row,
        textvariable=name_var,
        width=190,
        height=30,
        corner_radius=10,
        fg_color=_FIELD,
        border_color=_OUTLINE,
        border_width=1,
        text_color=_TEXT,
        font=font_body,
    )
    name_entry.pack(side="right")

    def _save_name(_event: Any = None) -> None:
        value = name_var.get().strip()[:64]
        if value:
            _apply({"pairing": {"deviceName": value}})

    name_entry.bind("<FocusOut>", _save_name)
    name_entry.bind("<Return>", _save_name)

    links_var = ctk.BooleanVar(value=bool(pairing.get("allowNewLinks", True)))
    _switch(
        device_card,
        "Yeni eşleşmelere izin ver",
        links_var,
        lambda: _apply({"pairing": {"allowNewLinks": links_var.get()}}),
    )

    action_row = _row(device_card, last=True)

    def _restart() -> None:
        _elyan_cli("restart")
        _flash_saved("Yeniden başlatılıyor…")

    def _unpair() -> None:
        if messagebox.askyesno(
            "Eşleşmeyi Kopar",
            "Bu bilgisayar telefondan görev alamayacak. Emin misin?",
            parent=root,
        ):
            _elyan_cli("unpair")
            _flash_saved("Eşleşme koparılıyor…")

    ctk.CTkButton(
        action_row,
        text="Yeniden Başlat",
        command=_restart,
        height=32,
        corner_radius=10,
        fg_color=_PRIMARY,
        hover_color=_PRIMARY_HOVER,
        text_color=_ON_PRIMARY,
        font=font_body,
    ).pack(side="left")
    ctk.CTkButton(
        action_row,
        text="Eşleşmeyi Kopar…",
        command=_unpair,
        height=32,
        corner_radius=10,
        fg_color="transparent",
        hover_color=_DANGER_HOVER,
        border_width=1,
        border_color=_DANGER,
        text_color=_DANGER,
        font=font_body,
    ).pack(side="left", padx=(10, 0))

    # --- Gizlilik ----------------------------------------------------------
    privacy_card = _section("Gizlilik")
    privacy_items = (
        ("localDataStaysLocal", "Yerel veri yerelde kalsın", True),
        ("analytics", "Anonim kullanım analitiği", False),
        ("redactCrashReports", "Kişisel veriyi maskele", True),
        ("autoClearHistory", "Geçmişi otomatik temizle", False),
    )
    for index, (key, label, default) in enumerate(privacy_items):
        var = ctk.BooleanVar(value=bool(privacy.get(key, default)))
        _switch(
            privacy_card,
            label,
            var,
            lambda k=key, v=var: _apply({"privacy": {k: v.get()}}),
            first=index == 0,
            last=index == len(privacy_items) - 1,
        )

    # Ayrı "Kapat" butonu yok — pencere native kapatma düğmesiyle kapanır
    # (SwiftUI ayar pencereleri gibi); kayıt geri bildirimi başlıkta.

    def _cleanup() -> None:
        try:
            _LOCK_PATH.unlink(missing_ok=True)
        except Exception:
            pass

    root.protocol("WM_DELETE_WINDOW", lambda: (_cleanup(), root.destroy()))
    _refresh_status()
    root.update_idletasks()
    # Ekran ortasına yerleştir (tk::PlaceWindow CTk ile her platformda tutarsız).
    width = root.winfo_reqwidth()
    height = root.winfo_reqheight()
    x = max(0, (root.winfo_screenwidth() - width) // 2)
    y = max(0, (root.winfo_screenheight() - height) // 3)
    root.geometry(f"+{x}+{y}")
    root.deiconify()  # kurulum tamam — pencereyi tek karede göster
    # Otomatik doğrulama modu: pencereyi kurup kısa süre sonra kendini kapatır
    # (CI/smoke-test; kullanıcı akışında etkisiz).
    if os.environ.get("ELYAN_SETTINGS_UI_SELFTEST"):
        root.after(1400, lambda: (_cleanup(), root.destroy()))
    try:
        root.mainloop()
    finally:
        _cleanup()
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(_REPO_ROOT))
    raise SystemExit(_run_window())
