"""cron.py — Cron/zamanlayıcı CLI"""
import asyncio
import json
from datetime import datetime
from config.elyan_config import elyan_config

def _get_engine():
    try:
        from core.scheduler.cron_engine import get_cron_engine

        return get_cron_engine()
    except Exception:
        return None


def run(args):
    sub = getattr(args, "subcommand", None)
    if not sub:
        print("Usage: elyan cron [list|status|add|rm|enable|disable|run|history|next]")
        return

    engine = _get_engine()

    if sub == "list":
        _list_jobs(engine)
    elif sub == "status":
        _status(engine)
    elif sub == "add":
        _add(args, engine)
    elif sub in ("rm", "remove"):
        _remove(args, engine)
    elif sub == "enable":
        _toggle(args, True, engine)
    elif sub == "disable":
        _toggle(args, False, engine)
    elif sub == "run":
        _run_now(args, engine)
    elif sub == "history":
        _history(args, engine)
    elif sub == "next":
        _next(args, engine)
    else:
        print(f"Bilinmeyen alt komut: {sub}")


def _list_jobs(engine):
    jobs = engine.list_jobs() if engine and hasattr(engine, "list_jobs") else elyan_config.get("cron", [])
    if not jobs:
        print("Kayıtlı cron işi yok.")
        return
    print(f"{'ID':<14} {'EXPRESSION':<16} {'DURUM':<8} {'PROMPT'}")
    print("─" * 70)
    for j in jobs:
        enabled = "Aktif" if j.get("enabled", True) else "Pasif"
        prompt = (j.get("prompt") or "")[:35]
        print(f"{j.get('id','?'):<14} {j.get('expression','?'):<16} {enabled:<8} {prompt}")


def _status(engine):
    jobs = engine.list_jobs() if engine and hasattr(engine, "list_jobs") else elyan_config.get("cron", [])
    active = len([j for j in jobs if j.get("enabled", True)])
    print(f"\n⏰  Cron Durumu")
    print(f"  Toplam iş: {len(jobs)}")
    print(f"  Aktif: {active}")
    print(f"  Pasif: {len(jobs) - active}")
    if engine and hasattr(engine, "running"):
        print(f"  Motor: {'Çalışıyor' if engine.running else 'Durduruldu'}")


def _add(args, engine):
    expression = getattr(args, "expression", None)
    prompt = getattr(args, "prompt", None)
    if not expression or not prompt:
        print("Hata: --expression ve --prompt gereklidir.")
        print("Örnek: elyan cron add --expression '0 9 * * *' --prompt 'Sabah özeti'")
        return

    if engine:
        job_id = engine.add_job(
            {
                "expression": expression,
                "prompt": prompt,
                "channel_id": getattr(args, "channel", None),
                "user_id": getattr(args, "user_id", "admin"),
                "enabled": True,
                "job_type": "prompt",
                "source": "runtime",
            }
        )
    else:
        import uuid
        job_id = str(uuid.uuid4())[:8]
        jobs = elyan_config.get("cron", [])
        jobs.append({
            "id": job_id,
            "expression": expression,
            "prompt": prompt,
            "enabled": True,
            "channel": getattr(args, "channel", None),
        })
        elyan_config.set("cron", jobs)

    print(f"✅  Cron işi eklendi — ID: {job_id}")


def _remove(args, engine):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        print("Hata: iş ID'si gerekli.")
        return
    if engine and hasattr(engine, "remove_job"):
        ok = engine.remove_job(job_id)
    else:
        jobs = elyan_config.get("cron", [])
        new_jobs = [j for j in jobs if j.get("id") != job_id]
        ok = len(new_jobs) < len(jobs)
        elyan_config.set("cron", new_jobs)
    print(f"{'✅' if ok else '⚠️'}  {job_id} {'kaldırıldı' if ok else 'bulunamadı'}.")


def _toggle(args, enable: bool, engine):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        print("Hata: iş ID'si gerekli.")
        return
    if engine and hasattr(engine, "enable_job") and hasattr(engine, "disable_job"):
        found = engine.enable_job(job_id) if enable else engine.disable_job(job_id)
    else:
        jobs = elyan_config.get("cron", [])
        found = False
        for j in jobs:
            if j.get("id") == job_id:
                j["enabled"] = enable
                found = True
        if found:
            elyan_config.set("cron", jobs)
    if found:
        verb = "etkinleştirildi" if enable else "durduruldu"
        print(f"✅  {job_id} {verb}.")
    else:
        print(f"⚠️  İş bulunamadı: {job_id}")


def _run_now(args, engine):
    job_id = getattr(args, "job_id", None)
    if not job_id:
        print("Hata: iş ID'si gerekli.")
        return
    if engine and hasattr(engine, "run_job"):
        print(f"▶  {job_id} tetikleniyor...")
        result = asyncio.run(engine.run_job(job_id))
        if result.get("success", False):
            print("✅  Tamamlandı.")
        else:
            print(f"⚠️  Çalıştırılamadı: {result.get('error') or result.get('report') or 'unknown_error'}")
    else:
        print(f"⚠️  Cron motoru çalışmıyor. Gateway'i başlatın: elyan gateway start")


def _history(args, engine):
    job_id = getattr(args, "job_id", None)
    if engine and hasattr(engine, "get_history"):
        history = engine.get_history(job_id)
        for entry in (history or []):
            print(f"  [{entry.get('time','')}] {entry.get('status','')} — {entry.get('message','')}")
    else:
        print("Geçmiş bilgisi mevcut değil. Gateway çalışmalı.")


def _next(args, engine):
    job_id = getattr(args, "job_id", None)
    try:
        from croniter import croniter
        jobs = engine.list_jobs() if engine and hasattr(engine, "list_jobs") else elyan_config.get("cron", [])
        targets = [j for j in jobs if not job_id or j.get("id") == job_id]
        for j in targets:
            expr = j.get("expression")
            if expr:
                it = croniter(expr, datetime.now())
                nxt = it.get_next(datetime)
                print(f"  {j['id']:<14} → {nxt.strftime('%Y-%m-%d %H:%M')}")
    except ImportError:
        print("⚠️  croniter paketi gerekli: pip install croniter")
    except Exception as e:
        print(f"Hata: {e}")
