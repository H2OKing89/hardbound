"""
Display utilities and formatting using Rich
"""

import re
import shutil
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

# Global console instance
console = Console()


class Sty:
    """Rich color/style compatibility layer"""

    RESET = ""
    BOLD = "bold"
    DIM = "dim"
    ITAL = "italic"
    GREY = "grey"
    RED = "red"
    GREEN = "green"
    YELLOW = "yellow"
    BLUE = "blue"
    MAGENTA = "magenta"
    CYAN = "cyan"
    WHITE = "white"

    enabled = True

    @classmethod
    def off(cls):
        cls.enabled = False


def term_width(default=100):
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return default


def ellipsize(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    if limit <= 10:
        return s[: max(0, limit - 1)] + "…"
    keep = (limit - 1) // 2
    return s[:keep] + "… " + s[-(limit - keep - 2) :]


def banner(title: str, mode: str):
    """Display a banner with title and mode using Rich Panel"""
    mode_tag = (
        "[yellow][DRY-RUN][/yellow]" if mode == "dry" else "[green][COMMIT][/green]"
    )

    panel = Panel.fit(
        f"[bold cyan] {title} [/bold cyan]{mode_tag}", border_style="cyan"
    )
    console.print(panel)


def section(title: str):
    """Display a section header using Rich"""
    console.print(f"\n[magenta]{title}[/magenta]")
    console.print("─" * term_width())


def row(
    status_icon: str, status_color: str, kind: str, src: Path, dst: Path, dry: bool
):
    """Display a row with status using Rich"""
    # Convert ANSI color to Rich markup
    color_map = {
        Sty.GREEN: "green",
        Sty.BLUE: "blue",
        Sty.YELLOW: "yellow",
        Sty.RED: "red",
        Sty.GREY: "grey",
        Sty.CYAN: "cyan",
        Sty.MAGENTA: "magenta",
    }

    # Handle both old Sty constants and direct color strings
    if status_color in color_map:
        rich_color = color_map[status_color]
    else:
        rich_color = status_color

    left = f"{status_icon} [{rich_color}]{kind:<6}[/{rich_color}]"
    middle = f"[grey]{src}[/grey] [dim]→[/dim] {dst}"

    console.print(f"{left}  {ellipsize(middle, term_width() - 20)}")


def strip_ansi(s: str) -> str:
    """Strip ANSI codes from string"""
    return re.sub(r"\x1b\[[0-9;]*m", "", s)


def summary_table(stats: dict, elapsed: float):
    """Display summary statistics using Rich Table"""
    table = Table(show_header=False, box=None)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right")

    table.add_row("linked", str(stats["linked"]), style="green")
    table.add_row("replaced", str(stats["replaced"]), style="blue")
    table.add_row("already", str(stats["already"]), style="grey")
    table.add_row("exists", str(stats["exists"]), style="yellow")
    table.add_row("excluded", str(stats["excluded"]), style="grey")
    table.add_row("skipped", str(stats["skipped"]), style="grey")
    table.add_row("errors", str(stats["errors"]), style="red")

    console.print(table)
    console.print(f"[cyan]elapsed[/cyan]: {elapsed:.3f}s")
