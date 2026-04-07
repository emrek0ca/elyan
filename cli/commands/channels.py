"""channels.py — Kanal yönetimi CLI."""
from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from config.elyan_config import elyan_config
from core.gateway.adapters.whatsapp_bridge import (
    BRIDGE_ENV_KEY,
    BRIDGE_HOST,
    DEFAULT_BRIDGE_PORT,
    BridgeRuntimeError,
    build_bridge_url,
    default_session_dir,
    ensure_bridge_runtime,
    generate_bridge_token,
    start_bridge_process,
    stop_bridge,
    wait_for_bridge,
)
from security.keychain import KeychainManager, keychain

_SUPPORTED = ["telegram", "discord", "whatsapp", "slack", "signal", "sms", "webchat"]


def _mask_sensitive_fields(data: Any) -> Any:
    markers = ("token", "secret", "password", "api_key", "apikey", "key")
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if any(m in str(k).lower() for m in markers):
                out[k] = "***" if v not in (None, "") else ""
            else:
                out[k] = _mask_sensitive_fields(v)
        return out
    if isinstance(data, list):
        return [_mask_sensitive_fields(x) for x in data]
    return data


def _load_channels() -> List[Dict[str, Any]]:
    channels = elyan_config.get("channels", [])
    return channels if isinstance(channels, list) else []


def _save_channels(channels: List[Dict[str, Any]]) -> None:
    elyan_config.set("channels", channels)


def _upsert_channel(channels: List[Dict[str, Any]], entry: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    inserted = False
    entry_id = str(entry.get("id") or entry.get("type") or "").strip().lower()
    entry_type = str(entry.get("type") or "").strip().lower()
    for ch in channels:
        if not isinstance(ch, dict):
            continue
        ch_id = str(ch.get("id") or ch.get("type") or "").strip().lower()
        ch_type = str(ch.get("type") or "").strip().lower()
        if ch_id == entry_id or (entry_type and ch_type == entry_type):
            out.append(entry)
            inserted = True
        else:
            out.append(ch)
    if not inserted:
        out.append(entry)
    return out


def _store_secret(env_key: str, secret: str) -> str:
    keychain_key = KeychainManager.key_for_env(env_key)
    if keychain_key and keychain.set_key(keychain_key, secret):
        return f"${env_key}"
    print("⚠️ Keychain yazılamadı; secret config dosyasına düz metin kaydedilecek.")
    return secret


def _find_channel(channels: List[Dict[str, Any]], cid: str) -> Optional[Dict[str, Any]]:
    target = str(cid or "").strip().lower()
    for ch in channels:
        if not isinstance(ch, dict):
            continue
        ch_id = str(ch.get("id") or "").strip().lower()
        ch_type = str(ch.get("type") or "").strip().lower()
        if target in {ch_id, ch_type}:
            return ch
    return None


def login_whatsapp(
    channel_id: str = "whatsapp",
    *,
    bridge_port: int = DEFAULT_BRIDGE_PORT,
    session_dir: Optional[Path] = None,
    timeout_s: int = 180,
) -> bool:
    """Interactive WhatsApp QR pairing and secure channel configuration."""
    channel_id = str(channel_id or "whatsapp").strip() or "whatsapp"
    session_dir = Path(session_dir or default_session_dir(channel_id)).expanduser()
    bridge_port = int(bridge_port or DEFAULT_BRIDGE_PORT)
    bridge_url = build_bridge_url(BRIDGE_HOST, bridge_port)

    print("🔐 WhatsApp QR eşleştirme başlatılıyor...")
    print(f"  Bridge URL: {bridge_url}")
    print(f"  Session:    {session_dir}")

    try:
        ensure_bridge_runtime(force_install=False)
    except BridgeRuntimeError as exc:
        print(f"❌  WhatsApp runtime hazır değil: {exc}")
        print("    Çözüm: Node.js 18+ kurup tekrar deneyin.")
        return False

    bridge_secret = generate_bridge_token()
    bridge_token_ref = _store_secret(BRIDGE_ENV_KEY, bridge_secret)

    proc = None
    try:
        proc = start_bridge_process(
            session_dir=session_dir,
            token=bridge_secret,
            host=BRIDGE_HOST,
            port=bridge_port,
            print_qr=True,
            detached=False,
            client_id=channel_id,
        )
        print("\n📱 Telefonda: WhatsApp > Bağlı Cihazlar > Cihaz Bağla ile QR okutun.")
        wait_for_bridge(
            bridge_url=bridge_url,
            token=bridge_secret,
            timeout_s=max(30, timeout_s),
            require_connected=True,
            poll_interval_s=1.0,
        )
        print("✅  WhatsApp eşleşmesi tamamlandı.")
    except Exception as exc:
        print(f"❌  WhatsApp QR login başarısız: {exc}")
        if proc and proc.poll() is None:
            proc.terminate()
        return False
    finally:
        stop_bridge(bridge_url=bridge_url, token=bridge_secret, timeout_s=3.0)
        if proc and proc.poll() is None:
            try:
                proc.wait(timeout=6)
            except Exception:
                proc.kill()

    # Re-run bridge detached for always-on gateway runtime.
    try:
        start_bridge_process(
            session_dir=session_dir,
            token=bridge_secret,
            host=BRIDGE_HOST,
            port=bridge_port,
            print_qr=False,
            detached=True,
            client_id=channel_id,
        )
        wait_for_bridge(
            bridge_url=bridge_url,
            token=bridge_secret,
            timeout_s=25,
            require_connected=False,
            poll_interval_s=1.0,
        )
    except Exception as exc:
        print(f"⚠️ Bridge arka planda başlatılamadı: {exc}")
        print("   Gateway, `auto_start_bridge` ile gerektiğinde yeniden başlatmayı deneyecek.")

    channels = _load_channels()
    entry = {
        "type": "whatsapp",
        "id": channel_id,
        "enabled": True,
        "bridge_url": bridge_url,
        "bridge_host": BRIDGE_HOST,
        "bridge_port": bridge_port,
        "bridge_token": bridge_token_ref,
        "session_dir": str(session_dir),
        "client_id": channel_id,
        "auto_start_bridge": True,
    }
    channels = _upsert_channel(channels, entry)
    _save_channels(channels)
    print("✅  WhatsApp kanalı kaydedildi ve etkinleştirildi.")
    return True


def configure_whatsapp_cloud(channel_id: str = "whatsapp") -> bool:
    """Interactive WhatsApp Cloud API setup (Meta webhook mode)."""
    channel_id = str(channel_id or "whatsapp").strip() or "whatsapp"
    print("☁️ WhatsApp Cloud API yapılandırması:")
    phone_number_id = input("  Phone Number ID: ").strip()
    access_token = input("  Access Token: ").strip()
    verify_token = input("  Verify Token (boş bırakılırsa otomatik üretilecek): ").strip()

    if not phone_number_id:
        print("❌ Phone Number ID zorunlu.")
        return False
    if not access_token:
        print("❌ Access Token zorunlu.")
        return False
    if not verify_token:
        verify_token = secrets.token_urlsafe(24)

    access_ref = _store_secret("WHATSAPP_ACCESS_TOKEN", access_token)
    verify_ref = _store_secret("WHATSAPP_VERIFY_TOKEN", verify_token)

    channels = _load_channels()
    entry = {
        "type": "whatsapp",
        "id": channel_id,
        "mode": "cloud",
        "enabled": True,
        "phone_number_id": phone_number_id,
        "access_token": access_ref,
        "verify_token": verify_ref,
        "webhook_path": "/whatsapp/webhook",
        "graph_base_url": "https://graph.facebook.com/v20.0",
    }
    channels = _upsert_channel(channels, entry)
    _save_channels(channels)

    host = str(elyan_config.get("gateway.host", "127.0.0.1") or "127.0.0.1")
    port = int(elyan_config.get("gateway.port", 18789) or 18789)
    print("✅  WhatsApp Cloud kanalı kaydedildi.")
    print(f"🔗 Meta webhook URL: http://{host}:{port}/whatsapp/webhook")
    print("   Not: Dışarıdan erişim için bu endpoint'i public HTTPS ile yayınlayın.")
    return True


def run(args):
    sub = getattr(args, "subcommand", None)
    if not sub:
        print("Usage: elyan channels [list|status|add|remove|enable|disable|test|login|logout|info|sync]")
        return

    channels = _load_channels()

    # ── list ────────────────────────────────────────────────────────────
    if sub == "list":
        fmt = getattr(args, "json", False)
        if fmt:
            print(json.dumps(_mask_sensitive_fields(channels), indent=2, ensure_ascii=False))
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
        t = str(t or "").strip().lower()
        if t not in _SUPPORTED:
            print(f"Hata: '{t}' desteklenmiyor. Seçenekler: {', '.join(_SUPPORTED)}")
            return

        if t == "whatsapp":
            mode = input("WhatsApp modu [1=QR/Bridge, 2=Cloud API] (varsayılan 1): ").strip().lower()
            if mode in {"2", "cloud", "api"}:
                configure_whatsapp_cloud(channel_id="whatsapp")
            else:
                login_whatsapp(channel_id="whatsapp")
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
        if t == "sms":
            account_sid = input("Twilio Account SID: ").strip()
            auth_token = input("Twilio Auth Token: ").strip()
            from_number = input("Twilio From Number: ").strip()
            if not account_sid or not auth_token or not from_number:
                print("SMS kurulumu için Account SID, Auth Token ve From Number zorunlu.")
                return
            auth_token_value = _store_secret("TWILIO_AUTH_TOKEN", auth_token)
            entry = {
                "type": "sms",
                "id": "sms",
                "account_sid": account_sid,
                "auth_token": auth_token_value,
                "from_number": from_number,
                "webhook_path": "/sms/webhook",
                "enabled": True,
            }
            channels = _upsert_channel(channels, entry)
            _save_channels(channels)
            print("✅ SMS kanalı kaydedildi.")
            return
        env_key = env_key_map.get(t)
        token_value = token
        if env_key:
            token_value = _store_secret(env_key, token)

        entry = {"type": t, "id": t, "token": token_value, "enabled": True}
        channels = _upsert_channel(channels, entry)
        _save_channels(channels)
        print(f"✅  {t} kanalı eklendi. Token kaydedildi.")

    # ── remove ──────────────────────────────────────────────────────────
    elif sub == "remove":
        cid = getattr(args, "channel_id", None)
        if not cid:
            print("Hata: kanal id gerekli.")
            return
        before = len(channels)
        channels = [c for c in channels if c.get("id") != cid and c.get("type") != cid]
        _save_channels(channels)
        removed = before - len(channels)
        print(f"{'✅' if removed else '⚠️'}  {removed} kanal kaldırıldı ({cid}).")

    # ── enable / disable ────────────────────────────────────────────────
    elif sub in ("enable", "disable"):
        cid = getattr(args, "channel_id", None)
        enabled = sub == "enable"
        found = False
        for ch in channels:
            if ch.get("id") == cid or ch.get("type") == cid:
                ch["enabled"] = enabled
                found = True
        if found:
            _save_channels(channels)
            print(f"✅  {cid} {'etkinleştirildi' if enabled else 'devre dışı bırakıldı'}.")
        else:
            print(f"Kanal bulunamadı: {cid}")

    # ── test ────────────────────────────────────────────────────────────
    elif sub == "test":
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
        found = _find_channel(channels, str(cid or ""))
        if found:
            print(json.dumps(_mask_sensitive_fields(found), indent=2, ensure_ascii=False))
        else:
            print(f"Kanal bulunamadı: {cid}")

    # ── login ────────────────────────────────────────────────────────────
    elif sub == "login":
        cid = str(getattr(args, "channel_id", "telegram") or "telegram").strip().lower()
        print(f"{cid} kimlik doğrulama:")
        if cid == "telegram":
            print("  Bot token zaten yapılandırılmış. Bot'a /start mesajı gönderin.")
        elif cid == "whatsapp":
            existing = _find_channel(channels, "whatsapp") or {}
            mode = str(existing.get("mode") or "bridge").strip().lower()
            if mode == "cloud":
                print("  Cloud mode aktif. QR login gerekmez.")
                verify_ref = str(existing.get("verify_token") or "").strip()
                phone_number_id = str(existing.get("phone_number_id") or "").strip()
                print(f"  phone_number_id: {phone_number_id or '—'}")
                print(f"  verify_token: {'set' if verify_ref else 'missing'}")
                print("  Webhook endpoint: /whatsapp/webhook")
            else:
                login_whatsapp(channel_id="whatsapp")
        else:
            print(f"  {cid} için interaktif login henüz desteklenmiyor.")

    # ── logout ───────────────────────────────────────────────────────────
    elif sub == "logout":
        cid = getattr(args, "channel_id", None)
        if not cid:
            print("Hata: kanal id gerekli.")
            return
        print(f"⚠️  {cid} oturumu kapatılıyor...")
        target = _find_channel(channels, str(cid))
        if target and str(target.get("type", "")).lower() == "whatsapp" and str(target.get("mode", "bridge")).lower() != "cloud":
            bridge_url = str(target.get("bridge_url") or build_bridge_url(BRIDGE_HOST, int(target.get("bridge_port", DEFAULT_BRIDGE_PORT))))
            bridge_token = str(target.get("bridge_token") or "")
            if stop_bridge(bridge_url=bridge_url, token=bridge_token, timeout_s=3):
                print("  ✓ WhatsApp bridge durduruldu.")
        for ch in channels:
            if ch.get("id") == cid or ch.get("type") == cid:
                ch["enabled"] = False
        _save_channels(channels)
        print(f"✅  {cid} devre dışı bırakıldı (logout).")

    # ── sync ─────────────────────────────────────────────────────────────
    elif sub == "sync":
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
