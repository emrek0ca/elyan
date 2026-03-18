"""security.py — Güvenlik CLI komutları"""
import json
import os
import shutil
from pathlib import Path
from datetime import datetime, timedelta
from config.elyan_config import elyan_config
from security.keychain import keychain


def run(args):
    sub = getattr(args, "subcommand", None)
    if not sub or sub == "audit":
        run_security_audit(fix=getattr(args, "fix", False))
    elif sub == "status":
        security_status()
    elif sub == "events":
        security_events(
            severity=getattr(args, "severity", None),
            hours=getattr(args, "hours", 24),
        )
    elif sub == "sandbox":
        sandbox_status()
    elif sub == "keychain":
        keychain_status(
            migrate=getattr(args, "fix", False),
            clear_env=getattr(args, "clear_env", False),
        )
    else:
        print("Usage: elyan security [audit|status|events|sandbox|keychain]")


def run_security_audit(fix: bool = False):
    print("\n🔒  Elyan Güvenlik Denetimi\n" + "=" * 40)
    issues = 0

    # 1. Sandbox
    if shutil.which("docker"):
        enabled = elyan_config.get("sandbox.enabled", False)
        status = "ETKİN" if enabled else "DEVRE DIŞI"
        icon = "✅" if enabled else "⚠️ "
        print(f"{icon}  Sandbox: {status}")
        if not enabled:
            issues += 1
            if fix:
                elyan_config.set("sandbox.enabled", True)
                print("    → Sandbox etkinleştirildi.")
    else:
        print("⚠️   Sandbox: Docker kurulu değil (kod çalıştırma için önerilir)")
        issues += 1

    # 2. Config dosyası izinleri
    config_path = Path.home() / ".elyan" / "elyan.json"
    if config_path.exists():
        mode = oct(os.stat(config_path).st_mode)[-3:]
        ok = mode in ("600", "700")
        print(f"{'✅' if ok else '⚠️ '}  Config izinleri: {mode} {'(Güvenli)' if ok else '(Önerilen: 600)'}")
        if not ok:
            issues += 1
            if fix:
                os.chmod(config_path, 0o600)
                print("    → İzinler 600 olarak ayarlandı.")
    else:
        print("ℹ️   Config dosyası bulunamadı (~/.elyan/elyan.json)")

    # 3. Tool politikası
    policy = elyan_config.get("tools", {})
    deny_list = policy.get("deny", [])
    risky = [t for t in ["exec", "delete_file"] if t not in deny_list]
    if risky:
        print(f"⚠️   Riskli araçlar engellenmemiş: {risky}")
        issues += 1
        if fix:
            deny_list.extend(risky)
            policy["deny"] = list(set(deny_list))
            elyan_config.set("tools", policy)
            print(f"    → {risky} deny listesine eklendi.")
    else:
        print(f"✅  Tool politikası: {len(deny_list)} araç engellendi")

    # 4. Rate limiting
    rl = elyan_config.get("security.rateLimitPerMinute", 0)
    ok = rl > 0
    print(f"{'✅' if ok else '⚠️ '}  Rate limiting: {'etkin (' + str(rl) + '/dak)' if ok else 'DEVRE DIŞI'}")
    if not ok:
        issues += 1

    # 5. Operator modu
    op_mode = elyan_config.get("security.operatorMode", "Advisory")
    safe = op_mode in ("Advisory", "Assisted", "Confirmed")
    print(f"{'✅' if safe else '⚠️ '}  Operator modu: {op_mode}")
    if not safe:
        issues += 1

    # Özet
    print("\n" + "─" * 40)
    if issues == 0:
        print("✅  Denetim tamamlandı — sorun bulunamadı.")
    else:
        verb = "düzeltildi" if fix else "bulundu"
        print(f"⚠️   {issues} sorun {verb}. {'Düzeltmek için --fix kullanın.' if not fix else ''}")


def security_status():
    print("\n🛡️  Güvenlik Durumu\n" + "─" * 35)
    items = {
        "Sandbox": elyan_config.get("sandbox.enabled", False),
        "Denetim Logu": elyan_config.get("security.auditLog", True),
        "Rate Limiting": elyan_config.get("security.rateLimitPerMinute", 0) > 0,
        "Plan Onayı": elyan_config.get("security.requirePlanApproval", True),
    }
    for name, ok in items.items():
        print(f"  {'✅' if ok else '❌'}  {name}")
    print(f"\n  Operator Modu: {elyan_config.get('security.operatorMode', '?')}")


def keychain_status(migrate: bool = False, clear_env: bool = False):
    print("\n🔐  Keychain Durumu\n" + "─" * 35)
    available = keychain.is_available()
    print(f"  Keychain: {'✅ Kullanılabilir' if available else '❌ Kullanılamıyor (macOS gerekli)'}")

    env_path = Path(".env")
    audit = keychain.audit_env_plaintext(env_path)
    findings = audit.get("findings", [])
    print(f"  .env dosyası: {'✅' if audit.get('exists') else '❌'}")
    print(f"  Düz metin secret: {len(findings)}")
    for item in findings:
        print(f"    - {item['env_key']}")

    cfg_path = Path.home() / ".elyan" / "elyan.json"
    cfg_audit = keychain.audit_config_plaintext(cfg_path)
    cfg_findings = cfg_audit.get("findings", [])
    print(f"  Config dosyası: {'✅' if cfg_audit.get('exists') else '❌'} ({cfg_path})")
    print(f"  Config plaintext token: {len(cfg_findings)}")
    for item in cfg_findings:
        print(f"    - channels[{item['index']}].token ({item['channel_type']})")

    if migrate:
        result = keychain.migrate_from_env(env_path, clear_env=clear_env)
        migrated = result.get("migrated", 0)
        print(f"\n  Migration: {migrated} secret Keychain'e taşındı")
        if result.get("updated_env"):
            print("  .env güncellendi: migrated değerler boşaltıldı")
        if result.get("reason"):
            print(f"  Not: {result['reason']}")

        cfg_result = keychain.migrate_config_channel_tokens(cfg_path, clear_config=True)
        cfg_migrated = cfg_result.get("migrated", 0)
        print(f"  Config migration: {cfg_migrated} channel token Keychain'e taşındı")
        if cfg_result.get("updated_config"):
            print("  Config güncellendi: token alanları $ENV referansına çevrildi")
        if cfg_result.get("reason"):
            print(f"  Not (config): {cfg_result['reason']}")


def security_events(severity: str = None, hours: int = 24):
    """Güvenlik olaylarını audit veritabanından göster."""
    print(f"\n🔍  Güvenlik Olayları (son {hours}s)\n" + "─" * 50)
    try:
        import sqlite3
        audit_path = Path.home() / ".elyan" / "audit.db"
        if not audit_path.exists():
            # Proje içindeki fallback
            audit_path = Path("/Users/emrekoca/Desktop/bot/.elyan_audit/audit.db")
        if not audit_path.exists():
            print("Denetim veritabanı bulunamadı. Gateway'i başlatın.")
            return

        conn = sqlite3.connect(audit_path)
        cursor = conn.cursor()
        since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
        query = "SELECT timestamp, operation, risk_level, status FROM audit_log WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 50"
        params = [since]

        rows = cursor.execute(query, params).fetchall()
        conn.close()

        if not rows:
            print("Bu dönemde kayıt yok.")
            return

        for ts, op, risk, status in rows:
            if severity and risk and risk.lower() != severity.lower():
                continue
            risk_icon = {"high": "🔴", "medium": "🟡", "low": "🟢"}.get(
                (risk or "low").lower(), "⚪"
            )
            print(f"  {risk_icon} [{ts[:19]}] {op:<25} {status}")
    except Exception as e:
        print(f"Hata: {e}")


def sandbox_status():
    import shutil
    print("\n📦  Sandbox Durumu\n" + "─" * 35)
    docker = shutil.which("docker")
    print(f"  Docker: {'✅ ' + docker if docker else '❌ Kurulu değil'}")
    if docker:
        enabled = elyan_config.get("sandbox.enabled", False)
        mode = elyan_config.get("sandbox.mode", "docker")
        print(f"  Etkin: {'✅' if enabled else '❌'}")
        print(f"  Mod: {mode}")
        mem = elyan_config.get("sandbox.memoryLimit", "512m")
        print(f"  Bellek limiti: {mem}")
