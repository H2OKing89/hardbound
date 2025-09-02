#!/usr/bin/env python3
"""
Interactive mode and wizard functionality
"""
import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Dict, List, Optional

from rich.console import Console

from .catalog import DB_FILE, AudiobookCatalog
from .config import load_config, save_config
from .display import Sty, summary_table
from .linker import plan_and_link, zero_pad_vol
from .ui.feedback import ErrorHandler, ProgressIndicator, VisualFeedback
from .ui.menu import create_main_menu, create_quick_actions_menu, menu_system
from .utils.validation import InputValidator, PathValidator

# Global Rich console for consistent output
console = Console()


def _get_recent_sources(config):
    """Safely get recent sources as a list"""
    sources = config.get("recent_sources", [])
    if isinstance(sources, list):
        return sources
    return []


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
    console.print(
        f"\n[yellow]Enter numbers (space-separated), 'all', or 'q' to quit:[/yellow]"
    )
    choice = input("Selection: ").strip().lower()

    if choice == "q":
        return []
    elif choice == "all":
        return [book["path"] for book in all_selectable]
    else:
        selected = []
        for num in choice.split():
            if num.isdigit():
                idx = int(num) - 1
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
        choice = input("\nEnter numbers (space-separated) or 'all': ").strip()
        if choice.lower() == "all":
            return [c["path"] for c in candidates]

        indices = [int(x) - 1 for x in choice.split() if x.isdigit()]
        return [candidates[i]["path"] for i in indices if 0 <= i < len(candidates)]
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

    # Get destination
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
            catalog.close()
            return
        dst_root = Path(dst_input)

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
            base_name = zero_pad_vol(src.name) if zero_pad else src.name
            dst = dst_root / base_name

            print(f"\nProcessing: {src.name}")
            plan_and_link(
                src, dst, base_name, also_cover, zero_pad, False, False, stats
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
        base_name = zero_pad_vol(book_dir.name) if zero_pad else book_dir.name
        dst_dir = dst_root / base_name
        print(f"\nProcessing: {book_dir.name}")
        plan_and_link(
            book_dir, dst_dir, base_name, also_cover, zero_pad, False, False, stats
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


def settings_menu():
    """Settings and preferences menu"""
    config = load_config()

    console.print(f"\n[cyan]⚙️ SETTINGS MENU[/cyan]")

    while True:
        console.print(
            f"""
[yellow]Current settings:[/yellow]
  Library path: {config.get('library_path', '')}
  Torrent path: {config.get('torrent_path', '')}
  Zero pad: {config.get('zero_pad', True)}
  Also cover: {config.get('also_cover', False)}
  Recent sources: {', '.join(_get_recent_sources(config)[:5])}

[green]Options:[/green]
  1) Change library path
  2) Change torrent path
  3) Toggle zero padding
  4) Toggle cover linking
  5) Add recent source
  6) Remove recent source
  7) Reset settings to default
  8) Back to main menu
"""
        )
        choice = input("Select an option (1-8): ").strip()

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
            config["zero_pad"] = not config.get("zero_pad", True)
            console.print(
                f"[green]Zero padding {'enabled' if config['zero_pad'] else 'disabled'}.[/green]"
            )
        elif choice == "4":
            config["also_cover"] = not config.get("also_cover", False)
            console.print(
                f"[green]Cover linking {'enabled' if config['also_cover'] else 'disabled'}.[/green]"
            )
        elif choice == "5":
            source = input("Enter source path to add: ").strip()
            recent_sources = config.get("recent_sources", [])
            if not isinstance(recent_sources, list):
                recent_sources = []
            if source and source not in recent_sources:
                recent_sources.append(source)
                config["recent_sources"] = recent_sources
                console.print(f"[green]Source added to recent sources.[/green]")
        elif choice == "6":
            source = input("Enter source path to remove: ").strip()
            recent_sources = config.get("recent_sources", [])
            if not isinstance(recent_sources, list):
                recent_sources = []
            if source and source in recent_sources:
                recent_sources.remove(source)
                config["recent_sources"] = recent_sources
                console.print(f"[green]Source removed from recent sources.[/green]")
        elif choice == "7":
            # Reset to default settings
            config = {
                "first_run": True,
                "library_path": "",
                "torrent_path": "",
                "zero_pad": True,
                "also_cover": False,
                "recent_sources": [],
            }
            console.print(f"[green]Settings reset to default.[/green]")
        elif choice == "8":
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
        base_name = zero_pad_vol(src.name) if zero_pad else src.name
        dst_dir = dst_root / base_name
        console.print(f"\n[cyan]Processing: {src.name}[/cyan]")
        plan_and_link(
            src, dst_dir, base_name, also_cover, zero_pad, False, False, stats
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
