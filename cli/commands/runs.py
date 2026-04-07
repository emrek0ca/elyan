"""
Run Inspector CLI Command

Manage execution runs from CLI:
- elyan runs list [--limit N] [--status STATUS]    → List runs
- elyan runs inspect <run_id>                       → Inspect run details
- elyan runs cancel <run_id>                        → Cancel running
"""

import typer
import requests
import json
from typing import Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.syntax import Syntax
from datetime import datetime
from config import get_gateway_api_base_url

console = Console()
app = typer.Typer(help="Run inspector commands")

BASE_URL = get_gateway_api_base_url()


def format_timestamp(ts: float) -> str:
    """Format timestamp as human readable."""
    if not ts:
        return "N/A"
    dt = datetime.fromtimestamp(ts)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def format_duration(seconds: Optional[float]) -> str:
    """Format duration in seconds."""
    if seconds is None:
        return "Running"
    if seconds < 60:
        return f"{int(seconds)}s"
    elif seconds < 3600:
        return f"{int(seconds // 60)}m {int(seconds % 60)}s"
    else:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        return f"{hours}h {minutes}m"


@app.command()
def list_runs(
    limit: int = typer.Option(20, "--limit", "-l", help="Maximum runs to return"),
    status: Optional[str] = typer.Option(None, "--status", "-s", help="Filter by status"),
    output: Optional[str] = typer.Option(None, "--output", "-o", help="Output format: json")
) -> None:
    """List execution runs."""
    try:
        params = {"limit": limit}
        if status:
            params["status"] = status

        response = requests.get(f"{BASE_URL}/runs", params=params, timeout=5)
        response.raise_for_status()
        data = response.json()

        if not data.get("success"):
            console.print(f"[red]Error:[/red] {data.get('error', 'Unknown error')}")
            raise typer.Exit(1)

        runs = data.get("runs", [])
        count = data.get("count", 0)

        if output == "json":
            console.print_json(data=runs)
            return

        if not runs:
            console.print("[yellow]No runs found[/yellow]")
            return

        # Create table
        table = Table(title=f"Execution Runs ({count})", show_header=True, header_style="bold")
        table.add_column("Run ID", style="cyan")
        table.add_column("Intent")
        table.add_column("Status", style="magenta")
        table.add_column("Started", style="blue")
        table.add_column("Duration", style="green")

        for run in runs:
            status_val = run.get("status", "UNKNOWN")
            status_style = "green" if status_val == "completed" else "yellow" if status_val == "pending" else "red"

            started = format_timestamp(run.get("started_at", 0))
            duration = format_duration(run.get("duration_seconds"))

            table.add_row(
                run.get("run_id", "?")[:12],
                run.get("intent", "?")[:50],
                f"[{status_style}]{status_val}[/{status_style}]",
                started,
                duration
            )

        console.print(table)

    except requests.exceptions.RequestException as e:
        console.print(f"[red]API Error:[/red] {str(e)}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        raise typer.Exit(1)


@app.command()
def inspect(
    run_id: str = typer.Argument(..., help="Run ID to inspect")
) -> None:
    """Inspect detailed run information."""
    try:
        response = requests.get(f"{BASE_URL}/runs/{run_id}", timeout=5)
        response.raise_for_status()
        data = response.json()

        if not data.get("success"):
            console.print(f"[red]Error:[/red] {data.get('error', 'Unknown error')}")
            raise typer.Exit(1)

        run = data.get("run", {})

        # Header panel
        status_val = run.get("status", "UNKNOWN")
        status_style = "green" if status_val == "completed" else "yellow" if status_val == "pending" else "red"

        header = Panel(
            f"[{status_style}]{status_val.upper()}[/{status_style}] | "
            f"Intent: {run.get('intent', '?')} | "
            f"Duration: {format_duration(run.get('duration_seconds'))}",
            title=f"[cyan]Run {run_id}[/cyan]",
            expand=False
        )
        console.print(header)

        # Metadata
        console.print("\n[bold]Metadata:[/bold]")
        meta_table = Table(show_header=False, show_lines=False)
        meta_table.add_row("Session", run.get("session_id", "?"))
        meta_table.add_row("Started", format_timestamp(run.get("started_at", 0)))
        if run.get("completed_at"):
            meta_table.add_row("Completed", format_timestamp(run.get("completed_at")))
        meta_table.add_row("Steps", str(len(run.get("steps", []))))
        meta_table.add_row("Tool Calls", str(len(run.get("tool_calls", []))))
        if run.get("error"):
            meta_table.add_row("Error", run.get("error"))
        console.print(meta_table)

        # Steps
        steps = run.get("steps", [])
        if steps:
            console.print("\n[bold]Steps:[/bold]")
            step_table = Table(show_header=True, header_style="bold")
            step_table.add_column("#", style="cyan")
            step_table.add_column("Type")
            step_table.add_column("Description")
            for i, step in enumerate(steps, 1):
                step_table.add_row(
                    str(i),
                    step.get("type", "?"),
                    str(step.get("description", "?"))[:60]
                )
            console.print(step_table)

        # Tool Calls
        tool_calls = run.get("tool_calls", [])
        if tool_calls:
            console.print("\n[bold]Tool Calls:[/bold]")
            tool_table = Table(show_header=True, header_style="bold")
            tool_table.add_column("#", style="cyan")
            tool_table.add_column("Tool")
            tool_table.add_column("Status", style="magenta")
            for i, call in enumerate(tool_calls, 1):
                tool_status = call.get("status", "?")
                tool_status_style = "green" if tool_status == "success" else "red"
                tool_table.add_row(
                    str(i),
                    call.get("tool", "?"),
                    f"[{tool_status_style}]{tool_status}[/{tool_status_style}]"
                )
            console.print(tool_table)

    except requests.exceptions.RequestException as e:
        console.print(f"[red]API Error:[/red] {str(e)}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        raise typer.Exit(1)


@app.command()
def cancel(
    run_id: str = typer.Argument(..., help="Run ID to cancel")
) -> None:
    """Cancel a running execution."""
    try:
        response = requests.post(f"{BASE_URL}/runs/{run_id}/cancel", timeout=5)
        response.raise_for_status()
        data = response.json()

        if data.get("success"):
            console.print(f"[green]✓[/green] Run [cyan]{run_id}[/cyan] cancellation requested")
        else:
            console.print(f"[red]✗[/red] {data.get('error', 'Unknown error')}")
            raise typer.Exit(1)

    except requests.exceptions.RequestException as e:
        console.print(f"[red]API Error:[/red] {str(e)}")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] {str(e)}")
        raise typer.Exit(1)
