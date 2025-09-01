"""Text formatting and display utilities"""

from pathlib import Path
from typing import Any, Dict, List

from rich import box
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console()


class TextFormatter:
    """Utilities for formatting text and data display"""

    @staticmethod
    def format_file_size(size_bytes: int) -> str:
        """Format file size in human readable format"""
        if size_bytes == 0:
            return "0 B"

        size_names = ["B", "KB", "MB", "GB", "TB"]
        size_index = 0
        size = float(size_bytes)

        while size >= 1024 and size_index < len(size_names) - 1:
            size /= 1024
            size_index += 1

        return f"{size:.1f} {size_names[size_index]}"

    @staticmethod
    def format_duration(seconds: float) -> str:
        """Format duration in human readable format"""
        if seconds < 60:
            return f"{seconds:.1f}s"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            secs = seconds % 60
            return f"{minutes}m {secs:.1f}s"
        else:
            hours = int(seconds // 3600)
            minutes = int((seconds % 3600) // 60)
            return f"{hours}h {minutes}m"

    @staticmethod
    def truncate_text(text: str, max_length: int, suffix: str = "...") -> str:
        """Truncate text to max length with suffix"""
        if len(text) <= max_length:
            return text
        return text[: max_length - len(suffix)] + suffix

    @staticmethod
    def format_path_list(paths: List[Path], max_items: int = 5) -> str:
        """Format a list of paths for display"""
        if not paths:
            return "None"

        if len(paths) <= max_items:
            return "\n".join(f"  • {p}" for p in paths)
        else:
            shown = paths[:max_items]
            remaining = len(paths) - max_items
            result = "\n".join(f"  • {p}" for p in shown)
            result += f"\n  ... and {remaining} more"
            return result


class DisplayFormatter:
    """Rich-based display formatting utilities"""

    @staticmethod
    def create_summary_table(data: List[Dict[str, Any]], title: str = "") -> Table:
        """Create a formatted table from data"""
        if not data:
            # Return empty table with message
            table = Table(title=title or "No Data", box=box.ROUNDED)
            table.add_column("Message", style="dim")
            table.add_row("No data available")
            return table

        table = Table(title=title, box=box.ROUNDED)
        headers = list(data[0].keys())

        for header in headers:
            table.add_column(header.title(), style="cyan")

        for row in data:
            table.add_row(*[str(row.get(h, "")) for h in headers])

        return table

    @staticmethod
    def create_info_panel(
        title: str, content: Dict[str, Any], style: str = "blue"
    ) -> Panel:
        """Create an information panel"""
        content_lines = []
        for key, value in content.items():
            content_lines.append(f"[bold]{key}:[/bold] {value}")

        content_text = "\n".join(content_lines)
        return Panel.fit(
            content_text, title=f"[{style}]{title}[/{style}]", border_style=style
        )

    @staticmethod
    def format_status_message(status: str, message: str, icon: str = "") -> Text:
        """Format a status message with appropriate styling"""
        status_styles = {
            "success": "green",
            "error": "red",
            "warning": "yellow",
            "info": "blue",
        }

        style = status_styles.get(status.lower(), "white")
        icon_map = {"success": "✅", "error": "❌", "warning": "⚠️", "info": "ℹ️"}

        icon = icon or icon_map.get(status.lower(), "")
        return Text(f"{icon} {message}", style=style)


# Global instances
text_formatter = TextFormatter()
display_formatter = DisplayFormatter()
