#!/usr/bin/env python3
"""
Interactive mode and wizard functionality
"""
import json
import subprocess
import shutil
import os
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from time import perf_counter

from .catalog import DB_FILE, AudiobookCatalog
from .display import Sty, summary_table
from .linker import plan_and_link, zero_pad_vol
from .config import load_config, save_config

def _get_recent_sources(config):
    """Safely get recent sources as a list"""
    sources = config.get('recent_sources', [])
    if isinstance(sources, list):
        return sources
    return []


def have_fzf() -> bool:
    """Check if fzf is available"""
    import shutil
    return shutil.which("fzf") is not None

def hierarchical_browser(catalog) -> List[str]:
    """Hierarchical browser for large audiobook collections - author-first approach"""
    
    # Get all unique authors from catalog
    all_items = catalog.search("*", limit=5000)
    
    # Build author index
    authors_by_initial = {}
    author_to_books = {}
    
    for item in all_items:
        author = item.get('author', 'Unknown')
        if not author or author == '—':
            author = 'Unknown'
        
        # Get first character for grouping
        initial = author[0].upper() if author else '#'
        if not initial.isalpha():
            initial = '#'  # Group numbers and special chars
        
        if initial not in authors_by_initial:
            authors_by_initial[initial] = set()
        authors_by_initial[initial].add(author)
        
        # Track books per author
        if author not in author_to_books:
            author_to_books[author] = []
        author_to_books[author].append(item)
    
    # Step 1: Choose initial letter
    print(f"\n{Sty.CYAN}📚 BROWSE BY AUTHOR{Sty.RESET}")
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
                row.append(f"{Sty.GREEN}{initial}{Sty.RESET}({count:2d})")
            else:
                row.append("      ")
        print("  " + "  ".join(row))
    
    print(f"\n{Sty.YELLOW}Enter letter(s), or 'search' for text search:{Sty.RESET}")
    choice = input("Choice: ").strip().upper()
    
    if choice.lower() == 'search':
        return text_search_browser(catalog)
    
    if not choice or choice not in authors_by_initial:
        print(f"{Sty.YELLOW}Invalid selection{Sty.RESET}")
        return []
    
    # Step 2: Choose author
    authors = sorted(authors_by_initial[choice])
    
    print(f"\n{Sty.CYAN}Authors starting with '{choice}':{Sty.RESET}\n")
    
    # Paginate if too many
    page_size = 20
    current_page = 0
    
    while True:
        start = current_page * page_size
        end = min(start + page_size, len(authors))
        
        for i, author in enumerate(authors[start:end], start + 1):
            book_count = len(author_to_books[author])
            print(f"{Sty.GREEN}{i:3d}{Sty.RESET}) {author} ({book_count} book{'s' if book_count > 1 else ''})")
        
        nav_options = []
        if current_page > 0:
            nav_options.append("'p' = previous")
        if end < len(authors):
            nav_options.append("'n' = next")
        nav_options.append("number = select")
        nav_options.append("'q' = quit")
        
        print(f"\n{Sty.YELLOW}{' | '.join(nav_options)}:{Sty.RESET}")
        choice = input("Choice: ").strip().lower()
        
        if choice == 'q':
            return []
        elif choice == 'n' and end < len(authors):
            current_page += 1
        elif choice == 'p' and current_page > 0:
            current_page -= 1
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(authors):
                selected_author = authors[idx]
                break
        else:
            print(f"{Sty.YELLOW}Invalid selection{Sty.RESET}")
    
    # Step 3: Browse author's books
    author_books = author_to_books[selected_author]
    
    # Group by series if applicable
    series_groups = {}
    standalone = []
    
    for book in author_books:
        series = book.get('series', '')
        if series and series != '—':
            if series not in series_groups:
                series_groups[series] = []
            series_groups[series].append(book)
        else:
            standalone.append(book)
    
    print(f"\n{Sty.CYAN}📚 {selected_author}{Sty.RESET}")
    
    all_selectable = []
    
    # Show series first
    if series_groups:
        print(f"\n{Sty.BOLD}Series:{Sty.RESET}")
        for series in sorted(series_groups.keys()):
            books = sorted(series_groups[series], key=lambda x: x.get('book', ''))
            print(f"\n  {Sty.MAGENTA}{series}{Sty.RESET} ({len(books)} books)")
            for book in books:
                all_selectable.append(book)
                idx = len(all_selectable)
                size_mb = book.get('size', 0) / (1024 * 1024)
                indicator = "📘" if book.get('has_m4b') else "🎵"
                print(f"    {Sty.GREEN}{idx:3d}{Sty.RESET}) {book['book']} {indicator} ({size_mb:.0f}MB)")
    
    # Show standalone books
    if standalone:
        print(f"\n{Sty.BOLD}Standalone:{Sty.RESET}")
        for book in sorted(standalone, key=lambda x: x.get('book', '')):
            all_selectable.append(book)
            idx = len(all_selectable)
            size_mb = book.get('size', 0) / (1024 * 1024)
            indicator = "📘" if book.get('has_m4b') else "🎵"
            print(f"  {Sty.GREEN}{idx:3d}{Sty.RESET}) {book['book']} {indicator} ({size_mb:.0f}MB)")
    
    # Selection
    print(f"\n{Sty.YELLOW}Enter numbers (space-separated), 'all', or 'q' to quit:{Sty.RESET}")
    choice = input("Selection: ").strip().lower()
    
    if choice == 'q':
        return []
    elif choice == 'all':
        return [book['path'] for book in all_selectable]
    else:
        selected = []
        for num in choice.split():
            if num.isdigit():
                idx = int(num) - 1
                if 0 <= idx < len(all_selectable):
                    selected.append(all_selectable[idx]['path'])
        return selected

def text_search_browser(catalog: AudiobookCatalog) -> List[str]:
    """Simple text search browser as fallback"""
    print(f"\n{Sty.CYAN}🔍 TEXT SEARCH{Sty.RESET}")
    print("\nEnter search terms (author, title, series):")
    query = input("Search: ").strip()
    
    if not query:
        return []
    
    results = catalog.search(query, limit=100)
    
    if not results:
        print(f"{Sty.YELLOW}No results found{Sty.RESET}")
        return []
    
    print(f"\n{Sty.GREEN}Found {len(results)} result(s):{Sty.RESET}\n")
    
    # Display with pagination
    page_size = 20
    current_page = 0
    
    while True:
        start = current_page * page_size
        end = min(start + page_size, len(results))
        
        for i, book in enumerate(results[start:end], start + 1):
            author = book.get('author', '—')
            series = book.get('series', '')
            title = book.get('book', '—')
            size_mb = book.get('size', 0) / (1024 * 1024)
            
            if series:
                display = f"{author} ▸ {series} ▸ {title}"
            else:
                display = f"{author} ▸ {title}"
            
            indicator = "📘" if book.get('has_m4b') else "🎵"
            print(f"{Sty.GREEN}{i:3d}{Sty.RESET}) {display} {indicator} ({size_mb:.0f}MB)")
        
        nav_options = []
        if current_page > 0:
            nav_options.append("'p' = previous")
        if end < len(results):
            nav_options.append("'n' = next")
        nav_options.append("numbers = select (space-separated)")
        nav_options.append("'all' = select all")
        nav_options.append("'q' = quit")
        
        print(f"\n{Sty.YELLOW}{' | '.join(nav_options)}:{Sty.RESET}")
        choice = input("Choice: ").strip().lower()
        
        if choice == 'q':
            return []
        elif choice == 'n' and end < len(results):
            current_page += 1
        elif choice == 'p' and current_page > 0:
            current_page -= 1
        elif choice == 'all':
            return [book['path'] for book in results]
        else:
            # Parse number selections
            selected = []
            for num in choice.split():
                if num.isdigit():
                    idx = int(num) - 1
                    if 0 <= idx < len(results):
                        selected.append(results[idx]['path'])
            if selected:
                return selected

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
        print(f"{Sty.YELLOW}fzf not found. Using hierarchical browser.{Sty.RESET}")
        
        # Create a temporary catalog-like interface
        class TempCatalog:
            def search(self, query, limit):
                if query == "*":
                    return candidates[:limit]
                query_lower = query.lower()
                results = []
                for c in candidates:
                    if (query_lower in c.get('author', '').lower() or
                        query_lower in c.get('book', '').lower() or
                        query_lower in c.get('series', '').lower()):
                        results.append(c)
                        if len(results) >= limit:
                            break
                return results
        
        temp_catalog = TempCatalog()
        return hierarchical_browser(temp_catalog)
    
    # Build searchable lines with metadata
    lines = []
    for r in candidates:
        author = r.get('author', '—')
        series = r.get('series', '—')
        book = r.get('book', '—')
        path = r['path']
        
        # Format: "Author ▸ Series ▸ Book\tpath\tJSON"
        display = f"{author} ▸ {series} ▸ {book}" if series != '—' else f"{author} ▸ {book}"
        
        # Add indicators
        if r.get('has_m4b'):
            display += " 📘"
        elif r.get('has_mp3'):
            display += " 🎵"
        
        # Add size
        size_mb = r.get('size', 0) / (1024 * 1024)
        display += f" ({size_mb:.0f}MB)"
        
        payload = json.dumps({"path": path})
        lines.append(f"{display}\t{path}\t{payload}")
    
    # Preview command - show files and stats
    preview_cmd = r'''
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
    '''
    
    # Build fzf command
    fzf_args = [
        "fzf",
        "--ansi",
        "--with-nth=1",  # Only show first column for searching
        "--delimiter=\t",
        "--height=90%",
        "--reverse",
        "--preview", preview_cmd,
        "--preview-window=right:50%:wrap",
        "--header=TAB: select, Enter: confirm, Ctrl-C: cancel",
        "--prompt=Search> "
    ]
    
    if multi:
        fzf_args.extend(["-m", "--bind=ctrl-a:select-all,ctrl-d:deselect-all"])
    
    try:
        proc = subprocess.run(
            fzf_args,
            input="\n".join(lines),
            text=True,
            capture_output=True
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
        print(f"{Sty.RED}fzf error: {e}{Sty.RESET}")
        return fallback_picker(candidates, multi)

def fallback_picker(candidates: List[Dict], multi: bool) -> List[str]:
    """Fallback picker when fzf is not available"""
    if not candidates:
        return []
    
    print(f"\n{Sty.CYAN}Select audiobook(s):{Sty.RESET}")
    for i, r in enumerate(candidates[:30], 1):
        author = r.get('author', '—')
        book = r.get('book', '—')
        print(f"{i:3d}) {author} - {book}")
        print(f"      {Sty.DIM}{r['path']}{Sty.RESET}")
    
    if len(candidates) > 30:
        print(f"... and {len(candidates) - 30} more")
    
    if multi:
        choice = input("\nEnter numbers (space-separated) or 'all': ").strip()
        if choice.lower() == 'all':
            return [c['path'] for c in candidates]
        
        indices = [int(x) - 1 for x in choice.split() if x.isdigit()]
        return [candidates[i]['path'] for i in indices if 0 <= i < len(candidates)]
    else:
        choice = input("\nEnter number: ").strip()
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(candidates):
                return [candidates[idx]['path']]
    
    return []

def interactive_mode():
    """Enhanced interactive mode with search-first workflow"""
    config = load_config()
    
    # Check if catalog exists
    if not DB_FILE.exists():
        print(f"{Sty.YELLOW}No catalog found. Building index...{Sty.RESET}")
        catalog = AudiobookCatalog()
        catalog.index_directory(Path("/mnt/user/data/audio/audiobooks"), verbose=True)
        catalog.close()
    
    if config.get("first_run", True):
        print(f"""
{Sty.CYAN}╔══════════════════════════════════════════════╗
║      WELCOME TO HARDBOUND - FIRST RUN        ║
╚══════════════════════════════════════════════╝{Sty.RESET}

Let's set up your default paths:
""")
        
        library = input(f"{Sty.BOLD}Audiobook library path: {Sty.RESET}").strip()
        if library:
            config["library_path"] = library
        
        torrent = input(f"{Sty.BOLD}Torrent destination root: {Sty.RESET}").strip()
        if torrent:
            config["torrent_path"] = torrent
            
        config["first_run"] = False
        save_config(config)
        print(f"{Sty.GREEN}✅ Settings saved!{Sty.RESET}\n")
    
    while True:
        print(f"""
{Sty.CYAN}╔══════════════════════════════════════════════╗
║     📚 AUDIOBOOK HARDLINK MANAGER 📚         ║
╚══════════════════════════════════════════════╝{Sty.RESET}

What would you like to do?

{Sty.GREEN}1{Sty.RESET}) 🔍 Search and link audiobooks (recommended)
{Sty.GREEN}2{Sty.RESET}) 📊 Update catalog index
{Sty.GREEN}3{Sty.RESET}) 🔗 Link recent downloads
{Sty.GREEN}4{Sty.RESET}) 📁 Browse by folder (legacy)
{Sty.GREEN}5{Sty.RESET}) ⚙️  Settings & Preferences
{Sty.GREEN}6{Sty.RESET}) ❓ Help & Tutorial
{Sty.GREEN}7{Sty.RESET}) 🚪 Exit

""")
        choice = input("Enter your choice (1-7): ").strip()
        
        try:
            if choice == "1":
                search_and_link_wizard()
            elif choice == "2":
                update_catalog_wizard()
            elif choice == "3":
                recent_downloads_scanner()
            elif choice == "4":
                folder_batch_wizard()
            elif choice == "5":
                settings_menu()
                config = load_config()  # Reload after settings change
            elif choice == "6":
                show_interactive_help()
            elif choice == "7" or choice.lower() in ['q', 'quit', 'exit']:
                print(f"{Sty.CYAN}👋 Goodbye!{Sty.RESET}")
                break
            else:
                print(f"{Sty.YELLOW}Please enter 1-7{Sty.RESET}")
        except KeyboardInterrupt:
            print(f"\n{Sty.CYAN}👋 Goodbye!{Sty.RESET}")
            break
        except Exception as e:
            print(f"{Sty.RED}❌ Error: {e}{Sty.RESET}")

def search_and_link_wizard():
    """Search-first linking wizard with hierarchical browsing"""
    print(f"\n{Sty.CYAN}🔍 SEARCH AND LINK{Sty.RESET}")
    
    catalog = AudiobookCatalog()
    
    # Offer choice of browse vs search
    print("\nHow would you like to find audiobooks?")
    print(f"  {Sty.GREEN}1{Sty.RESET}) Browse by author (recommended for large libraries)")
    print(f"  {Sty.GREEN}2{Sty.RESET}) Search by text")
    print(f"  {Sty.GREEN}3{Sty.RESET}) Show recent audiobooks")
    
    choice = input("\nChoice (1-3): ").strip()
    
    if choice == "1":
        selected_paths = hierarchical_browser(catalog)
    elif choice == "2":
        selected_paths = text_search_browser(catalog)
    elif choice == "3":
        results = catalog.search("*", limit=50)
        if results:
            print(f"\n{Sty.GREEN}Recent audiobooks:{Sty.RESET}")
            selected_paths = text_search_browser(catalog)
        else:
            print(f"{Sty.YELLOW}No audiobooks found{Sty.RESET}")
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
    
    print(f"\n{Sty.BOLD}Destination root:{Sty.RESET}")
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
    print(f"\n{Sty.YELLOW}Will link {len(selected_paths)} audiobook(s) to {dst_root}{Sty.RESET}")
    confirm = input("Continue? [y/N]: ").lower()
    
    if confirm in ['y', 'yes']:
        stats = {"linked":0, "replaced":0, "already":0, "exists":0, "excluded":0, "skipped":0, "errors":0}
        zero_pad = bool(config.get("zero_pad", True))
        also_cover = bool(config.get("also_cover", False))
        
        for path_str in selected_paths:
            src = Path(path_str)
            base_name = zero_pad_vol(src.name) if zero_pad else src.name
            dst = dst_root / base_name
            
            print(f"\nProcessing: {src.name}")
            plan_and_link(src, dst, base_name, also_cover, zero_pad, False, False, stats)
        
        summary_table(stats, perf_counter())
    
    catalog.close()

def update_catalog_wizard():
    """Wizard for updating the catalog"""
    print(f"\n{Sty.CYAN}📚 UPDATE CATALOG WIZARD{Sty.RESET}")
    
    catalog = AudiobookCatalog()
    
    # Step 1: Choose update method
    print(f"\n{Sty.BOLD}Choose update method:{Sty.RESET}")
    print(f"  {Sty.GREEN}1{Sty.RESET}) Update from library path (recommended)")
    print(f"  {Sty.GREEN}2{Sty.RESET}) Manual directory selection")
    
    choice = input("Choice (1-2): ").strip()
    
    if choice == "1":
        # Update from configured library path
        config = load_config()
        library_path = Path(str(config.get("library_path", "")))
        
        if not library_path.exists():
            print(f"{Sty.RED}❌ Library path not found: {library_path}{Sty.RESET}")
            catalog.close()
            return
        
        print(f"\n📂 Scanning library path: {library_path}")
        count = catalog.index_directory(library_path, verbose=True)
        print(f"{Sty.GREEN}✅ Indexed {count} audiobooks{Sty.RESET}")
    elif choice == "2":
        # Manual directory selection
        root = Path(input("Enter directory path: ").strip())
        if root.exists() and root.is_dir():
            count = catalog.index_directory(root, verbose=True)
            print(f"{Sty.GREEN}✅ Indexed {count} audiobooks{Sty.RESET}")
        else:
            print(f"{Sty.RED}❌ Invalid directory: {root}{Sty.RESET}")
    else:
        print(f"{Sty.YELLOW}Invalid selection{Sty.RESET}")
    
    catalog.close()

def recent_downloads_scanner():
    """Find and link recently downloaded audiobooks"""
    print(f"\n{Sty.CYAN}🔍 RECENT DOWNLOADS SCANNER{Sty.RESET}")
    
    # Check if catalog exists
    if DB_FILE.exists():
        print("Use catalog [C] or filesystem scan [F]? ", end="")
        choice = input().strip().upper()
        if choice == 'C':
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
    hours = input(f"\nScan for audiobooks modified in last N hours (default 24): ").strip()
    hours = int(hours) if hours.isdigit() else 24
    
    print(f"\n{Sty.YELLOW}Scanning filesystem...{Sty.RESET}")
    recent = find_recent_audiobooks(hours=hours)
    
    if not recent:
        print(f"{Sty.YELLOW}No recent audiobooks found{Sty.RESET}")
        return
    
    # Convert to dict format for picker
    candidates = []
    for path in recent:
        candidates.append({
            'path': str(path),
            'book': path.name,
            'author': path.parent.name if path.parent.name != 'audiobooks' else '—',
            'mtime': path.stat().st_mtime
        })
    
    selected_paths = fzf_pick(candidates, multi=True)
    if selected_paths:
        _link_selected_paths(selected_paths)

def folder_batch_wizard():
    """Legacy folder batch wizard - kept for compatibility"""
    print(f"\n{Sty.YELLOW}Note: For large libraries, use 'Search and link' instead{Sty.RESET}")
    print(f"{Sty.CYAN}📁 FOLDER BATCH LINKER (Legacy){Sty.RESET}")
    
    config = load_config()
    
    # Use directory browser
    print(f"\n{Sty.BOLD}Choose folder containing audiobooks:{Sty.RESET}")
    src_folder = browse_directory_tree()
    if not src_folder:
        return
    
    # Find audiobook subdirectories
    audiobook_dirs = []
    print(f"\n{Sty.YELLOW}Scanning for audiobooks...{Sty.RESET}")
    
    try:
        for item in src_folder.iterdir():
            if item.is_dir() and (any(item.glob("*.m4b")) or any(item.glob("*.mp3"))):
                audiobook_dirs.append(item)
    except PermissionError:
        print(f"{Sty.RED}❌ Permission denied{Sty.RESET}")
        return
    
    if not audiobook_dirs:
        if any(src_folder.glob("*.m4b")) or any(src_folder.glob("*.mp3")):
            audiobook_dirs = [src_folder]
        else:
            print(f"{Sty.RED}No audiobooks found{Sty.RESET}")
            return
    
    print(f"\n{Sty.GREEN}Found {len(audiobook_dirs)} audiobook(s){Sty.RESET}")
    
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
    stats = {"linked":0, "replaced":0, "already":0, "exists":0, "excluded":0, "skipped":0, "errors":0}
    zero_pad = bool(config.get("zero_pad", True))
    also_cover = bool(config.get("also_cover", False))
    
    for book_dir in audiobook_dirs:
        base_name = zero_pad_vol(book_dir.name) if zero_pad else book_dir.name
        dst_dir = dst_root / base_name
        print(f"\nProcessing: {book_dir.name}")
        plan_and_link(book_dir, dst_dir, base_name, also_cover, zero_pad, False, False, stats)
    
    summary_table(stats, perf_counter())

def settings_menu():
    """Settings and preferences menu"""
    config = load_config()
    
    print(f"\n{Sty.CYAN}⚙️ SETTINGS MENU{Sty.RESET}")
    
    while True:
        print(f"""
{Sty.YELLOW}Current settings:{Sty.RESET}
  Library path: {config.get('library_path', '')}
  Torrent path: {config.get('torrent_path', '')}
  Zero pad: {config.get('zero_pad', True)}
  Also cover: {config.get('also_cover', False)}
  Recent sources: {', '.join(_get_recent_sources(config)[:5])}

{Sty.GREEN}Options:{Sty.RESET}
  1) Change library path
  2) Change torrent path
  3) Toggle zero padding
  4) Toggle cover linking
  5) Add recent source
  6) Remove recent source
  7) Reset settings to default
  8) Back to main menu
""")
        choice = input("Select an option (1-8): ").strip()
        
        if choice == "1":
            new_path = input("Enter new library path: ").strip()
            if new_path:
                config["library_path"] = new_path
                print(f"{Sty.GREEN}Library path updated.{Sty.RESET}")
        elif choice == "2":
            new_path = input("Enter new torrent path: ").strip()
            if new_path:
                config["torrent_path"] = new_path
                print(f"{Sty.GREEN}Torrent path updated.{Sty.RESET}")
        elif choice == "3":
            config["zero_pad"] = not config.get("zero_pad", True)
            print(f"{Sty.GREEN}Zero padding {'enabled' if config['zero_pad'] else 'disabled'}.{Sty.RESET}")
        elif choice == "4":
            config["also_cover"] = not config.get("also_cover", False)
            print(f"{Sty.GREEN}Cover linking {'enabled' if config['also_cover'] else 'disabled'}.{Sty.RESET}")
        elif choice == "5":
            source = input("Enter source path to add: ").strip()
            recent_sources = config.get("recent_sources", [])
            if not isinstance(recent_sources, list):
                recent_sources = []
            if source and source not in recent_sources:
                recent_sources.append(source)
                config["recent_sources"] = recent_sources
                print(f"{Sty.GREEN}Source added to recent sources.{Sty.RESET}")
        elif choice == "6":
            source = input("Enter source path to remove: ").strip()
            recent_sources = config.get("recent_sources", [])
            if not isinstance(recent_sources, list):
                recent_sources = []
            if source and source in recent_sources:
                recent_sources.remove(source)
                config["recent_sources"] = recent_sources
                print(f"{Sty.GREEN}Source removed from recent sources.{Sty.RESET}")
        elif choice == "7":
            # Reset to default settings
            config = {
                "first_run": True,
                "library_path": "",
                "torrent_path": "",
                "zero_pad": True,
                "also_cover": False,
                "recent_sources": []
            }
            print(f"{Sty.GREEN}Settings reset to default.{Sty.RESET}")
        elif choice == "8":
            break
        else:
            print(f"{Sty.RED}Invalid choice, please try again.{Sty.RESET}")
    
    save_config(config)

def show_interactive_help():
    """Show help for interactive mode"""
    print(f"""
{Sty.CYAN}❓ HARDBOUND HELP{Sty.RESET}

{Sty.BOLD}What does Hardbound do?{Sty.RESET}
Creates hardlinks from your audiobook library to torrent folders.
This saves space while letting you seed without duplicating files.

{Sty.BOLD}Search-first workflow (NEW!):{Sty.RESET}
  hardbound index              # Build catalog (1500+ books → instant search)
  hardbound search "rowling"   # Find books instantly  
  hardbound select -m          # Interactive multi-select with fzf

{Sty.BOLD}Classic commands:{Sty.RESET}
  hardbound --src /path/book --dst /path/dest  # Single book
  hardbound --src /path/book --dst-root /root  # Auto-create dest folder

{Sty.BOLD}Safety:{Sty.RESET}
• Defaults to dry-run (preview) mode
• Use --commit to actually create links
• Checks that source and destination are on same filesystem

{Sty.YELLOW}Press Enter to continue...{Sty.RESET}""")
    input()


def find_recent_audiobooks(hours=24, max_depth=3):
    """Find recently modified audiobook folders with better depth control"""
    recent = []
    seen = set()
    cutoff = datetime.now().timestamp() - (hours * 3600)
    
    search_paths = [
        "/mnt/user/data/audio/audiobooks",
        "/mnt/user/data/downloads",
        Path.home() / "audiobooks",
        Path.home() / "Downloads"
    ]
    
    for base_path in search_paths:
        if not Path(base_path).exists():
            continue
            
        try:
            for root, dirs, files in os.walk(base_path):
                # Limit depth
                depth = root[len(str(base_path)):].count(os.sep)
                if depth > max_depth:
                    dirs.clear()
                    continue
                
                root_path = Path(root)
                if root_path.stat().st_mtime > cutoff:
                    # Check if it contains audiobook files
                    if any(f.endswith(('.m4b', '.mp3')) for f in files):
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
    
    print(f"\n{Sty.BOLD}Destination root:{Sty.RESET}")
    if default_dst:
        print(f"Default: {default_dst}")
        dst_input = input("Path (Enter for default): ").strip()
        dst_root = Path(dst_input) if dst_input else Path(str(default_dst))
    else:
        dst_input = input("Path: ").strip()
        if not dst_input:
            return
        dst_root = Path(dst_input)
    
    print(f"\n{Sty.YELLOW}Link {len(selected_paths)} audiobook(s)? [y/N]: {Sty.RESET}", end="")
    if input().strip().lower() not in ['y', 'yes']:
        return
    
    stats = {"linked":0, "replaced":0, "already":0, "exists":0, "excluded":0, "skipped":0, "errors":0}
    zero_pad = bool(config.get("zero_pad", True))
    also_cover = bool(config.get("also_cover", False))
    
    for path_str in selected_paths:
        src = Path(path_str)
        base_name = zero_pad_vol(src.name) if zero_pad else src.name
        dst_dir = dst_root / base_name
        print(f"\n{Sty.CYAN}Processing: {src.name}{Sty.RESET}")
        plan_and_link(src, dst_dir, base_name, also_cover, zero_pad, False, False, stats)
    
    summary_table(stats, perf_counter())


def browse_directory_tree():
    """Interactive directory tree browser (legacy mode)"""
    current = Path.cwd()
    
    while True:
        print(f"\n{Sty.CYAN}📁 Current: {current}{Sty.RESET}")
        
        items = []
        try:
            # Show parent
            items.append(('..',  current.parent))
            
            # List directories first
            for item in sorted(current.iterdir()):
                if item.is_dir():
                    # Check if it contains audiobooks
                    has_audio = any(item.glob("*.m4b")) or any(item.glob("*.mp3"))
                    marker = " 🎵" if has_audio else ""
                    items.append((f"[D] {item.name}{marker}", item))
        except PermissionError:
            print(f"{Sty.RED}Permission denied{Sty.RESET}")
            
        for i, (display, path) in enumerate(items[:20], 1):
            print(f"  {i:2d}) {display}")
        
        if len(items) > 20:
            print(f"  ... and {len(items) - 20} more")
        
        print(f"\n{Sty.YELLOW}Enter number to navigate, 'select' to choose current, 'back' to go up:{Sty.RESET}")
        choice = input("Choice: ").strip().lower()
        
        if choice == 'select':
            return current
        elif choice == 'back':
            current = current.parent
        elif choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(items):
                _, new_path = items[idx]
                if new_path.is_dir():
                    current = new_path