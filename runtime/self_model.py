"""Öz-model — Elyan'ın kendini KODDAN tanıması.

NEDEN
-----
"Ben neyim, neyi yapabilirim, neyi yapamam" bilgisi bugüne kadar elle yazılmış
tanıtım metinlerinde duruyordu; kod değişince metin bayatlıyor ve model kendi
yetenekleri hakkında yanlış konuşuyordu (olmayan aracı vaat etmek ya da var
olanı reddetmek). Bu modül öz-kartı **çalışma zamanı gerçeklerinden türetir**:
kayıtlı yetenekler, gerçek izin durumu, eşleşme ve backend erişimi.

Değişmezler:
  * Elle yazılmış yetenek listesi YOK — tek kaynak `capability_registry`.
  * İzin durumu olduğu gibi bildirilir; kapalı izin "yapabilirim" diye
    sunulmaz. Model böylece kaçamak yerine dürüst sınır cümlesi kurar.
  * Kart sınırlıdır (özet sayılar + gruplar), tüm katalog prompt'a dökülmez.
"""

from __future__ import annotations

from typing import Any

SELF_MODEL_CONTRACT = "elyan.self_model.v1"

# İzin bayrağı → modelin anlayacağı kısa yetki adı. Bunlar yetenek DESENİ
# değildir; state'te zaten var olan izin anahtarlarının okunur karşılığıdır.
_PERMISSION_LABELS = {
    "allow_shell": "terminal",
    "allow_computer_control": "bilgisayar kontrolü",
    "allow_screen_analysis": "ekran okuma",
    "allow_browser_control": "tarayıcı",
    "allow_file_indexing": "dosya dizini",
    "allow_system_inspection": "sistem bilgisi",
    "allow_personal_actions": "kişisel eylemler",
    "allow_destructive_tools": "yıkıcı işlemler",
}


def _capability_groups() -> dict[str, int]:
    """Yetenekleri modül önekine göre kabaca gruplar (kaynak: registry)."""
    from runtime.capability_registry import capability_names

    groups: dict[str, int] = {}
    for name in capability_names():
        head = str(name).split(".", 1)[0].split("_", 1)[0]
        if not head:
            continue
        groups[head] = groups.get(head, 0) + 1
    return groups


def build_self_card(state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Çalışma zamanı gerçeklerinden öz-kart üretir.

    Hiçbir alan uydurulmaz: kaynak okunamazsa alan hiç eklenmez."""
    card: dict[str, Any] = {"contract": SELF_MODEL_CONTRACT}

    try:
        from runtime.capability_registry import capability_names

        names = capability_names()
        card["capabilityCount"] = len(names)
        groups = _capability_groups()
        # En kalabalık 6 grup: modele "hangi alanlarda yeteneğim var" fikri
        # verir, tüm katalog dökülmeden.
        card["capabilityGroups"] = [
            name
            for name, _count in sorted(
                groups.items(), key=lambda item: (-item[1], item[0])
            )[:6]
        ]
    except Exception:
        pass

    permissions = (state or {}).get("permissions") if isinstance(state, dict) else None
    if isinstance(permissions, dict):
        granted: list[str] = []
        denied: list[str] = []
        for key, label in _PERMISSION_LABELS.items():
            if key not in permissions:
                continue
            (granted if permissions.get(key) is True else denied).append(label)
        if granted:
            card["permissionsGranted"] = granted
        if denied:
            # KRİTİK: kapalı izinler AÇIKÇA bildirilir. Model "yapabilirim"
            # deyip sonra izin duvarına çarpmak yerine baştan dürüst olur.
            card["permissionsDenied"] = denied

    runtime = (state or {}).get("runtime") if isinstance(state, dict) else None
    runtime = runtime if isinstance(runtime, dict) else {}
    if "desktopPaired" in runtime:
        card["desktopPaired"] = runtime.get("desktopPaired") is True
    backend_ready = runtime.get("serverBrainReady")
    if backend_ready is not None:
        card["sharedBrainReady"] = backend_ready is True
    return card


def self_card_is_informative(card: dict[str, Any]) -> bool:
    """Kart yalnız sözleşme alanı taşıyorsa bağlama eklemeye değmez."""
    return len([key for key in card if key != "contract"]) > 0
