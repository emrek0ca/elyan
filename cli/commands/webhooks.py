"""webhooks.py — Webhook yönetimi CLI (Yeni komut)"""
import json
from pathlib import Path
from config.elyan_config import elyan_config

def run(args):
    sub = getattr(args, "subcommand", None)
    if not sub:
        print("Usage: elyan webhooks [list|add|remove|test|logs]")
        return

    if sub == "list":
        _list(getattr(args, "json", False))
    elif sub == "add":
        _add(getattr(args, "name", None), getattr(args, "url", None))
    elif sub == "remove":
        _remove(getattr(args, "name", None))
    elif sub == "test":
        _test(getattr(args, "name", None))
    elif sub == "logs":
        _logs(getattr(args, "name", None))
    elif sub in ("gmail",):
        _gmail_setup(getattr(args, "action", "setup"), getattr(args, "account", None))
    else:
        print(f"Bilinmeyen alt komut: {sub}")


def _get_webhooks() -> list:
    return elyan_config.get("webhooks", [])


def _save_webhooks(webhooks: list):
    elyan_config.set("webhooks", webhooks)


def _list(as_json: bool = False):
    webhooks = _get_webhooks()
    if as_json:
        print(json.dumps(webhooks, indent=2, ensure_ascii=False))
        return
    if not webhooks:
        print("Kayıtlı webhook yok. 'elyan webhooks add <ad> <url>' ile ekleyin.")
        return
    print(f"{'AD':<18} {'URL':<40} {'DURUM'}")
    print("─" * 70)
    for wh in webhooks:
        url = wh.get("url", "?")
        url_disp = url[:37] + "..." if len(url) > 40 else url
        active = "Aktif" if wh.get("enabled", True) else "Pasif"
        print(f"{wh.get('name','?'):<18} {url_disp:<40} {active}")


def _add(name: str, url: str):
    if not name or not url:
        print("Hata: ad ve URL gereklidir.")
        print("Örnek: elyan webhooks add myhook https://example.com/hook")
        return
    webhooks = _get_webhooks()
    if any(w["name"] == name for w in webhooks):
        print(f"⚠️  '{name}' zaten mevcut.")
        return
    webhooks.append({"name": name, "url": url, "enabled": True})
    _save_webhooks(webhooks)
    print(f"✅  Webhook eklendi: {name} → {url}")


def _remove(name: str):
    if not name:
        print("Hata: webhook adı gereklidir.")
        return
    webhooks = _get_webhooks()
    before = len(webhooks)
    webhooks = [w for w in webhooks if w.get("name") != name]
    _save_webhooks(webhooks)
    removed = before - len(webhooks)
    print(f"{'✅' if removed else '⚠️'}  {removed} webhook kaldırıldı ({name}).")


def _test(name: str):
    webhooks = _get_webhooks()
    target = next((w for w in webhooks if w.get("name") == name), None)
    if not target and name:
        # URL doğrudan verilebilir
        url = name
    elif target:
        url = target.get("url")
    else:
        print("Hata: webhook adı veya URL gereklidir.")
        return

    import httpx
    print(f"Test payload gönderiliyor → {url}")
    try:
        resp = httpx.post(
            url,
            json={"event": "test", "source": "elyan-cli", "message": "Test webhook"},
            timeout=10,
        )
        print(f"✅  HTTP {resp.status_code} — {resp.text[:80]}")
    except Exception as e:
        print(f"❌  Hata: {e}")


def _logs(name: str = None):
    import httpx
    port = elyan_config.get("gateway.port", 18789)
    try:
        resp = httpx.get(
            f"http://localhost:{port}/api/webhooks/logs",
            params={"name": name} if name else {},
            timeout=5,
        )
        data = resp.json()
        logs = data.get("logs", [])
        if not logs:
            print("Log bulunamadı.")
            return
        for entry in logs[-20:]:
            print(f"  [{entry.get('time','')}] {entry.get('name','?'):<15} {entry.get('status','?')}")
    except Exception:
        print("Gateway çalışmıyor, log görüntülenemiyor.")


def _gmail_setup(action: str, account: str = None):
    """Gmail Pub/Sub webhook kurulum yardımcısı."""
    print("\n📧  Gmail Webhook Kurulumu")
    print("  1. Google Cloud Console'da Pub/Sub topic oluşturun.")
    print("  2. Gmail API → Watch isteği gönderin.")
    if account:
        print(f"  Hesap: {account}")
    print("  Detaylar için: https://developers.google.com/gmail/api/guides/push")
