"""channels.py — Kanal yönetimi CLI"""
import json
from config.elyan_config import elyan_config
from security.keychain import keychain, KeychainManager

_SUPPORTED = ["telegram", "discord", "whatsapp", "slack", "signal", "webchat"]

def run(args):
    sub = getattr(args, "subcommand", None)
    if not sub:
        print("Usage: elyan channels [list|status|add|remove|enable|disable|test|login|logout|info|sync]")
        return

    channels: list = elyan_config.get("channels", [])

    # ── list ────────────────────────────────────────────────────────────
    if sub == "list":
        fmt = getattr(args, "json", False)
        if fmt:
            print(json.dumps(channels, indent=2))
        else:
            print(f"{'TYPE':<14} {'ID':<22} {'ENABLED':<9} {'STATUS'}")
            print("─" * 60)
            for ch in channels:
                st = "Aktif" if ch.get("enabled") else "Devre dışı"
                print(f"{ch.get('type','?'):<14} {ch.get('id','default'):<22} {str(ch.get('enabled','?')):<9} {st}")
        if not channels:
            print("Henüz kanal yapılandırılmamış. 'elyan channels add' ile ekleyin.")

    # ── status ──────────────────────────────────────────────────────────
    elif sub == "status":
        import httpx
        port = elyan_config.get("gateway.port", 18789)
        try:
            resp = httpx.get(f"http://localhost:{port}/api/channels", timeout=4)
            data = resp.json()
            print("Canlı kanal durumları (Gateway'den):")
            for ch in data.get("channels", []):
                icon = "✓" if ch.get("connected") else "✗"
                status = ch.get("status", "unknown")
                health = ch.get("health", {}) or {}
                retries = int(health.get("retries", 0))
                failures = int(health.get("failures", 0))
                last_error = health.get("last_error")
                line = f"  {icon} {ch.get('type','?'):<14} {str(status):<12} retry={retries} fail={failures}"
                if last_error:
                    line += f" err={str(last_error)[:80]}"
                print(line)
        except Exception:
            print("Gateway çalışmıyor, config durumu gösteriliyor:")
            for ch in channels:
                icon = "✓" if ch.get("enabled") else "✗"
                print(f"  {icon} {ch.get('type','?')}")

    # ── add ─────────────────────────────────────────────────────────────
    elif sub == "add":
        t = getattr(args, "type", None) or getattr(args, "channel_type", None)
        if not t:
            print(f"Desteklenen kanallar: {', '.join(_SUPPORTED)}")
            t = input("Kanal tipi: ").strip().lower()
        if t not in _SUPPORTED:
            print(f"Hata: '{t}' desteklenmiyor. Seçenekler: {', '.join(_SUPPORTED)}")
            return
        token = input(f"{t.capitalize()} bot token: ").strip()
        if not token:
            print("Token boş olamaz.")
            return

        env_key_map = {
            "telegram": "TELEGRAM_BOT_TOKEN",
            "discord": "DISCORD_BOT_TOKEN",
            "slack": "SLACK_BOT_TOKEN",
            "whatsapp": "WHATSAPP_BOT_TOKEN",
            "signal": "SIGNAL_BOT_TOKEN",
        }
        env_key = env_key_map.get(t)
        token_value = token
        if env_key:
            keychain_key = KeychainManager.key_for_env(env_key)
            if keychain_key and keychain.set_key(keychain_key, token):
                token_value = f"${env_key}"
            else:
                print("⚠️ Keychain yazılamadı; token config dosyasına düz metin kaydedilecek.")

        entry = {"type": t, "id": t, "token": token_value, "enabled": True}
        channels.append(entry)
        elyan_config.set("channels", channels)
        print(f"✅  {t} kanalı eklendi. Token kaydedildi.")

    # ── remove ──────────────────────────────────────────────────────────
    elif sub == "remove":
        cid = getattr(args, "channel_id", None)
        if not cid:
            print("Hata: kanal id gerekli.")
            return
        before = len(channels)
        channels = [c for c in channels if c.get("id") != cid and c.get("type") != cid]
        elyan_config.set("channels", channels)
        removed = before - len(channels)
        print(f"{'✅' if removed else '⚠️'}  {removed} kanal kaldırıldı ({cid}).")

    # ── enable / disable ────────────────────────────────────────────────
    elif sub in ("enable", "disable"):
        cid = getattr(args, "channel_id", None)
        enabled = (sub == "enable")
        found = False
        for ch in channels:
            if ch.get("id") == cid or ch.get("type") == cid:
                ch["enabled"] = enabled
                found = True
        if found:
            elyan_config.set("channels", channels)
            print(f"✅  {cid} {'etkinleştirildi' if enabled else 'devre dışı bırakıldı'}.")
        else:
            print(f"Kanal bulunamadı: {cid}")

    # ── test ────────────────────────────────────────────────────────────
    elif sub == "test":
        import httpx
        cid = getattr(args, "channel_id", None) or "tümü"
        port = elyan_config.get("gateway.port", 18789)
        print(f"Test mesajı gönderiliyor → {cid}...")
        try:
            resp = httpx.post(
                f"http://localhost:{port}/api/channels/test",
                json={"channel": cid},
                timeout=10,
            )
            result = resp.json()
            print(f"{'✅' if result.get('ok') else '❌'}  {result.get('message','Yanıt yok')}")
        except Exception as e:
            print(f"❌  Gateway erişilemedi: {e}")

    # ── info ────────────────────────────────────────────────────────────
    elif sub == "info":
        cid = getattr(args, "channel_id", None)
        found = next((c for c in channels if c.get("id") == cid or c.get("type") == cid), None)
        if found:
            masked = {k: ("***" if "token" in k.lower() or "key" in k.lower() else v)
                      for k, v in found.items()}
            print(json.dumps(masked, indent=2, ensure_ascii=False))
        else:
            print(f"Kanal bulunamadı: {cid}")

    # ── login ────────────────────────────────────────────────────────────
    elif sub == "login":
        cid = getattr(args, "channel_id", "telegram")
        print(f"{cid} kimlik doğrulama:")
        if cid == "telegram":
            print("  Bot token zaten yapılandırılmış. Bot'a /start mesajı gönderin.")
        elif cid == "whatsapp":
            print("  WhatsApp bağlantısı için QR kod gerekiyor.")
            print("  Gateway çalışırken dashboard'u açın: elyan dashboard")
        else:
            print(f"  {cid} için interaktif login henüz desteklenmiyor.")

    # ── logout ───────────────────────────────────────────────────────────
    elif sub == "logout":
        cid = getattr(args, "channel_id", None)
        print(f"⚠️  {cid} oturumu kapatılıyor...")
        for ch in channels:
            if ch.get("id") == cid or ch.get("type") == cid:
                ch["enabled"] = False
        elyan_config.set("channels", channels)
        print(f"✅  {cid} devre dışı bırakıldı (logout).")

    # ── sync ─────────────────────────────────────────────────────────────
    elif sub == "sync":
        import httpx
        port = elyan_config.get("gateway.port", 18789)
        print("Kanallar senkronize ediliyor...")
        try:
            resp = httpx.post(f"http://localhost:{port}/api/channels/sync", timeout=15)
            print(f"✅  {resp.json().get('message', 'Senkronizasyon tamamlandı.')}")
        except Exception as e:
            print(f"❌  Gateway erişilemedi: {e}")

    else:
        print(f"Bilinmeyen alt komut: {sub}")
        print("Usage: elyan channels [list|status|add|remove|enable|disable|test|login|logout|info|sync]")
