#!/usr/bin/env python3
"""
Hardbound - Scalable audiobook hardlink manager
Combines CLI power with search-first workflow for large libraries
"""
import argparse, os, re, sys, shutil, json, sqlite3, subprocess
from pathlib import Path
from time import perf_counter
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple, Any, Union

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

# -------------------------
# Exclusions (DESTINATION)
# -------------------------
EXCLUDE_DEST_NAMES = {"cover.jpg", "metadata.json"}
EXCLUDE_DEST_EXTS = {".epub"}

WEIRD_SUFFIXES = [
    (".cue.jpg", ".jpg"),
    (".cue.jpeg", ".jpeg"),
    (".cue.png", ".png"),
    (".cue.m4b", ".m4b"),
    (".cue.mp3", ".mp3"),
]

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
DOC_EXTS = {".pdf", ".txt", ".nfo"}
AUDIO_EXTS = {".m4b", ".mp3", ".flac", ".m4a"}

# Configuration handling
CONFIG_DIR = Path.home() / ".config" / "hardbound"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Add near top with other paths
DB_DIR = Path.home() / ".cache" / "hardbound"
DB_FILE = DB_DIR / "catalog.db"

class AudiobookCatalog:
    """SQLite FTS5 catalog for fast audiobook searching"""
    
    def __init__(self):
        DB_DIR.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(DB_FILE)
        self.conn.row_factory = sqlite3.Row
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema"""
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY,
                author TEXT,
                series TEXT,
                book TEXT,
                path TEXT UNIQUE,
                asin TEXT,
                mtime REAL,
                size INTEGER,
                file_count INTEGER,
                has_m4b BOOLEAN,
                has_mp3 BOOLEAN
            );
            
            CREATE INDEX IF NOT EXISTS idx_mtime ON items(mtime DESC);
            CREATE INDEX IF NOT EXISTS idx_path ON items(path);
            
            CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
                author, series, book, asin,
                content='items',
                content_rowid='id'
            );
            
            CREATE TRIGGER IF NOT EXISTS items_ai AFTER INSERT ON items BEGIN
                INSERT INTO items_fts(rowid, author, series, book, asin)
                VALUES (new.id, new.author, new.series, new.book, new.asin);
            END;
            
            CREATE TRIGGER IF NOT EXISTS items_au AFTER UPDATE ON items BEGIN
                UPDATE items_fts SET 
                    author = new.author,
                    series = new.series,
                    book = new.book,
                    asin = new.asin
                WHERE rowid = new.id;
            END;
            
            CREATE TRIGGER IF NOT EXISTS items_ad AFTER DELETE ON items BEGIN
                DELETE FROM items_fts WHERE rowid = old.id;
            END;
        """)
        self.conn.commit()
    
    def parse_audiobook_path(self, path: Path) -> Dict[str, str]:
        """Extract author/series/book from path structure"""
        parts = path.parts
        result = {"author": "", "series": "", "book": path.name, "asin": ""}
        
        # Common patterns:
        # /audiobooks/Author/Series/Book
        # /audiobooks/Author/Book
        # /downloads/Book
        
        if "audiobooks" in parts:
            idx = parts.index("audiobooks")
            remaining = parts[idx+1:]
            if len(remaining) >= 1:
                result["author"] = remaining[0]
            if len(remaining) >= 2:
                # Check if it's a series folder
                if len(remaining) == 3:
                    result["series"] = remaining[1]
                    result["book"] = remaining[2]
                else:
                    result["book"] = remaining[1]
        
        # Extract ASIN if present in book name (common pattern: "Title [ASIN]")
        asin_match = re.search(r'\[([A-Z0-9]{10})\]', result["book"])
        if asin_match:
            result["asin"] = asin_match.group(1)
        
        return result
    
    def index_directory(self, root: Path, verbose: bool = False):
        """Index or update a directory tree"""
        if verbose:
            print(f"{Sty.YELLOW}Indexing {root}...{Sty.RESET}")
        
        count = 0
        for path in root.rglob("*"):
            if not path.is_dir():
                continue
            
            # Check if it's an audiobook directory
            m4b_files = list(path.glob("*.m4b"))
            mp3_files = list(path.glob("*.mp3"))
            
            if not (m4b_files or mp3_files):
                continue
            
            # Calculate stats
            total_size = sum(f.stat().st_size for f in path.iterdir() if f.is_file())
            file_count = len(list(path.iterdir()))
            mtime = path.stat().st_mtime
            
            # Parse metadata
            meta = self.parse_audiobook_path(path)
            
            # Upsert into database
            self.conn.execute("""
                INSERT OR REPLACE INTO items 
                (path, author, series, book, asin, mtime, size, file_count, has_m4b, has_mp3)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                str(path), meta["author"], meta["series"], meta["book"], meta["asin"],
                mtime, total_size, file_count, bool(m4b_files), bool(mp3_files)
            ))
            
            count += 1
            if verbose and count % 100 == 0:
                print(f"  Indexed {count} audiobooks...")
        
        self.conn.commit()
        
        if verbose:
            print(f"{Sty.GREEN}✅ Indexed {count} audiobooks{Sty.RESET}")
        
        return count
    
    def search(self, query: str, limit: int = 500) -> List[Dict]:
        """Full-text search the catalog"""
        if not query or query == "*":
            # Return recent items
            cursor = self.conn.execute("""
                SELECT * FROM items 
                ORDER BY mtime DESC 
                LIMIT ?
            """, (limit,))
        else:
            # FTS5 search
            cursor = self.conn.execute("""
                SELECT i.* FROM items i
                JOIN items_fts f ON i.id = f.rowid
                WHERE items_fts MATCH ?
                ORDER BY i.mtime DESC
                LIMIT ?
            """, (query, limit))
        
        return [dict(row) for row in cursor.fetchall()]
    
    def get_stats(self) -> Dict[str, int]:
        """Get catalog statistics"""
        cursor = self.conn.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(DISTINCT author) as authors,
                COUNT(DISTINCT series) as series,
                SUM(size) as total_size,
                SUM(file_count) as total_files
            FROM items
        """)
        return dict(cursor.fetchone())
    
    def close(self):
        self.conn.close()

def load_config():
    """Load configuration with sensible defaults"""
    if CONFIG_FILE.exists():
        try:
            return json.loads(CONFIG_FILE.read_text())
        except Exception:
            pass
    return {
        "first_run": True,
        "library_path": "",
        "torrent_path": "",
        "zero_pad": True,
        "also_cover": False,
        "recent_sources": []
    }

def save_config(config_data):
    """Save configuration to file"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config_data, indent=2))

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

def time_since(timestamp):
    """Human readable time since timestamp"""
    delta = datetime.now() - datetime.fromtimestamp(timestamp)
    if delta.days > 0:
        return f"{delta.days}d ago"
    elif delta.seconds > 3600:
        return f"{delta.seconds // 3600}h ago"
    else:
        return f"{delta.seconds // 60}m ago"

def have_fzf() -> bool:
    """Check if fzf is available"""
    return shutil.which("fzf") is not None

def fzf_pick(candidates: List[Dict], multi: bool = True) -> List[str]:
    """
    Use fzf for interactive fuzzy selection with preview
    Returns list of selected paths
    """
    if not candidates:
        return []
    
    if not have_fzf():
        print(f"{Sty.YELLOW}fzf not found. Install it for better selection UI:{Sty.RESET}")
        print("  brew install fzf  # macOS")
        print("  apt install fzf   # Debian/Ubuntu")
        return fallback_picker(candidates, multi)
    
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

def index_command(args):
    """Index audiobook directories"""
    catalog = AudiobookCatalog()
    
    # Default search roots if none specified
    if not args.roots:
        args.roots = [
            "/mnt/user/data/audio/audiobooks",
            "/mnt/user/data/downloads",
            Path.home() / "audiobooks"
        ]
    
    total = 0
    for root in args.roots:
        root = Path(root).expanduser()
        if root.exists():
            count = catalog.index_directory(root, verbose=not args.quiet)
            total += count
        elif not args.quiet:
            print(f"{Sty.YELLOW}Skipping non-existent: {root}{Sty.RESET}")
    
    if not args.quiet:
        stats = catalog.get_stats()
        print(f"\n{Sty.CYAN}Catalog stats:{Sty.RESET}")
        print(f"  Total audiobooks: {stats['total']}")
        print(f"  Unique authors: {stats['authors']}")
        print(f"  Unique series: {stats['series']}")
        print(f"  Total size: {stats['total_size'] / (1024**3):.1f} GB")
    
    catalog.close()

def search_command(args):
    """Search the audiobook catalog"""
    catalog = AudiobookCatalog()
    
    # Build query
    query_parts = []
    if args.query:
        query_parts.extend(args.query)
    if args.author:
        query_parts.append(f'author:"{args.author}"')
    if args.series:
        query_parts.append(f'series:"{args.series}"')
    if args.book:
        query_parts.append(f'book:"{args.book}"')
    
    query = " ".join(query_parts) if query_parts else "*"
    
    results = catalog.search(query, limit=args.limit)
    
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for r in results:
            author = r.get('author', '—')
            series = r.get('series', '')
            book = r.get('book', '—')
            
            if series:
                print(f"{Sty.GREEN}{author} ▸ {series} ▸ {book}{Sty.RESET}")
            else:
                print(f"{Sty.GREEN}{author} ▸ {book}{Sty.RESET}")
            print(f"  {Sty.DIM}{r['path']}{Sty.RESET}")
    
    catalog.close()

def select_command(args):
    """Interactive audiobook selection with fzf"""
    catalog = AudiobookCatalog()
    
    # Get candidates from search
    query = " ".join(args.query) if args.query else "*"
    candidates = catalog.search(query, limit=1000)
    
    if not candidates:
        print(f"{Sty.YELLOW}No audiobooks found{Sty.RESET}")
        catalog.close()
        return
    
    # Interactive selection
    selected_paths = fzf_pick(candidates, multi=args.multi)
    
    if not selected_paths:
        print(f"{Sty.YELLOW}No selection made{Sty.RESET}")
        catalog.close()
        return
    
    # If --link flag is set, proceed to linking
    if args.link and args.dst_root:
        config = load_config()
        stats = {"linked":0, "replaced":0, "already":0, "exists":0, "excluded":0, "skipped":0, "errors":0}
        
        zero_pad = bool(config.get("zero_pad", True))
        also_cover = bool(config.get("also_cover", False))
        
        print(f"\n{Sty.CYAN}Linking {len(selected_paths)} audiobook(s) to {args.dst_root}{Sty.RESET}")
        
        for path_str in selected_paths:
            src = Path(path_str)
            base_name = zero_pad_vol(src.name) if zero_pad else src.name
            dst = args.dst_root / base_name
            
            print(f"\n{Sty.BOLD}{src.name}{Sty.RESET}")
            
            if args.dry_run:
                plan_and_link(src, dst, base_name, also_cover, zero_pad, False, True, stats)
            else:
                plan_and_link(src, dst, base_name, also_cover, zero_pad, False, False, stats)
        
        summary_table(stats, perf_counter())
    else:
        # Just print the selected paths
        for path in selected_paths:
            print(path)
    
    catalog.close()

# Update interactive mode to use search-first approach
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
    """Search-first linking wizard"""
    print(f"\n{Sty.CYAN}🔍 SEARCH AND LINK{Sty.RESET}")
    
    catalog = AudiobookCatalog()
    
    # Get search query
    print("\nSearch for audiobooks (examples: 'rowling', 'series:harry', 'author:tolkien')")
    print("Leave empty to see recent audiobooks")
    query = input("Search: ").strip() or "*"
    
    # Search catalog
    results = catalog.search(query, limit=500)
    
    if not results:
        print(f"{Sty.YELLOW}No audiobooks found{Sty.RESET}")
        catalog.close()
        return
    
    print(f"\n{Sty.GREEN}Found {len(results)} audiobook(s){Sty.RESET}")
    
    # Select with fzf
    selected_paths = fzf_pick(results, multi=True)
    
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
        dst_root = Path(dst_input) if dst_input else Path(default_dst)
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
    """Update the audiobook catalog"""
    print(f"\n{Sty.CYAN}📊 UPDATE CATALOG{Sty.RESET}")
    
    catalog = AudiobookCatalog()
    
    # Show current stats
    stats = catalog.get_stats()
    print(f"\nCurrent catalog:")
    print(f"  Audiobooks: {stats['total']}")
    print(f"  Authors: {stats['authors']}")
    print(f"  Size: {stats['total_size'] / (1024**3):.1f} GB")
    
    # Update
    print(f"\n{Sty.YELLOW}Updating catalog...{Sty.RESET}")
    
    roots = [
        Path("/mnt/user/data/audio/audiobooks"),
        Path("/mnt/user/data/downloads"),
        Path.home() / "audiobooks"
    ]
    
    total = 0
    for root in roots:
        if root.exists():
            count = catalog.index_directory(root, verbose=True)
            total += count
    
    print(f"\n{Sty.GREEN}✅ Indexed {total} audiobooks{Sty.RESET}")
    catalog.close()

def settings_menu():
    """Settings and preferences menu"""
    config = load_config()
    
    while True:
        print(f"\n{Sty.CYAN}⚙️  SETTINGS & PREFERENCES{Sty.RESET}\n")
        
        print(f"1) Library path: {config.get('library_path', 'Not set')}")
        print(f"2) Torrent path: {config.get('torrent_path', 'Not set')}")
        print(f"3) Zero-pad volumes: {config.get('zero_pad', True)}")
        print(f"4) Create cover.jpg: {config.get('also_cover', False)}")
        print(f"5) Clear recent sources")
        print(f"6) Reset all settings")
        print(f"7) Back to main menu")
        
        choice = input("\nYour choice (1-7): ").strip()
        
        if choice == "1":
            path = input("Library path: ").strip()
            if path:
                config["library_path"] = path
                save_config(config)
                print(f"{Sty.GREEN}✅ Saved{Sty.RESET}")
        elif choice == "2":
            path = input("Torrent path: ").strip()
            if path:
                config["torrent_path"] = path
                save_config(config)
                print(f"{Sty.GREEN}✅ Saved{Sty.RESET}")
        elif choice == "3":
            config["zero_pad"] = not config.get("zero_pad", True)
            save_config(config)
            print(f"{Sty.GREEN}✅ Toggled{Sty.RESET}")
        elif choice == "4":
            config["also_cover"] = not config.get("also_cover", False)
            save_config(config)
            print(f"{Sty.GREEN}✅ Toggled{Sty.RESET}")
        elif choice == "5":
            config["recent_sources"] = []
            save_config(config)
            print(f"{Sty.GREEN}✅ Cleared{Sty.RESET}")
        elif choice == "6":
            if input("Reset all settings? [y/N]: ").lower() == 'y':
                CONFIG_FILE.unlink(missing_ok=True)
                print(f"{Sty.GREEN}✅ Reset complete{Sty.RESET}")
                return
        elif choice == "7":
            return

# ---------- Styling ----------
class Sty:
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    ITAL = "\x1b[3m"
    GREY = "\x1b[90m"
    RED = "\x1b[31m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    BLUE = "\x1b[34m"
    MAGENTA = "\x1b[35m"
    CYAN = "\x1b[36m"
    WHITE = "\x1b[37m"

    enabled = True

    @classmethod
    def off(cls):
        cls.enabled = False
        for k, v in cls.__dict__.items():
            if isinstance(v, str) and v.startswith("\x1b"):
                setattr(cls, k, "")

def term_width(default=100):
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return default

def ellipsize(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    if limit <= 10:
        return s[:max(0, limit - 1)] + "…"
    keep = (limit - 1) // 2
    return s[:keep] + "… " + s[-(limit - keep - 2):]

def banner(title: str, mode: str):
    w = term_width()
    line = "─" * max(4, w - 2)
    label = f"{Sty.BOLD}{Sty.CYAN} {title} {Sty.RESET}"
    mode_tag = f"{Sty.YELLOW}[DRY-RUN]{Sty.RESET}" if mode == "dry" else f"{Sty.GREEN}[COMMIT]{Sty.RESET}"
    print(f"┌{line}┐")
    print(f"│ {label}{mode_tag}".ljust(w - 1) + "│")
    print(f"└{line}┘")

def section(title: str):
    w = term_width()
    line = "─" * max(4, w - 2)
    print(f"{Sty.MAGENTA}{title}{Sty.RESET}")
    print(line)

def row(status_icon: str, status_color: str, kind: str, src: Path, dst: Path, dry: bool):
    w = term_width()
    left = f"{status_icon} {status_color}{kind:<6}{Sty.RESET}"
    middle = f"{Sty.GREY}{src}{Sty.RESET} {Sty.DIM}→{Sty.RESET} {dst}"
    usable = max(20, w - len(strip_ansi(left)) - 6)
    print(f"{left}  {ellipsize(middle, usable)}")

def strip_ansi(s: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", s)

def summary_table(stats: dict, elapsed: float):
    w = term_width()
    line = "─" * max(4, w - 2)
    print(line)
    def cell(label, n, color):
        return f"{color}{label}:{Sty.RESET} {n}"
    cells = [
        cell("linked", stats["linked"], Sty.GREEN),
        cell("replaced", stats["replaced"], Sty.BLUE),
        cell("already", stats["already"], Sty.GREY),
        cell("exists", stats["exists"], Sty.YELLOW),
        cell("excluded", stats["excluded"], Sty.GREY),
        cell("skipped", stats["skipped"], Sty.GREY),
        cell("errors", stats["errors"], Sty.RED),
    ]
    s = "  |  ".join(cells)
    print(s)
    print(f"{Sty.CYAN}elapsed{Sty.RESET}: {elapsed:.3f}s")
    print(line)

# ---------- Core helpers ----------
def zero_pad_vol(name: str, width: int = 2) -> str:
    """Turn 'vol_4' into 'vol_04' (width=2) only in the basename string provided."""
    def pad(match):
        num = match.group(1)
        return f"vol_{int(num):0{width}d}"
    return re.sub(r"vol_(\d+)", pad, name)

def normalize_weird_ext(src_name: str) -> str:
    """Normalize weird suffixes like *.cue.jpg -> *.jpg and *.cue.m4b -> *.m4b."""
    for bad, good in WEIRD_SUFFIXES:
        if src_name.endswith(bad):
            return src_name[: -len(bad)] + good
    return src_name

def choose_base_outputs(dest_dir: Path, base_name: str):
    """Return canonical dest paths for common types."""
    return {
        "cue": dest_dir / f"{base_name}.cue",
        "jpg": dest_dir / f"{base_name}.jpg",
        "m4b": dest_dir / f"{base_name}.m4b",
        "mp3": dest_dir / f"{base_name}.mp3",
        "flac": dest_dir / f"{base_name}.flac",
        "pdf": dest_dir / f"{base_name}.pdf",
        "txt": dest_dir / f"{base_name}.txt",
        "nfo": dest_dir / f"{base_name}.nfo",
    }

def dest_is_excluded(p: Path) -> bool:
    """Check if destination should be excluded"""
    name = p.name.casefold()
    if name in EXCLUDE_DEST_NAMES:
        return True
    if p.suffix.lower() in EXCLUDE_DEST_EXTS:
        return True
    return False

def same_inode(a: Path, b: Path) -> bool:
    try:
        sa = a.stat()
        sb = b.stat()
        return (sa.st_ino == sb.st_ino) and (sa.st_dev == sb.st_dev)
    except FileNotFoundError:
        return False

def ensure_dir(p: Path, dry_run: bool, stats: dict):
    if p.exists():
        return
    if dry_run:
        row("📁", Sty.YELLOW, "mkdir", Path("—"), p, dry_run)
        stats["skipped"] += 0  # just noise control
    else:
        p.mkdir(parents=True, exist_ok=True)
        row("📁", Sty.BLUE, "mkdir", Path("—"), p, dry_run)

def do_link(src: Path, dst: Path, force: bool, dry_run: bool, stats: dict):
    # Safety: ensure we have a valid source
    if src is None or not isinstance(src, Path):
        row("🚫", Sty.GREY, "skip", Path("—"), dst, dry_run)
        stats["skipped"] += 1
        return

    if not dry_run and not src.exists():
        row("⚠️ ", Sty.YELLOW, "skip", src, dst, dry_run)
        stats["skipped"] += 1
        return

    # Respect destination exclusions
    if dest_is_excluded(dst):
        row("🚫", Sty.GREY, "excl.", src, dst, dry_run)
        stats["excluded"] += 1
        return

    # Already hardlinked?
    if dst.exists() and same_inode(src, dst):
        row("✓", Sty.GREY, "ok", src, dst, dry_run)
        stats["already"] += 1
        return

    # Replace if exists & force
    if dst.exists() and force:
        if dry_run:
            row("↻", Sty.YELLOW, "repl", src, dst, dry_run)
            stats["replaced"] += 1
        else:
            try:
                dst.unlink()
                os.link(src, dst)
                row("↻", Sty.BLUE, "repl", src, dst, dry_run)
                stats["replaced"] += 1
            except OSError as e:
                row("💥", Sty.RED, "err", src, dst, dry_run)
                print(f"{Sty.RED}    {e}{Sty.RESET}", file=sys.stderr)
                stats["errors"] += 1
        return

    # Don’t overwrite without force
    if dst.exists() and not force:
        row("⏭️", Sty.YELLOW, "exist", src, dst, dry_run)
        stats["exists"] += 1
        return

    # Create link
    if dry_run:
        row("🔗", Sty.YELLOW, "link", src, dst, dry_run)
        stats["linked"] += 1
    else:
        try:
            os.link(src, dst)
            row("🔗", Sty.GREEN, "link", src, dst, dry_run)
            stats["linked"] += 1
        except OSError as e:
            row("💥", Sty.RED, "err", src, dst, dry_run)
            print(f"{Sty.RED}    {e}{Sty.RESET}", file=sys.stderr)
            stats["errors"] += 1

def plan_and_link(src_dir: Path,
                  dst_dir: Path,
                  base_name: str,
                  also_cover: bool,
                  zero_pad: bool,
                  force: bool,
                  dry_run: bool,
                  stats: dict):
    if zero_pad:
        base_name = zero_pad_vol(base_name)

    ensure_dir(dst_dir, dry_run, stats)
    outputs = choose_base_outputs(dst_dir, base_name)

    # Gather source files
    try:
        files = list(src_dir.iterdir())
    except FileNotFoundError:
        print(f"{Sty.RED}[ERR] Source directory not found: {src_dir}{Sty.RESET}", file=sys.stderr)
        stats["errors"] += 1
        return

    if not files:
        print(f"{Sty.YELLOW}[WARN] No files found in {src_dir}{Sty.RESET}")
        return

    # Categorize and normalize weird suffixes
    normalized = []
    for p in files:
        fixed_name = normalize_weird_ext(p.name)
        normalized.append((p, fixed_name))

    # Prioritize linking: cue, audio, image, docs
    for src_path, fixed_name in normalized:
        ext = Path(fixed_name).suffix.lower()
        if ext not in (AUDIO_EXTS | IMG_EXTS | DOC_EXTS | {".cue"}):
            continue

        if ext == ".cue":
            dst = outputs["cue"]
            kind = "cue"
        elif ext in AUDIO_EXTS:
            if ext == ".m4b":
                dst = outputs["m4b"]
            elif ext == ".mp3":
                dst = outputs["mp3"]
            elif ext == ".flac":
                dst = outputs["flac"]
            elif ext == ".m4a":
                dst = dst_dir / f"{base_name}.m4a"
            else:
                continue
            kind = "audio"
        elif ext in IMG_EXTS:
            dst = outputs["jpg"]  # canonical .jpg name regardless of source img ext
            kind = "image"
        elif ext in DOC_EXTS:
            if ext == ".pdf":
                dst = outputs["pdf"]
            elif ext == ".txt":
                dst = outputs["txt"]
            elif ext == ".nfo":
                dst = outputs["nfo"]
            else:
                continue
            kind = "doc"
        else:
            continue

        do_link(src_path, dst, force=force, dry_run=dry_run, stats=stats)

    # Optionally make a plain cover.jpg as well — but only if not excluded
    if also_cover:
        named_cover = outputs["jpg"]
        plain_cover = dst_dir / "cover.jpg"
        if not dest_is_excluded(plain_cover):
            if named_cover.exists() or dry_run:
                # If dry-run and not created yet, pick source image to show intent
                src_img = None
                if not named_cover.exists():
                    src_img = next(
                        (p for p, n in normalized
                         if normalize_weird_ext(n).lower().endswith((".jpg", ".jpeg", ".png"))),
                        None
                    )
                do_link(src_img if src_img is not None else named_cover,
                        plain_cover, force=force, dry_run=dry_run, stats=stats)
        else:
            row("🚫", Sty.GREY, "excl.", named_cover, plain_cover, dry_run)

def run_batch(batch_file: Path, also_cover, zero_pad, force, dry_run):
    stats = {"linked":0, "replaced":0, "already":0, "exists":0, "excluded":0, "skipped":0, "errors":0}
    with batch_file.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                src_s, dst_s = [x.strip() for x in line.split("|", 1)]
            except ValueError:
                print(f"{Sty.YELLOW}[WARN] bad line (expected 'SRC|DST'): {line}{Sty.RESET}")
                continue
            src = Path(src_s)
            dst = Path(dst_s)
            base = dst.name
            section(f"🎧 {base}")
            plan_and_link(src, dst, base, also_cover, zero_pad, force, dry_run, stats)
    return stats

# ---------- Legacy and interactive helpers ----------
def show_recent_audiobooks():
    """Show recently modified audiobooks"""
    print(f"\n{Sty.CYAN}📊 RECENT AUDIOBOOKS{Sty.RESET}")
    
    recent = find_recent_audiobooks(hours=48)
    if not recent:
        print(f"{Sty.YELLOW}No recent audiobooks found{Sty.RESET}")
        return
    
    for i, path in enumerate(recent, 1):
        print(f"{Sty.GREEN}{i:2d}{Sty.RESET}) {path.name}")
        print(f"     📍 {path}")
        print(f"     📅 Modified: {time_since(path.stat().st_mtime)}")
        print()
    
    print(f"{Sty.YELLOW}Press Enter to continue...{Sty.RESET}")
    input()

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

def preflight_checks(src: Path, dst: Path) -> bool:
    """Run preflight checks before linking"""
    # Check if paths exist
    if not src.exists():
        print(f"{Sty.RED}❌ Source doesn't exist: {src}{Sty.RESET}")
        return False
    
    # Check same filesystem
    try:
        if src.stat().st_dev != dst.parent.stat().st_dev:
            print(f"{Sty.RED}❌ Cross-device link error{Sty.RESET}")
            print(f"   Source and destination must be on same filesystem")
            print(f"   Source: {src}")
            print(f"   Dest:   {dst}")
            return False
    except FileNotFoundError:
        pass  # Destination doesn't exist yet, that's ok
    
    # Check for Unraid user/disk mixing
    src_str, dst_str = str(src), str(dst)
    if ("/mnt/user/" in src_str and "/mnt/disk" in dst_str) or \
       ("/mnt/disk" in src_str and "/mnt/user/" in dst_str):
        print(f"{Sty.RED}❌ Unraid user/disk mixing detected{Sty.RESET}")
        print(f"   Hardlinks won't work between /mnt/user and /mnt/disk paths")
        return False
    
    return True

# ---------- Main program ----------
# Update main() to properly handle subcommands
def main():
    """Main program entry point"""
    ap = argparse.ArgumentParser(
        description="Hardbound - Scalable audiobook hardlink manager",
        epilog="Examples:\n"
               "  hardbound                    # Interactive mode\n"
               "  hardbound index              # Build search catalog\n"
               "  hardbound select -m          # Search and multi-select\n"
               "  hardbound --src X --dst Y    # Classic single link",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    
    subparsers = ap.add_subparsers(dest='command', help='Commands')
    
    # Index command
    index_parser = subparsers.add_parser('index', help='Build/update audiobook catalog')
    index_parser.add_argument('roots', nargs='*', type=Path, help='Directories to index')
    index_parser.add_argument('-q', '--quiet', action='store_true', help='Quiet mode')
    
    # Search command
    search_parser = subparsers.add_parser('search', help='Search audiobook catalog')
    search_parser.add_argument('query', nargs='*', help='Search terms')
    search_parser.add_argument('--author', help='Filter by author')
    search_parser.add_argument('--series', help='Filter by series')
    search_parser.add_argument('--book', help='Filter by book name')
    search_parser.add_argument('--limit', type=int, default=100, help='Max results')
    search_parser.add_argument('--json', action='store_true', help='Output as JSON')
    
    # Select command
    select_parser = subparsers.add_parser('select', help='Interactive selection with fzf')
    select_parser.add_argument('query', nargs='*', help='Initial search filter')
    select_parser.add_argument('-m', '--multi', action='store_true', help='Multi-select mode')
    select_parser.add_argument('--link', action='store_true', help='Link selected items')
    select_parser.add_argument('--dst-root', type=Path, help='Destination root for linking')
    select_parser.add_argument('--dry-run', action='store_true', help='Preview only')
    
    # Classic arguments (for backward compatibility)
    ap.add_argument("--src", type=Path, help="Source album directory")
    ap.add_argument("--dst", type=Path, help="Destination album directory")
    ap.add_argument("--dst-root", type=Path, help="Destination root (creates subdir)")
    ap.add_argument("--base-name", type=str, help="Destination base filename")
    ap.add_argument("--zero-pad-vol", action="store_true", help="Normalize vol_4 → vol_04")
    ap.add_argument("--also-cover", action="store_true", help="Also create cover.jpg")
    ap.add_argument("--force", action="store_true", help="Overwrite existing files")
    ap.add_argument("--commit", action="store_true", help="Actually create links")
    ap.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    ap.add_argument("--batch-file", type=Path, help="Process batch file")
    ap.add_argument("--no-color", action="store_true", help="Disable colors")
    
    args = ap.parse_args()
    
    # Color control
    if args.no_color or not sys.stdout.isatty():
        Sty.off()
    
    # Route to appropriate handler
    if args.command == 'index':
        index_command(args)
    elif args.command == 'search':
        search_command(args)
    elif args.command == 'select':
        select_command(args)
    elif args.src or args.batch_file:
        # Classic CLI mode
        _classic_cli_mode(args)
    else:
        # Interactive mode (default)
        interactive_mode()

def _classic_cli_mode(args):
    """Handle classic CLI arguments for backward compatibility"""
    # Mutually-aware run mode
    if args.commit and args.dry_run:
        print(f"{Sty.RED}[ERR] Use either --commit or --dry-run, not both.{Sty.RESET}", file=sys.stderr)
        sys.exit(2)
    dry = args.dry_run or (not args.commit)

    # Handle batch file mode
    if args.batch_file:
        if any([args.src, args.dst, args.base_name]):
            print(f"{Sty.RED}[ERR] Use --batch-file OR single --src/--dst, not both.{Sty.RESET}", file=sys.stderr)
            sys.exit(2)
        if not args.batch_file.exists():
            print(f"{Sty.RED}[ERR] Batch file not found: {args.batch_file}{Sty.RESET}", file=sys.stderr)
            sys.exit(2)
        
        start = perf_counter()
        banner("Audiobook Hardlinker", "dry" if dry else "commit")
        stats = run_batch(args.batch_file, args.also_cover, args.zero_pad_vol, args.force, dry)
        summary_table(stats, perf_counter() - start)
        return

    # Single run mode
    if not args.src or (not args.dst and not args.dst_root):
        print(f"{Sty.YELLOW}[HINT]{Sty.RESET} Provide --src and either --dst or --dst-root (or use --batch-file).")
        sys.exit(2)

    if not args.src.exists():
        print(f"{Sty.RED}[ERR] Source not found: {args.src}{Sty.RESET}", file=sys.stderr)
        sys.exit(2)

    # Sanity check: don't allow both --dst and --dst-root
    if args.dst and args.dst_root:
        print(f"{Sty.RED}[ERR] Use either --dst or --dst-root, not both.{Sty.RESET}", file=sys.stderr)
        sys.exit(2)

    # If using dst-root, compute the real destination folder and base name
    if args.dst_root:
        base = args.base_name or args.src.name
        dst_dir = args.dst_root / base
    else:
        dst_dir = args.dst
        base = args.base_name or args.dst.name

    # Run preflight checks
    if not preflight_checks(args.src, dst_dir):
        sys.exit(1)

    start = perf_counter()
    banner("Audiobook Hardlinker", "dry" if dry else "commit")
    
    section("Plan")
    print(f"{Sty.BOLD} SRC{Sty.RESET}: {args.src}")
    print(f"{Sty.BOLD} DST{Sty.RESET}: {dst_dir}")
    print(f"{Sty.BOLD} BASE{Sty.RESET}: {base}")
    print(f"{Sty.BOLD} MODE{Sty.RESET}: {'DRY-RUN' if dry else 'COMMIT'}")
    print(f"{Sty.BOLD} OPTS{Sty.RESET}: zero_pad_vol={args.zero_pad_vol}  also_cover={args.also_cover}  force={args.force}")
    print()

    stats = {"linked":0, "replaced":0, "already":0, "exists":0, "excluded":0, "skipped":0, "errors":0}
    plan_and_link(args.src, dst_dir, base, args.also_cover, args.zero_pad_vol, args.force, dry, stats)
    summary_table(stats, perf_counter() - start)

if __name__ == "__main__":
    main()
