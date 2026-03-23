"""
CLI: workflow commands — Multi-step workflow execution.
Usage:
  elyan workflow run WORKFLOW_ID_OR_FILE [--format text|json|md]
  elyan workflow create SPEC_FILE [--name NAME]
  elyan workflow list [--format text|json]
  elyan workflow status WORKFLOW_ID [--format text|json]
  elyan workflow delete WORKFLOW_ID [--yes]
"""

import asyncio
import click
import json
from pathlib import Path


def _get_workflow_engine():
    """Get WorkflowEngine instance."""
    from core.workflow import get_workflow_engine
    return get_workflow_engine()


@click.group("workflow")
def workflow_group():
    """⚙️ Adim Adim İş Akışı — Multi-step otomasyonu."""
    pass


@workflow_group.command("run")
@click.argument("workflow_id_or_file")
@click.option(
    "--format",
    type=click.Choice(["text", "json", "md"], case_sensitive=False),
    default="text",
    help="Cikti biçimi"
)
def workflow_run(workflow_id_or_file: str, format: str):
    """İş akışını çalıştır."""
    async def _run():
        engine = _get_workflow_engine()

        # Check if it's a file path
        spec_path = Path(workflow_id_or_file)
        if spec_path.exists() and spec_path.suffix == ".json":
            # Load spec from file and run inline
            try:
                spec = json.loads(spec_path.read_text())
                result = await engine.run_inline(
                    steps=spec.get("steps", []),
                    name=spec.get("name", "inline"),
                )
            except Exception as e:
                click.echo(f"✗ Spec yükleme hatası: {e}", err=True)
                return
        else:
            # Run by workflow ID
            click.echo(f"⚙️  Workflow Çalıştırılıyor: {workflow_id_or_file}")
            result = await engine.run(workflow_id_or_file)

        if not result.success:
            click.echo(f"✗ {result.text}", err=True)
            return

        click.echo("")

        if format.lower() == "json":
            from core.workflow import format_json
            click.echo(format_json(result))
        elif format.lower() == "md":
            from core.workflow import format_md
            click.echo(format_md(result))
        else:  # text
            from core.workflow import format_text
            click.echo(format_text(result))

    try:
        asyncio.run(_run())
    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)


@workflow_group.command("create")
@click.argument("spec_file")
@click.option(
    "--name",
    default=None,
    help="İş akışı adı (spec'te yoksa)"
)
def workflow_create(spec_file: str, name: str):
    """Yeni iş akışı oluştur."""
    try:
        spec_path = Path(spec_file).expanduser()
        if not spec_path.exists():
            click.echo(f"✗ Dosya bulunamadı: {spec_file}", err=True)
            return

        spec = json.loads(spec_path.read_text())
        wf_name = name or spec.get("name", "Unnamed")

        engine = _get_workflow_engine()
        wf = engine.create(
            name=wf_name,
            description=spec.get("description", ""),
            steps=spec.get("steps", []),
        )

        click.echo(f"✓ İş akışı oluşturuldu: {wf.workflow_id}")
        click.echo(f"  Ad: {wf.name}")
        click.echo(f"  Adım sayısı: {len(wf.steps)}")

    except json.JSONDecodeError:
        click.echo(f"✗ Geçersiz JSON: {spec_file}", err=True)
    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)


@workflow_group.command("list")
@click.option(
    "--format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Cikti biçimi"
)
def workflow_list(format: str):
    """Tüm iş akışlarını listele."""
    try:
        engine = _get_workflow_engine()
        workflows = engine.list()

        if not workflows:
            click.echo("Kaydedilmiş iş akışı yok.")
            return

        if format.lower() == "json":
            click.echo(json.dumps(workflows, indent=2, ensure_ascii=False))
        else:  # text
            click.echo(f"⚙️  {len(workflows)} İş Akışı")
            click.echo("-" * 70)

            for wf in workflows:
                click.echo(f"ID: {wf.get('workflow_id', '?')}")
                click.echo(f"  Ad: {wf.get('name', '?')}")
                click.echo(f"  Adımlar: {wf.get('step_count', 0)}")
                click.echo(f"  Oluşturuldu: {wf.get('created_at', '?')}")
                click.echo("")

    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)


@workflow_group.command("status")
@click.argument("workflow_id")
@click.option(
    "--format",
    type=click.Choice(["text", "json"], case_sensitive=False),
    default="text",
    help="Cikti biçimi"
)
def workflow_status(workflow_id: str, format: str):
    """İş akışı detaylarını göster."""
    try:
        engine = _get_workflow_engine()
        wf = engine.get(workflow_id)

        if not wf:
            click.echo(f"✗ İş akışı bulunamadı: {workflow_id}", err=True)
            return

        if format.lower() == "json":
            data = {
                "workflow_id": wf.workflow_id,
                "name": wf.name,
                "description": wf.description,
                "step_count": len(wf.steps),
                "steps": [
                    {
                        "name": s.name,
                        "action": s.action,
                        "timeout": s.timeout,
                        "retry": s.retry,
                    }
                    for s in wf.steps
                ],
                "created_at": wf.created_at,
            }
            click.echo(json.dumps(data, indent=2, ensure_ascii=False))
        else:  # text
            click.echo(f"⚙️  {wf.name}")
            click.echo(f"ID: {wf.workflow_id}")
            click.echo(f"Description: {wf.description}")
            click.echo(f"Adımlar: {len(wf.steps)}")
            click.echo("")

            for i, step in enumerate(wf.steps, 1):
                click.echo(f"[{i}] {step.name}")
                click.echo(f"    Action: {step.action}")
                click.echo(f"    Timeout: {step.timeout}s")
                click.echo(f"    On failure: {step.on_failure}")

    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)


@workflow_group.command("delete")
@click.argument("workflow_id")
@click.option(
    "--yes",
    is_flag=True,
    help="Onaylamadan sil"
)
def workflow_delete(workflow_id: str, yes: bool):
    """İş akışını sil."""
    try:
        engine = _get_workflow_engine()
        wf = engine.get(workflow_id)

        if not wf:
            click.echo(f"✗ İş akışı bulunamadı: {workflow_id}", err=True)
            return

        if not yes:
            if not click.confirm(f"İş akışı '{wf.name}'yi silmek istediğinize emin misiniz?"):
                click.echo("İptal edildi.")
                return

        success = engine.delete(workflow_id)
        if success:
            click.echo(f"✓ İş akışı silindi: {workflow_id}")
        else:
            click.echo(f"✗ Silme başarısız", err=True)

    except Exception as e:
        click.echo(f"✗ Hata: {e}", err=True)


__all__ = ["workflow_group"]
