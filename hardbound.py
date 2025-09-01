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
import hashlib
import threading
import time

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
BOOKMARKS_FILE = CONFIG_DIR / "bookmarks.json"
HISTORY_FILE = CONFIG_DIR / "history.json"
WATCH_FILE = CONFIG_DIR / "watch.json"

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
                has_mp3 BOOLEAN,
                last_linked REAL,
                link_count INTEGER DEFAULT 0,
                tags TEXT,
                rating INTEGER,
                checksum TEXT
            );
            
            CREATE INDEX IF NOT EXISTS idx_mtime ON items(mtime DESC);
            CREATE INDEX IF NOT EXISTS idx_path ON items(path);
            CREATE INDEX IF NOT EXISTS idx_last_linked ON items(last_linked DESC);
            
            CREATE VIRTUAL TABLE IF NOT EXISTS items_fts USING fts5(
                author, series, book, asin, tags,
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
            
            CREATE TABLE IF NOT EXISTS link_history (
                id INTEGER PRIMARY KEY,
                source_path TEXT,
                dest_path TEXT,
                timestamp REAL,
                action TEXT,
                success BOOLEAN
            );
            
            CREATE INDEX IF NOT EXISTS idx_history_time ON link_history(timestamp DESC);
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
    
    def get_dashboard_stats(self) -> Dict[str, Any]:
        """Get comprehensive dashboard statistics"""
        cursor = self.conn.execute("""
            SELECT 
                COUNT(*) as total,
                COUNT(DISTINCT author) as authors,
                COUNT(DISTINCT series) as series,
                SUM(size) as total_size,
                SUM(file_count) as total_files,
                COUNT(CASE WHEN has_m4b THEN 1 END) as m4b_count,
                COUNT(CASE WHEN has_mp3 THEN 1 END) as mp3_count,
                COUNT(CASE WHEN last_linked IS NOT NULL THEN 1 END) as linked_count,
                AVG(rating) as avg_rating
            FROM items
        """)
        stats = dict(cursor.fetchone())
        
        # Get recent activity
        cursor = self.conn.execute("""
            SELECT * FROM link_history 
            ORDER BY timestamp DESC 
            LIMIT 10
        """)
        stats['recent_activity'] = [dict(row) for row in cursor.fetchall()]
        
        # Get top authors
        cursor = self.conn.execute("""
            SELECT author, COUNT(*) as count 
            FROM items 
            WHERE author IS NOT NULL AND author != '—'
            GROUP BY author 
            ORDER BY count DESC 
            LIMIT 5
        """)
        stats['top_authors'] = [dict(row) for row in cursor.fetchall()]
        
        return stats
    
    def add_to_history(self, source: str, dest: str, action: str, success: bool):
        """Add entry to link history"""
        self.conn.execute("""
            INSERT INTO link_history (source_path, dest_path, timestamp, action, success)
            VALUES (?, ?, ?, ?, ?)
        """, (source, dest, time.time(), action, success))
        self.conn.commit()
    
    def update_link_stats(self, path: str):
        """Update link statistics for an item"""
        self.conn.execute("""
            UPDATE items 
            SET last_linked = ?, link_count = link_count + 1
            WHERE path = ?
        """, (time.time(), path))
        self.conn.commit()

class BookmarkManager:
    """Manage bookmarks and favorites"""
    
    def __init__(self):
        self.bookmarks = self._load_bookmarks()
    
    def _load_bookmarks(self) -> Dict[str, Any]:
        if BOOKMARKS_FILE.exists():
            try:
                return json.loads(BOOKMARKS_FILE.read_text())
            except:
                pass
        return {"favorites": [], "tags": {}}
    
    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        BOOKMARKS_FILE.write_text(json.dumps(self.bookmarks, indent=2))
    
    def add_favorite(self, path: str, name: str = None):
        entry = {"path": path, "name": name or Path(path).name, "added": time.time()}
        self.bookmarks["favorites"].append(entry)
        self.save()
    
    def remove_favorite(self, path: str):
        self.bookmarks["favorites"] = [
            f for f in self.bookmarks["favorites"] 
            if f["path"] != path
        ]
        self.save()
    
    def is_favorite(self, path: str) -> bool:
        return any(f["path"] == path for f in self.bookmarks["favorites"])
    
    def get_favorites(self) -> List[Dict]:
        return self.bookmarks["favorites"]
    
    def add_tag(self, path: str, tag: str):
        if path not in self.bookmarks["tags"]:
            self.bookmarks["tags"][path] = []
        if tag not in self.bookmarks["tags"][path]:
            self.bookmarks["tags"][path].append(tag)
        self.save()

class WatchManager:
    """Manage watch folders for automatic linking"""
    
    def __init__(self):
        self.config = self._load_config()
        self.running = False
        self.thread = None
    
    def _load_config(self) -> Dict:
        if WATCH_FILE.exists():
            try:
                return json.loads(WATCH_FILE.read_text())
            except:
                pass
        return {"folders": [], "interval": 300, "enabled": False}
    
    def save(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        WATCH_FILE.write_text(json.dumps(self.config, indent=2))
    
    def add_folder(self, source: str, destination: str, pattern: str = "*"):
        self.config["folders"].append({
            "source": source,
            "destination": destination,
            "pattern": pattern,
            "added": time.time()
        })
        self.save()
    
    def start(self):
        if not self.running and self.config["enabled"]:
            self.running = True
            self.thread = threading.Thread(target=self._watch_loop, daemon=True)
            self.thread.start()
    
    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
    
    def _watch_loop(self):
        while self.running:
            for folder in self.config["folders"]:
                self._check_folder(folder)
            time.sleep(self.config["interval"])
    
    def _check_folder(self, folder_config: Dict):
        # Implementation for checking and auto-linking new audiobooks
        pass

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

def hierarchical_browser(catalog: AudiobookCatalog) -> List[str]:
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
    
    # Start watch manager if enabled
    watch = WatchManager()
    if watch.config.get('enabled'):
        watch.start()
    
    while True:
        print(f"""
{Sty.CYAN}╔══════════════════════════════════════════════╗
║     📚 AUDIOBOOK HARDLINK MANAGER 📚         ║
╚══════════════════════════════════════════════╝{Sty.RESET}

What would you like to do?

{Sty.GREEN}1{Sty.RESET}) 📊 Dashboard
{Sty.GREEN}2{Sty.RESET}) 🔍 Search and link audiobooks
{Sty.GREEN}3{Sty.RESET}) ⚡ Batch operations
{Sty.GREEN}4{Sty.RESET}) 📊 Update catalog index
{Sty.GREEN}5{Sty.RESET}) ⭐ Manage favorites
{Sty.GREEN}6{Sty.RESET}) 👁️  Watch folders
{Sty.GREEN}7{Sty.RESET}) 🔍 Find duplicates
{Sty.GREEN}8{Sty.RESET}) ↩️  Undo last operation
{Sty.GREEN}9{Sty.RESET}) ⚙️  Settings
{Sty.GREEN}0{Sty.RESET}) 🚪 Exit

""")
        choice = input("Enter your choice: ").strip()
        
        try:
            if choice == "1":
                show_dashboard()
            elif choice == "2":
                catalog = AudiobookCatalog()
                selected = enhanced_search_browser(catalog)
                if selected:
                    _link_selected_paths(selected)
                catalog.close()
            elif choice == "3":
                batch_operations_wizard()
            elif choice == "4":
                update_catalog_wizard()
            elif choice == "5":
                manage_favorites_menu()
            elif choice == "6":
                watch_folders_manager()
            elif choice == "7":
                duplicate_finder()
            elif choice == "8":
                undo_last_operation()
            elif choice == "9":
                settings_menu()
                config = load_config()
            elif choice == "0" or choice.lower() in ['q', 'quit', 'exit']:
                watch.stop()
                print(f"{Sty.CYAN}👋 Goodbye!{Sty.RESET}")
                break
            else:
                print(f"{Sty.YELLOW}Please enter 0-9{Sty.RESET}")
        except KeyboardInterrupt:
            watch.stop()
            print(f"\n{Sty.CYAN}👋 Goodbye!{Sty.RESET}")
            break
        except Exception as e:
            print(f"{Sty.RED}❌ Error: {e}{Sty.RESET}")

def show_dashboard():
    """Display comprehensive dashboard"""
    catalog = AudiobookCatalog()
    stats = catalog.get_dashboard_stats()
    bookmarks = BookmarkManager()
    
    print(f"""
{Sty.CYAN}╔══════════════════════════════════════════════════════════════╗
║                     📊 HARDBOUND DASHBOARD                      ║
╚══════════════════════════════════════════════════════════════╝{Sty.RESET}

{Sty.BOLD}📚 Library Overview{Sty.RESET}
├─ Total Audiobooks: {Sty.GREEN}{stats['total']:,}{Sty.RESET}
├─ Unique Authors: {stats['authors']}
├─ Series: {stats['series']}
├─ Total Size: {Sty.YELLOW}{stats['total_size'] / (1024**3):.1f} GB{Sty.RESET}
├─ M4B Files: {stats['m4b_count']}
└─ MP3 Collections: {stats['mp3_count']}

{Sty.BOLD}🔗 Link Statistics{Sty.RESET}
├─ Books Linked: {stats['linked_count']}
└─ Average Rating: {'⭐' * int(stats.get('avg_rating', 0) or 0)}

{Sty.BOLD}👤 Top Authors{Sty.RESET}""")
    
    for author in stats['top_authors']:
        print(f"├─ {author['author']}: {author['count']} books")
    
    if bookmarks.get_favorites():
        print(f"\n{Sty.BOLD}⭐ Favorites{Sty.RESET}")
        for fav in bookmarks.get_favorites()[:5]:
            print(f"├─ {fav['name']}")
    
    if stats['recent_activity']:
        print(f"\n{Sty.BOLD}📅 Recent Activity{Sty.RESET}")
        for activity in stats['recent_activity'][:5]:
            action_icon = "✅" if activity['success'] else "❌"
            print(f"├─ {action_icon} {activity['action']} - {Path(activity['source_path']).name}")
    
    catalog.close()
    
    print(f"\n{Sty.YELLOW}Press Enter to continue...{Sty.RESET}")
    input()

def enhanced_search_browser(catalog: AudiobookCatalog) -> List[str]:
    """Enhanced search with filters and sorting"""
    print(f"\n{Sty.CYAN}🔍 ADVANCED SEARCH{Sty.RESET}")
    
    # Search options menu
    print("""
Search Options:
  1) Simple text search
  2) Author filter
  3) Series filter  
  4) Size range
  5) File type (M4B/MP3)
  6) Recently added
  7) Most linked
  8) Favorites only
""")
    
    option = input("Select option (1-8): ").strip()
    
    query = "*"
    if option == "1":
        query = input("Enter search terms: ").strip()
    elif option == "2":
        author = input("Author name: ").strip()
        query = f'author:"{author}"' if author else "*"
    elif option == "3":
        series = input("Series name: ").strip()
        query = f'series:"{series}"' if series else "*"
    elif option == "6":
        # Custom query for recent items
        cursor = catalog.conn.execute("""
            SELECT * FROM items 
            ORDER BY mtime DESC 
            LIMIT 100
        """)
        results = [dict(row) for row in cursor.fetchall()]
    elif option == "7":
        # Most linked items
        cursor = catalog.conn.execute("""
            SELECT * FROM items 
            WHERE link_count > 0
            ORDER BY link_count DESC, last_linked DESC
            LIMIT 100
        """)
        results = [dict(row) for row in cursor.fetchall()]
    else:
        results = catalog.search(query, limit=500)
    
    if option not in ["6", "7"]:
        results = catalog.search(query, limit=500)
    
    if not results:
        print(f"{Sty.YELLOW}No results found{Sty.RESET}")
        return []
    
    # Sorting options
    print(f"\n{Sty.GREEN}Found {len(results)} results{Sty.RESET}")
    print("Sort by: [N]ame, [A]uthor, [S]ize, [D]ate, [L]ink count")
    sort = input("Choice: ").strip().lower()
    
    if sort == 'n':
        results.sort(key=lambda x: x.get('book', ''))
    elif sort == 'a':
        results.sort(key=lambda x: x.get('author', ''))
    elif sort == 's':
        results.sort(key=lambda x: x.get('size', 0), reverse=True)
    elif sort == 'd':
        results.sort(key=lambda x: x.get('mtime', 0), reverse=True)
    elif sort == 'l':
        results.sort(key=lambda x: x.get('link_count', 0), reverse=True)
    
    # Display with enhanced information
    bookmarks = BookmarkManager()
    page_size = 20
    current_page = 0
    
    while True:
        start = current_page * page_size
        end = min(start + page_size, len(results))
        
        print(f"\n{Sty.BOLD}Results {start+1}-{end} of {len(results)}{Sty.RESET}\n")
        
        for i, book in enumerate(results[start:end], start + 1):
            author = book.get('author', '—')
            series = book.get('series', '')
            title = book.get('book', '—')
            size_mb = book.get('size', 0) / (1024 * 1024)
            link_count = book.get('link_count', 0)
            
            # Build display with indicators
            if series:
                display = f"{author} ▸ {series} ▸ {title}"
            else:
                display = f"{author} ▸ {title}"
            
            # Add status indicators
            indicators = []
            if book.get('has_m4b'):
                indicators.append("📘")
            elif book.get('has_mp3'):
                indicators.append("🎵")
            
            if bookmarks.is_favorite(book['path']):
                indicators.append("⭐")
            
            if link_count > 0:
                indicators.append(f"🔗{link_count}")
            
            indicator_str = " ".join(indicators)
            
            print(f"{Sty.GREEN}{i:3d}{Sty.RESET}) {display} {indicator_str} ({size_mb:.0f}MB)")
        
        # Navigation with more options
        nav_options = []
        if current_page > 0:
            nav_options.append("'p' = previous")
        if end < len(results):
            nav_options.append("'n' = next")
        nav_options.append("numbers = select")
        nav_options.append("'f+N' = toggle favorite")
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
        elif choice.startswith('f+'):
            # Toggle favorite
            num = choice[2:]
            if num.isdigit():
                idx = int(num) - 1
                if 0 <= idx < len(results):
                    book = results[idx]
                    if bookmarks.is_favorite(book['path']):
                        bookmarks.remove_favorite(book['path'])
                        print(f"{Sty.YELLOW}Removed from favorites{Sty.RESET}")
                    else:
                        bookmarks.add_favorite(book['path'], book.get('book'))
                        print(f"{Sty.GREEN}Added to favorites{Sty.RESET}")
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

def batch_operations_wizard():
    """Wizard for batch operations with templates"""
    print(f"\n{Sty.CYAN}⚡ BATCH OPERATIONS{Sty.RESET}")
    
    templates = {
        "1": {
            "name": "Link all by author",
            "description": "Link all books from a specific author"
        },
        "2": {
            "name": "Link complete series",
            "description": "Link all books in a series"
        },
        "3": {
            "name": "Link favorites",
            "description": "Link all bookmarked favorites"
        },
        "4": {
            "name": "Link by size",
            "description": "Link books within size range"
        },
        "5": {
            "name": "Custom filter",
            "description": "Create custom filter for batch"
        }
    }
    
    print("\nSelect batch template:")
    for key, template in templates.items():
        print(f"  {Sty.GREEN}{key}{Sty.RESET}) {template['name']}")
        print(f"     {Sty.DIM}{template['description']}{Sty.RESET}")
    
    choice = input("\nChoice: ").strip()
    
    catalog = AudiobookCatalog()
    selected_paths = []
    
    if choice == "1":
        # By author
        author = input("Author name: ").strip()
        if author:
            results = catalog.search(f'author:"{author}"', limit=500)
            if results:
                print(f"\n{Sty.GREEN}Found {len(results)} books by {author}{Sty.RESET}")
                confirm = input("Link all? [y/N]: ").lower()
                if confirm in ['y', 'yes']:
                    selected_paths = [r['path'] for r in results]
    
    elif choice == "2":
        # By series
        series = input("Series name: ").strip()
        if series:
            results = catalog.search(f'series:"{series}"', limit=500)
            if results:
                print(f"\n{Sty.GREEN}Found {len(results)} books in {series}{Sty.RESET}")
                for r in results:
                    print(f"  • {r.get('book', '—')}")
                confirm = input("\nLink all? [y/N]: ").lower()
                if confirm in ['y', 'yes']:
                    selected_paths = [r['path'] for r in results]
    
    elif choice == "3":
        # Favorites
        bookmarks = BookmarkManager()
        favorites = bookmarks.get_favorites()
        if favorites:
            print(f"\n{Sty.GREEN}Found {len(favorites)} favorites{Sty.RESET}")
            for fav in favorites:
                print(f"  ⭐ {fav['name']}")
            confirm = input("\nLink all? [y/N]: ").lower()
            if confirm in ['y', 'yes']:
                selected_paths = [f['path'] for f in favorites]
    
    elif choice == "4":
        # By size
        min_mb = input("Minimum size (MB): ").strip()
        max_mb = input("Maximum size (MB): ").strip()
        
        min_size = int(min_mb) * 1024 * 1024 if min_mb.isdigit() else 0
        max_size = int(max_mb) * 1024 * 1024 if max_mb.isdigit() else float('inf')
        
        results = catalog.search("*", limit=1000)
        filtered = [r for r in results if min_size <= r.get('size', 0) <= max_size]
        
        if filtered:
            print(f"\n{Sty.GREEN}Found {len(filtered)} books in size range{Sty.RESET}")
            confirm = input("Link all? [y/N]: ").lower()
            if confirm in ['y', 'yes']:
                selected_paths = [r['path'] for r in filtered]
    
    catalog.close()
    
    if selected_paths:
        _link_selected_paths(selected_paths)

def undo_last_operation():
    """Undo the last link operation"""
    catalog = AudiobookCatalog()
    
    # Get last operation from history
    cursor = catalog.conn.execute("""
        SELECT * FROM link_history 
        WHERE success = 1
        ORDER BY timestamp DESC 
        LIMIT 10
    """)
    
    recent = [dict(row) for row in cursor.fetchall()]
    
    if not recent:
        print(f"{Sty.YELLOW}No operations to undo{Sty.RESET}")
        catalog.close()
        return
    
    print(f"\n{Sty.CYAN}Recent operations:{Sty.RESET}")
    for i, op in enumerate(recent, 1):
        timestamp = datetime.fromtimestamp(op['timestamp']).strftime("%Y-%m-%d %H:%M")
        print(f"  {i}) {op['action']} - {Path(op['source_path']).name}")
        print(f"     {Sty.DIM}Destination: {op['dest_path']}{Sty.RESET}")
        print(f"     {Sty.DIM}Time: {timestamp}{Sty.RESET}")
    
    choice = input("\nSelect operation to undo (1-10): ").strip()
    
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(recent):
            op = recent[idx]
            dest = Path(op['dest_path'])
            
            if dest.exists():
                confirm = input(f"\n{Sty.YELLOW}Remove {dest}? [y/N]: {Sty.RESET}").lower()
                if confirm in ['y', 'yes']:
                    try:
                        if dest.is_file():
                            dest.unlink()
                        else:
                            shutil.rmtree(dest)
                        print(f"{Sty.GREEN}✅ Undone successfully{Sty.RESET}")
                        catalog.add_to_history(op['source_path'], op['dest_path'], 'undo', True)
                    except Exception as e:
                        print(f"{Sty.RED}❌ Error: {e}{Sty.RESET}")
            else:
                print(f"{Sty.YELLOW}Destination no longer exists{Sty.RESET}")
    
    catalog.close()

def watch_folders_manager():
    """Manage watch folders for automatic linking"""
    watch = WatchManager()
    
    while True:
        print(f"""
{Sty.CYAN}👁️  WATCH FOLDERS{Sty.RESET}

Auto-link new audiobooks when they appear in watched folders.

Current Status: {Sty.GREEN if watch.config['enabled'] else Sty.RED}{'ENABLED' if watch.config['enabled'] else 'DISABLED'}{Sty.RESET}
Check Interval: {watch.config['interval']} seconds

Watched Folders:""")
        
        if watch.config['folders']:
            for i, folder in enumerate(watch.config['folders'], 1):
                print(f"  {i}) {folder['source']} → {folder['destination']}")
                print(f"     Pattern: {folder['pattern']}")
        else:
            print(f"  {Sty.DIM}No folders configured{Sty.RESET}")
        
        print(f"""
Options:
  1) Add watch folder
  2) Remove watch folder
  3) {'Disable' if watch.config['enabled'] else 'Enable'} watching
  4) Change interval
  5) Back to main menu
""")
        
        choice = input("Choice: ").strip()
        
        if choice == "1":
            source = input("Source folder to watch: ").strip()
            dest = input("Destination for new audiobooks: ").strip()
            
            if source and dest:
                watch.add_folder(source, dest)
                print(f"{Sty.GREEN}✅ Added watch folder{Sty.RESET}")
        
        elif choice == "2":
            if watch.config['folders']:
                idx = input("Folder number to remove: ").strip()
                if idx.isdigit():
                    idx = int(idx) - 1
                    if 0 <= idx < len(watch.config['folders']):
                        del watch.config['folders'][idx]
                        watch.save()
                        print(f"{Sty.GREEN}✅ Removed{Sty.RESET}")
        
        elif choice == "3":
            watch.config['enabled'] = not watch.config['enabled']
            watch.save()
            if watch.config['enabled']:
                watch.start()
            else:
                watch.stop()
        
        elif choice == "4":
            interval = input("Check interval in seconds (current: {}): ".format(
                watch.config['interval']
            )).strip()
            if interval.isdigit():
                watch.config['interval'] = int(interval)
                watch.save()
                print(f"{Sty.GREEN}✅ Updated interval{Sty.RESET}")
        
        elif choice == "5":
            break

def duplicate_finder():
    """Find and manage duplicate audiobooks"""
    print(f"\n{Sty.CYAN}🔍 DUPLICATE FINDER{Sty.RESET}")
    
    catalog = AudiobookCatalog()
    
    print("\nAnalyzing library for duplicates...")
    
    # Find duplicates by book name
    cursor = catalog.conn.execute("""
        SELECT book, author, COUNT(*) as count, GROUP_CONCAT(path, '||') as paths
        FROM items
        WHERE book IS NOT NULL AND book != '—'
        GROUP BY book, author
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC
    """)
    
    duplicates = [dict(row) for row in cursor.fetchall()]
    
    if not duplicates:
        print(f"{Sty.GREEN}No duplicates found!{Sty.RESET}")
        catalog.close()
        return
    
    print(f"\n{Sty.YELLOW}Found {len(duplicates)} potential duplicate sets{Sty.RESET}\n")
    
    for i, dup in enumerate(duplicates[:20], 1):
        paths = dup['paths'].split('||')
        print(f"{Sty.GREEN}{i}{Sty.RESET}) {dup['book']} by {dup['author']} ({dup['count']} copies)")
        
        for path in paths[:3]:
            p = Path(path)
            size_mb = p.stat().st_size / (1024 * 1024) if p.exists() else 0
            print(f"   • {path} ({size_mb:.0f}MB)")
        
        if len(paths) > 3:
            print(f"   ... and {len(paths) - 3} more")
    
    choice = input("\nSelect duplicate set to review (1-20): ").strip()
    
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(duplicates):
            dup = duplicates[idx]
            paths = dup['paths'].split('||')
            
            print(f"\n{Sty.BOLD}Duplicate copies of: {dup['book']}{Sty.RESET}\n")
            
            for i, path in enumerate(paths, 1):
                p = Path(path)
                if p.exists():
                    size = p.stat().st_size / (1024 * 1024)
                    mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d")
                    file_count = len(list(p.iterdir()))
                    
                    print(f"{i}) {path}")
                    print(f"   Size: {size:.0f}MB | Files: {file_count} | Modified: {mtime}")
            
            print(f"\n{Sty.YELLOW}Options: 'keep N' to keep only copy N, 'skip' to skip{Sty.RESET}")
            action = input("Action: ").strip().lower()
            
            if action.startswith("keep "):
                keep_idx = action.split()[1]
                if keep_idx.isdigit():
                    keep_idx = int(keep_idx) - 1
                    if 0 <= keep_idx < len(paths):
                        keep_path = paths[keep_idx]
                        print(f"\n{Sty.YELLOW}This will remove other copies. Continue? [y/N]: {Sty.RESET}")
                        if input().lower() in ['y', 'yes']:
                            for i, path in enumerate(paths):
                                if i != keep_idx:
                                    print(f"Would remove: {path}")
                                    # In production, actually remove: shutil.rmtree(Path(path))
    
    catalog.close()

def update_catalog_wizard():
    """Enhanced catalog update wizard with progress"""
    print(f"\n{Sty.CYAN}📊 UPDATE CATALOG{Sty.RESET}")
    
    catalog = AudiobookCatalog()
    
    # Get current stats
    stats = catalog.get_stats()
    print(f"\nCurrent catalog: {stats['total']} audiobooks")
    
    # Default paths to index
    default_paths = [
        "/mnt/user/data/audio/audiobooks",
        "/mnt/user/data/downloads",
        Path.home() / "audiobooks",
        Path.home() / "Downloads"
    ]
    
    print("\nPaths to index:")
    for i, path in enumerate(default_paths, 1):
        exists = "✅" if Path(path).exists() else "❌"
        print(f"  {i}) {exists} {path}")
    
    print(f"\n{Sty.YELLOW}Options:{Sty.RESET}")
    print("  1) Quick update (modified in last 7 days)")
    print("  2) Full reindex (slower but thorough)")
    print("  3) Add custom path")
    print("  4) Cancel")
    
    choice = input("\nChoice: ").strip()
    
    if choice == "1":
        # Quick update - only check recently modified
        print(f"\n{Sty.YELLOW}Quick updating...{Sty.RESET}")
        count = 0
        for path in default_paths:
            if Path(path).exists():
                # Only index items modified recently
                count += catalog.index_directory(Path(path), verbose=True)
        
        print(f"\n{Sty.GREEN}✅ Added/updated {count} audiobooks{Sty.RESET}")
    
    elif choice == "2":
        # Full reindex
        print(f"\n{Sty.YELLOW}Full reindexing...{Sty.RESET}")
        
        # Clear existing data
        confirm = input("Clear existing catalog? [y/N]: ").lower()
        if confirm in ['y', 'yes']:
            catalog.conn.execute("DELETE FROM items")
            catalog.conn.commit()
        
        total = 0
        for path in default_paths:
            if Path(path).exists():
                count = catalog.index_directory(Path(path), verbose=True)
                total += count
        
        print(f"\n{Sty.GREEN}✅ Indexed {total} audiobooks{Sty.RESET}")
    
    elif choice == "3":
        # Custom path
        custom = input("Enter path to index: ").strip()
        if custom and Path(custom).exists():
            count = catalog.index_directory(Path(custom), verbose=True)
            print(f"\n{Sty.GREEN}✅ Indexed {count} audiobooks{Sty.RESET}")
    
    # Show new stats
    new_stats = catalog.get_stats()
    if new_stats['total'] != stats['total']:
        diff = new_stats['total'] - stats['total']
        print(f"\nCatalog updated: {new_stats['total']} audiobooks ({'+' if diff > 0 else ''}{diff})")
    
    catalog.close()

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
    
    # Add to history tracking
    catalog = AudiobookCatalog()
    
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
