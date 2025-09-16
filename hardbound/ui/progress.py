"""Progress indicators and spinners for long-running operations"""

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

console = Console()


class ProgressManager:
    """Manager for progress indicators and spinners"""

    def __init__(self) -> None:
        self.active_progress = None

    def create_spinner(self, description: str) -> Progress:
        """Create a spinner progress indicator"""
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        )

    def create_bar(self, description: str, total: int) -> Progress:
        """Create a progress bar indicator"""
        return Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        )

    def start_task(
        self, progress: Progress, description: str, total: int | None = None
    ) -> TaskID:
        """Start a progress task"""
        if total is not None:
            return progress.add_task(description, total=total)
        else:
            return progress.add_task(description)

    def update_task(
        self,
        progress: Progress,
        task_id: TaskID,
        advance: int = 1,
        description: str | None = None,
    ) -> None:
        """Update progress task"""
        progress.update(task_id, advance=advance, description=description)

    def finish_task(self, progress: Progress, task_id: TaskID) -> None:
        """Mark task as completed"""
        progress.update(task_id, completed=True)


# Global progress manager instance
progress_manager = ProgressManager()
