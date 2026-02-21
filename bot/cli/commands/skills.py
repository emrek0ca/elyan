"""skills.py — Beceri (skill) yönetimi CLI"""
from __future__ import annotations

import json
from typing import Any

from core.skills.manager import skill_manager


def handle_skills(args):
    action = getattr(args, "action", None) or "list"
    name = getattr(args, "name", None)

    if action == "list":
        _list_skills(
            available=bool(getattr(args, "available", False)),
            enabled_only=bool(getattr(args, "enabled_only", False)),
        )
        return

    if action == "info":
        if not name:
            print("Hata: beceri adı gerekli.")
            return
        _skill_info(name)
        return

    if action == "install":
        if not name:
            print("Hata: beceri adı gerekli.")
            return
        ok, msg, _ = skill_manager.install_skill(name)
        print(("✅  " if ok else "❌  ") + msg)
        return

    if action == "enable":
        if not name:
            print("Hata: beceri adı gerekli.")
            return
        ok, msg, _ = skill_manager.set_enabled(name, True)
        print(("✅  " if ok else "❌  ") + msg)
        return

    if action == "disable":
        if not name:
            print("Hata: beceri adı gerekli.")
            return
        ok, msg, _ = skill_manager.set_enabled(name, False)
        print(("✅  " if ok else "❌  ") + msg)
        return

    if action == "update":
        if getattr(args, "update_all", False):
            result = skill_manager.update_skills(update_all=True)
        else:
            result = skill_manager.update_skills(name=name, update_all=False)
        updated = result.get("updated", [])
        skipped = result.get("skipped", [])
        if updated:
            print("✅  Güncellenen beceriler:")
            for s in updated:
                print(f"  - {s}")
        if skipped:
            print("⚠️  Atlanan beceriler:")
            for s in skipped:
                print(f"  - {s}")
        if not updated and not skipped:
            print("Güncellenecek beceri bulunamadı.")
        return

    if action == "remove":
        if not name:
            print("Hata: beceri adı gerekli.")
            return
        ok, msg = skill_manager.remove_skill(name)
        print(("✅  " if ok else "❌  ") + msg)
        return

    if action == "search":
        query = name or getattr(args, "query", "") or ""
        _search_skills(query)
        return

    if action == "check":
        _check_skills(name)
        return

    print(f"Bilinmeyen eylem: {action}")
    print("Usage: elyan skills [list|info|install|enable|disable|update|remove|search|check] <name>")


def _list_skills(*, available: bool = False, enabled_only: bool = False):
    skills = skill_manager.list_skills(available=available, enabled_only=enabled_only)
    if not skills:
        print("Beceri bulunamadı.")
        return

    print(f"{'AD':<16} {'SÜRÜM':<8} {'DURUM':<12} {'KAYNAK':<10} {'AÇIKLAMA'}")
    print("─" * 90)
    for s in skills:
        if s.get("installed"):
            st = "✅ aktif" if s.get("enabled") else "⚪ pasif"
        else:
            st = "⬇️ mevcut"
        desc = (s.get("description") or "")[:42]
        print(f"{s.get('name','?'):<16} {s.get('version','?'):<8} {st:<12} {s.get('source','?'):<10} {desc}")


def _skill_info(name: str):
    info = skill_manager.get_skill(name)
    if not info:
        print(f"Beceri bulunamadı: {name}")
        return
    print(json.dumps(info, indent=2, ensure_ascii=False))


def _search_skills(query: str):
    results = skill_manager.search(query)
    if not results:
        print(f"'{query}' için sonuç bulunamadı.")
        return
    print(f"'{query}' için {len(results)} sonuç:")
    for s in results:
        status = "installed" if s.get("installed") else "available"
        print(f"  • {s.get('name')} ({status}) — {s.get('description','')}")


def _check_skills(name: str | None):
    result = skill_manager.check(name=name)
    checks = result.get("checks", [])
    if not checks:
        print("Kontrol edilecek beceri bulunamadı.")
        return
    overall = "✅ OK" if result.get("ok") else "⚠️ Sorun var"
    print(f"Skill sağlık kontrolü: {overall}")
    for c in checks:
        ok = c.get("health_ok", False)
        prefix = "✅" if ok else "❌"
        print(f"{prefix} {c.get('name')} (enabled={c.get('enabled')})")
        if c.get("missing_tools"):
            print(f"   eksik tools: {', '.join(c['missing_tools'])}")
        if c.get("missing_dependencies"):
            print(f"   eksik bağımlılıklar: {', '.join(c['missing_dependencies'])}")
