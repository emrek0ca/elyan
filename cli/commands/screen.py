"""
CLI: screen commands — Visual analysis, OCR, accessibility.
Usage:
  elyan screen analyze [TARGET] [--prompt TEXT] [--type comprehensive|ocr|ui] [--format text|json|md] [--session ID]
  elyan screen ocr [TARGET] [--format text|json]
  elyan screen accessibility [--app APP] [--format text|json]
  elyan screen session SESSION_ID [--format text|json|md]
  elyan screen list [--format text|json]
"""

import asyncio
import click
import json
from pathlib import Path


def _get_vision_engine():
    """Get VisionEngine instance."""
    from core.vision import get_vision_engine
    return get_vision_engine()


@click.group("screen")
def screen_group():
    """👁️ Gorsel Analiz — OCR, erisilebilirlik, gorsel zeka."""
    pass


@screen_group.command("analyze")
@click.argument("target", required=False)
@click.option(
    "--prompt",
    default=None,
    help="Gorsel analiz icin prompt"
)
@click.option(
    "--type",
    "analysis_type",
    type=click.Choice(["comprehensive", "ocr", "ui", "diff"], case_sensitive=False),
    default="comprehensive",
    help="Analiz tipi"
)
@click.option(
    "--format",
    type=click.Choice(["text", "json", "md"], case_sensitive=False),
    default="text",
    help="Cikti biçimi"
)
@click.option(
    "--session",
    default=None,
    help="Oturum ID'si (isteğe bağlı)"
)
def screen_analyze(target: str, prompt: str, analysis_type: str, format: str, session: str):
    """Gorsel analiz yap — resim dosyasi veya ekran goruntusu."""
    async def _run():
        engine = _get_vision_engine()

        if not prompt:
            prompt = "Gorseli detayli analiz et. Metinleri, nesneleri, baglami acikla."

        click.echo(f"👁️  Gorsel Analiz: {target or 'Ekran Goruntusu'}")
        click.echo(f"   Tip: {analysis_type}")
        if session:
            click.echo(f"   Oturum: {session}")
        click.echo("")

        result = await engine.capture_and_analyze(target, prompt, analysis_type)

        # Save to session if provided
        if session and result.success:
            try:
                from core.vision import get_vision_session, save_vision_session
                sess = get_vision_session(session)
                if not sess:
                    from core.vision.session import VisionSession
                    sess = VisionSession(session_id=session)
                sess.add_entry(
                    result.image_path or "live",
                    analysis_type,
                    result.text,
                )
                save_vision_session(sess)
                click.echo(f"✓ Oturum kaydedildi: {session}")
                click.echo("")
            except Exception as e:
                click.echo(f"⚠ Oturum kaydedilemedi: {e}", err=True)

        # Format output
        if format.lower() == "json":
            from core.vision import format_json
            click.echo(format_json(result))
        elif format.lower() == "md":
            from core.vision import format_md
            click.echo(format_md(result))
        else:  # text
            from core.vision import format_text
            click.echo(format_text(result))

    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)


@screen_group.command("ocr")
@click.argument("target", required=False)
@click.option(
    "--format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Cikti biçimi"
)
def screen_ocr(target: str, format: str):
    """Metni Gorsel Okuma (OCR) ile cikart."""
    async def _run():
        engine = _get_vision_engine()

        click.echo(f"📝 OCR: {target or 'Ekran Goruntusu'}")
        click.echo("")

        result = await engine.ocr(target)

        if format.lower() == "json":
            from core.vision import format_json
            click.echo(format_json(result))
        else:  # text
            from core.vision import format_text
            click.echo(format_text(result))

    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)


@screen_group.command("accessibility")
@click.option(
    "--app",
    default=None,
    help="Uygulama adi (isteğe bağlı)"
)
@click.option(
    "--format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Cikti biçimi"
)
def screen_accessibility(app: str, format: str):
    """Erisilebilirlik agaci (UI ogeleri, dugmeler, alanlar)."""
    async def _run():
        engine = _get_vision_engine()

        click.echo("🔍 Erisilebilirlik Avraci")
        if app:
            click.echo(f"   Uygulama: {app}")
        click.echo("")

        result = await engine.accessibility(app)

        if format.lower() == "json":
            from core.vision import format_json
            click.echo(format_json(result))
        else:  # text
            from core.vision import format_text
            click.echo(format_text(result))

    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)


@screen_group.command("session")
@click.argument("session_id")
@click.option(
    "--format",
    type=click.Choice(["text", "json", "md"], case_sensitive=False),
    default="text",
    help="Cikti biçimi"
)
def screen_session(session_id: str, format: str):
    """Gecmis gorsel analiz oturumunu goster."""
    try:
        from core.vision import get_vision_session

        session = get_vision_session(session_id)
        if not session:
            click.echo(f"✗ Oturum bulunamadi: {session_id}", err=True)
            return

        if format.lower() == "json":
            click.echo(json.dumps(session.to_dict(), indent=2, ensure_ascii=False))
        else:  # text
            click.echo(f"📸 Oturum: {session.session_id}")
            click.echo(f"   Olusturuldu: {session.created_at}")
            click.echo(f"   Guncellenendi: {session.updated_at}")
            click.echo(f"   Girdi Sayisi: {len(session.entries)}")
            click.echo("")

            for i, entry in enumerate(session.entries, 1):
                click.echo(f"[{i}] {entry.get('analysis_type', 'unknown')}")
                click.echo(f"    Dosya: {entry.get('image_path', '?')}")
                click.echo(f"    Zaman: {entry.get('timestamp', '?')}")

    except Exception as e:
        click.echo(f"✗ Oturum gosterilemedi: {e}", err=True)


@screen_group.command("list")
@click.option(
    "--format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Cikti biçimi"
)
def screen_list(format: str):
    """Tum gorsel analiz oturumlarini listele."""
    try:
        from core.vision import list_vision_sessions

        sessions = list_vision_sessions()

        if not sessions:
            click.echo("Kaydedilmis oturum yok.")
            return

        if format.lower() == "json":
            click.echo(json.dumps(sessions, indent=2, ensure_ascii=False))
        else:  # text
            click.echo(f"📸 {len(sessions)} Kaydedilmis Oturum")
            click.echo("-" * 70)

            for session in sessions:
                session_id = session.get("session_id", "?")
                created = session.get("created_at", "?")
                entry_count = session.get("entry_count", 0)
                last_analysis = session.get("last_analysis", "?")

                click.echo(f"ID: {session_id}")
                click.echo(f"  Olusturuldu: {created}")
                click.echo(f"  Girdiler: {entry_count}")
                click.echo(f"  Son Analiz: {last_analysis}")
                click.echo("")

    except Exception as e:
        click.echo(f"✗ Oturumlar listelenemiyor: {e}", err=True)


__all__ = ["screen_group"]
