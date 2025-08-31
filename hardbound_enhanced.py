# DELETE THIS FILE - all features have been merged into hardbound.py
#!/usr/bin/env python3
"""
Enhanced Hardbound - User-friendly audiobook hardlinker
Combines CLI power with interactive wizards for non-technical users
"""
import argparse
import os
import re
import sys
import json
import shutil
from pathlib import Path
from time import perf_counter
from datetime import datetime, timedelta
from functools import wraps
from typing import Optional, Dict, Any, List, Union

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

# Import existing constants and functions from original script
from hardbound import (
    WEIRD_SUFFIXES, IMG_EXTS, DOC_EXTS, AUDIO_EXTS,
    Sty, banner, section, row, summary_table,
    zero_pad_vol, normalize_weird_ext, choose_base_outputs, 
    same_inode, ensure_dir, do_link, plan_and_link
)

# Fixed exclusion handling
EXCLUDE_DEST_NAMES = {"cover.jpg", "metadata.json"}
EXCLUDE_DEST_EXTS = {".epub"}

def dest_is_excluded(p: Path) -> bool:
    """Check if destination should be excluded"""
    name = p.name.casefold()
    if name in EXCLUDE_DEST_NAMES:
        return True
    if p.suffix.lower() in EXCLUDE_DEST_EXTS:
        return True
    return False

# Configuration handling
CONFIG_DIR = Path.home() / ".config" / "hardbound"
CONFIG_FILE = CONFIG_DIR / "config.json"

class Config:
    def __init__(self):
        self.data: Dict[str, Any] = self.load()
    
    def load(self) -> Dict[str, Any]:
        """Load configuration from file"""
        if CONFIG_FILE.exists():
            try:
                return json.loads(CONFIG_FILE.read_text())
            except Exception:
                pass
        return {
            "first_run": True,
            "library_path": "",
            "torrent_path": "",
            "default_naming": "original",
            "zero_pad": True,
            "also_cover": False,
            "recent_sources": [],
            "recent_destinations": []
        }
    
    def save(self):
        """Save configuration to file"""
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(self.data, indent=2))
    
    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)
    
    def set(self, key: str, value: Any):
        self.data[key] = value
        self.save()

config = Config()

# Preflight checks
def is_unraid_mixed_paths(a: Path, b: Path) -> bool:
    """Check for Unraid user/disk mixing"""
    sa, sb = str(a), str(b)
    return (
        ("/mnt/user/" in sa and "/mnt/disk" in sb) or
        ("/mnt/user/" in sb and "/mnt/disk" in sa)
    )

def same_device(p1: Path, p2: Path) -> bool:
    """Check if paths are on same device"""
    try:
        return p1.stat().st_dev == p2.stat().st_dev
    except FileNotFoundError:
        return False

def preflight(src_dir: Path, dst_dir: Path) -> bool:
    """Preflight checks before linking"""
    if src_dir.resolve() == dst_dir.resolve():
        print(f"{Sty.RED}[ERR]{Sty.RESET} Source and destination are the same folder.")
        return False
    if is_unraid_mixed_paths(src_dir, dst_dir):
        print(f"{Sty.RED}[ERR]{Sty.RESET} Unraid user/disk mixing detected "
              f"({src_dir} ↔ {dst_dir}). Hardlinks will fail.")
        return False
    if not same_device(src_dir, dst_dir):
        print(f"{Sty.RED}[ERR]{Sty.RESET} Cross-device: {src_dir} ↔ {dst_dir}. "
              "Hardlinks require same filesystem.")
        return False
    return True

# Error handling decorator
def friendly_error_handler(func):
    """Decorator to catch errors and provide helpful solutions"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except PermissionError as e:
            print(f"""
{Sty.RED}❌ Permission Denied{Sty.RESET}

The script doesn't have permission to create hardlinks.

{Sty.YELLOW}Solutions:{Sty.RESET}
1. Run with sudo: sudo {sys.argv[0]}
2. Check folder permissions
3. Make sure both folders are on the same drive
""")
            sys.exit(3)
        except OSError as e:
            if e.errno == 18:  # Cross-device link
                print(f"""
{Sty.RED}❌ Cross-Device Link Error{Sty.RESET}

Hardlinks can only be created on the same drive/partition.
""")
                sys.exit(4)
            else:
                print(f"{Sty.RED}❌ System Error: {e}{Sty.RESET}")
                sys.exit(5)
    return wrapper

def find_recent_audiobooks(hours: int = 24, max_results: int = 10) -> List[Path]:
    """Find recently modified audiobook folders"""
    cutoff = datetime.now().timestamp() - hours * 3600
    candidates: List[Path] = []
    seen: set = set()
    
    bases = [
        Path("/mnt/user/data/audio/audiobooks"),
        Path("/mnt/user/data/downloads"),
        Path.home() / "audiobooks",
        Path.home() / "Downloads",
    ]
    
    for base in bases:
        if not base.exists():
            continue
        try:
            # Limit depth to avoid huge walks
            for p in base.rglob("*"):
                try:
                    # Fixed parentheses for proper precedence
                    if p.is_dir() and p.stat().st_mtime > cutoff:
                        if any(p.glob("*.m4b")) or any(p.glob("*.mp3")):
                            rp = p.resolve()
                            if rp not in seen:
                                seen.add(rp)
                                candidates.append(rp)
                except (PermissionError, FileNotFoundError):
                    continue
        except PermissionError:
            continue
    
    candidates.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    return candidates[:max_results]

def time_since(timestamp: float) -> str:
    """Human readable time since timestamp"""
    delta = datetime.now() - datetime.fromtimestamp(timestamp)
    if delta.days > 0:
        return f"{delta.days}d ago"
    elif delta.seconds > 3600:
        return f"{delta.seconds // 3600}h ago"
    else:
        return f"{delta.seconds // 60}m ago"

def browse_for_audiobooks() -> Optional[Path]:
    """Visual file browser with audiobook detection"""
    print(f"\n{Sty.CYAN}📂 AUDIOBOOK BROWSER{Sty.RESET}\n")
    
    # Show recent audiobooks
    recent = find_recent_audiobooks()
    if recent:
        print(f"{Sty.BOLD}Recently modified audiobook folders:{Sty.RESET}")
        for i, path in enumerate(recent, 1):
            print(f"  {Sty.GREEN}{i:2d}{Sty.RESET}) {path.name}")
            print(f"      📍 {Sty.DIM}{path}{Sty.RESET}")
            print(f"      📅 Modified: {time_since(path.stat().st_mtime)}")
            print()
    
    # Show saved paths - properly handle the list type
    saved_sources = config.get("recent_sources", [])
    if isinstance(saved_sources, list) and saved_sources:
        print(f"{Sty.BOLD}Your frequent source folders:{Sty.RESET}")
        for i, path_str in enumerate(saved_sources[:5], len(recent) + 1):
            path = Path(path_str)
            print(f"  {Sty.BLUE}{i:2d}{Sty.RESET}) {path.name}")
            print(f"      📍 {Sty.DIM}{path}{Sty.RESET}")
            print()
    
    print(f"{Sty.YELLOW}Or enter a custom path:{Sty.RESET}")
    choice = input("Your choice (number or path): ").strip()
    
    if choice.isdigit():
        idx = int(choice) - 1
        all_paths = recent + [Path(p) for p in (saved_sources[:5] if isinstance(saved_sources, list) else [])]
        if 0 <= idx < len(all_paths):
            return all_paths[idx]
    
    # Custom path
    if choice:
        path = Path(choice).expanduser().resolve()
        if path.exists():
            # Add to recent sources - ensure it's a list
            recent_sources = config.get("recent_sources", [])
            if not isinstance(recent_sources, list):
                recent_sources = []
            path_str = str(path)
            if path_str not in recent_sources:
                recent_sources.insert(0, path_str)
                config.set("recent_sources", recent_sources[:10])
            return path
        else:
            print(f"{Sty.RED}❌ Path not found: {path}{Sty.RESET}")
    
    return None

def single_audiobook_wizard():
    """Wizard for linking a single audiobook with preview"""
    print(f"\n{Sty.CYAN}🔗 SINGLE AUDIOBOOK LINKER{Sty.RESET}\n")
    
    # Step 1: Source
    print(f"{Sty.BOLD}Step 1: Choose your audiobook source{Sty.RESET}")
    src = browse_for_audiobooks()
    if not src:
        print(f"{Sty.YELLOW}Cancelled.{Sty.RESET}")
        return
    
    print(f"✓ Source: {src}")
    
    # Step 2: Destination root
    print(f"\n{Sty.BOLD}Step 2: Choose destination root{Sty.RESET}")
    torrent_path = config.get("torrent_path", "")
    
    if torrent_path and isinstance(torrent_path, str) and torrent_path:
        print(f"Use saved destination: {torrent_path} ? [Y/n]: ", end="")
        if input().strip().lower() not in ['n', 'no']:
            dst_root = Path(torrent_path)
        else:
            dst_root = None
    else:
        dst_root = None
    
    if not dst_root:
        dst_input = input(f"Destination root path: ").strip()
        if not dst_input:
            print(f"{Sty.YELLOW}Cancelled.{Sty.RESET}")
            return
        dst_root = Path(dst_input).expanduser().resolve()
        config.set("torrent_path", str(dst_root))
    
    # Step 3: Options - ensure boolean types
    print(f"\n{Sty.BOLD}Step 3: Options{Sty.RESET}")
    zero_pad = bool(config.get("zero_pad", True))
    also_cover = bool(config.get("also_cover", False))
    
    print(f"Zero-pad volumes (vol_4 → vol_04): {'Yes' if zero_pad else 'No'} [y/N]: ", end="")
    if input().strip().lower() in ['y', 'yes']:
        zero_pad = not zero_pad
        config.set("zero_pad", zero_pad)
    
    print(f"Also create cover.jpg: {'Yes' if also_cover else 'No'} [y/N]: ", end="")
    if input().strip().lower() in ['y', 'yes']:
        also_cover = not also_cover
        config.set("also_cover", also_cover)
    
    # Step 4: Preview and confirm
    print(f"\n{Sty.BOLD}Step 4: Preview{Sty.RESET}")
    base_name = src.name
    if zero_pad:
        base_name = zero_pad_vol(base_name)
    
    dst_dir = dst_root / base_name
    
    # Preflight check
    if not preflight(src, dst_dir):
        print(f"{Sty.RED}Preflight checks failed. Cannot continue.{Sty.RESET}")
        return
    
    print(f"  Source:      {src}")
    print(f"  Destination: {dst_dir}")
    print(f"  Base name:   {base_name}")
    print(f"  Zero pad:    {zero_pad}")
    print(f"  Cover.jpg:   {also_cover}")
    
    # DRY RUN FIRST
    stats = {"linked":0, "replaced":0, "already":0, "exists":0, "excluded":0, "skipped":0, "errors":0}
    start = perf_counter()
    
    print(f"\n{Sty.YELLOW}Preview (DRY-RUN):{Sty.RESET}")
    plan_and_link(src, dst_dir, base_name, also_cover, zero_pad, False, True, stats)
    
    print(f"\n{Sty.YELLOW}Proceed to COMMIT these changes? [y/N]: {Sty.RESET}", end="")
    if input().strip().lower() in ['y', 'yes']:
        # Reset stats for real run
        stats = {k:0 for k in stats}
        print(f"\n{Sty.GREEN}🚀 Linking...{Sty.RESET}")
        plan_and_link(src, dst_dir, base_name, also_cover, zero_pad, False, False, stats)
        summary_table(stats, perf_counter() - start)
        
        if stats["errors"] == 0:
            print(f"{Sty.GREEN}✅ Success! Audiobook linked successfully.{Sty.RESET}")
        else:
            print(f"{Sty.YELLOW}⚠️  Completed with {stats['errors']} errors.{Sty.RESET}")
    else:
        print(f"{Sty.CYAN}Cancelled before commit.{Sty.RESET}")

def folder_wizard():
    """Wizard for linking all audiobooks in a folder"""
    print(f"\n{Sty.CYAN}📁 FOLDER BATCH LINKER{Sty.RESET}\n")
    
    # Step 1: Source folder
    print(f"{Sty.BOLD}Step 1: Choose folder containing audiobooks{Sty.RESET}")
    src_folder = browse_for_audiobooks()
    if not src_folder:
        return
    
    # Find audiobook subdirectories - fixed parentheses
    audiobook_dirs: List[Path] = []
    try:
        for item in src_folder.iterdir():
            if item.is_dir() and (any(item.glob("*.m4b")) or any(item.glob("*.mp3"))):
                audiobook_dirs.append(item)
    except PermissionError:
        print(f"{Sty.RED}❌ Permission denied reading {src_folder}{Sty.RESET}")
        return
    
    if not audiobook_dirs:
        print(f"{Sty.YELLOW}No audiobooks found in {src_folder}{Sty.RESET}")
        return
    
    print(f"\n{Sty.GREEN}Found {len(audiobook_dirs)} audiobooks:{Sty.RESET}")
    for book in sorted(audiobook_dirs)[:5]:
        print(f"  • {book.name}")
    if len(audiobook_dirs) > 5:
        print(f"  ... and {len(audiobook_dirs) - 5} more")
    
    # Step 2: Destination
    print(f"\n{Sty.BOLD}Step 2: Choose destination root{Sty.RESET}")
    torrent_path = config.get("torrent_path", "")
    
    if torrent_path and isinstance(torrent_path, str):
        dst_root = Path(torrent_path)
        print(f"Using: {dst_root}")
    else:
        dst_input = input("Destination root: ").strip()
        if not dst_input:
            return
        dst_root = Path(dst_input)
        config.set("torrent_path", str(dst_root))
    
    # Step 3: Batch options - ensure boolean types
    zero_pad = bool(config.get("zero_pad", True))
    also_cover = bool(config.get("also_cover", False))
    
    print(f"\n{Sty.YELLOW}Ready to link {len(audiobook_dirs)} audiobooks? [y/N]: {Sty.RESET}", end="")
    if input().strip().lower() not in ['y', 'yes']:
        return
    
    # Execute batch
    stats = {"linked":0, "replaced":0, "already":0, "exists":0, "excluded":0, "skipped":0, "errors":0}
    start = perf_counter()
    
    progress_iter = audiobook_dirs
    if HAS_TQDM:
        progress_iter = tqdm(audiobook_dirs, desc="Processing audiobooks", unit="book")
    
    for book_dir in progress_iter:
        base_name = book_dir.name
        if zero_pad:
            base_name = zero_pad_vol(base_name)
        
        dst_dir = dst_root / base_name
        
        # Preflight check for each book
        if not preflight(book_dir, dst_dir):
            continue
        
        if HAS_TQDM and hasattr(progress_iter, 'set_postfix_str'):
            progress_iter.set_postfix_str(f"📖 {book_dir.name[:30]}")
        else:
            print(f"Processing: {book_dir.name}")
        
        plan_and_link(book_dir, dst_dir, base_name, also_cover, zero_pad, False, False, stats)
    
    elapsed = perf_counter() - start
    print()  # New line after progress bar
    summary_table(stats, elapsed)

def first_run_wizard():
    """Guide new users through initial setup"""
    print(f"""
{Sty.CYAN}╔══════════════════════════════════════════════╗
║         WELCOME TO AUDIOBOOK MANAGER         ║
║           First-Time Setup Wizard            ║
╚══════════════════════════════════════════════╝{Sty.RESET}

This wizard will help you set up Hardbound for your system.
""")
    
    # Step 1: Library location
    print(f"\n{Sty.BOLD}📚 Step 1: Where do you keep your audiobook library?{Sty.RESET}")
    print("   (This is where your organized audiobooks live)")
    
    # Common paths to suggest
    suggestions = [
        "/mnt/user/data/audio/audiobooks",
        "/mnt/user/data/audiobooks", 
        Path.home() / "audiobooks",
        Path.home() / "Downloads"
    ]
    
    existing_suggestions = [p for p in suggestions if Path(p).exists()]
    
    if existing_suggestions:
        print(f"\n{Sty.GREEN}Found these common locations:{Sty.RESET}")
        for i, path in enumerate(existing_suggestions, 1):
            print(f"   {i}) {path}")
        print("   0) Enter custom path")
        
        choice = input("\nYour choice: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(existing_suggestions):
            library_path = str(existing_suggestions[int(choice) - 1])
        else:
            library_path = input("Custom path: ").strip()
    else:
        library_path = input("Library path: ").strip()
    
    # Step 2: Torrent destination
    print(f"\n{Sty.BOLD}🎯 Step 2: Where should linked copies go?{Sty.RESET}")
    print("   (Usually your torrent client's folder)")
    
    torrent_suggestions = [
        "/mnt/user/data/downloads/torrents",
        "/mnt/user/data/torrents",
        Path.home() / "torrents"
    ]
    
    existing_torrent = [p for p in torrent_suggestions if Path(p).exists()]
    
    if existing_torrent:
        print(f"\n{Sty.GREEN}Found these torrent locations:{Sty.RESET}")
        for i, path in enumerate(existing_torrent, 1):
            print(f"   {i}) {path}")
        print("   0) Enter custom path")
        
        choice = input("\nYour choice: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(existing_torrent):
            torrent_path = str(existing_torrent[int(choice) - 1])
        else:
            torrent_path = input("Custom path: ").strip()
    else:
        torrent_path = input("Torrent path: ").strip()
    
    # Step 3: Defaults
    print(f"\n{Sty.BOLD}⚙️  Step 3: Default settings{Sty.RESET}")
    
    print("Zero-pad volume numbers (vol_4 → vol_04)? [Y/n]: ", end="")
    zero_pad = input().strip().lower() not in ['n', 'no']
    
    print("Create cover.jpg by default? [y/N]: ", end="")
    also_cover = input().strip().lower() in ['y', 'yes']
    
    # Save configuration
    config.set("first_run", False)
    config.set("library_path", library_path)
    config.set("torrent_path", torrent_path)
    config.set("zero_pad", zero_pad)
    config.set("also_cover", also_cover)
    
    print(f"\n{Sty.GREEN}✅ Setup complete! Your settings have been saved.{Sty.RESET}")
    print(f"\n{Sty.CYAN}Quick start examples:{Sty.RESET}")
    print(f"  hardbound                    # Interactive menu")
    print(f"  hardbound --src /path/book   # Link one audiobook")
    print(f"  hardbound --help             # See all options")

def interactive_mode():
    """User-friendly interactive mode with menus"""
    
    # First run wizard
    if config.get("first_run", True):
        first_run_wizard()
        print("\nReturning to main menu...\n")
    
    while True:
        print(f"""
{Sty.CYAN}╔══════════════════════════════════════════════╗
║     📚 AUDIOBOOK HARDLINK MANAGER 📚         ║
╚══════════════════════════════════════════════╝{Sty.RESET}

What would you like to do?

{Sty.GREEN}1{Sty.RESET}) 🔗 Link a single audiobook
{Sty.GREEN}2{Sty.RESET}) 📁 Link all audiobooks in a folder  
{Sty.GREEN}3{Sty.RESET}) 📋 Link from a list (batch file)
{Sty.GREEN}4{Sty.RESET}) 🔍 Find and link recent downloads
{Sty.GREEN}5{Sty.RESET}) ⚙️  Settings & Preferences
{Sty.GREEN}6{Sty.RESET}) ❓ Help & Tutorial
{Sty.GREEN}7{Sty.RESET}) 🚪 Exit

""")
        choice = input("Enter your choice (1-7): ").strip()
        
        try:
            if choice == "1":
                single_audiobook_wizard()
            elif choice == "2":
                folder_wizard()
            elif choice == "3":
                print(f"{Sty.YELLOW}Batch file feature coming soon!{Sty.RESET}")
            elif choice == "4":
                print(f"{Sty.YELLOW}Recent downloads scanner coming soon!{Sty.RESET}")
            elif choice == "5":
                print(f"{Sty.YELLOW}Settings panel coming soon!{Sty.RESET}")
            elif choice == "6":
                show_help()
            elif choice == "7" or choice.lower() in ['q', 'quit', 'exit']:
                print(f"{Sty.CYAN}👋 Goodbye!{Sty.RESET}")
                break
            else:
                print(f"{Sty.YELLOW}Please enter a number 1-7{Sty.RESET}")
        except KeyboardInterrupt:
            print(f"\n{Sty.CYAN}👋 Goodbye!{Sty.RESET}")
            break
        except Exception as e:
            print(f"{Sty.RED}❌ Error: {e}{Sty.RESET}")

def show_help():
    """Show help and examples"""
    print(f"""
{Sty.CYAN}❓ HARDBOUND HELP{Sty.RESET}

{Sty.BOLD}What is Hardbound?{Sty.RESET}
Hardbound creates hardlinks from your audiobook library to torrent folders.
This lets you seed without duplicating files (saves space) while keeping
your library organized.

{Sty.BOLD}Quick Examples:{Sty.RESET}
  hardbound                           # Interactive mode (easiest)
  hardbound --src /books/novel1       # Link one audiobook  
  hardbound --src /books --dst-root /torrents  # Link using destination root

{Sty.BOLD}Key Concepts:{Sty.RESET}
• {Sty.GREEN}Source{Sty.RESET}: Your organized audiobook library
• {Sty.GREEN}Destination{Sty.RESET}: Where linked copies go (usually torrents folder)
• {Sty.GREEN}Hardlink{Sty.RESET}: Same file, two names (saves space vs copying)
• {Sty.GREEN}Dry-run{Sty.RESET}: Preview mode - shows what would happen (default)

{Sty.BOLD}Safety Features:{Sty.RESET}
• Defaults to dry-run mode (no changes until you use --commit)
• Checks for same filesystem (hardlinks require this)
• Never overwrites without --force
• Excludes sensitive files (metadata.json, etc.)

{Sty.YELLOW}Press Enter to continue...{Sty.RESET}""")
    input()

@friendly_error_handler 
def enhanced_main():
    """Enhanced main function with wizard support"""
    import hardbound as hb_core
    
    ap = argparse.ArgumentParser(
        description="Hardbound - User-friendly audiobook hardlinker",
        epilog="Use 'hardbound' with no args for interactive mode"
    )
    
    # Interactive mode
    ap.add_argument("--interactive", action="store_true",
                    help="Start interactive wizard mode")
    ap.add_argument("--wizard", action="store_true",
                    help="Run first-time setup wizard")
    
    # Original arguments (keeping compatibility)
    ap.add_argument("--src", type=Path, help="Source album directory (library/working copy).")
    ap.add_argument("--dst", type=Path, help="Destination album directory (seed/torrent folder).")
    ap.add_argument("--base-name", type=str,
                    help="Destination base filename (defaults to the dest folder name).")
    ap.add_argument("--zero-pad-vol", action="store_true",
                    help="Normalize 'vol_4' -> 'vol_04' inside the base name.")
    ap.add_argument("--also-cover", action="store_true",
                    help="Also create a 'cover.jpg' hardlink alongside the named .jpg (unless excluded).")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing dest files.")
    ap.add_argument("--commit", action="store_true",
                    help="Actually create links.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview actions without making changes (default unless --commit).")
    ap.add_argument("--batch-file", type=Path,
                    help="Process many albums. Each line: 'SRC_DIR|DST_DIR'.")
    ap.add_argument("--no-color", action="store_true", help="Disable ANSI colors/icons.")
    ap.add_argument("--dst-root", type=Path,
                    help="Root folder under which a per-album directory will be created as DST_ROOT/<base-name>.")
    
    args = ap.parse_args()

    # Color control
    if args.no_color or not sys.stdout.isatty():
        Sty.off()

    # Interactive mode (default if no args)
    if len(sys.argv) == 1 or args.interactive:
        interactive_mode()
        return
    
    # First-time wizard
    if args.wizard:
        first_run_wizard()
        return

    # Fall back to original CLI behavior
    return hb_core.main()

if __name__ == "__main__":
    enhanced_main()
