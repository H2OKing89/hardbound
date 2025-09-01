"""Visual feedback and messaging system"""
from typing import Dict, Any, Optional
from ..display import Sty
import time


class VisualFeedback:
    """Rich visual feedback for user actions"""

    @staticmethod
    def success(message: str, details: str = ""):
        """Show success with icon and color"""
        print(f"\n{Sty.GREEN}✅ Success!{Sty.RESET}")
        print(f"   {message}")
        if details:
            print(f"   {Sty.DIM}{details}{Sty.RESET}")

    @staticmethod
    def warning(message: str, suggestion: str = ""):
        """Show warning with helpful suggestion"""
        print(f"\n{Sty.YELLOW}⚠️  Warning{Sty.RESET}")
        print(f"   {message}")
        if suggestion:
            print(f"   {Sty.CYAN}💡 Tip: {suggestion}{Sty.RESET}")

    @staticmethod
    def error(message: str, recovery: str = ""):
        """Show error with recovery options"""
        print(f"\n{Sty.RED}❌ Error{Sty.RESET}")
        print(f"   {message}")
        if recovery:
            print(f"   {Sty.DIM}Try: {recovery}{Sty.RESET}")

    @staticmethod
    def info(message: str):
        """Show informational message"""
        print(f"\n{Sty.CYAN}ℹ️  {message}{Sty.RESET}")

    @staticmethod
    def info_box(title: str, content: Dict[str, Any], width: int = 50):
        """Display information in a formatted box"""
        print(f"\n{Sty.CYAN}╔{'═' * width}╗")
        print(f"║ {title.center(width-2)} ║")
        print(f"╠{'═' * width}╣{Sty.RESET}")

        for key, value in content.items():
            line = f" {key}: {value}"
            print(f"║{line:<{width}}║")

        print(f"{Sty.CYAN}╚{'═' * width}╝{Sty.RESET}")

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
    """Visual progress feedback for long operations"""

    def __init__(self, title: str, total: Optional[int] = None):
        self.title = title
        self.total = total
        self.current = 0
        self.start_time = None

    def start(self):
        """Start the progress indicator"""
        self.start_time = time.time()
        print(f"{Sty.CYAN}⏳{Sty.RESET} {self.title}...")

    def update(self, message: str = ""):
        """Update progress"""
        self.current += 1

        if self.total:
            VisualFeedback.progress_bar(self.current, self.total, message)
        else:
            frame = self.current % 10
            VisualFeedback.spinner(frame, f"{self.title}: {message}")

    def done(self, message: str = "Complete"):
        """Mark as complete"""
        if self.total:
            VisualFeedback.progress_bar(self.total, self.total, message)

        elapsed = None
        if self.start_time:
            elapsed = time.time() - self.start_time

        detail = ""
        if elapsed:
            detail = f"({elapsed:.1f}s)"

        VisualFeedback.success(f"{self.title} {message}", detail)


class ErrorHandler:
    """User-friendly error handling"""

    @staticmethod
    def handle_path_error(path: str, operation: str):
        """User-friendly path error messages"""
        from pathlib import Path

        p = Path(path)
        if not p.exists():
            VisualFeedback.error(
                f"Path not found: {path}",
                "Check the path spelling and ensure the location exists"
            )
        elif not p.is_dir():
            VisualFeedback.error(
                f"Not a directory: {path}",
                "Expected a folder but found a file"
            )
        else:
            VisualFeedback.error(
                f"Access denied: {path}",
                "Check permissions or try running with elevated privileges"
            )

    @staticmethod
    def handle_operation_error(error: Exception, context: str):
        """Contextual error messages"""
        error_msg = str(error).lower()

        if "permission" in error_msg:
            VisualFeedback.error(
                f"Permission denied during {context}",
                "Check file/folder permissions"
            )
        elif "disk" in error_msg or "space" in error_msg:
            VisualFeedback.error(
                f"Disk space issue during {context}",
                "Free up disk space and try again"
            )
        elif "network" in error_msg:
            VisualFeedback.error(
                f"Network error during {context}",
                "Check network connection and try again"
            )
        else:
            VisualFeedback.error(
                f"Operation failed: {error}",
                "Try again or check the logs for more details"
            )
