"""Visual feedback and messaging system with Rich"""
from typing import Dict, Any, Optional
from rich.console import Console
from rich.panel import Panel
from rich import box
import time


class VisualFeedback:
    """Rich visual feedback for user actions"""

    def __init__(self):
        self.console = Console()

    def success(self, message: str, details: str = ""):
        """Show success with icon and color"""
        self.console.print(f"\n[green]✅ Success![/green]")
        self.console.print(f"   {message}")
        if details:
            self.console.print(f"   [dim]{details}[/dim]")

    def warning(self, message: str, suggestion: str = ""):
        """Show warning with helpful suggestion"""
        self.console.print(f"\n[yellow]⚠️  Warning[/yellow]")
        self.console.print(f"   {message}")
        if suggestion:
            self.console.print(f"   [cyan]💡 Tip: {suggestion}[/cyan]")

    def error(self, message: str, recovery: str = ""):
        """Show error with recovery options"""
        self.console.print(f"\n[red]❌ Error[/red]")
        self.console.print(f"   {message}")
        if recovery:
            self.console.print(f"   [dim]Try: {recovery}[/dim]")

    def info(self, message: str):
        """Show informational message"""
        self.console.print(f"\n[cyan]ℹ️  {message}[/cyan]")

    def info_box(self, title: str, content: Dict[str, Any], width: int = 50):
        """Display information in a formatted box using Rich"""
        # Create content string
        content_lines = []
        for key, value in content.items():
            content_lines.append(f" {key}: {value}")

        content_str = "\n".join(content_lines)

        panel = Panel.fit(
            content_str,
            title=f"[bold cyan]{title}[/bold cyan]",
            box=box.DOUBLE,
            padding=(0, 2),
            border_style="cyan"
        )
        self.console.print(panel)

    @staticmethod
    def progress_bar(current: int, total: int, message: str = "", width: int = 40):
        """Display progress bar"""
        if total == 0:
            return

        percent = (current / total) * 100
        filled = int(width * current / total)
        bar = "█" * filled + "░" * (width - filled)

        print(f"\r{Sty.CYAN}⏳{Sty.RESET} [{bar}] {percent:.1f}% {message}", end="", flush=True)

        if current >= total:
            print()  # New line when complete

    @staticmethod
    def spinner(frame: int, message: str):
        """Display spinning indicator"""
        spinner_chars = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        char = spinner_chars[frame % len(spinner_chars)]
        print(f"\r{Sty.CYAN}{char}{Sty.RESET} {message}", end="", flush=True)


class ProgressIndicator:
    """Visual progress feedback for long operations with Rich"""

    def __init__(self, title: str, total: Optional[int] = None):
        from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn

        self.title = title
        self.total = total
        self.current = 0
        self.start_time = None

        # Create Rich progress display
        if total:
            self.progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
                TimeElapsedColumn(),
            )
        else:
            self.progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                TimeElapsedColumn(),
            )
        self.task_id = None

    def start(self):
        """Start the progress indicator"""
        self.start_time = time.time()
        self.progress.start()
        if self.total:
            self.task_id = self.progress.add_task(f"[cyan]{self.title}...", total=self.total)
        else:
            self.task_id = self.progress.add_task(f"[cyan]{self.title}...", total=None)

    def update(self, message: str = ""):
        """Update progress"""
        self.current += 1
        if self.task_id is not None:
            if self.total:
                self.progress.update(self.task_id, completed=self.current, description=f"[cyan]{self.title}: {message}")
            else:
                self.progress.update(self.task_id, description=f"[cyan]{self.title}: {message}")

    def done(self, message: str = "Complete"):
        """Mark as complete"""
        if self.task_id is not None and self.total:
            self.progress.update(self.task_id, completed=self.total, description=f"[green]{self.title} {message}")

        elapsed = None
        if self.start_time:
            elapsed = time.time() - self.start_time

        self.progress.stop()

        # Show final success message
        console = Console()
        console.print(f"\n[green]✅ {self.title} {message}[/green]")
        if elapsed:
            console.print(f"   [dim]({elapsed:.1f}s)[/dim]")


class ErrorHandler:
    """User-friendly error handling with Rich"""

    def __init__(self):
        self.feedback = VisualFeedback()

    def handle_path_error(self, path: str, operation: str):
        """User-friendly path error messages"""
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            self.feedback.error(
                f"Path not found: {path}",
                "Check the path spelling and ensure the location exists"
            )
        elif not p.is_dir():
            self.feedback.error(
                f"Not a directory: {path}",
                "Expected a folder but found a file"
            )
        else:
            self.feedback.error(
                f"Access denied: {path}",
                "Check permissions or try running with elevated privileges"
            )

    def handle_operation_error(self, error: Exception, context: str):
        """Contextual error messages"""
        error_msg = str(error).lower()

        if "permission" in error_msg:
            self.feedback.error(
                f"Permission denied during {context}",
                "Check file/folder permissions"
            )
        elif "disk" in error_msg or "space" in error_msg:
            self.feedback.error(
                f"Disk space issue during {context}",
                "Free up disk space and try again"
            )
        elif "network" in error_msg:
            self.feedback.error(
                f"Network error during {context}",
                "Check network connection and try again"
            )
        else:
            self.feedback.error(
                f"Operation failed: {error}",
                "Try again or check the logs for more details"
            )
