"""Input validation and path handling utilities"""

from pathlib import Path
from typing import List, Optional

from rich.console import Console

# Global console instance
console = Console()


class PathValidator:
    """Centralized path validation"""

    @staticmethod
    def validate_library_path(path_str: str) -> Optional[Path]:
        """Validate and return library path"""
        if not path_str or not path_str.strip():
            return None

        path = Path(path_str.strip()).expanduser()

        if not path.exists():
            console.print(f"[yellow]⚠️  Path does not exist: {path}[/yellow]")
            console.print(
                f"[cyan]💡 Tip: Check if the path is mounted or spelled correctly[/cyan]"
            )
            return None

        if not path.is_dir():
            console.print(f"[yellow]⚠️  Not a directory: {path}[/yellow]")
            console.print(f"[cyan]💡 Tip: Expected a folder, got a file[/cyan]")
            return None

        return path

    @staticmethod
    def validate_destination_path(path_str: str) -> Optional[Path]:
        """Validate destination path (can be non-existent)"""
        if not path_str or not path_str.strip():
            return None

        path = Path(path_str.strip()).expanduser()

        # Check if parent exists
        if not path.parent.exists():
            console.print(
                f"[yellow]⚠️  Parent directory does not exist: {path.parent}[/yellow]"
            )
            console.print(f"[cyan]💡 Tip: Create the parent directory first[/cyan]")
            return None

        return path

    @staticmethod
    def validate_destination_path_with_limit(path_str: str, limit: Optional[int] = None) -> Optional[Path]:
        """Validate destination path with optional character limit"""
        if not path_str or not path_str.strip():
            return None

        path = Path(path_str.strip()).expanduser()
        path_str = str(path)

        # Check path length limit
        if limit is not None and len(path_str) > limit:
            console.print(
                f"[yellow]⚠️  Path too long: {len(path_str)} characters (limit: {limit})[/yellow]"
            )
            console.print(f"[cyan]💡 Tip: Use a shorter path or abbreviations[/cyan]")
            return None

        # Check if parent exists
        if not path.parent.exists():
            console.print(
                f"[yellow]⚠️  Parent directory does not exist: {path.parent}[/yellow]"
            )
            console.print(f"[cyan]💡 Tip: Create the parent directory first[/cyan]")
            return None

        return path

    @staticmethod
    def get_default_search_paths() -> List[Path]:
        """Get sensible default search paths"""
        defaults = []

        # Common audiobook locations
        candidates = [
            Path.home() / "audiobooks",
            Path.home() / "Downloads",
            Path.home() / "Documents" / "audiobooks",
            Path("/mnt/user/data/audio/audiobooks"),  # Unraid default
            Path("/mnt/user/data/downloads"),  # Unraid downloads
        ]

        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                defaults.append(candidate)

        return defaults

    @staticmethod
    def suggest_similar_paths(input_path: str) -> List[str]:
        """Suggest similar existing paths"""
        path = Path(input_path).expanduser()
        suggestions = []

        # Check parent directory
        if path.parent.exists():
            siblings = [p.name for p in path.parent.iterdir() if p.is_dir()]
            # Find similar names
            import difflib

            matches = difflib.get_close_matches(path.name, siblings, n=3, cutoff=0.6)
            suggestions.extend([str(path.parent / match) for match in matches])

        return suggestions


class InputValidator:
    """Input validation utilities"""

    @staticmethod
    def get_choice(
        prompt: str, valid_choices: List[str], default: Optional[str] = None
    ) -> Optional[str]:
        """Get validated choice from user"""
        while True:
            if default:
                choice = input(f"{prompt} [{default}]: ").strip() or default
            else:
                choice = input(f"{prompt}: ").strip()

            if not choice:
                continue

            # Exact match
            if choice in valid_choices:
                return choice

            # Single character match
            if len(choice) == 1:
                for valid in valid_choices:
                    if valid.lower().startswith(choice.lower()):
                        return valid

            console.print(
                f"[yellow]⚠️  Invalid choice. Valid options: {', '.join(valid_choices)}[/yellow]"
            )

    @staticmethod
    def get_path(prompt: str, must_exist: bool = True) -> Optional[Path]:
        """Get and validate path input"""
        while True:
            path_str = input(f"{prompt}: ").strip()

            if not path_str:
                return None

            if must_exist:
                path = PathValidator.validate_library_path(path_str)
            else:
                path = PathValidator.validate_destination_path(path_str)

            if path:
                return path

            # Offer suggestions
            suggestions = PathValidator.suggest_similar_paths(path_str)
            if suggestions:
                console.print(f"[cyan]💡 Did you mean:[/cyan]")
                for i, suggestion in enumerate(suggestions, 1):
                    console.print(f"   {i}. {suggestion}")

                if InputValidator.get_choice("Use suggestion?", ["y", "n"]) == "y":
                    choice = InputValidator.get_choice(
                        "Which one?", [str(i) for i in range(1, len(suggestions) + 1)]
                    )
                    if choice and choice.isdigit():
                        return Path(suggestions[int(choice) - 1])

    @staticmethod
    def confirm_action(message: str, default: bool = False) -> bool:
        """Get confirmation with default"""
        default_text = "Y/n" if default else "y/N"
        response = input(f"{message} [{default_text}]: ").strip().lower()

        if not response:
            return default

        return response in ["y", "yes", "true", "1"]

    @staticmethod
    def get_number(
        prompt: str,
        min_val: Optional[int] = None,
        max_val: Optional[int] = None,
        default: Optional[int] = None,
    ) -> Optional[int]:
        """Get validated number input"""
        while True:
            if default is not None:
                num_str = input(f"{prompt} [{default}]: ").strip() or str(default)
            else:
                num_str = input(f"{prompt}: ").strip()

            if not num_str:
                continue

            try:
                num = int(num_str)

                if min_val is not None and num < min_val:
                    console.print(f"[yellow]⚠️  Minimum value is {min_val}[/yellow]")
                    continue

                if max_val is not None and num > max_val:
                    console.print(f"[yellow]⚠️  Maximum value is {max_val}[/yellow]")
                    continue

                return num

            except ValueError:
                console.print(f"[yellow]⚠️  Please enter a valid number[/yellow]")
