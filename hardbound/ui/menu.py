"""Unified menu system for consistent navigation"""
from typing import Dict, Callable, Optional
from ..display import Sty


class MenuSystem:
    """Standardized menu system with consistent navigation"""

    def __init__(self):
        self.menus: Dict[str, Dict] = {}
        self.current_menu: Optional[str] = None

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
        """Display a menu and get user choice

        Returns:
            Selected choice or None if invalid
        """
        if name not in self.menus:
            print(f"{Sty.RED}❌ Menu '{name}' not found{Sty.RESET}")
            return None

        menu = self.menus[name]
        width = menu['width']

        # Display header
        print(f"\n{Sty.CYAN}╔{'═' * width}╗")
        print(f"║ {menu['title'].center(width-2)} ║")
        print(f"╠{'═' * width}╣{Sty.RESET}")

        # Display options
        for choice, (label, _) in menu['options'].items():
            print(f"║ {Sty.GREEN}{choice}{Sty.RESET}) {label}{' ' * (width - len(label) - len(choice) - 4)} ║")

        # Display footer
        print(f"{Sty.CYAN}╚{'═' * width}╝{Sty.RESET}")

        return self._get_choice(list(menu['options'].keys()))

    def _get_choice(self, valid_choices: list) -> Optional[str]:
        """Get and validate user choice"""
        while True:
            try:
                choice = input(f"\n{Sty.CYAN}➤ Enter choice: {Sty.RESET}").strip().lower()

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

                print(f"{Sty.YELLOW}⚠️  Invalid choice. Please select from: {', '.join(valid_choices)}{Sty.RESET}")

            except KeyboardInterrupt:
                print(f"\n{Sty.CYAN}👋 Cancelled{Sty.RESET}")
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
                    print(f"{Sty.RED}❌ Error: {e}{Sty.RESET}")
                    return True

        return True


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
        from ..ui.feedback import VisualFeedback
        VisualFeedback.info("Goodbye!")
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
