#!/usr/bin/env python3
"""
Interactive mode and wizard functionality
"""
import json
import os
import shutil
import subprocess
import copy
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Dict, List, Optional

from rich.console import Console

from .catalog import DB_FILE, AudiobookCatalog
from .config import load_config, save_config, ConfigManager, DEFAULT_CONFIG
from .display import Sty, summary_table
from .linker import plan_and_link, plan_and_link_red, zero_pad_vol
from .ui.feedback import ErrorHandler, ProgressIndicator, VisualFeedback
from .ui.menu import create_main_menu, create_quick_actions_menu, menu_system
from .utils.validation import InputValidator, PathValidator
from .utils.logging import get_logger

# Global Rich console for consistent output
console = Console()

# Get structured logger for interactive module
log = get_logger(__name__)


def _get_recent_sources(config):
    """Safely get recent sources as a list"""
    sources = config.get("recent_sources", [])
    return sources if isinstance(sources, list) else []


def parse_selection_input(input_str: str, max_items: int) -> List[int]:
    """Parse selection input with support for ranges and comma-separated values.
    
    Examples:
    - "1,3,5" -> [0, 2, 4]
    - "1-5" -> [0, 1, 2, 3, 4]
    - "1-3,7,9-11" -> [0, 1, 2, 6, 8, 9, 10]
    
    Returns 0-based indices.
    """
    indices = set()
    
    # Split by commas and handle each part
    for part in input_str.replace(' ', '').split(','):
        if not part:
            continue
            
        if '-' in part:
            # Handle range (e.g., "1-5")
            try:
                start_str, end_str = part.split('-', 1)
                start = int(start_str)
                end = int(end_str)
                
                # Convert to 0-based and validate
                if start >= 1 and end >= 1 and start <= max_items and end <= max_items:
                    for i in range(min(start, end), max(start, end) + 1):
                        indices.add(i - 1)  # Convert to 0-based
            except ValueError:
                # Skip invalid ranges
                continue
        else:
            # Handle single number
            try:
                num = int(part)
                if 1 <= num <= max_items:
                    indices.add(num - 1)  # Convert to 0-based
            except ValueError:
                # Skip invalid numbers
                continue
    
    return sorted(list(indices))


def have_fzf() -> bool:
    """Check if fzf is available"""
    import shutil

    return shutil.which("fzf") is not None


def hierarchical_browser(catalog) -> List[str]:
    """Browse audiobooks by author/series hierarchy"""

    # Get all unique authors from catalog
    all_items = catalog.search("*", limit=5000)

    # Build author index
    authors_by_initial = {}
    author_to_books = {}

    for item in all_items:
        author = item.get("author", "Unknown")
        if not author or author == "—":
            author = "Unknown"

        # Get first character for grouping
        initial = author[0].upper() if author else "#"
        if not initial.isalpha():
            initial = "#"  # Group numbers and special chars

        if initial not in authors_by_initial:
            authors_by_initial[initial] = set()
        authors_by_initial[initial].add(author)

        # Track books per author
        if author not in author_to_books:
            author_to_books[author] = []
        author_to_books[author].append(item)

    console.print("[cyan]📚 BROWSE BY AUTHOR[/cyan]")
    print(f"\nSelect first letter of author's name:\n")

    # Show initials with counts
    initials = sorted(authors_by_initial.keys())
    cols = 6  # Number of columns
    for i in range(0, len(initials), cols):
        row = []
        for j in range(cols):
            if i + j < len(initials):
                initial = initials[i + j]
                count = len(authors_by_initial[initial])
                row.append(f"[yellow]{initial}[/yellow]({count:2d})")
            else:
                row.append("      ")
        console.print("  " + "  ".join(row))

    console.print(f"\n[yellow]Enter letter(s), or 'search' for text search:[/yellow]")
    choice = input("Choice: ").strip().upper()

    if choice.lower() == "search":
        return enhanced_text_search_browser(catalog)

    if not choice or choice not in authors_by_initial:
        console.print(f"[yellow]Invalid selection[/yellow]")
        return []

    # Step 2: Choose author
    authors = sorted(authors_by_initial[choice])

    console.print(f"\n[cyan]Authors starting with '{choice}':[/cyan]\n")

    # Paginate if too many
    page_size = 20
    current_page = 0

    while True:
        start = current_page * page_size
        end = min(start + page_size, len(authors))

        for i, author in enumerate(authors[start:end], start + 1):
            book_count = len(author_to_books[author])
            console.print(
                f"[green]{i:3d}[/green]) {author} ({book_count} book{'s' if book_count > 1 else ''})"
            )

        nav_options = []
        if current_page > 0:
            nav_options.append("'p' = previous")
        if end < len(authors):
            nav_options.append("'n' = next")
        nav_options.append("number = select")
        nav_options.append("'q' = quit")

        console.print(f"\n[yellow]{' | '.join(nav_options)}:[/yellow]")
        choice = input("Choice: ").strip().lower()

        if choice == "q":
            return []
        elif choice == "n" and end < len(authors):
            current_page += 1
        elif choice == "p" and current_page > 0:
            current_page -= 1
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(authors):
                selected_author = authors[idx]
                break
        else:
            console.print(f"[yellow]Invalid selection[/yellow]")

    # Step 3: Browse author's books
    author_books = author_to_books[selected_author]

    # Group by series if applicable
    series_groups = {}
    standalone = []

    for book in author_books:
        series = book.get("series", "")
        if series and series != "—":
            if series not in series_groups:
                series_groups[series] = []
            series_groups[series].append(book)
        else:
            standalone.append(book)

    console.print(f"\n[cyan]📚 {selected_author}[/cyan]")

    all_selectable = []

    # Show series first
    if series_groups:
        console.print(f"\n[bold]Series:[/bold]")
        for series in sorted(series_groups.keys()):
            books = sorted(series_groups[series], key=lambda x: x.get("book", ""))
            console.print(f"\n  [magenta]{series}[/magenta] ({len(books)} books)")
            for book in books:
                all_selectable.append(book)
                idx = len(all_selectable)
                size_mb = book.get("size", 0) / (1024 * 1024)
                indicator = "📘" if book.get("has_m4b") else "🎵"
                console.print(
                    f"    [green]{idx:3d}[/green]) {book['book']} {indicator} ({size_mb:.0f}MB)"
                )

    # Show standalone books
    if standalone:
        console.print(f"\n[bold]Standalone:[/bold]")
        for book in sorted(standalone, key=lambda x: x.get("book", "")):
            all_selectable.append(book)
            idx = len(all_selectable)
            size_mb = book.get("size", 0) / (1024 * 1024)
            indicator = "📘" if book.get("has_m4b") else "🎵"
            console.print(
                f"  [green]{idx:3d}[/green]) {book['book']} {indicator} ({size_mb:.0f}MB)"
            )

    # Selection
    console.print(f"\n[cyan]🎯 Selection Instructions:[/cyan]")
    console.print(f"  • Enter numbers separated by commas: [green]1,3,5[/green]")
    console.print(f"  • Use ranges with dashes: [green]1-5,8,10-12[/green]")
    console.print(f"  • Enter [green]all[/green] to select everything")
    console.print(f"  • Press Enter without input to cancel")
    console.print(f"\n[yellow]Selection (or 'q' to quit):[/yellow]")
    choice = input("Choice: ").strip().lower()

    if choice == "q":
        return []
    elif choice == "all":
        return [book["path"] for book in all_selectable]
    elif not choice:
        return []
    else:
        selected = []
        selected_indices = parse_selection_input(choice, len(all_selectable))
        for idx in selected_indices:
            if 0 <= idx < len(all_selectable):
                selected.append(all_selectable[idx]["path"])
        return selected


def enhanced_text_search_browser(catalog) -> List[str]:
    """Enhanced text search browser with autocomplete and history"""
    console.print(f"\n[cyan]🔍 ENHANCED TEXT SEARCH[/cyan]")

    # Load search history
    history_file = Path.home() / ".cache" / "hardbound" / "search_history.txt"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    search_history = []
    if history_file.exists():
        try:
            with open(history_file, "r", encoding="utf-8") as f:
                search_history = [
                    line.strip() for line in f.readlines() if line.strip()
                ]
        except Exception:
            pass  # Ignore history loading errors

    # Get autocomplete suggestions from catalog
    autocomplete_suggestions = _get_autocomplete_suggestions(catalog)

    print("\nEnter search terms (author, title, series):")
    console.print(f"[dim]💡 Type a few letters and press Tab for suggestions[/dim]")
    console.print(f"[dim]💡 Press ↑/↓ for search history[/dim]")

    query = _enhanced_input("Search: ", autocomplete_suggestions, search_history)

    if not query:
        return []

    # Save to history
    if query not in search_history:
        search_history.insert(0, query)
        search_history = search_history[:50]  # Keep last 50 searches
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                f.write("\n".join(search_history))
        except Exception:
            pass  # Ignore history saving errors

    results = catalog.search(query, limit=100)

    if not results:
        console.print(f"[yellow]No results found[/yellow]")
        console.print(f"[dim]💡 Try different keywords or check spelling[/dim]")
        return []

    console.print(f"\n[green]Found {len(results)} result(s):[/green]\n")

    # Display with pagination
    page_size = 20
    current_page = 0

    while True:
        start = current_page * page_size
        end = min(start + page_size, len(results))

        for i, book in enumerate(results[start:end], start + 1):
            author = book.get("author", "—")
            series = book.get("series", "")
            title = book.get("book", "—")
            size_mb = book.get("size", 0) / (1024 * 1024)

            if series:
                display = f"{author} ▸ {series} ▸ {title}"
            else:
                display = f"{author} ▸ {title}"

            indicator = "📘" if book.get("has_m4b") else "🎵"
            console.print(
                f"[green]{i:3d}[/green]) {display} {indicator} ({size_mb:.0f}MB)"
            )

        nav_options = []
        if current_page > 0:
            nav_options.append("'p' = previous")
        if end < len(results):
            nav_options.append("'n' = next")
        nav_options.append("numbers = select (space-separated)")
        nav_options.append("'all' = select all")
        nav_options.append("'q' = quit")

        console.print(f"\n[yellow]{' | '.join(nav_options)}:[/yellow]")
        choice = input("Choice: ").strip().lower()

        if choice == "q":
            return []
        elif choice == "n" and end < len(results):
            current_page += 1
        elif choice == "p" and current_page > 0:
            current_page -= 1
        elif choice == "all":
            return [book["path"] for book in results]
        else:
            # Parse number selections
            selected = []
            for num in choice.split():
                if num.isdigit():
                    idx = int(num) - 1
                    if 0 <= idx < len(results):
                        selected.append(results[idx]["path"])
            if selected:
                return selected


def _get_autocomplete_suggestions(catalog) -> List[str]:
    """Get autocomplete suggestions from catalog"""
    suggestions = set()

    # Check if this is a database-backed catalog
    if hasattr(catalog, "conn"):
        # Database-backed catalog (AudiobookCatalog)
        try:
            cursor = catalog.conn.execute(
                """
                SELECT author, series, book FROM items
                WHERE author != 'Unknown'
                ORDER BY mtime DESC
                LIMIT 100
            """
            )

            for row in cursor.fetchall():
                author = row[0]
                series = row[1]
                book = row[2]

                if author and len(author) > 2:
                    suggestions.add(author)
                if series and len(series) > 2:
                    suggestions.add(series)
                if book and len(book) > 3:
                    # Add first few words of book title
                    words = book.split()[:3]
                    if len(words) >= 2:
                        suggestions.add(" ".join(words))

        except Exception:
            pass  # Ignore errors
    else:
        # In-memory catalog (TempCatalog) - get suggestions from search results
        try:
            # Get a sample of items to build suggestions
            items = catalog.search("*", limit=100)
            for item in items:
                author = item.get("author", "")
                series = item.get("series", "")
                book = item.get("book", "")

                if author and len(author) > 2:
                    suggestions.add(author)
                if series and len(series) > 2:
                    suggestions.add(series)
                if book and len(book) > 3:
                    # Add first few words of book title
                    words = book.split()[:3]
                    if len(words) >= 2:
                        suggestions.add(" ".join(words))

        except Exception:
            pass  # Ignore errors

    return sorted(list(suggestions))


def _enhanced_input(prompt: str, autocomplete: List[str], history: List[str]) -> str:
    """Enhanced input with basic autocomplete and history"""
    print(prompt, end="", flush=True)

    # Simple implementation - in a real enhancement, this would use readline
    # For now, just provide basic input with hints
    try:
        query = input().strip()
        return query
    except KeyboardInterrupt:
        print("\nCancelled.")
        return ""


# Update fzf_pick to use hierarchical browser when fzf is not available
def fzf_pick(candidates: List[Dict], multi: bool = True) -> List[str]:
    """
    Use fzf for interactive fuzzy selection with preview
    Falls back to hierarchical browser when fzf is not available
    """
    if not candidates:
        return []

    if not have_fzf():
        # Use hierarchical browser instead of simple fallback
        console.print(f"[yellow]fzf not found. Using hierarchical browser.[/yellow]")

        # Create a temporary catalog-like interface
        class TempCatalog:
            def search(self, query, limit=500):
                if query == "*":
                    return candidates[:limit]
                query_lower = query.lower()
                results = []
                for c in candidates:
                    if (
                        query_lower in c.get("author", "").lower()
                        or query_lower in c.get("book", "").lower()
                        or query_lower in c.get("series", "").lower()
                    ):
                        results.append(c)
                        if len(results) >= limit:
                            break
                return results

        temp_catalog = TempCatalog()
        return hierarchical_browser(temp_catalog)

    # Build searchable lines with metadata
    lines = []
    for r in candidates:
        author = r.get("author", "—")
        series = r.get("series", "—")
        book = r.get("book", "—")
        path = r["path"]

        # Format: "Author ▸ Series ▸ Book\tpath\tJSON"
        display = (
            f"{author} ▸ {series} ▸ {book}" if series != "—" else f"{author} ▸ {book}"
        )

        # Add indicators
        if r.get("has_m4b"):
            display += " 📘"
        elif r.get("has_mp3"):
            display += " 🎵"

        # Add size
        size_mb = r.get("size", 0) / (1024 * 1024)
        display += f" ({size_mb:.0f}MB)"

        payload = json.dumps({"path": path})
        lines.append(f"{display}\t{path}\t{payload}")

    # Preview command - show files and stats
    preview_cmd = r"""
    p=$(echo {} | awk -F"\t" "{print \$2}");
    if [ -d "$p" ]; then
        echo "📁 $p";
        echo "";
        echo "Files:";
        ls -lah "$p" 2>/dev/null | head -20;
        echo "";
        echo "Audio files:";
        find "$p" -maxdepth 1 \( -name "*.m4b" -o -name "*.mp3" \) -exec basename {} \; 2>/dev/null | head -10;
        echo "";
        echo "Total size: $(du -sh "$p" 2>/dev/null | cut -f1)";
    fi
    """

    # Build fzf command
    fzf_args = [
        "fzf",
        "--ansi",
        "--with-nth=1",  # Only show first column for searching
        "--delimiter=\t",
        "--height=90%",
        "--reverse",
        "--preview",
        preview_cmd,
        "--preview-window=right:50%:wrap",
        "--header=TAB: select, Enter: confirm, Ctrl-C: cancel",
        "--prompt=Search> ",
    ]

    if multi:
        fzf_args.extend(["-m", "--bind=ctrl-a:select-all,ctrl-d:deselect-all"])

    try:
        proc = subprocess.run(
            fzf_args, input="\n".join(lines), text=True, capture_output=True
        )

        if proc.returncode != 0:
            return []

        # Extract paths from selected lines
        paths = []
        for line in proc.stdout.strip().splitlines():
            parts = line.split("\t")
            if len(parts) >= 3:
                try:
                    payload = json.loads(parts[2])
                    paths.append(payload["path"])
                except json.JSONDecodeError:
                    pass

        return paths

    except Exception as e:
        console.print(f"[red]fzf error: {e}[/red]")
        return fallback_picker(candidates, multi)


def fallback_picker(candidates: List[Dict], multi: bool) -> List[str]:
    """Fallback picker when fzf is not available"""
    if not candidates:
        return []

    console.print(f"\n[cyan]Select audiobook(s):[/cyan]")
    for i, r in enumerate(candidates[:30], 1):
        author = r.get("author", "—")
        book = r.get("book", "—")
        print(f"{i:3d}) {author} - {book}")
        console.print(f"      [dim]{r['path']}[/dim]")

    if len(candidates) > 30:
        print(f"... and {len(candidates) - 30} more")

    if multi:
        console.print(f"\n[cyan]🎯 Selection Instructions:[/cyan]")
        console.print(f"  • Enter numbers separated by commas: [green]1,3,5[/green]")
        console.print(f"  • Use ranges with dashes: [green]1-5,8,10-12[/green]")
        console.print(f"  • Enter [green]all[/green] to select everything")
        console.print(f"  • Press Enter without input to cancel")
        choice = input("\nSelection: ").strip()
        
        if choice.lower() == "all":
            return [c["path"] for c in candidates]
        elif not choice:
            return []

        selected_indices = parse_selection_input(choice, len(candidates))
        return [candidates[i]["path"] for i in selected_indices if 0 <= i < len(candidates)]
    else:
        choice = input("\nEnter number: ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(candidates):
                return [candidates[idx]["path"]]

    return []


def interactive_mode():
    """Enhanced interactive mode with improved UX"""
    config = load_config()

    # Initialize catalog if needed
    if not DB_FILE.exists():
        feedback = VisualFeedback()
        feedback.info("No catalog found. Building index...")

        catalog = AudiobookCatalog()
        default_path = PathValidator.get_default_search_paths()
        if default_path:
            progress = ProgressIndicator("Building catalog")
            catalog.index_directory(
                default_path[0], verbose=False, progress_callback=progress
            )
        catalog.close()

    # First run setup with better UX
    if config.get("first_run", True):
        _first_run_setup(config)

    # Create main menu
    create_main_menu()
    create_quick_actions_menu()

    # Main interaction loop
    current_menu = "main"
    running = True
    while running:
        try:
            choice = menu_system.display_menu(current_menu)
            if choice:
                result = menu_system.handle_choice(current_menu, choice)
                if isinstance(result, str):
                    # Menu switch requested
                    if result in ["main", "quick"]:
                        current_menu = result
                    else:
                        running = False if result == "exit" else True
                else:
                    # Boolean result
                    running = result if result is not None else True
            else:
                running = False

        except KeyboardInterrupt:
            feedback = VisualFeedback()
            feedback.info("Goodbye!")
            running = False
        except Exception as e:
            error_handler = ErrorHandler()
            error_handler.handle_operation_error(e, "menu operation")
            running = False


def _first_run_setup(config):
    """Enhanced first run setup with validation"""
    feedback = VisualFeedback()
    feedback.info_box(
        "Welcome to Hardbound!",
        {
            "Setup": "Let's configure your paths",
            "Tip": "You can change these later in Settings",
        },
    )

    # Library path setup
    library_path = None
    while not library_path:
        console.print(f"[cyan]➤[/cyan] Audiobook library path: ", end="")
        path_str = input().strip()
        if not path_str:
            # Try to auto-detect
            defaults = PathValidator.get_default_search_paths()
            if defaults:
                if InputValidator.confirm_action(f"Use {defaults[0]}?"):
                    library_path = defaults[0]
                else:
                    continue
            else:
                feedback = VisualFeedback()
                feedback.warning(
                    "No path provided", "You can set this later in Settings"
                )
                break
        else:
            library_path = PathValidator.validate_library_path(path_str)

    if library_path:
        config["library_path"] = str(library_path)

    # Destination path setup
    dest_path = None
    while not dest_path:
        console.print(f"[cyan]➤[/cyan] Torrent destination root: ", end="")
        path_str = input().strip()
        if not path_str:
            feedback = VisualFeedback()
            feedback.warning(
                "No destination provided", "You can set this later in Settings"
            )
            break

        dest_path = PathValidator.validate_destination_path(path_str)

    if dest_path:
        config["torrent_path"] = str(dest_path)

    config["first_run"] = False
    save_config(config)
    feedback = VisualFeedback()
    feedback.success("Setup complete!", "Your preferences have been saved")


# Progress indicator for long operations - Now using Rich-based ProgressIndicator from ui.feedback


def search_and_link_wizard():
    """Search-first linking wizard with hierarchical browsing"""
    console.print(f"\n[cyan]🔍 SEARCH AND LINK[/cyan]")

    catalog = AudiobookCatalog()

    # Offer choice of browse vs search
    print("\nHow would you like to find audiobooks?")
    console.print(
        f"  [green]1[/green]) Browse by author (recommended for large libraries)"
    )
    console.print(f"  [green]2[/green]) Search by text")
    console.print(f"  [green]3[/green]) Show recent audiobooks")

    choice = input("\nChoice (1-3): ").strip()

    if choice == "1":
        selected_paths = hierarchical_browser(catalog)
    elif choice == "2":
        selected_paths = enhanced_text_search_browser(catalog)
    elif choice == "3":
        results = catalog.search("*", limit=50)
        if results:
            console.print(f"\n[green]Recent audiobooks:[/green]")
            selected_paths = enhanced_text_search_browser(catalog)
        else:
            console.print(f"[yellow]No audiobooks found[/yellow]")
            selected_paths = []
    else:
        catalog.close()
        return

    if not selected_paths:
        catalog.close()
        return

    # Get destination - now with integration support
    config = load_config()
    config_manager = ConfigManager()
    config_manager.config = config
    
    # Get available integrations
    enabled_integrations = config_manager.get_enabled_integrations()
    
    if not enabled_integrations:
        console.print(f"[yellow]⚠️  No integrations are enabled. Please configure at least one integration.[/yellow]")
        catalog.close()
        return
    
    # Select integration if multiple are available
    selected_integration = None
    if len(enabled_integrations) == 1:
        selected_integration = list(enabled_integrations.keys())[0]
        console.print(f"[cyan]Using {selected_integration} integration[/cyan]")
    else:
        console.print(f"\n[bold]Select integration:[/bold]")
        for i, (name, config_data) in enumerate(enabled_integrations.items(), 1):
            path_limit = config_data.get("path_limit")
            limit_str = f" (limit: {path_limit} chars)" if path_limit else ""
            console.print(f"  [green]{i}[/green]) {name.upper()}{limit_str}: {config_data.get('path', '')}")
        
        choice = input(f"\nChoice (1-{len(enabled_integrations)}): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(enabled_integrations):
                selected_integration = list(enabled_integrations.keys())[idx]
            else:
                console.print(f"[red]Invalid choice[/red]")
                catalog.close()
                return
        except ValueError:
            console.print(f"[red]Invalid choice[/red]")
            catalog.close()
            return

    integration_config = enabled_integrations[selected_integration]
    default_dst = integration_config.get("path", "")

    console.print(f"\n[bold]Destination root ({selected_integration.upper()}):[/bold]")
    if default_dst:
        print(f"Default: {default_dst}")
        dst_input = input("Path (Enter for default): ").strip()
        dst_root = Path(dst_input) if dst_input else Path(str(default_dst))
    else:
        dst_input = input("Path: ").strip()
        if not dst_input:
            catalog.close()
            return
        dst_root = Path(dst_input)

    # Validate path length for the selected integration
    path_limit = integration_config.get("path_limit")
    if path_limit and len(str(dst_root)) > path_limit:
        console.print(f"[red]⚠️  Path too long: {len(str(dst_root))} characters (limit: {path_limit})[/red]")
        console.print(f"[cyan]💡 Tip: Use a shorter path for {selected_integration.upper()} integration[/cyan]")
        catalog.close()
        return

    # Preview and confirm
    console.print(
        f"\n[yellow]Will link {len(selected_paths)} audiobook(s) to {dst_root}[/yellow]"
    )
    confirm = input("Continue? [y/N]: ").lower()

    if confirm in ["y", "yes"]:
        stats = {
            "linked": 0,
            "replaced": 0,
            "already": 0,
            "exists": 0,
            "excluded": 0,
            "skipped": 0,
            "errors": 0,
        }
        zero_pad = bool(config.get("zero_pad", True))
        also_cover = bool(config.get("also_cover", False))

        for path_str in selected_paths:
            src = Path(path_str)

            print(f"\nProcessing: {src.name}")
            plan_and_link_red(
                src, dst_root, also_cover, zero_pad, False, False, stats
            )

        summary_table(stats, perf_counter())

    catalog.close()


def update_catalog_wizard():
    """Wizard for updating the catalog"""
    console.print(f"\n[cyan]📚 UPDATE CATALOG WIZARD[/cyan]")

    catalog = AudiobookCatalog()

    # Step 1: Choose update method
    console.print(f"\n[bold]Choose update method:[/bold]")
    console.print(f"  [green]1[/green]) Update from library path (recommended)")
    console.print(f"  [green]2[/green]) Manual directory selection")

    choice = input("Choice (1-2): ").strip()

    if choice == "1":
        # Update from configured library path
        config = load_config()
        library_path = Path(str(config.get("library_path", "")))

        if not library_path.exists():
            console.print(f"[red]❌ Library path not found: {library_path}[/red]")
            catalog.close()
            return

        print(f"\n📂 Scanning library path: {library_path}")
        progress = ProgressIndicator("Indexing audiobooks")
        count = catalog.index_directory(
            library_path, verbose=False, progress_callback=progress
        )
        console.print(f"[green]✅ Indexed {count} audiobooks[/green]")
    elif choice == "2":
        # Manual directory selection
        root = Path(input("Enter directory path: ").strip())
        if root.exists() and root.is_dir():
            print(f"\n📂 Scanning directory: {root}")
            progress = ProgressIndicator("Indexing audiobooks")
            count = catalog.index_directory(
                root, verbose=False, progress_callback=progress
            )
            console.print(f"[green]✅ Indexed {count} audiobooks[/green]")
        else:
            console.print(f"[red]❌ Invalid directory: {root}[/red]")
    else:
        console.print(f"[yellow]Invalid selection[/yellow]")

    catalog.close()


def recent_downloads_scanner():
    """Find and link recently downloaded audiobooks"""
    console.print(f"\n[cyan]🔍 RECENT DOWNLOADS SCANNER[/cyan]")

    # Check if catalog exists
    if DB_FILE.exists():
        print("Use catalog [C] or filesystem scan [F]? ", end="")
        choice = input().strip().upper()
        if choice == "C":
            # Use catalog for recent items
            catalog = AudiobookCatalog()
            results = catalog.search("*", limit=50)  # Get 50 most recent

            if results:
                selected_paths = fzf_pick(results, multi=True)
                if selected_paths:
                    _link_selected_paths(selected_paths)
            catalog.close()
            return

    # Fallback to filesystem scan
    hours = input(
        f"\nScan for audiobooks modified in last N hours (default 24): "
    ).strip()
    hours = int(hours) if hours.isdigit() else 24

    console.print(f"\n[yellow]Scanning filesystem...[/yellow]")
    recent = find_recent_audiobooks(hours=hours)

    if not recent:
        console.print(f"[yellow]No recent audiobooks found[/yellow]")
        return

    # Convert to dict format for picker
    candidates = []
    for path in recent:
        candidates.append(
            {
                "path": str(path),
                "book": path.name,
                "author": path.parent.name if path.parent.name != "audiobooks" else "—",
                "mtime": path.stat().st_mtime,
            }
        )

    selected_paths = fzf_pick(candidates, multi=True)
    if selected_paths:
        _link_selected_paths(selected_paths)


def folder_batch_wizard():
    """Legacy folder batch wizard - kept for compatibility"""
    console.print(
        f"\n[yellow]Note: For large libraries, use 'Search and link' instead[/yellow]"
    )
    console.print(f"[cyan]📁 FOLDER BATCH LINKER (Legacy)[/cyan]")

    config = load_config()

    # Use directory browser
    console.print(f"\n[bold]Choose folder containing audiobooks:[/bold]")
    src_folder = browse_directory_tree()
    if not src_folder:
        return

    # Find audiobook subdirectories
    audiobook_dirs = []
    console.print(f"\n[yellow]Scanning for audiobooks...[/yellow]")

    try:
        for item in src_folder.iterdir():
            if item.is_dir() and (any(item.glob("*.m4b")) or any(item.glob("*.mp3"))):
                audiobook_dirs.append(item)
    except PermissionError:
        console.print(f"[red]❌ Permission denied[/red]")
        return

    if not audiobook_dirs:
        if any(src_folder.glob("*.m4b")) or any(src_folder.glob("*.mp3")):
            audiobook_dirs = [src_folder]
        else:
            console.print(f"[red]No audiobooks found[/red]")
            return

    console.print(f"\n[green]Found {len(audiobook_dirs)} audiobook(s)[/green]")

    # Process with existing logic
    default_dst = config.get("torrent_path", "")
    if default_dst:
        print(f"Destination: {default_dst}")
        dst_input = input(f"Destination root (Enter for default): ").strip()
        dst_root = Path(dst_input) if dst_input else Path(str(default_dst))
    else:
        dst_input = input("Destination root: ").strip()
        if not dst_input:
            return
        dst_root = Path(dst_input)

    # Link all found audiobooks
    stats = {
        "linked": 0,
        "replaced": 0,
        "already": 0,
        "exists": 0,
        "excluded": 0,
        "skipped": 0,
        "errors": 0,
    }
    zero_pad = bool(config.get("zero_pad", True))
    also_cover = bool(config.get("also_cover", False))

    for book_dir in audiobook_dirs:
        print(f"\nProcessing: {book_dir.name}")
        plan_and_link_red(
            book_dir, dst_root, also_cover, zero_pad, False, False, stats
        )

    summary_table(stats, perf_counter())


def maintenance_menu():
    """Database maintenance and management menu"""
    from .catalog import AudiobookCatalog

    console.print(f"\n[cyan]🛠️ DATABASE MAINTENANCE[/cyan]")

    while True:
        console.print(
            f"""
[yellow]Database maintenance options:[/yellow]

[green]1[/green]) 🧹 Clean orphaned entries
[green]2[/green]) 📊 Show database statistics
[green]3[/green]) ⚡ Optimize database
[green]4[/green]) 🧽 Vacuum database (reclaim space)
[green]5[/green]) 🔍 Verify database integrity
[green]6[/green]) 🔄 Rebuild indexes
[green]7[/green]) ↩️  Back to main menu

"""
        )
        choice = input("Enter your choice (1-7): ").strip()

        catalog = AudiobookCatalog()

        try:
            if choice == "1":
                console.print(f"\n[cyan]🧹 Cleaning orphaned entries...[/cyan]")
                result = catalog.clean_orphaned_entries(True)
                console.print(f"[green]✅ Cleaned {result['removed']} orphaned entries[/green]")

            elif choice == "2":
                console.print(f"\n[cyan]📊 Database Statistics:[/cyan]")
                db_stats = catalog.get_db_stats()
                idx_stats = catalog.get_index_stats()

                console.print(f"  Database size: {db_stats.get('db_size', 0) / (1024*1024):.1f} MB")
                console.print(f"  Items table: {db_stats.get('items_rows', 0)} rows")
                console.print(f"  FTS table: {db_stats.get('items_fts_rows', 0)} rows")
                console.print(f"  Indexes: {len(db_stats.get('indexes', []))}")

                if db_stats.get("fts_integrity") is False:
                    console.print(f"[yellow]  ⚠️  FTS integrity issues detected[/yellow]")

            elif choice == "3":
                console.print(f"\n[cyan]⚡ Optimizing database...[/cyan]")
                result = catalog.optimize_database(True)
                console.print(f"[green]✅ Database optimized[/green]")
                console.print(f"  Space saved: {result['space_saved'] / (1024*1024):.1f} MB")
                console.print(f"  Time taken: {result['elapsed']:.2f}s")

            elif choice == "4":
                console.print(f"\n[cyan]🧽 Vacuuming database...[/cyan]")
                result = catalog.vacuum_database(True)
                console.print(f"[green]✅ Database vacuumed[/green]")
                console.print(f"  Space saved: {result['space_saved'] / (1024*1024):.1f} MB")

            elif choice == "5":
                console.print(f"\n[cyan]🔍 Verifying database integrity...[/cyan]")
                result = catalog.verify_integrity(True)

                console.print(f"[cyan]Integrity Check Results:[/cyan]")
                console.print(f"  SQLite integrity: {'✅ OK' if result['sqlite_integrity'] else '❌ FAILED'}")
                console.print(f"  FTS integrity: {'✅ OK' if result['fts_integrity'] else '❌ FAILED'}")
                console.print(f"  Orphaned FTS entries: {result['orphaned_fts_count']}")
                console.print(f"  Missing FTS entries: {result['missing_fts_count']}")

                if not all(v is not False for v in result.values() if v is not None):
                    console.print(f"[yellow]⚠️  Issues found - consider running 'optimize'[/yellow]")

            elif choice == "6":
                console.print(f"\n[cyan]🔄 Rebuilding indexes...[/cyan]")
                result = catalog.rebuild_indexes(True)
                console.print(f"[green]✅ Indexes rebuilt successfully[/green]")

            elif choice == "7" or choice.lower() in ["q", "quit", "back"]:
                catalog.close()
                break

            else:
                console.print(f"[yellow]Invalid choice. Please enter 1-7.[/yellow]")
                catalog.close()
                continue

        except Exception as e:
            console.print(f"[red]❌ Error: {e}[/red]")
        finally:
            catalog.close()

        console.print(f"\n[yellow]Press Enter to continue...[/yellow]")
        input()


def configure_permissions_wizard(config):
    """Configure file permissions with helpful defaults and explanations"""
    console.print(f"\n[cyan]📋 FILE PERMISSIONS SETUP[/cyan]")
    console.print(f"""
[yellow]About file permissions:[/yellow]
File permissions control who can read, write, and execute files. 
They're represented as 3-digit octal numbers (e.g., 644, 755).

[dim]Common permission values:[/dim]
  • 644 (rw-r--r--) - Owner can read/write, others can read [green](recommended for most files)[/green]
  • 666 (rw-rw-rw-) - Everyone can read/write
  • 755 (rwxr-xr-x) - Owner can read/write/execute, others can read/execute
  • 600 (rw-------) - Only owner can read/write [green](more secure)[/green]
""")
    
    current_enabled = config.get('set_permissions', False)
    current_perms = config.get('file_permissions', 0o644)
    
    if current_enabled:
        console.print(f"[yellow]Current setting: ✅ Enabled - {oct(current_perms)} ({oct(current_perms)[-3:]})[/yellow]")
    else:
        console.print(f"[yellow]Current setting: ❌ Disabled[/yellow]")
    
    # Enable/disable
    enable_choice = input("\nEnable automatic permission setting? [y/N]: ").strip().lower()
    
    if enable_choice in ['y', 'yes']:
        config['set_permissions'] = True
        
        console.print(f"\n[green]Choose permission mode:[/green]")
        console.print(f"  1) 644 (rw-r--r--) - Standard file permissions [green](recommended)[/green]")  
        console.print(f"  2) 666 (rw-rw-rw-) - Everyone can read/write")
        console.print(f"  3) 755 (rwxr-xr-x) - Executable files")
        console.print(f"  4) 600 (rw-------) - Owner-only access (secure)")
        console.print(f"  5) Custom (enter octal number)")
        
        perm_choice = input("\nSelect permission mode (1-5): ").strip()
        
        if perm_choice == "1":
            config['file_permissions'] = 0o644
            console.print(f"[green]✅ Set to 644 (rw-r--r--) - Standard file permissions[/green]")
        elif perm_choice == "2":
            config['file_permissions'] = 0o666  
            console.print(f"[green]✅ Set to 666 (rw-rw-rw-) - Everyone can read/write[/green]")
        elif perm_choice == "3":
            config['file_permissions'] = 0o755
            console.print(f"[green]✅ Set to 755 (rwxr-xr-x) - Executable files[/green]")
        elif perm_choice == "4":
            config['file_permissions'] = 0o600
            console.print(f"[green]✅ Set to 600 (rw-------) - Owner-only access[/green]")
        elif perm_choice == "5":
            custom_perm = input("Enter octal permission (e.g. 644): ").strip()
            try:
                if custom_perm.startswith('0o'):
                    perm_value = int(custom_perm, 8)
                else:
                    perm_value = int(custom_perm, 8)
                if 0 <= perm_value <= 0o777:
                    config['file_permissions'] = perm_value
                    console.print(f"[green]✅ Set to {oct(perm_value)} ({oct(perm_value)[-3:]})[/green]")
                else:
                    console.print(f"[red]Invalid permission value. Keeping current setting.[/red]")
            except ValueError:
                console.print(f"[red]Invalid octal number. Keeping current setting.[/red]")
        else:
            console.print(f"[yellow]Invalid choice. Keeping current permission.[/yellow]")
    else:
        config['set_permissions'] = False
        console.print(f"[yellow]❌ File permission setting disabled[/yellow]")


def configure_dir_permissions_wizard(config):
    """Configure directory permissions with helpful defaults and explanations"""
    console.print(f"\n[cyan]📁 DIRECTORY PERMISSIONS SETUP[/cyan]")
    console.print(f"""
[yellow]About directory permissions:[/yellow]
Directory permissions control who can access and list directory contents. 
They're represented as 3-digit octal numbers (e.g., 755, 775).

[dim]Common permission values for directories:[/dim]
  • 755 (rwxr-xr-x) - Owner can read/write/access, others can read/access [green](recommended)[/green]
  • 775 (rwxrwxr-x) - Owner and group can read/write/access, others can read/access
  • 700 (rwx------) - Only owner can read/write/access [green](more secure)[/green]
  • 644 (rw-r--r--) - Not recommended for directories (no execute permission)

[yellow]Note:[/yellow] Directory execute permission (x) allows entering the directory.
""")
    
    current_enabled = config.get('set_dir_permissions', False)
    current_perms = config.get('dir_permissions', 0o755)
    
    if current_enabled:
        console.print(f"[yellow]Current setting: ✅ Enabled - {oct(current_perms)} ({oct(current_perms)[-3:]})[/yellow]")
    else:
        console.print(f"[yellow]Current setting: ❌ Disabled[/yellow]")
    
    # Enable/disable
    enable_choice = input("\nEnable automatic directory permission setting? [y/N]: ").strip().lower()
    
    if enable_choice in ['y', 'yes']:
        config['set_dir_permissions'] = True
        
        console.print(f"\n[green]Choose permission mode:[/green]")
        console.print(f"  1) 755 (rwxr-xr-x) - Standard directory permissions [green](recommended)[/green]")  
        console.print(f"  2) 775 (rwxrwxr-x) - Group write access")
        console.print(f"  3) 700 (rwx------) - Owner-only access (secure)")
        console.print(f"  4) Custom (enter octal number)")
        
        perm_choice = input("\nSelect permission mode (1-4): ").strip()
        
        if perm_choice == "1":
            config['dir_permissions'] = 0o755
            console.print(f"[green]✅ Set to 755 (rwxr-xr-x) - Standard directory permissions[/green]")
        elif perm_choice == "2":
            config['dir_permissions'] = 0o775  
            console.print(f"[green]✅ Set to 775 (rwxrwxr-x) - Group write access[/green]")
        elif perm_choice == "3":
            config['dir_permissions'] = 0o700
            console.print(f"[green]✅ Set to 700 (rwx------) - Owner-only access[/green]")
        elif perm_choice == "4":
            custom_perm = input("Enter octal permission (e.g. 755): ").strip()
            try:
                if custom_perm.startswith('0o'):
                    perm_value = int(custom_perm, 8)
                else:
                    perm_value = int(custom_perm, 8)
                if 0 <= perm_value <= 0o777:
                    config['dir_permissions'] = perm_value
                    console.print(f"[green]✅ Set to {oct(perm_value)} ({oct(perm_value)[-3:]})[/green]")
                else:
                    console.print(f"[red]Invalid permission value. Keeping current setting.[/red]")
            except ValueError:
                console.print(f"[red]Invalid octal number. Keeping current setting.[/red]")
        else:
            console.print(f"[yellow]Invalid choice. Keeping current permission.[/yellow]")
    else:
        config['set_dir_permissions'] = False
        console.print(f"[yellow]❌ Directory permission setting disabled[/yellow]")


def configure_ownership_wizard(config):
    """Configure file ownership with helpful defaults and explanations"""
    console.print(f"\n[cyan]👤 FILE OWNERSHIP SETUP[/cyan]")
    console.print(f"""
[yellow]About file ownership:[/yellow]
File ownership determines which user and group own the files.
You can use either numeric IDs or names.

[dim]Common examples:[/dim]
  • Numeric: User 99, Group 100 (like 'chown 99:100')
  • Names: User 'nobody', Group 'users' (like 'chown nobody:users')
  • Docker: User 1000, Group 1000 (common Docker user)
  • Plex: User 'plex', Group 'plex'

[yellow]⚠️  Note:[/yellow] Changing ownership typically requires root/sudo privileges.
""")
    
    current_enabled = config.get('set_ownership', False)
    current_user = config.get('owner_user', '')
    current_group = config.get('owner_group', '')
    
    if current_enabled and (current_user or current_group):
        console.print(f"[yellow]Current setting: ✅ Enabled - {current_user}:{current_group}[/yellow]")
    else:
        console.print(f"[yellow]Current setting: ❌ Disabled[/yellow]")
    
    # Enable/disable
    enable_choice = input("\nEnable automatic ownership setting? [y/N]: ").strip().lower()
    
    if enable_choice in ['y', 'yes']:
        config['set_ownership'] = True
        
        console.print(f"\n[green]Choose ownership setup:[/green]")
        console.print(f"  1) Docker user (1000:1000) [green](common Docker setup)[/green]")
        console.print(f"  2) Nobody user (99:100) [green](common for services)[/green]")
        console.print(f"  3) Plex user (plex:plex)")
        console.print(f"  4) Custom numeric IDs")
        console.print(f"  5) Custom usernames")
        
        owner_choice = input("\nSelect ownership setup (1-5): ").strip()
        
        if owner_choice == "1":
            config['owner_user'] = "1000"
            config['owner_group'] = "1000"
            console.print(f"[green]✅ Set to 1000:1000 (Docker user)[/green]")
        elif owner_choice == "2":
            config['owner_user'] = "99"
            config['owner_group'] = "100"
            console.print(f"[green]✅ Set to 99:100 (nobody:users)[/green]")
        elif owner_choice == "3":
            config['owner_user'] = "plex"
            config['owner_group'] = "plex"
            console.print(f"[green]✅ Set to plex:plex[/green]")
        elif owner_choice == "4":
            user_id = input("Enter numeric user ID (e.g. 99): ").strip()
            group_id = input("Enter numeric group ID (e.g. 100): ").strip()
            if user_id.isdigit() and group_id.isdigit():
                config['owner_user'] = user_id
                config['owner_group'] = group_id
                console.print(f"[green]✅ Set to {user_id}:{group_id}[/green]")
            else:
                console.print(f"[red]Invalid numeric IDs. Keeping current setting.[/red]")
        elif owner_choice == "5":
            username = input("Enter username (e.g. nobody): ").strip()
            groupname = input("Enter group name (e.g. users): ").strip()
            if username and groupname:
                config['owner_user'] = username
                config['owner_group'] = groupname
                console.print(f"[green]✅ Set to {username}:{groupname}[/green]")
            else:
                console.print(f"[red]Username and group name cannot be empty. Keeping current setting.[/red]")
        else:
            console.print(f"[yellow]Invalid choice. Keeping current ownership.[/yellow]")
    else:
        config['set_ownership'] = False
        console.print(f"[yellow]❌ File ownership setting disabled[/yellow]")


def settings_menu():
    """Settings and preferences menu"""
    config = load_config()

    console.print(f"\n[cyan]⚙️ SETTINGS MENU[/cyan]")

    while True:
        config_manager = ConfigManager()
        config_manager.config = config
        
        # Display integrations info
        integrations = config_manager.get("integrations", {})
        integration_info = []
        if isinstance(integrations, dict):
            for name, int_config in integrations.items():
                if isinstance(int_config, dict):
                    enabled = "✅" if int_config.get("enabled", False) else "❌"
                    path = int_config.get("path", "Not set")
                    limit = int_config.get("path_limit")
                    limit_str = f" (limit: {limit})" if limit else ""
                    integration_info.append(f"    {name.upper()}: {enabled} {path}{limit_str}")
        
        integration_display = "\n".join(integration_info) if integration_info else "    None configured"
        
        # Display permission/ownership settings for files
        file_perm_enabled = config.get('set_permissions', False)
        file_perm_value = config.get('file_permissions', 0o644)
        if isinstance(file_perm_value, int):
            file_perm_display = f"✅ {oct(file_perm_value)} ({oct(file_perm_value)[-3:]})" if file_perm_enabled else "❌ Disabled"
        else:
            file_perm_display = "❌ Disabled"
        
        # Display permission/ownership settings for directories
        dir_perm_enabled = config.get('set_dir_permissions', False)
        dir_perm_value = config.get('dir_permissions', 0o755)
        if isinstance(dir_perm_value, int):
            dir_perm_display = f"✅ {oct(dir_perm_value)} ({oct(dir_perm_value)[-3:]})" if dir_perm_enabled else "❌ Disabled"
        else:
            dir_perm_display = "❌ Disabled"
        
        owner_enabled = config.get('set_ownership', False)
        owner_user = config.get('owner_user', '')
        owner_group = config.get('owner_group', '')
        if isinstance(owner_user, str) and isinstance(owner_group, str):
            owner_display = f"✅ {owner_user}:{owner_group}" if owner_enabled else "❌ Disabled"
        else:
            owner_display = "❌ Disabled"
        
        # Display logging settings
        logging_config = config.get('logging', {})
        if isinstance(logging_config, dict):
            log_level = logging_config.get('level', 'INFO')
            log_file_enabled = logging_config.get('file_enabled', True)
            log_console_enabled = logging_config.get('console_enabled', True)
            log_json = logging_config.get('json_file', True)
        else:
            log_level = 'INFO'
            log_file_enabled = True
            log_console_enabled = True
            log_json = True
        
        log_level_display = f"[cyan]{log_level}[/cyan]"
        log_file_display = "✅ Enabled" if log_file_enabled else "❌ Disabled"
        log_console_display = "✅ Enabled" if log_console_enabled else "❌ Disabled"
        log_format_display = "JSON + Console" if log_json and log_console_enabled else ("JSON" if log_json else ("Console" if log_console_enabled else "None"))
        
        console.print(
            f"""
[yellow]Current settings:[/yellow]
  Library path: {config.get('library_path', '')}
  Legacy torrent path: {config.get('torrent_path', '')}
  Integrations:
{integration_display}
  Zero pad: {config.get('zero_pad', True)}
  Also cover: {config.get('also_cover', False)}
  File permissions: {file_perm_display}
  Directory permissions: {dir_perm_display}
  Ownership: {owner_display}
  Logging level: {log_level_display}
  Log file: {log_file_display}
  Log console: {log_console_display}
  Log format: {log_format_display}
  Recent sources: {', '.join(_get_recent_sources(config)[:5])}

[green]Options:[/green]
  1) Change library path
  2) Change legacy torrent path
  3) Configure integrations
  4) Toggle zero padding
  5) Toggle cover linking
  6) Configure file permissions
  7) Configure directory permissions
  8) Configure ownership
  9) Configure logging
 10) Add recent source
 11) Remove recent source
 12) Reset settings to default
 13) Back to main menu
"""
        )
        choice = input("Select an option (1-13): ").strip()

        if choice == "1":
            new_path = input("Enter new library path: ").strip()
            if new_path:
                config["library_path"] = new_path
                console.print(f"[green]Library path updated.[/green]")
        elif choice == "2":
            new_path = input("Enter new torrent path: ").strip()
            if new_path:
                config["torrent_path"] = new_path
                console.print(f"[green]Torrent path updated.[/green]")
        elif choice == "3":
            configure_integrations_wizard(config_manager)
            config = config_manager.config  # Update config after changes
        elif choice == "4":
            config["zero_pad"] = not config.get("zero_pad", True)
            console.print(
                f"[green]Zero padding {'enabled' if config['zero_pad'] else 'disabled'}.[/green]"
            )
        elif choice == "5":
            config["also_cover"] = not config.get("also_cover", False)
            console.print(
                f"[green]Cover linking {'enabled' if config['also_cover'] else 'disabled'}.[/green]"
            )
        elif choice == "6":
            configure_permissions_wizard(config)
        elif choice == "7":
            configure_dir_permissions_wizard(config)
        elif choice == "8":
            configure_ownership_wizard(config)
        elif choice == "9":
            configure_logging_wizard(config)
        elif choice == "10":
            source = input("Enter source path to add: ").strip()
            recent_sources = config.get("recent_sources", [])
            if not isinstance(recent_sources, list):
                recent_sources = []
            if source and source not in recent_sources:
                recent_sources.append(source)
                config["recent_sources"] = recent_sources
                console.print(f"[green]Source added to recent sources.[/green]")
        elif choice == "11":
            source = input("Enter source path to remove: ").strip()
            recent_sources = config.get("recent_sources", [])
            if not isinstance(recent_sources, list):
                recent_sources = []
            if source and source in recent_sources:
                recent_sources.remove(source)
                config["recent_sources"] = recent_sources
                console.print(f"[green]Source removed from recent sources.[/green]")
        elif choice == "12":
            # Reset to default settings
            config = {
                "first_run": True,
                "library_path": "",
                "torrent_path": "",
                "zero_pad": True,
                "also_cover": False,
                "set_permissions": False,
                "file_permissions": 0o644,
                "set_dir_permissions": False,
                "dir_permissions": 0o755,
                "set_ownership": False,
                "owner_user": "",
                "owner_group": "",
                "recent_sources": [],
                "logging": {
                    "level": "INFO",
                    "file_enabled": True,
                    "console_enabled": True,
                    "json_file": True,
                    "log_path": "/mnt/cache/scripts/hardbound/logs/hardbound.log",
                    "rotate_max_bytes": 10485760,
                    "rotate_backups": 5,
                    "rich_tracebacks": True,
                    "show_path": False
                }
            }
            console.print(f"[green]Settings reset to default.[/green]")
        elif choice == "13":
            break
        else:
            console.print(f"[red]Invalid choice, please try again.[/red]")

    save_config(config)


def show_interactive_help():
    """Show help for interactive mode"""
    print(
        f"""
[cyan]❓ HARDBOUND HELP[/cyan]

[bold]What does Hardbound do?[/bold]
Creates hardlinks from your audiobook library to torrent folders.
This saves space while letting you seed without duplicating files.

[bold]Search-first workflow (NEW!):[/bold]
  hardbound index              # Build catalog (1500+ books → instant search)
  hardbound search "rowling"   # Find books instantly  
  hardbound select -m          # Interactive multi-select with fzf

[bold]Classic commands:[/bold]
  hardbound --src /path/book --dst /path/dest  # Single book
  hardbound --src /path/book --dst-root /root  # Auto-create dest folder

[bold]Safety:[/bold]
• Defaults to dry-run (preview) mode
• Use --commit to actually create links
• Checks that source and destination are on same filesystem

[yellow]Press Enter to continue...[/yellow]"""
    )
    input()


def find_recent_audiobooks(hours=24, max_depth=3, config=None):
    """Find recently modified audiobook files"""
    if config is None:
        config = load_config()
    """Find recently modified audiobook folders with better depth control"""
    recent = []
    seen = set()
    cutoff = datetime.now().timestamp() - (hours * 3600)

    search_paths = [
        Path.home() / "audiobooks",
        Path.home() / "Downloads",
        Path.home() / "Documents" / "audiobooks",
    ]

    # Add system-specific paths from config if they exist
    system_paths_config = config.get("system_search_paths")
    if system_paths_config and isinstance(system_paths_config, list):
        system_paths = [Path(p) for p in system_paths_config]
    else:
        # Default system paths
        system_paths = [
            Path("/mnt/user/data/audio/audiobooks"),
            Path("/mnt/user/data/downloads"),
        ]

    for sys_path in system_paths:
        if sys_path.exists():
            search_paths.append(sys_path)

    for base_path in search_paths:
        if not Path(base_path).exists():
            continue

        try:
            for root, dirs, files in os.walk(base_path):
                # Limit depth
                depth = root[len(str(base_path)) :].count(os.sep)
                if depth > max_depth:
                    dirs.clear()
                    continue

                root_path = Path(root)
                if root_path.stat().st_mtime > cutoff:
                    # Check if it contains audiobook files
                    if any(f.endswith((".m4b", ".mp3")) for f in files):
                        resolved = root_path.resolve()
                        if resolved not in seen:
                            seen.add(resolved)
                            recent.append(root_path)

        except PermissionError:
            continue

    return sorted(recent, key=lambda p: p.stat().st_mtime, reverse=True)[:20]


def _link_selected_paths(selected_paths: List[str]):
    """Helper to link selected paths"""
    config = load_config()
    default_dst = config.get("torrent_path", "")

    console.print(f"\n[bold]Destination root:[/bold]")
    if default_dst:
        print(f"Default: {default_dst}")
        dst_input = input("Path (Enter for default): ").strip()
        dst_root = Path(dst_input) if dst_input else Path(str(default_dst))
    else:
        dst_input = input("Path: ").strip()
        if not dst_input:
            return
        dst_root = Path(dst_input)

    console.print(
        f"\n[yellow]Link {len(selected_paths)} audiobook(s)? [y/N]: [/yellow]",
        end="",
    )
    if input().strip().lower() not in ["y", "yes"]:
        return

    stats = {
        "linked": 0,
        "replaced": 0,
        "already": 0,
        "exists": 0,
        "excluded": 0,
        "skipped": 0,
        "errors": 0,
    }
    zero_pad = bool(config.get("zero_pad", True))
    also_cover = bool(config.get("also_cover", False))

    for path_str in selected_paths:
        src = Path(path_str)
        
        console.print(f"\n[cyan]Processing: {src.name}[/cyan]")
        plan_and_link_red(
            src, dst_root, also_cover, zero_pad, False, False, stats
        )

    summary_table(stats, perf_counter())


def browse_directory_tree():
    """Interactive directory tree browser (legacy mode)"""
    current = Path.cwd()

    while True:
        console.print(f"\n[cyan]📁 Current: {current}[/cyan]")

        items = []
        try:
            # Show parent
            items.append(("..", current.parent))

            # List directories first
            for item in sorted(current.iterdir()):
                if item.is_dir():
                    # Check if it contains audiobooks
                    has_audio = any(item.glob("*.m4b")) or any(item.glob("*.mp3"))
                    marker = " 🎵" if has_audio else ""
                    items.append((f"[D] {item.name}{marker}", item))
        except PermissionError:
            console.print(f"[red]Permission denied[/red]")

        for i, (display, path) in enumerate(items[:20], 1):
            print(f"  {i:2d}) {display}")

        if len(items) > 20:
            print(f"  ... and {len(items) - 20} more")

        console.print(
            f"\n[yellow]Enter number to navigate, 'select' to choose current, 'back' to go up:[/yellow]"
        )
        choice = input("Choice: ").strip().lower()

        if choice == "select":
            return current
        elif choice == "back":
            current = current.parent
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(items):
                _, new_path = items[idx]
                if new_path.is_dir():
                    current = new_path


def configure_integrations_wizard(config_manager: ConfigManager):
    """Configure integration settings"""
    console.print(f"\n[cyan]🔧 INTEGRATION CONFIGURATION[/cyan]")
    
    while True:
        integrations = config_manager.get("integrations", {})
        if not isinstance(integrations, dict):
            integrations = copy.deepcopy(DEFAULT_CONFIG["integrations"])
            config_manager.config["integrations"] = integrations
        
        assert isinstance(integrations, dict)  # Tell Pylance integrations is a dict
        
        console.print(f"\n[yellow]Available integrations:[/yellow]")
        integration_list = list(integrations.keys())
        for i, (name, int_config) in enumerate(integrations.items(), 1):
            if isinstance(int_config, dict):
                enabled = "✅" if int_config.get("enabled", False) else "❌"
                path = int_config.get("path", "Not set")
                limit = int_config.get("path_limit")
                limit_str = f" (limit: {limit} chars)" if limit else ""
                console.print(f"  [green]{i}[/green]) {name.upper()}: {enabled} {path}{limit_str}")
        
        console.print(f"\n[green]Options:[/green]")
        console.print(f"  [green]1-{len(integration_list)}[/green]) Configure integration")
        console.print(f"  [green]q[/green]) Back to settings")
        
        choice = input(f"\nChoice (1-{len(integration_list)}, q): ").strip().lower()
        
        if choice == "q":
            break
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(integration_list):
                integration_name = integration_list[idx]
                configure_single_integration(config_manager, integration_name)
        else:
            console.print(f"[yellow]Invalid choice.[/yellow]")


def configure_single_integration(config_manager: ConfigManager, integration_name: str):
    """Configure a single integration"""
    console.print(f"\n[cyan]🔧 CONFIGURING {integration_name.upper()} INTEGRATION[/cyan]")
    
    integration = config_manager.get_integration(integration_name)
    if not integration or not isinstance(integration, dict):
        console.print(f"[red]Integration {integration_name} not found[/red]")
        return
    
    while True:
        enabled = integration.get("enabled", False)
        path = integration.get("path", "")
        limit = integration.get("path_limit")
        limit_str = f" (limit: {limit} chars)" if limit else " (no limit)"
        
        console.print(f"\n[yellow]{integration_name.upper()} Integration Settings:[/yellow]")
        console.print(f"  Status: {'✅ Enabled' if enabled else '❌ Disabled'}")
        console.print(f"  Path: {path if path else 'Not set'}")
        console.print(f"  Path limit{limit_str}")
        
        console.print(f"\n[green]Options:[/green]")
        console.print(f"  [green]1[/green]) {'Disable' if enabled else 'Enable'} integration")
        console.print(f"  [green]2[/green]) Change path")
        console.print(f"  [green]3[/green]) Test path (validate)")
        console.print(f"  [green]q[/green]) Back")
        
        choice = input("Choice (1-3, q): ").strip().lower()
        
        if choice == "q":
            break
        elif choice == "1":
            config_manager.enable_integration(integration_name, not enabled)
            console.print(f"[green]{integration_name.upper()} integration {'enabled' if not enabled else 'disabled'}[/green]")
        elif choice == "2":
            current_path = integration.get("path", "")
            console.print(f"\nCurrent path: {current_path}")
            if limit:
                console.print(f"[yellow]Note: Path must be ≤ {limit} characters for {integration_name.upper()}[/yellow]")
            
            new_path = input("Enter new path (Enter to keep current): ").strip()
            if new_path:
                if limit and len(new_path) > limit:
                    console.print(f"[red]❌ Path too long: {len(new_path)} characters (limit: {limit})[/red]")
                else:
                    config_manager.set_integration_path(integration_name, new_path)
                    console.print(f"[green]Path updated for {integration_name.upper()} integration[/green]")
        elif choice == "3":
            path = integration.get("path", "")
            if not path:
                console.print(f"[yellow]No path configured[/yellow]")
            else:
                from .utils.validation import PathValidator
                if limit and len(path) > limit:
                    console.print(f"[red]❌ Path too long: {len(path)} characters (limit: {limit})[/red]")
                elif PathValidator.validate_destination_path_with_limit(path, limit):
                    console.print(f"[green]✅ Path is valid[/green]")
                else:
                    console.print(f"[red]❌ Path validation failed[/red]")
        else:
            console.print(f"[yellow]Invalid choice.[/yellow]")
        
        # Refresh integration data
        integration = config_manager.get_integration(integration_name)
        if not isinstance(integration, dict):
            break


def configure_logging_wizard(config):
    """Configure logging settings wizard"""
    log.info("logging.config_wizard_start", operation="configure_logging")
    
    console.print(f"\n[cyan]📋 LOGGING CONFIGURATION[/cyan]")
    
    # Ensure logging config exists
    if "logging" not in config:
        config["logging"] = {}
    
    logging_config = config["logging"]
    if not isinstance(logging_config, dict):
        logging_config = config["logging"] = {}
    
    while True:
        # Display current settings
        level = logging_config.get("level", "INFO")
        file_enabled = logging_config.get("file_enabled", True)
        console_enabled = logging_config.get("console_enabled", True)
        json_file = logging_config.get("json_file", True)
        log_path = logging_config.get("log_path", "/mnt/cache/scripts/hardbound/logs/hardbound.log")
        rotate_max_bytes = logging_config.get("rotate_max_bytes", 10485760)
        rotate_backups = logging_config.get("rotate_backups", 5)
        rich_tracebacks = logging_config.get("rich_tracebacks", True)
        show_path = logging_config.get("show_path", False)
        
        console.print(f"""
[yellow]Current logging settings:[/yellow]
  Log level: [cyan]{level}[/cyan]
  File logging: {'✅ Enabled' if file_enabled else '❌ Disabled'}
  Console logging: {'✅ Enabled' if console_enabled else '❌ Disabled'}
  JSON file format: {'✅ Enabled' if json_file else '❌ Disabled'}
  Log file path: {log_path}
  File rotation: {rotate_max_bytes // 1024 // 1024}MB, {rotate_backups} backups
  Rich tracebacks: {'✅ Enabled' if rich_tracebacks else '❌ Disabled'}
  Show file paths: {'✅ Enabled' if show_path else '❌ Disabled'}

[green]Options:[/green]
  1) Change log level (DEBUG/INFO/WARNING/ERROR)
  2) Toggle file logging
  3) Toggle console logging
  4) Toggle JSON file format
  5) Change log file path
  6) Configure rotation settings
  7) Toggle rich tracebacks
  8) Toggle file path display
  9) Apply settings (reinitialize logging)
  q) Back to settings menu
""")
        
        choice = input("Select option (1-9, q): ").strip().lower()
        
        if choice == "q":
            break
        elif choice == "1":
            console.print("Available levels: DEBUG, INFO, WARNING, ERROR")
            new_level = input("Enter log level: ").strip().upper()
            if new_level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
                logging_config["level"] = new_level
                log.info("logging.level_changed", new_level=new_level)
                console.print(f"[green]Log level changed to {new_level}.[/green]")
            else:
                console.print("[red]Invalid level. Use DEBUG, INFO, WARNING, or ERROR.[/red]")
        elif choice == "2":
            logging_config["file_enabled"] = not file_enabled
            new_state = "enabled" if logging_config["file_enabled"] else "disabled"
            log.info("logging.file_toggled", enabled=logging_config["file_enabled"])
            console.print(f"[green]File logging {new_state}.[/green]")
        elif choice == "3":
            logging_config["console_enabled"] = not console_enabled
            new_state = "enabled" if logging_config["console_enabled"] else "disabled"
            log.info("logging.console_toggled", enabled=logging_config["console_enabled"])
            console.print(f"[green]Console logging {new_state}.[/green]")
        elif choice == "4":
            logging_config["json_file"] = not json_file
            new_state = "enabled" if logging_config["json_file"] else "disabled"
            log.info("logging.json_toggled", enabled=logging_config["json_file"])
            console.print(f"[green]JSON file format {new_state}.[/green]")
        elif choice == "5":
            new_path = input("Enter new log file path: ").strip()
            if new_path:
                logging_config["log_path"] = new_path
                log.info("logging.path_changed", new_path=new_path)
                console.print(f"[green]Log path updated to {new_path}.[/green]")
        elif choice == "6":
            console.print("Configure file rotation:")
            try:
                max_mb = int(input(f"Max file size in MB (current: {rotate_max_bytes // 1024 // 1024}): ").strip())
                backups = int(input(f"Number of backup files (current: {rotate_backups}): ").strip())
                if max_mb > 0 and backups >= 0:
                    logging_config["rotate_max_bytes"] = max_mb * 1024 * 1024
                    logging_config["rotate_backups"] = backups
                    log.info("logging.rotation_configured", max_bytes=logging_config["rotate_max_bytes"], backups=backups)
                    console.print(f"[green]Rotation configured: {max_mb}MB, {backups} backups.[/green]")
                else:
                    console.print("[red]Invalid values. Size must be > 0, backups must be >= 0.[/red]")
            except ValueError:
                console.print("[red]Invalid input. Please enter numbers only.[/red]")
        elif choice == "7":
            logging_config["rich_tracebacks"] = not rich_tracebacks
            new_state = "enabled" if logging_config["rich_tracebacks"] else "disabled"
            log.info("logging.rich_tracebacks_toggled", enabled=logging_config["rich_tracebacks"])
            console.print(f"[green]Rich tracebacks {new_state}.[/green]")
        elif choice == "8":
            logging_config["show_path"] = not show_path
            new_state = "enabled" if logging_config["show_path"] else "disabled"
            log.info("logging.show_path_toggled", enabled=logging_config["show_path"])
            console.print(f"[green]File path display {new_state}.[/green]")
        elif choice == "9":
            # Apply settings by reinitializing logging
            try:
                from .utils.logging import setup_logging
                from pathlib import Path
                
                setup_logging(
                    level=logging_config.get("level", "INFO"),
                    file_enabled=logging_config.get("file_enabled", True),
                    console_enabled=logging_config.get("console_enabled", True),
                    json_file=logging_config.get("json_file", True),
                    log_path=Path(logging_config.get("log_path", "/mnt/cache/scripts/hardbound/logs/hardbound.log")),
                    rotate_max_bytes=logging_config.get("rotate_max_bytes", 10485760),
                    rotate_backups=logging_config.get("rotate_backups", 5),
                    rich_tracebacks=logging_config.get("rich_tracebacks", True),
                    show_path=logging_config.get("show_path", False)
                )
                log.info("logging.config_applied", operation="reinitialize_logging")
                console.print("[green]Logging settings applied and reinitialized![/green]")
            except Exception as e:
                log.error("logging.config_apply_failed", error=str(e))
                console.print(f"[red]Failed to apply settings: {e}[/red]")
        else:
            console.print("[yellow]Invalid choice.[/yellow]")
    
    log.info("logging.config_wizard_complete", operation="configure_logging")
