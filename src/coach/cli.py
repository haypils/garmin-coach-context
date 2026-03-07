from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import typer
from rich import print as rprint
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from mcp.server.fastmcp import FastMCP

from .config import (
    CONFIG_PATH,
    CONTEXT_FILE,
    has_garmin_credentials,
    load_config,
    save_config,
    save_garmin_credentials,
)
from .database import Database

app = typer.Typer(
    name="coach",
    help="Personal AI Ironman Coach — sync Garmin data and generate context for AI coaching in Cursor.",
    no_args_is_help=True,
)
console = Console()

@app.command()
def login(
    email: str = typer.Option(None, prompt="Garmin Connect email"),
    password: str = typer.Option(None, prompt="Garmin Connect password", hide_input=True),
) -> None:
    """Authenticate with Garmin Connect and save credentials to system keychain."""
    save_garmin_credentials(email, password)

    from .garmin_client import _get_client

    try:
        rprint("Authenticating with Garmin Connect...")
        rprint("[dim]If you have 2FA enabled, you'll be prompted for the code.[/dim]")
        _get_client()
        rprint("[bold green]Logged in successfully.[/bold green]")
        rprint("Credentials stored in system keychain (macOS Keychain / OS credential store).")
    except Exception as e:
        rprint(f"[bold red]Login failed:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def sync(
    lookback: int = typer.Option(None, "--lookback", "-l", help="Days to look back (default: from config)"),
    health_days: int = typer.Option(14, "--health-days", help="Days of health data to sync"),
) -> None:
    """Sync training data from Garmin Connect."""
    from .garmin_client import sync_activities, sync_health

    cfg = load_config()
    days = lookback or cfg.sync.lookback_days
    db = Database()

    try:
        rprint(f"\n[bold]Syncing activities ({days} days)...[/bold]")
        act_count = sync_activities(db, lookback_days=days)
        rprint(f"  [green]{act_count}[/green] activities synced.")

        rprint(f"\n[bold]Syncing health metrics ({health_days} days)...[/bold]")
        health_count = sync_health(db, lookback_days=health_days)
        rprint(f"  [green]{health_count}[/green] days of health data synced.")

        rprint(f"\n[bold]Database totals:[/bold] {db.activity_count()} activities, {db.health_count()} health records")
        db.close()

        rprint("\n[dim]Run [bold]coach context[/bold] to generate the training context file.[/dim]")
    except Exception as e:
        rprint(f"\n[bold red]Sync failed:[/bold red] {e}")
        rprint("[dim]Try [bold]coach login[/bold] to re-authenticate.[/dim]")
        raise typer.Exit(1)
    
@app.command()
def mcp() -> None:
    """Sync training data from Garmin Connect."""
    from .garmin_client import sync_activities, sync_health

    app = FastMCP("Garmin Connect MCP")



@app.command()
def context(
    output: Path = typer.Option(None, "--output", "-o", help="Output path (default: training_context.md)"),
    live: bool = typer.Option(False, "--live", help="Use local database instead of fetching from Garmin API"),
) -> None:
    """Generate the training context markdown file for Cursor AI."""
    from .context import build_context

    try:
        result = build_context(output_path=output, use_db=not live)
        rprint(f"\n[bold green]Context file generated:[/bold green] {result}")
        rprint(f"\n[dim]Reference it in Cursor chat with [bold]@{result.name}[/bold] to get AI coaching.[/dim]")
    except Exception as e:
        rprint(f"[bold red]Failed to generate context:[/bold red] {e}")
        raise typer.Exit(1)


@app.command()
def summary(
    weeks: int = typer.Option(8, "--weeks", "-w", help="Number of weeks to show"),
) -> None:
    """Show weekly training summary table."""
    db = Database()
    week_data = db.get_weekly_summaries(weeks=weeks)
    db.close()

    if not week_data:
        rprint("[yellow]No training data yet. Run [bold]coach sync[/bold] first.[/yellow]")
        raise typer.Exit(0)

    table = Table(title=f"Weekly Training Summary (last {weeks} weeks)", show_lines=True)
    table.add_column("Week", style="bold")
    table.add_column("Swim", justify="right")
    table.add_column("Bike", justify="right")
    table.add_column("Run", justify="right")
    table.add_column("Strength", justify="center")
    table.add_column("Total Hrs", justify="right", style="bold cyan")
    table.add_column("TSS", justify="right")

    for w in week_data:
        swim = f"{w.swim_hours:.1f}h / {w.swim_km:.1f}km ({w.swim_sessions}x)" if w.swim_sessions else "-"
        bike = f"{w.bike_hours:.1f}h / {w.bike_km:.0f}km ({w.bike_sessions}x)" if w.bike_sessions else "-"
        run = f"{w.run_hours:.1f}h / {w.run_km:.1f}km ({w.run_sessions}x)" if w.run_sessions else "-"
        strength = f"{w.strength_sessions}x" if w.strength_sessions else "-"
        tss = f"{w.total_tss:.0f}" if w.total_tss else "-"
        table.add_row(str(w.week_start), swim, bike, run, strength, f"{w.total_hours:.1f}", tss)

    console.print(table)


@app.command()
def status() -> None:
    """Show current training status, load, and health indicators."""
    cfg = load_config()
    db = Database()
    weeks = db.get_weekly_summaries(weeks=8)
    health = db.get_health_metrics(since_days=14)
    activities = db.get_recent_activities(limit=5)
    db.close()

    # Race countdown
    if cfg.athlete.race_date:
        try:
            rd = date.fromisoformat(cfg.athlete.race_date)
            days_out = (rd - date.today()).days
            rprint(Panel(
                f"[bold]{cfg.athlete.race_name or 'Race'}[/bold]\n"
                f"{cfg.athlete.race_date} — [bold cyan]{days_out} days[/bold cyan] to go",
                title="Race Countdown",
            ))
        except ValueError:
            pass

    # Training load
    if weeks:
        rprint("\n[bold]Training Load[/bold]")
        if weeks:
            acute = weeks[0].total_hours
            chronic_hours = [w.total_hours for w in weeks[:6]]
            chronic = sum(chronic_hours) / max(len(chronic_hours), 1)
            ratio = acute / chronic if chronic > 0 else 0

            color = "green"
            if ratio > 1.3:
                color = "red"
            elif ratio < 0.8:
                color = "yellow"

            rprint(f"  This week: [bold]{acute:.1f}[/bold] hours")
            rprint(f"  6-week avg: [bold]{chronic:.1f}[/bold] hours/week")
            rprint(f"  Acute:Chronic ratio: [bold {color}]{ratio:.2f}[/bold {color}]")

    # Health snapshot
    if health:
        latest = health[0]
        rprint("\n[bold]Health Snapshot (latest)[/bold]")
        if latest.resting_hr:
            rprint(f"  Resting HR: {latest.resting_hr} bpm")
        if latest.hrv_last_night:
            status_str = f" ({latest.hrv_status})" if latest.hrv_status else ""
            rprint(f"  HRV: {latest.hrv_last_night:.0f} ms{status_str}")
        if latest.sleep_score:
            rprint(f"  Sleep score: {latest.sleep_score}/100")
        if latest.body_battery_high is not None:
            rprint(f"  Body battery: {latest.body_battery_low}-{latest.body_battery_high}")
        if latest.training_readiness:
            rprint(f"  Training readiness: {latest.training_readiness}")
        if latest.stress_avg:
            rprint(f"  Stress avg: {latest.stress_avg}")

    # Recent activities
    if activities:
        rprint("\n[bold]Recent Activities[/bold]")
        for a in activities[:5]:
            date_str = a.start_time.strftime("%m/%d") if a.start_time else "?"
            sport = a.sport_type or "?"
            dur_h = int(a.duration_seconds // 3600)
            dur_m = int((a.duration_seconds % 3600) // 60)
            dur = f"{dur_h}h{dur_m:02d}m" if dur_h else f"{dur_m}m"
            km = a.distance_meters / 1000
            hr_str = f"  HR {a.avg_hr:.0f}/{a.max_hr:.0f}" if a.avg_hr else ""
            rprint(f"  {date_str}  {sport:<12} {dur:>7}  {km:>6.1f}km{hr_str}")

    if not weeks and not health and not activities:
        rprint("[yellow]No data yet. Run [bold]coach sync[/bold] first.[/yellow]")


@app.command()
def config() -> None:
    """Show or edit athlete configuration."""
    cfg = load_config()

    rprint(Panel(
        f"[bold]Race:[/bold] {cfg.athlete.race_name or 'Not set'}\n"
        f"[bold]Date:[/bold] {cfg.athlete.race_date or 'Not set'}\n"
        f"[bold]Experience:[/bold] {cfg.athlete.experience}\n"
        f"[bold]Max weekly hours:[/bold] {cfg.athlete.max_weekly_hours}\n"
        f"[bold]Goals:[/bold] {cfg.athlete.goals or 'Not set'}\n"
        f"[bold]Injuries:[/bold] {', '.join(cfg.athlete.injury_history) if cfg.athlete.injury_history else 'None'}\n"
        f"\n[dim]Config file: {CONFIG_PATH}[/dim]",
        title="Athlete Configuration",
    ))

    if typer.confirm("\nEdit configuration?", default=False):
        cfg.athlete.race_name = typer.prompt("Race name", default=cfg.athlete.race_name)
        cfg.athlete.race_date = typer.prompt("Race date (YYYY-MM-DD)", default=cfg.athlete.race_date)
        cfg.athlete.experience = typer.prompt("Experience level", default=cfg.athlete.experience)
        cfg.athlete.max_weekly_hours = float(typer.prompt("Max weekly hours", default=str(cfg.athlete.max_weekly_hours)))
        cfg.athlete.goals = typer.prompt("Goals", default=cfg.athlete.goals)
        save_config(cfg)
        rprint("[bold green]Configuration saved.[/bold green]")


@app.command()
def reset() -> None:
    """Reset the local database (keeps config)."""
    from .config import DB_PATH

    if DB_PATH.exists():
        if typer.confirm(f"Delete database at {DB_PATH}?", default=False):
            DB_PATH.unlink()
            rprint("[green]Database reset.[/green]")
    else:
        rprint("[yellow]No database found.[/yellow]")


def main() -> None:
    app()


if __name__ == "__main__":
    main()
