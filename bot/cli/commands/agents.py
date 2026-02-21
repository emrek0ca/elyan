"""
CLI: agents commands — Full implementation
"""
import asyncio
import json
import click


@click.group("agents")
def agents_group():
    """Multi-agent yönetimi."""
    pass


@agents_group.command("list")
@click.option("--json", "as_json", is_flag=True, help="JSON formatında çıktı")
def agents_list(as_json):
    """Tüm agent'ları listele."""
    try:
        from core.multi_agent.manager import MultiAgentManager
        mgr = MultiAgentManager()
        agents = mgr.list_agents()
        if as_json:
            click.echo(json.dumps(agents, indent=2, ensure_ascii=False))
            return
        if not agents:
            click.echo("Kayıtlı agent yok.")
            return
        click.echo(f"{'ID':<15} {'Durum':<10} {'Kanallar':<25} {'Model'}")
        click.echo("-" * 65)
        for a in agents:
            status = "✓ Çalışıyor" if a.get("running") else "✗ Durdu"
            channels = ", ".join(a.get("routes", []))
            click.echo(f"{a['id']:<15} {status:<10} {channels:<25} {a.get('model', '-')}")
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@agents_group.command("status")
@click.argument("agent_id", required=False)
def agents_status(agent_id):
    """Agent durumunu göster."""
    try:
        from core.multi_agent.manager import MultiAgentManager
        mgr = MultiAgentManager()
        if agent_id:
            info = mgr.get_agent(agent_id)
            if not info:
                click.echo(f"✗ Agent bulunamadı: {agent_id}", err=True)
                return
            click.echo(json.dumps(info, indent=2, ensure_ascii=False))
        else:
            agents = mgr.list_agents()
            for a in agents:
                status = "✓" if a.get("running") else "✗"
                click.echo(f"{status} {a['id']} — {a.get('model', '-')}")
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@agents_group.command("add")
@click.option("--id", "agent_id", required=True, help="Agent ID")
@click.option("--workspace", required=True, help="Workspace dizini")
@click.option("--model", default="claude-opus-4-5-20251101", help="AI modeli")
@click.option("--channel", "channels", multiple=True, help="Kanal yönlendirme (birden fazla)")
def agents_add(agent_id, workspace, model, channels):
    """Yeni agent ekle."""
    try:
        from core.multi_agent.manager import MultiAgentManager
        mgr = MultiAgentManager()
        mgr.add_agent({
            "id": agent_id,
            "workspace": workspace,
            "model": model,
            "routes": list(channels)
        })
        click.echo(f"✓ Agent eklendi: {agent_id}")
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@agents_group.command("remove")
@click.argument("agent_id")
@click.confirmation_option(prompt="Agent'ı silmek istediğinizden emin misiniz?")
def agents_remove(agent_id):
    """Agent sil."""
    try:
        from core.multi_agent.manager import MultiAgentManager
        mgr = MultiAgentManager()
        mgr.remove_agent(agent_id)
        click.echo(f"✓ Agent silindi: {agent_id}")
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@agents_group.command("start")
@click.argument("agent_id")
def agents_start(agent_id):
    """Agent başlat."""
    try:
        from core.multi_agent.manager import MultiAgentManager
        mgr = MultiAgentManager()
        asyncio.run(mgr.start_agent(agent_id))
        click.echo(f"✓ Agent başlatıldı: {agent_id}")
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@agents_group.command("stop")
@click.argument("agent_id")
def agents_stop(agent_id):
    """Agent durdur."""
    try:
        from core.multi_agent.manager import MultiAgentManager
        mgr = MultiAgentManager()
        asyncio.run(mgr.stop_agent(agent_id))
        click.echo(f"✓ Agent durduruldu: {agent_id}")
    except Exception as e:
        click.echo(f"✗ {e}", err=True)


@agents_group.command("logs")
@click.argument("agent_id")
@click.option("--tail", default=50, help="Son N satır")
def agents_logs(agent_id, tail):
    """Agent loglarını göster."""
    import subprocess
    from pathlib import Path
    log_file = Path.home() / ".elyan" / "logs" / f"agent_{agent_id}.log"
    if not log_file.exists():
        # Try project logs dir
        log_file = Path("logs") / f"agent_{agent_id}.log"
    if log_file.exists():
        result = subprocess.run(["tail", f"-{tail}", str(log_file)], capture_output=True, text=True)
        click.echo(result.stdout)
    else:
        click.echo(f"Log dosyası bulunamadı: {log_file}", err=True)


def register(cli):
    cli.add_command(agents_group, name="agents")
