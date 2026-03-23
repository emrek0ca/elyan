"""
CLI: research commands — Multi-source research with citations.
Usage:
  elyan research "query" [--depth basic|standard|deep|academic] [--format text|json|md]
  elyan research --session <id>
  elyan research --list
"""

import asyncio
import click
import json
from pathlib import Path


def _get_research_engine():
    """Get ResearchEngine instance."""
    from core.research import get_research_engine
    return get_research_engine()


@click.group("research")
def research_group():
    """🔬 Araştırma Motoru — Multi-kaynak, atıf, LLM sentezi."""
    pass


@research_group.command("search")
@click.argument("query")
@click.option(
    "--depth",
    type=click.Choice(["basic", "standard", "deep", "academic"], case_sensitive=False),
    default="standard",
    help="Araştırma derinliği",
)
@click.option(
    "--format",
    type=click.Choice(["text", "json", "md"], case_sensitive=False),
    default="text",
    help="Çıktı biçimi",
)
@click.option(
    "--session",
    default=None,
    help="Session ID'si (isteğe bağlı, oturum kaydetmek için)",
)
def research_search(query: str, depth: str, format: str, session: str):
    """Sorgu araştırması yap."""
    async def _run():
        engine = _get_research_engine()

        click.echo(f"🔬 Araştırılıyor: {query[:60]}")
        click.echo(f"   Derinlik: {depth}")
        if session:
            click.echo(f"   Oturum: {session}")
        click.echo("")

        result = await engine.research(query, depth)

        # Save to session if provided
        if session:
            try:
                from core.research import get_session, save_research_session
                sess = get_session(session)
                if not sess:
                    from core.research import ResearchSession
                    sess = ResearchSession(session_id=session)
                sess.add_query(query, result)
                save_research_session(sess)
                click.echo(f"✓ Oturum kaydedildi: {session}")
                click.echo("")
            except Exception as e:
                click.echo(f"⚠ Oturum kaydedilemedi: {e}", err=True)

        # Format output
        if format.lower() == "json":
            from core.research import format_json_result
            click.echo(format_json_result(result))
        elif format.lower() == "md":
            from core.research import format_cited_answer
            click.echo(format_cited_answer(result))
        else:  # text (default)
            from core.research import format_cli_summary
            click.echo(format_cli_summary(result))

    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ Araştırma başarısız: {e}", err=True)


@research_group.command("session")
@click.argument("session_id")
@click.option(
    "--format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Çıktı biçimi",
)
def research_session(session_id: str, format: str):
    """Geçmiş araştırma oturumunu göster."""
    try:
        from core.research import get_session

        session = get_session(session_id)
        if not session:
            click.echo(f"✗ Oturum bulunamadı: {session_id}", err=True)
            return

        if format.lower() == "json":
            click.echo(json.dumps(session.to_dict(), indent=2, ensure_ascii=False))
        else:  # text
            click.echo(f"📝 Oturum: {session.session_id}")
            click.echo(f"   Oluşturuldu: {session.created_at}")
            click.echo(f"   Güncellenendi: {session.updated_at}")
            click.echo(f"   Sorgular: {len(session.queries)}")
            click.echo("")

            for i, q in enumerate(session.queries, 1):
                click.echo(f"[{i}] Sorgu: {q.get('query', '?')[:60]}")
                result = q.get("result", {})
                if isinstance(result, dict):
                    confidence = result.get("confidence", 0)
                    sources = len(result.get("citations", []))
                    click.echo(f"    Güven: {confidence:.0%} | Kaynaklar: {sources}")

    except Exception as e:
        click.echo(f"✗ Oturum gösterilemedi: {e}", err=True)


@research_group.command("list")
@click.option(
    "--format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Çıktı biçimi",
)
def research_list(format: str):
    """Tüm araştırma oturumlarını listele."""
    try:
        from core.research import list_sessions

        sessions = list_sessions()

        if not sessions:
            click.echo("Kaydedilmiş oturum yok.")
            return

        if format.lower() == "json":
            click.echo(json.dumps(sessions, indent=2, ensure_ascii=False))
        else:  # text
            click.echo(f"📚 {len(sessions)} Kaydedilmiş Oturum")
            click.echo("-" * 70)

            for session in sessions:
                session_id = session.get("session_id", "?")
                created = session.get("created_at", "?")
                query_count = session.get("query_count", 0)
                last_query = session.get("last_query", "?")

                click.echo(f"ID: {session_id}")
                click.echo(f"  Oluşturuldu: {created}")
                click.echo(f"  Sorgular: {query_count}")
                click.echo(f"  Son Sorgu: {last_query[:60]}")
                click.echo("")

    except Exception as e:
        click.echo(f"✗ Oturumlar listelenemiyor: {e}", err=True)


__all__ = ["research_group"]
