from __future__ import annotations

from typing import Any


def build_install_to_ui_guide(*, setup_ready: bool, gateway_running: bool | None = None) -> dict[str, Any]:
    """
    Build a small, human-readable path from first setup to the desktop UI.

    The caller only needs to provide two booleans:
    - setup_ready: whether the local configuration is sufficient to launch
    - gateway_running: whether the gateway is already up
    """

    if not setup_ready:
        current = "elyan setup"
    elif gateway_running:
        current = "elyan desktop"
    else:
        current = "elyan launch"

    steps = [
        {
            "index": 1,
            "command": "elyan setup",
            "detail": "İlk kurulum, model seçimi ve yerel konfigürasyon",
        },
        {
            "index": 2,
            "command": "elyan launch",
            "detail": "Gateway'i ayağa kaldır ve runtime readiness'i doğrula",
        },
        {
            "index": 3,
            "command": "elyan desktop",
            "detail": "Desktop arayüzünü aç",
        },
        {
            "index": 4,
            "command": "bootstrap-owner -> login -> auth/me -> logout",
            "detail": "İlk kullanıcı hesabı ve session zincirini doğrula",
        },
        {
            "index": 5,
            "command": "elyan channels / elyan routines",
            "detail": "Kanal bağlantıları ve otomasyonları tamamla",
        },
    ]

    return {
        "title": "Kurulumdan UI'ya",
        "current": current,
        "steps": steps,
        "verification": steps[3]["command"],
        "next_surface": "Desktop",
    }


def render_install_to_ui_guide(
    *,
    setup_ready: bool,
    gateway_running: bool | None = None,
    prefix: str = "  ",
) -> None:
    guide = build_install_to_ui_guide(setup_ready=setup_ready, gateway_running=gateway_running)
    print(f"{prefix}{guide['title']}")
    print(f"{prefix}  Şu an: {guide['current']}")
    print(f"{prefix}  Yol:   elyan setup → elyan launch → elyan desktop")
    print(f"{prefix}  Doğrulama: {guide['verification']}")
    print(f"{prefix}  Sonra: elyan channels / elyan routines")
