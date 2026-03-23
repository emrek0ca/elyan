"""
CLI: ux commands — Premium UX features.
Usage:
  elyan ux message TEXT [--session ID] [--stream] [--format text|json|md] [--multimodal FILE...]
  elyan ux session SESSION_ID [--format text|json|md]
  elyan ux sessions [--format text|json]
  elyan ux clear SESSION_ID [--yes]
"""

import asyncio
import click
import json
from pathlib import Path


def _get_ux_engine():
    """Get UXEngine instance."""
    from core.ux_engine import get_ux_engine
    return get_ux_engine()


@click.group("ux")
def ux_group():
    """✨ Premium UX — Conversational flow, streaming, suggestions, context continuity, multi-modal."""
    pass


@ux_group.command("message")
@click.argument("text")
@click.option(
    "--session",
    default="default",
    help="Session ID"
)
@click.option(
    "--stream",
    is_flag=True,
    help="Enable real-time streaming"
)
@click.option(
    "--format",
    type=click.Choice(["text", "json", "md"], case_sensitive=False),
    default="text",
    help="Output format"
)
@click.option(
    "--multimodal",
    multiple=True,
    help="Multimodal input files (images, audio, documents)"
)
def ux_message(text: str, session: str, stream: bool, format: str, multimodal):
    """Send message with premium UX features."""
    async def _run():
        engine = _get_ux_engine()

        multimodal_list = list(multimodal) if multimodal else None

        result = await engine.process_message(
            user_message=text,
            session_id=session,
            multimodal_inputs=multimodal_list,
            enable_streaming=stream,
        )

        # If streaming, iterate through chunks
        if stream:
            async for chunk in result:
                click.echo(chunk, nl=False)
            click.echo()
        else:
            # Regular output
            if format.lower() == "json":
                from core.ux_engine.formatter import format_json
                click.echo(format_json(result))
            elif format.lower() == "md":
                from core.ux_engine.formatter import format_md
                click.echo(format_md(result))
            else:  # text
                from core.ux_engine.formatter import format_text
                click.echo(format_text(result))

    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)


@ux_group.command("session")
@click.argument("session_id")
@click.option(
    "--format",
    type=click.Choice(["text", "json", "md"], case_sensitive=False),
    default="text",
    help="Output format"
)
def ux_session(session_id: str, format: str):
    """Show session details."""
    try:
        engine = _get_ux_engine()
        session = engine.get_session(session_id)

        if not session:
            click.echo(f"✗ Session bulunamadı: {session_id}", err=True)
            return

        if format.lower() == "json":
            click.echo(json.dumps(session, indent=2, ensure_ascii=False))
        else:  # text or md
            click.echo(f"📌 Session: {session_id}")
            click.echo(f"Oluşturuldu: {session.get('created_at', '?')}")
            click.echo(f"Mesajlar: {len(session.get('messages', []))}")
            click.echo(f"Sorular: {len(session.get('questions_asked', []))}")
            click.echo("")

            if format.lower() == "md":
                click.echo("## Conversation History")
                click.echo("")
                for msg in session.get("messages", []):
                    click.echo(f"**User**: {msg.get('user', '?')}")
                    click.echo(f"**Assistant**: {msg.get('assistant', '?')}")
                    click.echo("")
            else:  # text
                for i, msg in enumerate(session.get("messages", []), 1):
                    click.echo(f"[{i}] User: {msg.get('user', '?')[:50]}...")
                    click.echo(f"    Asst: {msg.get('assistant', '?')[:50]}...")

    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)


@ux_group.command("sessions")
@click.option(
    "--format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Output format"
)
def ux_sessions(format: str):
    """List all sessions."""
    try:
        engine = _get_ux_engine()
        sessions = engine.list_sessions()

        if not sessions:
            click.echo("Aktif session yok.")
            return

        if format.lower() == "json":
            session_data = []
            for sid in sessions:
                s = engine.get_session(sid)
                if s:
                    session_data.append({
                        "session_id": sid,
                        "created_at": s.get("created_at"),
                        "message_count": len(s.get("messages", [])),
                    })
            click.echo(json.dumps(session_data, indent=2, ensure_ascii=False))
        else:  # text
            click.echo(f"✨ {len(sessions)} Session")
            click.echo("-" * 70)
            for sid in sessions:
                s = engine.get_session(sid)
                if s:
                    click.echo(f"ID: {sid}")
                    click.echo(f"  Oluşturuldu: {s.get('created_at', '?')}")
                    click.echo(f"  Mesajlar: {len(s.get('messages', []))}")
                    click.echo("")

    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)


@ux_group.command("clear")
@click.argument("session_id")
@click.option(
    "--yes",
    is_flag=True,
    help="Confirm without prompt"
)
def ux_clear(session_id: str, yes: bool):
    """Clear session data."""
    try:
        engine = _get_ux_engine()

        if not yes:
            if not click.confirm(f"Session '{session_id}'i silmek istediğinize emin misiniz?"):
                click.echo("İptal edildi.")
                return

        success = engine.clear_session(session_id)
        if success:
            click.echo(f"✓ Session silindi: {session_id}")
        else:
            click.echo(f"✗ Session bulunamadı: {session_id}", err=True)

    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)


__all__ = ["ux_group"]
