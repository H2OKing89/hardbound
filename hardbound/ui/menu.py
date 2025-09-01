"""Unified menu system with Rich for perfect Unicode handling"""
import re
from typing import Dict, Callable, Optional
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich import box
from ..display import Sty
from .feedback import VisualFeedback


class MenuSystem:
    """Standardized menu system with Rich for perfect Unicode display"""

    def __init__(self):
        self.menus: Dict[str, Dict] = {}
        self.current_menu: Optional[str] = None
        self.console = Console()

    def add_menu(self, name: str, title: str, options: Dict[str, tuple], width: int = 50):
        """Add a menu with options

        Args:
            name: Menu identifier
            title: Menu title
            options: Dict of {choice: (label, handler)}
            width: Menu width in characters
        """
        self.menus[name] = {
            'title': title,
            'options': options,
            'width': width
        }

    def display_menu(self, name: str) -> Optional[str]:
        """Display a menu using Rich for perfect alignment

        Returns:
            Selected choice or None if invalid
        """
        if name not in self.menus:
            self.console.print(f"[red]❌ Menu '{name}' not found[/red]")
            return None

        menu = self.menus[name]

        # Create table for menu items
        table = Table.grid(padding=(0, 1))
        table.add_column(justify="left")

        # Add menu items
        for choice, (label, _) in menu['options'].items():
            table.add_row(f"[bold green]{choice})[/] {label}")

        # Create panel with perfect borders
        panel = Panel.fit(
            table,
            title=f"[bold cyan]{menu['title']}[/]",
            box=box.DOUBLE,  # ╔═╦═╗ style
            padding=(0, 2),
            border_style="cyan"
        )

        self.console.print(panel)
        return self._get_choice(list(menu['options'].keys()))

    def _get_choice(self, valid_choices: list) -> Optional[str]:
        """Get and validate user choice"""
        while True:
            try:
                choice = self.console.input("[bold cyan]➤ Enter choice: [/]").strip().lower()

                if not choice:
                    continue

                # Check for exact match
                if choice in valid_choices:
                    return choice

                # Check for single character match (e.g., '1' matches '1')
                if len(choice) == 1:
                    for valid in valid_choices:
                        if valid.lower().startswith(choice):
                            return valid

                self.console.print(f"[yellow]⚠️  Invalid choice. Please select from: {', '.join(valid_choices)}[/yellow]")

            except KeyboardInterrupt:
                self.console.print("[cyan]👋 Cancelled[/cyan]")
                return None
            except EOFError:
                return None

    def handle_choice(self, menu_name: str, choice: str) -> bool:
        """Handle menu choice and return True if should continue"""
        if menu_name not in self.menus:
            return True

        menu = self.menus[menu_name]
        if choice in menu['options']:
            label, handler = menu['options'][choice]
            if handler:
                try:
                    result = handler()
                    return result if result is not None else True
                except Exception as e:
                    self.console.print(f"[red]❌ Error: {e}[/red]")
                    return True

        return True
import re
import unicodedata
from typing import Dict, Callable, Optional
from ..display import Sty


def display_width(text: str) -> int:
    """Calculate the display width of text, accounting for full-width characters"""
    # Remove ANSI codes first
    clean_text = re.sub(r'\x1b\[[0-9;]*m', '', text)

    width = 0
    for char in clean_text:
        # Check if character is full-width (East Asian Wide, Full-width, etc.)
        if unicodedata.east_asian_width(char) in ('W', 'F', 'A'):
            width += 2
        else:
            width += 1
    return width


# Global menu system instance
menu_system = MenuSystem()


def create_main_menu():
    """Create the main interactive menu"""
    def search_handler():
        """Handle search and link choice"""
        from ..interactive import search_and_link_wizard
        search_and_link_wizard()
        return True

    def update_handler():
        """Handle catalog update choice"""
        from ..interactive import update_catalog_wizard
        update_catalog_wizard()
        return True

    def recent_handler():
        """Handle recent downloads choice"""
        from ..interactive import recent_downloads_scanner
        recent_downloads_scanner()
        return True

    def browse_handler():
        """Handle folder browsing choice"""
        from ..interactive import folder_batch_wizard
        folder_batch_wizard()
        return True

    def settings_handler():
        """Handle settings choice"""
        from ..interactive import settings_menu
        settings_menu()
        return True

    def help_handler():
        """Handle help choice"""
        from ..interactive import show_interactive_help
        show_interactive_help()
        return True

    def exit_handler():
        """Handle exit choice"""
        feedback = VisualFeedback()
        feedback.info("Goodbye!")
        return False

    menu_system.add_menu(
        'main',
        'HARDBOUND - Audiobook Manager',
        {
            '1': ('🔍 Search & Link Books', search_handler),
            '2': ('📊 Update Catalog', update_handler),
            '3': ('🔗 Link Recent Downloads', recent_handler),
            '4': ('📁 Browse by Folder', browse_handler),
            '5': ('⚙️  Settings & Preferences', settings_handler),
            '6': ('❓ Help & Tutorial', help_handler),
            '7': ('🚪 Exit', exit_handler)
        },
        width=45
    )


def create_quick_actions_menu():
    """Create streamlined quick actions menu"""
    menu_system.add_menu(
        'quick',
        'Quick Actions',
        {
            '1': ('🔍 Search & Link', None),
            '2': ('📥 Process Recent', None),
            '3': ('📚 Browse Library', None),
            '4': ('⚙️  More Options...', None),
            '0': ('🚪 Exit', None)
        },
        width=35
    )
