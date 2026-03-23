"""
CLI: code commands — Static analysis, security scanning, execution, test generation.
Usage:
  elyan code analyze TARGET [--language LANG] [--format text|json|md]
  elyan code run TARGET [--language LANG] [--timeout SEC]
  elyan code scan TARGET [--language LANG] [--severity low|medium|high|critical] [--format text|json]
  elyan code test TARGET [--language LANG] [--format text|md]
"""

import asyncio
import click
import json


def _get_code_engine():
    """Get CodeEngine instance."""
    from core.code_intel import get_code_engine
    return get_code_engine()


def _read_input(target: str) -> str:
    """Read code from file or stdin."""
    if target == "-":
        # Read from stdin
        import sys
        return sys.stdin.read()
    else:
        # Read from file
        from pathlib import Path
        path = Path(target).expanduser()
        if not path.exists():
            click.echo(f"✗ Dosya bulunamadi: {target}", err=True)
            raise click.Abort()
        return path.read_text(encoding="utf-8")


def _detect_language(target: str, language: str) -> str:
    """Auto-detect language from file extension."""
    if language != "auto":
        return language

    from pathlib import Path
    if target == "-":
        return "python"  # Default for stdin

    suffix = Path(target).suffix.lower()
    if suffix == ".py":
        return "python"
    elif suffix in {".sh", ".bash"}:
        return "shell"
    elif suffix == ".js":
        return "javascript"
    else:
        return "python"  # Default


@click.group("code")
def code_group():
    """🔍 Kod Analizi — Tarama, çalıştırma, test üretimi."""
    pass


@code_group.command("analyze")
@click.argument("target")  # file path or "-" for stdin
@click.option(
    "--language",
    "-l",
    default="auto",
    help="Programlama dili (auto: otomatik algıla)"
)
@click.option(
    "--format",
    type=click.Choice(["text", "json", "md"], case_sensitive=False),
    default="text",
    help="Cikti biçimi"
)
def code_analyze(target: str, language: str, format: str):
    """Kod analizi — fonksiyonlar, sınıflar, karmaşıklık."""
    try:
        code = _read_input(target)
        language = _detect_language(target, language)

        engine = _get_code_engine()
        result = engine.analyze(code, language)

        click.echo(f"📊 Kod Analizi: {target}")
        click.echo(f"   Dil: {language}")
        click.echo("")

        if format.lower() == "json":
            from core.code_intel import format_json
            click.echo(format_json(result))
        elif format.lower() == "md":
            from core.code_intel import format_md
            click.echo(format_md(result))
        else:  # text
            from core.code_intel import format_text
            click.echo(format_text(result))

    except click.Abort:
        return 1
    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)
        return 1


@code_group.command("run")
@click.argument("target")
@click.option(
    "--language",
    "-l",
    default="auto",
    help="Programlama dili"
)
@click.option(
    "--timeout",
    type=int,
    default=10,
    help="Yürütme zaman siniri (saniye)"
)
def code_run(target: str, language: str, timeout: int):
    """Kodu guvenli ortamda calistir."""
    async def _run():
        try:
            code = _read_input(target)
            language_detected = _detect_language(target, language)

            engine = _get_code_engine()
            result = await engine.run(code, language_detected, timeout)

            click.echo(f"▶️  Çalıştırma: {target}")
            click.echo(f"   Dil: {language_detected}")
            click.echo("")

            if result.success:
                click.echo(result.output or "(Çıktı yok)")
            else:
                click.echo(f"❌ {result.text}", err=True)
                return 1

        except click.Abort:
            return 1
        except Exception as e:
            click.echo(f"✗ Hata: {e}", err=True)
            return 1

    asyncio.run(_run())


@code_group.command("scan")
@click.argument("target")  # file or directory
@click.option(
    "--language",
    "-l",
    default="auto",
    help="Programlama dili"
)
@click.option(
    "--severity",
    type=click.Choice(["low", "medium", "high", "critical"]),
    default=None,
    help="Sadece bu seviyedeki sorunlari goster"
)
@click.option(
    "--format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Cikti biçimi"
)
def code_scan(target: str, language: str, severity: str, format: str):
    """Güvenlik taraması — tehlikeli pattern'ler ve gizli bilgiler."""
    try:
        code = _read_input(target)
        language = _detect_language(target, language)

        engine = _get_code_engine()
        result = engine.scan(code, language)

        # Filter by severity if specified
        if severity and result.issues:
            result.issues = [iss for iss in result.issues if iss.get("severity") == severity]

        click.echo(f"🔒 Güvenlik Taraması: {target}")
        click.echo(f"   Dil: {language}")
        if severity:
            click.echo(f"   Filtre: {severity}")
        click.echo("")

        if format.lower() == "json":
            from core.code_intel import format_json
            click.echo(format_json(result))
        else:  # text
            from core.code_intel import format_text
            click.echo(format_text(result))

    except click.Abort:
        return 1
    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)
        return 1


@code_group.command("test")
@click.argument("target")
@click.option(
    "--language",
    "-l",
    default="python",
    help="Programlama dili"
)
@click.option(
    "--format",
    type=click.Choice(["text", "md"], case_sensitive=False),
    default="text",
    help="Test çikti biçimi"
)
def code_test(target: str, language: str, format: str):
    """Test kodu uret — fonksiyonlar için test sablon'ları."""
    async def _run():
        try:
            code = _read_input(target)

            engine = _get_code_engine()
            result = await engine.generate_tests(code, language)

            click.echo(f"✏️  Test Üretimi: {target}")
            click.echo(f"   Dil: {language}")
            click.echo("")

            if result.success:
                click.echo(result.output)
            else:
                click.echo(f"❌ {result.text}", err=True)
                return 1

        except click.Abort:
            return 1
        except Exception as e:
            click.echo(f"✗ Hata: {e}", err=True)
            return 1

    asyncio.run(_run())


__all__ = ["code_group"]
