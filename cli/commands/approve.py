"""
Approval System CLI Command

Manage pending approvals from CLI:
- elyan approve pending      → List pending approvals
- elyan approve approve <id> → Approve request
- elyan approve deny <id>    → Deny request
- elyan approvals pending    → Alias for listing pending approvals
"""

import typer
import requests
import json
import os
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from datetime import datetime, timedelta
from config import get_gateway_api_base_url
from config.elyan_config import elyan_config

console = Console()
app = typer.Typer(help="Approval system commands")

BASE_URL = get_gateway_api_base_url()


def _admin_headers() -> dict[str, str]:
    admin_token = str(
        os.environ.get("ELYAN_ADMIN_TOKEN", "")
        or elyan_config.get("gateway.admin.token", "")
        or ""
    ).strip()
    headers = {"Content-Type": "application/json"}
    if admin_token:
        headers["X-Elyan-Admin-Token"] = admin_token
    return headers


def format_age(created_at: float) -> str:
    """Format timestamp as human readable age."""
    age_seconds = int(datetime.now().timestamp() - created_at)
    if age_seconds < 60:
        return f"{age_seconds}s"
    elif age_seconds < 3600:
        return f"{age_seconds // 60}m"
    else:
        return f"{age_seconds // 3600}h"


@app.command()
def pending(
    output: Optional[str] = typer.Option(
        None,
        "--output",
        "-o",
        help="Output format: json or table"
    )
) -> None:
    """List all pending approvals."""
    try:
        response = requests.get(f"{BASE_URL}/approvals/pending", headers=_admin_headers(), timeout=5)
        response.raise_for_status()
        data = response.json()

        if not data.get("success"):
            console.print(f"[red]Error:[/red] {data.get('error', 'Unknown error')}")
            raise typer.Exit(1)

        approvals = data.get("approvals", [])
        count = data.get("count", 0)

        if output == "json":
            console.print_json(data=approvals)
            return

        if not approvals:
            console.print("[yellow]No pending approvals[/yellow]")
            return

        # Create table
        table = Table(title=f"Pending Approvals ({count})", show_header=True, header_style="bold")
        table.add_column("Request ID", style="cyan")
        table.add_column("Action Type", style="magenta")
        table.add_column("Risk Level", style="yellow")
        table.add_column("Reason")
        table.add_column("Session", style="blue")
        table.add_column("Age", style="green")

        for appr in approvals:
            risk = appr.get("risk_level", "UNKNOWN")
            if risk.upper() == "CRITICAL":
                risk_style = "red"
            elif risk.upper() in ("HIGH", "SEVERE"):
                risk_style = "orange1"
            else:
                risk_style = "yellow"

            age = format_age(appr.get("created_at", 0))
            table.add_row(
                appr.get("request_id", "?")[:10],
                appr.get("action_type", "?"),
                f"[{risk_style}]{risk}[/{risk_style}]",
                appr.get("reason", "?")[:40],
                appr.get("session_id", "?")[:8],
                age
            )

        console.print(table)

    except requests.exceptions.RequestException as e:
        console.print(f"[red]API Error:[/red] {str(e)}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        raise typer.Exit(1)


@app.command()
def approve(
    request_id: str = typer.Argument(..., help="Approval request ID")
) -> None:
    """Approve a pending request."""
    try:
        payload = {
            "request_id": request_id,
            "approved": True,
            "resolver_id": "cli"
        }
        response = requests.post(
            f"{BASE_URL}/approvals/resolve",
            json=payload,
            headers=_admin_headers(),
            timeout=5
        )
        response.raise_for_status()
        data = response.json()

        if data.get("success"):
            console.print(f"[green]✓[/green] Approval [cyan]{request_id}[/cyan] approved")
        else:
            console.print(f"[red]✗[/red] {data.get('error', 'Unknown error')}")
            raise typer.Exit(1)

    except requests.exceptions.RequestException as e:
        console.print(f"[red]API Error:[/red] {str(e)}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        raise typer.Exit(1)


@app.command()
def deny(
    request_id: str = typer.Argument(..., help="Approval request ID")
) -> None:
    """Deny a pending request."""
    try:
        payload = {
            "request_id": request_id,
            "approved": False,
            "resolver_id": "cli"
        }
        response = requests.post(
            f"{BASE_URL}/approvals/resolve",
            json=payload,
            headers=_admin_headers(),
            timeout=5
        )
        response.raise_for_status()
        data = response.json()

        if data.get("success"):
            console.print(f"[red]✗[/red] Approval [cyan]{request_id}[/cyan] denied")
        else:
            console.print(f"[red]Error:[/red] {data.get('error', 'Unknown error')}")
            raise typer.Exit(1)

    except requests.exceptions.RequestException as e:
        console.print(f"[red]API Error:[/red] {str(e)}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        raise typer.Exit(1)
