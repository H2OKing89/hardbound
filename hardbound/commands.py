#!/usr/bin/env python3
"""
Hardbound - Scalable audiobook hardlink manager
Combines CLI power with search-first workflow for large libraries
"""
import argparse
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional, Tuple, Union

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
        self.conn.executescript(
            """
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
        """
        )
        self.conn.commit()

    def parse_audiobook_path(self, path: Path) -> Dict[str, str]:
        """Extract author/series/book from path structure"""
        parts = path.parts
        result = {"author": "Unknown", "series": "", "book": path.name, "asin": ""}

        # Extract ASIN from book name if present
        asin_patterns = [
            r"\{ASIN\.([A-Z0-9]{10})\}",  # {ASIN.B0C34GQRYZ}
            r"\[ASIN\.([A-Z0-9]{10})\]",  # [ASIN.B0C34GQRYZ]
            r"\[([A-Z0-9]{10})\]",  # [B0C34GQRYZ]
        ]

        for pattern in asin_patterns:
            asin_match = re.search(pattern, result["book"])
            if asin_match:
                result["asin"] = asin_match.group(1)
                break

        # Handle structured audiobook paths
        if "audiobooks" in parts:
            idx = parts.index("audiobooks")
            remaining = parts[idx + 1 :]

            if len(remaining) >= 3:
                # Pattern: /audiobooks/Author/Series/Book
                result["author"] = remaining[0]
                result["series"] = remaining[1]
                result["book"] = remaining[2]
            elif len(remaining) == 2:
                # Pattern: /audiobooks/Author/Book (no series)
                result["author"] = remaining[0]
                result["book"] = remaining[1]
                result["series"] = ""
            elif len(remaining) == 1:
                # Pattern: /audiobooks/Book (flat structure)
                result["book"] = remaining[0]
                result["author"] = self._extract_author_from_title(result["book"])
        else:
            # Not in audiobooks folder - try to extract from filename/path
            if len(parts) >= 3:
                # Check if we're in a nested structure
                parent = parts[-2]  # Series or Author
                grandparent = parts[-3] if len(parts) >= 3 else ""

                # If grandparent looks like author and parent looks like series
                if self._looks_like_author(grandparent) and not self._looks_like_author(
                    parent
                ):
                    result["author"] = grandparent
                    result["series"] = parent
                elif self._looks_like_author(parent):
                    result["author"] = parent
                else:
                    result["author"] = self._extract_author_from_title(result["book"])
            else:
                result["author"] = self._extract_author_from_title(result["book"])

        # Clean up and validate
        if not result["author"] or result["author"] == "Unknown":
            result["author"] = (
                self._extract_author_from_title(result["book"]) or "Unknown"
            )

        # Clean series name
        if result["series"] and self._looks_like_book_title(result["series"]):
            result["series"] = ""

        return result

    def _looks_like_author(self, name: str) -> bool:
        """Check if a directory name looks like an author name"""
        if not name:
            return False

        # Skip common non-author directory names
        skip_names = {
            "audiobooks",
            "downloads",
            "books",
            "audio",
            "data",
            "user",
            "mnt",
            "tmp",
            "home",
            "var",
            "opt",
            "media",
            "library",
            "collection",
            "series",
        }

        if name.lower() in skip_names:
            return False

        # Author names typically have 1-4 words, reasonable length
        words = name.split()
        if len(words) > 4 or len(name) > 50:
            return False

        # Check for patterns that indicate it's not an author
        lower_name = name.lower()
        bad_patterns = [
            "vol_",
            "volume",
            "book",
            "part",
            "chapter",
            "collection",
            "unabridged",
            "audiobook",
            "litrpg",
            "saga",
            "series",
        ]

        if any(pattern in lower_name for pattern in bad_patterns):
            return False

        # Check for excessive special characters/numbers
        special_count = sum(
            1 for c in name if not (c.isalnum() or c.isspace() or c in ".-'")
        )
        if special_count > 2:
            return False

        return True

    def _looks_like_book_title(self, name: str) -> bool:
        """Check if a name looks more like a book title than a series name"""
        if not name:
            return False

        lower_name = name.lower()
        book_indicators = [
            "vol_",
            "volume",
            "book",
            "part",
            "chapter",
            "episode",
            "unabridged",
            "[",
            "]",
            "{",
            "}",
            "audiobook",
        ]

        return any(indicator in lower_name for indicator in book_indicators)

    def _extract_author_from_title(self, title: str) -> str:
        """Try to extract author name from book title using common patterns"""
        if not title:
            return "Unknown"

        # Remove common suffixes and metadata
        title = re.sub(r"\[.*?\]", "", title)  # Remove [metadata]
        title = re.sub(r"\{.*?\}", "", title)  # Remove {metadata}
        title = re.sub(r"\(.*?\)", "", title)  # Remove (metadata)
        title = title.strip()

        # Pattern: "Author - Title" or "Author: Title"
        for separator in [" - ", ": ", " – ", " — "]:
            if separator in title:
                parts = title.split(separator, 1)
                potential_author = parts[0].strip()
                if self._looks_like_author(potential_author):
                    return potential_author

        # Pattern: "Title by Author"
        by_match = re.search(r"\bby\s+([^,]+)", title, re.IGNORECASE)
        if by_match:
            potential_author = by_match.group(1).strip()
            if self._looks_like_author(potential_author):
                return potential_author

        # As last resort, try first few words
        words = title.split()
        if len(words) >= 2:
            for i in range(1, min(3, len(words))):
                potential_author = " ".join(words[:i])
                if (
                    self._looks_like_author(potential_author)
                    and len(potential_author.split()) <= 3
                ):
                    return potential_author

        return "Unknown"

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
            self.conn.execute(
                """
                INSERT OR REPLACE INTO items 
                (path, author, series, book, asin, mtime, size, file_count, has_m4b, has_mp3)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    str(path),
                    meta["author"],
                    meta["series"],
                    meta["book"],
                    meta["asin"],
                    mtime,
                    total_size,
                    file_count,
                    bool(m4b_files),
                    bool(mp3_files),
                ),
            )

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
            cursor = self.conn.execute(
                """
                SELECT * FROM items 
                ORDER BY mtime DESC 
                LIMIT ?
            """,
                (limit,),
            )
        else:
            # FTS5 search
            cursor = self.conn.execute(
                """
                SELECT i.* FROM items i
                JOIN items_fts f ON i.id = f.rowid
                WHERE items_fts MATCH ?
                ORDER BY i.mtime DESC
                LIMIT ?
            """,
                (query, limit),
            )

        return [dict(row) for row in cursor.fetchall()]

    def get_stats(self) -> Dict[str, int]:
        """Get catalog statistics"""
        cursor = self.conn.execute(
            """
            SELECT 
                COUNT(*) as total,
                COUNT(DISTINCT author) as authors,
                COUNT(DISTINCT series) as series,
                SUM(size) as total_size,
                SUM(file_count) as total_files
            FROM items
        """
        )
        return dict(cursor.fetchone())

    def rebuild_indexes(self, verbose: bool = False) -> Dict[str, Any]:
        """Rebuild all database indexes for optimal performance"""
        if verbose:
            print(f"{Sty.YELLOW}Rebuilding database indexes...{Sty.RESET}")

        start_time = perf_counter()

        # Rebuild FTS5 index
        if verbose:
            print("  Rebuilding FTS5 index...")
        self.conn.execute("INSERT INTO items_fts(items_fts) VALUES('rebuild')")

        # Rebuild regular indexes
        if verbose:
            print("  Rebuilding regular indexes...")
        self.conn.execute("REINDEX idx_mtime")
        self.conn.execute("REINDEX idx_path")

        # Analyze for query optimization
        if verbose:
            print("  Analyzing tables...")
        self.conn.execute("ANALYZE items")
        self.conn.execute("ANALYZE items_fts")

        self.conn.commit()

        elapsed = perf_counter() - start_time
        if verbose:
            print(f"{Sty.GREEN}✅ Indexes rebuilt in {elapsed:.2f}s{Sty.RESET}")

        return {"elapsed": elapsed}

    def clean_orphaned_entries(self, verbose: bool = False) -> Dict[str, int]:
        """Remove entries for audiobooks that no longer exist on disk"""
        if verbose:
            print(f"{Sty.YELLOW}Cleaning orphaned catalog entries...{Sty.RESET}")

        cursor = self.conn.execute("SELECT id, path FROM items")
        orphaned = []

        for row in cursor:
            if not Path(row["path"]).exists():
                orphaned.append(row["id"])

        if not orphaned:
            if verbose:
                print(f"{Sty.GREEN}✅ No orphaned entries found{Sty.RESET}")
            return {"removed": 0, "checked": len(list(cursor))}

        # Remove orphaned entries
        placeholders = ",".join("?" * len(orphaned))
        self.conn.execute(f"DELETE FROM items WHERE id IN ({placeholders})", orphaned)
        self.conn.commit()

        if verbose:
            print(f"{Sty.GREEN}✅ Removed {len(orphaned)} orphaned entries{Sty.RESET}")

        return {"removed": len(orphaned), "checked": len(list(cursor))}

    def optimize_database(self, verbose: bool = False) -> Dict[str, Any]:
        """Run database optimization routines"""
        if verbose:
            print(f"{Sty.YELLOW}Optimizing database...{Sty.RESET}")

        start_time = perf_counter()

        # Get initial stats
        initial_stats = self.get_db_stats()

        # Clean orphaned entries
        clean_stats = self.clean_orphaned_entries(verbose)

        # Rebuild indexes
        rebuild_stats = self.rebuild_indexes(verbose)

        # Vacuum to reclaim space
        if verbose:
            print("  Vacuuming database...")
        self.conn.execute("VACUUM")

        # Final stats
        final_stats = self.get_db_stats()

        elapsed = perf_counter() - start_time

        if verbose:
            print(f"{Sty.GREEN}✅ Database optimized in {elapsed:.2f}s{Sty.RESET}")

        return {
            "elapsed": elapsed,
            "initial_size": initial_stats.get("db_size", 0),
            "final_size": final_stats.get("db_size", 0),
            "space_saved": initial_stats.get("db_size", 0)
            - final_stats.get("db_size", 0),
            "orphaned_removed": clean_stats.get("removed", 0),
        }

    def get_db_stats(self) -> Dict[str, Any]:
        """Get detailed database statistics"""
        stats = {}

        # Database file size
        if DB_FILE.exists():
            stats["db_size"] = DB_FILE.stat().st_size

        # Table statistics
        cursor = self.conn.execute(
            """
            SELECT 
                'items' as table_name,
                COUNT(*) as row_count
            FROM items
            UNION ALL
            SELECT 
                'items_fts' as table_name,
                COUNT(*) as row_count
            FROM items_fts
        """
        )

        for row in cursor:
            stats[f"{row['table_name']}_rows"] = row["row_count"]

        # Index information
        cursor = self.conn.execute(
            """
            SELECT name, sql 
            FROM sqlite_master 
            WHERE type='index' AND name LIKE 'idx_%'
        """
        )

        stats["indexes"] = [dict(row) for row in cursor]

        # FTS5 statistics
        try:
            cursor = self.conn.execute("SELECT * FROM items_fts('integrity-check')")
            stats["fts_integrity"] = len(list(cursor)) == 0  # Empty result means OK
        except sqlite3.OperationalError:
            # Fallback: check if FTS table has same number of rows as items table
            cursor = self.conn.execute("SELECT COUNT(*) FROM items")
            items_count = cursor.fetchone()[0]
            cursor = self.conn.execute("SELECT COUNT(*) FROM items_fts")
            fts_count = cursor.fetchone()[0]
            stats["fts_integrity"] = items_count == fts_count

        return stats

    def get_index_stats(self) -> Dict[str, Any]:
        """Get index usage and performance statistics"""
        stats = {}

        # Index sizes (approximate)
        cursor = self.conn.execute(
            """
            SELECT 
                name,
                'index' as type
            FROM sqlite_master 
            WHERE type='index'
            UNION ALL
            SELECT 
                name,
                'table' as type
            FROM sqlite_master 
            WHERE type='table'
        """
        )

        stats["objects"] = [dict(row) for row in cursor]

        # Query performance hints
        cursor = self.conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM items WHERE mtime > ? ORDER BY mtime DESC",
            (0,),
        )
        stats["query_plan_mtime"] = [dict(row) for row in cursor]

        cursor = self.conn.execute(
            "EXPLAIN QUERY PLAN SELECT * FROM items WHERE path LIKE ?", ("%",)
        )
        stats["query_plan_path"] = [dict(row) for row in cursor]

        return stats

    def vacuum_database(self, verbose: bool = False) -> Dict[str, int]:
        """Reclaim unused database space"""
        if verbose:
            print(f"{Sty.YELLOW}Vacuuming database...{Sty.RESET}")

        start_size = DB_FILE.stat().st_size if DB_FILE.exists() else 0

        self.conn.execute("VACUUM")

        end_size = DB_FILE.stat().st_size if DB_FILE.exists() else 0
        space_saved = start_size - end_size

        if verbose:
            print(
                f"{Sty.GREEN}✅ Reclaimed {space_saved / (1024*1024):.1f} MB{Sty.RESET}"
            )

        return {"space_saved": space_saved, "final_size": end_size}

    def verify_integrity(self, verbose: bool = False) -> Dict[str, Any]:
        """Verify database integrity and FTS5 consistency"""
        if verbose:
            print(f"{Sty.YELLOW}Verifying database integrity...{Sty.RESET}")

        results = {}

        # SQLite integrity check
        cursor = self.conn.execute("PRAGMA integrity_check")
        integrity_result = list(cursor)
        results["sqlite_integrity"] = integrity_result[0][0] == "ok"

        # FTS5 integrity check
        try:
            cursor = self.conn.execute("SELECT * FROM items_fts('integrity-check')")
            fts_issues = list(cursor)
            results["fts_integrity"] = len(fts_issues) == 0
        except sqlite3.OperationalError:
            # Fallback: check if FTS table has same number of rows as items table
            cursor = self.conn.execute("SELECT COUNT(*) FROM items")
            items_count = cursor.fetchone()[0]
            cursor = self.conn.execute("SELECT COUNT(*) FROM items_fts")
            fts_count = cursor.fetchone()[0]
            results["fts_integrity"] = items_count == fts_count
        except Exception as e:
            results["fts_integrity"] = False
            if verbose:
                print(f"{Sty.RED}FTS integrity check error: {e}{Sty.RESET}")

        # Check for orphaned FTS entries
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) as orphaned_fts
            FROM items_fts 
            WHERE rowid NOT IN (SELECT id FROM items)
        """
        )
        results["orphaned_fts_count"] = cursor.fetchone()[0]

        # Check for missing FTS entries
        cursor = self.conn.execute(
            """
            SELECT COUNT(*) as missing_fts
            FROM items 
            WHERE id NOT IN (SELECT rowid FROM items_fts)
        """
        )
        results["missing_fts_count"] = cursor.fetchone()[0]

        if verbose:
            status = (
                "✅ OK"
                if all(v is not False for v in results.values() if v is not None)
                else "❌ ISSUES FOUND"
            )
            print(
                f"{Sty.GREEN if all(v is not False for v in results.values() if v is not None) else Sty.RED}{status}{Sty.RESET}"
            )

        return results

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
        "recent_sources": [],
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
        Path.home() / "Downloads",
    ]

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

    if choice.lower() == "search":
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
            print(
                f"{Sty.GREEN}{i:3d}{Sty.RESET}) {author} ({book_count} book{'s' if book_count > 1 else ''})"
            )

        nav_options = []
        if current_page > 0:
            nav_options.append("'p' = previous")
        if end < len(authors):
            nav_options.append("'n' = next")
        nav_options.append("number = select")
        nav_options.append("'q' = quit")

        print(f"\n{Sty.YELLOW}{' | '.join(nav_options)}:{Sty.RESET}")
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
            print(f"{Sty.YELLOW}Invalid selection{Sty.RESET}")

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

    print(f"\n{Sty.CYAN}📚 {selected_author}{Sty.RESET}")

    all_selectable = []

    # Show series first
    if series_groups:
        print(f"\n{Sty.BOLD}Series:{Sty.RESET}")
        for series in sorted(series_groups.keys()):
            books = sorted(series_groups[series], key=lambda x: x.get("book", ""))
            print(f"\n  {Sty.MAGENTA}{series}{Sty.RESET} ({len(books)} books)")
            for book in books:
                all_selectable.append(book)
                idx = len(all_selectable)
                size_mb = book.get("size", 0) / (1024 * 1024)
                indicator = "📘" if book.get("has_m4b") else "🎵"
                print(
                    f"    {Sty.GREEN}{idx:3d}{Sty.RESET}) {book['book']} {indicator} ({size_mb:.0f}MB)"
                )

    # Show standalone books
    if standalone:
        print(f"\n{Sty.BOLD}Standalone:{Sty.RESET}")
        for book in sorted(standalone, key=lambda x: x.get("book", "")):
            all_selectable.append(book)
            idx = len(all_selectable)
            size_mb = book.get("size", 0) / (1024 * 1024)
            indicator = "📘" if book.get("has_m4b") else "🎵"
            print(
                f"  {Sty.GREEN}{idx:3d}{Sty.RESET}) {book['book']} {indicator} ({size_mb:.0f}MB)"
            )

    # Selection
    print(
        f"\n{Sty.YELLOW}Enter numbers (space-separated), 'all', or 'q' to quit:{Sty.RESET}"
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


def text_search_browser(catalog: AudiobookCatalog) -> List[str]:
    """Enhanced text search browser with autocomplete and history"""
    print(f"\n{Sty.CYAN}🔍 ENHANCED TEXT SEARCH{Sty.RESET}")

    # Load search history
    history_file = Path.home() / ".cache" / "hardbound" / "search_history.txt"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    search_history = []
    if history_file.exists():
        try:
            with open(history_file, 'r', encoding='utf-8') as f:
                search_history = [line.strip() for line in f.readlines() if line.strip()]
        except Exception:
            pass  # Ignore history loading errors

    # Get autocomplete suggestions from catalog
    autocomplete_suggestions = _get_autocomplete_suggestions(catalog)

    print("\nEnter search terms (author, title, series):")
    print(f"{Sty.DIM}💡 Type a few letters and press Tab for suggestions{Sty.RESET}")
    print(f"{Sty.DIM}💡 Press ↑/↓ for search history{Sty.RESET}")

    query = _enhanced_input("Search: ", autocomplete_suggestions, search_history)

    if not query:
        return []

    # Save to history
    if query not in search_history:
        search_history.insert(0, query)
        search_history = search_history[:50]  # Keep last 50 searches
        try:
            with open(history_file, 'w', encoding='utf-8') as f:
                f.write('\n'.join(search_history))
        except Exception:
            pass  # Ignore history saving errors

    results = catalog.search(query, limit=100)

    if not results:
        print(f"{Sty.YELLOW}No results found{Sty.RESET}")
        print(f"{Sty.DIM}💡 Try different keywords or check spelling{Sty.RESET}")
        return []

    print(f"\n{Sty.GREEN}Found {len(results)} result(s):{Sty.RESET}\n")

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
            print(
                f"{Sty.GREEN}{i:3d}{Sty.RESET}) {display} {indicator} ({size_mb:.0f}MB)"
            )

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


def _get_autocomplete_suggestions(catalog: AudiobookCatalog) -> List[str]:
    """Get autocomplete suggestions from catalog"""
    suggestions = set()

    # Get some recent/popular authors and series
    try:
        cursor = catalog.conn.execute("""
            SELECT author, series, book FROM items
            WHERE author != 'Unknown'
            ORDER BY mtime DESC
            LIMIT 100
        """)

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
                    suggestions.add(' '.join(words))

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
        print(f"{Sty.YELLOW}fzf not found. Using hierarchical browser.{Sty.RESET}")

        # Create a temporary catalog-like interface
        class TempCatalog:
            def search(self, query, limit):
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

        temp_catalog = AudiobookCatalog()
        try:
            return hierarchical_browser(temp_catalog)
        finally:
            temp_catalog.close()

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
        print(f"{Sty.RED}fzf error: {e}{Sty.RESET}")
        return fallback_picker(candidates, multi)


def fallback_picker(candidates: List[Dict], multi: bool) -> List[str]:
    """Fallback picker when fzf is not available"""
    if not candidates:
        return []

    print(f"\n{Sty.CYAN}Select audiobook(s):{Sty.RESET}")
    for i, r in enumerate(candidates[:30], 1):
        author = r.get("author", "—")
        book = r.get("book", "—")
        print(f"{i:3d}) {author} - {book}")
        print(f"      {Sty.DIM}{r['path']}{Sty.RESET}")

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


def index_command(args):
    """Index audiobook directories"""
    catalog = AudiobookCatalog()

    # Default search roots if none specified
    if not args.roots:
        args.roots = ["/mnt/user/data/audio/audiobooks", Path.home() / "audiobooks"]

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


def manage_command(args):
    """Database index management"""
    catalog = AudiobookCatalog()
    verbose = not args.quiet

    try:
        if args.action == "rebuild":
            result = catalog.rebuild_indexes(verbose)
            if verbose:
                print(f"{Sty.GREEN}✅ Indexes rebuilt successfully{Sty.RESET}")

        elif args.action == "clean":
            result = catalog.clean_orphaned_entries(verbose)
            if verbose:
                print(
                    f"{Sty.GREEN}✅ Cleaned {result['removed']} orphaned entries{Sty.RESET}"
                )

        elif args.action == "optimize":
            result = catalog.optimize_database(verbose)
            if verbose:
                print(f"{Sty.GREEN}✅ Database optimized{Sty.RESET}")
                print(f"  Space saved: {result['space_saved'] / (1024*1024):.1f} MB")
                print(f"  Time taken: {result['elapsed']:.2f}s")

        elif args.action == "stats":
            db_stats = catalog.get_db_stats()
            idx_stats = catalog.get_index_stats()

            print(f"{Sty.CYAN}Database Statistics:{Sty.RESET}")
            print(f"  Database size: {db_stats.get('db_size', 0) / (1024*1024):.1f} MB")
            print(f"  Items table: {db_stats.get('items_rows', 0)} rows")
            print(f"  FTS table: {db_stats.get('items_fts_rows', 0)} rows")
            print(f"  Indexes: {len(db_stats.get('indexes', []))}")

            if db_stats.get("fts_integrity") is False:
                print(f"{Sty.YELLOW}  ⚠️  FTS integrity issues detected{Sty.RESET}")

        elif args.action == "vacuum":
            result = catalog.vacuum_database(verbose)
            if verbose:
                print(f"{Sty.GREEN}✅ Database vacuumed{Sty.RESET}")
                print(f"  Space saved: {result['space_saved'] / (1024*1024):.1f} MB")

        elif args.action == "verify":
            result = catalog.verify_integrity(verbose)

            print(f"{Sty.CYAN}Integrity Check Results:{Sty.RESET}")
            print(
                f"  SQLite integrity: {'✅ OK' if result['sqlite_integrity'] else '❌ FAILED'}"
            )
            print(
                f"  FTS integrity: {'✅ OK' if result['fts_integrity'] else '❌ FAILED'}"
            )
            print(f"  Orphaned FTS entries: {result['orphaned_fts_count']}")
            print(f"  Missing FTS entries: {result['missing_fts_count']}")

            if not all(v is not False for v in result.values() if v is not None):
                print(
                    f"{Sty.YELLOW}⚠️  Issues found - consider running 'optimize'{Sty.RESET}"
                )

    except Exception as e:
        print(f"{Sty.RED}❌ Error during {args.action}: {e}{Sty.RESET}")
        if verbose:
            import traceback

            traceback.print_exc()

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
            author = r.get("author", "—")
            series = r.get("series", "")
            book = r.get("book", "—")

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

        print(
            f"\n{Sty.CYAN}Linking {len(selected_paths)} audiobook(s) to {args.dst_root}{Sty.RESET}"
        )

        for path_str in selected_paths:
            src = Path(path_str)
            base_name = zero_pad_vol(src.name) if zero_pad else src.name
            dst = args.dst_root / base_name

            print(f"\n{Sty.BOLD}{src.name}{Sty.RESET}")

            if args.dry_run:
                plan_and_link(
                    src, dst, base_name, also_cover, zero_pad, False, True, stats
                )
            else:
                plan_and_link(
                    src, dst, base_name, also_cover, zero_pad, False, False, stats
                )

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
        print(
            f"""
{Sty.CYAN}╔══════════════════════════════════════════════╗
║      WELCOME TO HARDBOUND - FIRST RUN        ║
╚══════════════════════════════════════════════╝{Sty.RESET}

Let's set up your default paths:
"""
        )

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
        print(
            f"""
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

"""
        )
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
            elif choice == "7" or choice.lower() in ["q", "quit", "exit"]:
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
    print(
        f"  {Sty.GREEN}1{Sty.RESET}) Browse by author (recommended for large libraries)"
    )
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
    default_dst = str(config.get("torrent_path", "")).strip()

    print(f"\n{Sty.BOLD}Destination root:{Sty.RESET}")
    if default_dst:
        print(f"Default: {default_dst}")
        dst_input = input("Path (Enter for default): ").strip()
        if dst_input:
            dst_root = Path(dst_input)
        else:
            dst_root = Path(default_dst)
    else:
        dst_input = input("Path: ").strip()
        if not dst_input:
            catalog.close()
            return
        dst_root = Path(dst_input)

    # Preview and confirm
    print(
        f"\n{Sty.YELLOW}Will link {len(selected_paths)} audiobook(s) to {dst_root}{Sty.RESET}"
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
        return s[: max(0, limit - 1)] + "…"
    keep = (limit - 1) // 2
    return s[:keep] + "… " + s[-(limit - keep - 2) :]


def banner(title: str, mode: str):
    w = term_width()
    line = "─" * max(4, w - 2)
    label = f"{Sty.BOLD}{Sty.CYAN} {title} {Sty.RESET}"
    mode_tag = (
        f"{Sty.YELLOW}[DRY-RUN]{Sty.RESET}"
        if mode == "dry"
        else f"{Sty.GREEN}[COMMIT]{Sty.RESET}"
    )
    print(f"┌{line}┐")
    print(f"│ {label}{mode_tag}".ljust(w - 1) + "│")
    print(f"└{line}┘")


def section(title: str):
    w = term_width()
    line = "─" * max(4, w - 2)
    print(f"{Sty.MAGENTA}{title}{Sty.RESET}")
    print(line)


def row(
    status_icon: str, status_color: str, kind: str, src: Path, dst: Path, dry: bool
):
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


def clean_base_name(name: str) -> str:
    """Remove user tags from base name for cleaner destination names"""
    # Remove common user tags like [H2OKing], [UserName], etc.
    # Pattern: [anything] at the end of the name
    import re

    cleaned = re.sub(r"\s*\[[^\]]+\]\s*$", "", name)
    return cleaned.strip()


def choose_base_outputs(dest_dir: Path, base_name: str):
    """Return canonical dest paths for common types."""
    # Remove user tags from file names while keeping them in folder names
    clean_file_base = clean_base_name(base_name)

    return {
        "cue": dest_dir / f"{clean_file_base}.cue",
        "jpg": dest_dir / f"{clean_file_base}.jpg",
        "m4b": dest_dir / f"{clean_file_base}.m4b",
        "mp3": dest_dir / f"{clean_file_base}.mp3",
        "flac": dest_dir / f"{clean_file_base}.flac",
        "pdf": dest_dir / f"{clean_file_base}.pdf",
        "txt": dest_dir / f"{clean_file_base}.txt",
        "nfo": dest_dir / f"{clean_file_base}.nfo",
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


def plan_and_link(
    src_dir: Path,
    dst_dir: Path,
    base_name: str,
    also_cover: bool,
    zero_pad: bool,
    force: bool,
    dry_run: bool,
    stats: dict,
):
    if zero_pad:
        base_name = zero_pad_vol(base_name)

    ensure_dir(dst_dir, dry_run, stats)
    outputs = choose_base_outputs(dst_dir, base_name)

    # Gather source files
    try:
        files = list(src_dir.iterdir())
    except FileNotFoundError:
        print(
            f"{Sty.RED}[ERR] Source directory not found: {src_dir}{Sty.RESET}",
            file=sys.stderr,
        )
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
                        (
                            p
                            for p, n in normalized
                            if normalize_weird_ext(n)
                            .lower()
                            .endswith((".jpg", ".jpeg", ".png"))
                        ),
                        None,
                    )
                do_link(
                    src_img if src_img is not None else named_cover,
                    plain_cover,
                    force=force,
                    dry_run=dry_run,
                    stats=stats,
                )
        else:
            row("🚫", Sty.GREY, "excl.", named_cover, plain_cover, dry_run)


def run_batch(batch_file: Path, also_cover, zero_pad, force, dry_run):
    stats = {
        "linked": 0,
        "replaced": 0,
        "already": 0,
        "exists": 0,
        "excluded": 0,
        "skipped": 0,
        "errors": 0,
    }
    with batch_file.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                src_s, dst_s = [x.strip() for x in line.split("|", 1)]
            except ValueError:
                print(
                    f"{Sty.YELLOW}[WARN] bad line (expected 'SRC|DST'): {line}{Sty.RESET}"
                )
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
    print(
        f"""
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

{Sty.YELLOW}Press Enter to continue...{Sty.RESET}"""
    )
    input()


def browse_directory_tree():
    """Interactive directory tree browser (legacy mode)"""
    current = Path.cwd()

    while True:
        print(f"\n{Sty.CYAN}📁 Current: {current}{Sty.RESET}")

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
            print(f"{Sty.RED}Permission denied{Sty.RESET}")

        for i, (display, path) in enumerate(items[:20], 1):
            print(f"  {i:2d}) {display}")

        if len(items) > 20:
            print(f"  ... and {len(items) - 20} more")

        print(
            f"\n{Sty.YELLOW}Enter number to navigate, 'select' to choose current, 'back' to go up:{Sty.RESET}"
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


def folder_batch_wizard():
    """Legacy folder batch wizard - kept for compatibility"""
    print(
        f"\n{Sty.YELLOW}Note: For large libraries, use 'Search and link' instead{Sty.RESET}"
    )
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


def recent_downloads_scanner():
    """Find and link recently downloaded audiobooks"""
    print(f"\n{Sty.CYAN}🔍 RECENT DOWNLOADS SCANNER{Sty.RESET}")

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

    print(f"\n{Sty.YELLOW}Scanning filesystem...{Sty.RESET}")
    recent = find_recent_audiobooks(hours=hours)

    if not recent:
        print(f"{Sty.YELLOW}No recent audiobooks found{Sty.RESET}")
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

    print(
        f"\n{Sty.YELLOW}Link {len(selected_paths)} audiobook(s)? [y/N]: {Sty.RESET}",
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
        print(f"\n{Sty.CYAN}Processing: {src.name}{Sty.RESET}")
        plan_and_link(
            src, dst_dir, base_name, also_cover, zero_pad, False, False, stats
        )

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
            return False
    except FileNotFoundError:
        pass  # Destination doesn't exist yet, that's ok

    # Check for Unraid user/disk mixing
    src_str, dst_str = str(src), str(dst)
    if ("/mnt/user/" in src_str and "/mnt/disk" in dst_str) or (
        "/mnt/disk" in src_str and "/mnt/user/" in dst_str
    ):
        print(f"{Sty.RED}❌ Unraid user/disk mixing detected{Sty.RESET}")
        print(f"   Hardlinks won't work between /mnt/user and /mnt/disk paths")
        return False

    return True


def update_catalog_wizard():
    """Update catalog index wizard"""
    print(f"\n{Sty.CYAN}📊 UPDATE CATALOG INDEX{Sty.RESET}")
    print("This will rebuild the search index for faster queries.")

    confirm = input("Continue? [y/N]: ").strip().lower()
    if confirm not in ["y", "yes"]:
        return

    catalog = AudiobookCatalog()
    try:
        # Rebuild the FTS index
        catalog.conn.executescript(
            """
            DROP TABLE IF EXISTS items_fts;
            CREATE VIRTUAL TABLE items_fts USING fts5(
                author, series, book, asin,
                content='items',
                content_rowid='id'
            );
            
            INSERT INTO items_fts(rowid, author, series, book, asin)
            SELECT id, author, series, book, asin FROM items;
        """
        )
        catalog.conn.commit()
        print(f"{Sty.GREEN}✅ Catalog index updated successfully{Sty.RESET}")
    except Exception as e:
        print(f"{Sty.RED}❌ Error updating catalog: {e}{Sty.RESET}")
    finally:
        catalog.close()


def settings_menu():
    """Settings and preferences menu"""
    print(f"\n{Sty.CYAN}⚙️  SETTINGS & PREFERENCES{Sty.RESET}")

    config = load_config()

    print(f"\nCurrent settings:")
    print(f"  Library path: {config.get('library_path', 'Not set')}")
    print(f"  Torrent path: {config.get('torrent_path', 'Not set')}")
    print(f"  Zero pad volumes: {config.get('zero_pad', True)}")
    print(f"  Also create cover.jpg: {config.get('also_cover', False)}")

    print(f"\n{Sty.YELLOW}Settings menu not yet implemented{Sty.RESET}")
    print(f"{Sty.YELLOW}Use config.json file directly for now{Sty.RESET}")

    input(f"\n{Sty.YELLOW}Press Enter to continue...{Sty.RESET}")
