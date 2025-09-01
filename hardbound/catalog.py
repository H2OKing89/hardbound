#!/usr/bin/env python3
"""
Audiobook catalog and database management
"""
import re
import sqlite3
from pathlib import Path
from time import perf_counter
from typing import Any, Dict, List, Optional
from rich.console import Console

from .display import Sty

# Global console instance
console = Console()

# Database paths
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

    def index_directory(self, root: Path, verbose: bool = False, progress_callback=None):
        """Index or update a directory tree"""
        if verbose:
            console.print(f"[yellow]Indexing {root}...[/yellow]")

        count = 0
        # First pass: count total directories to process
        total_dirs = 0
        for path in root.rglob("*"):
            if path.is_dir():
                m4b_files = list(path.glob("*.m4b"))
                mp3_files = list(path.glob("*.mp3"))
                if m4b_files or mp3_files:
                    total_dirs += 1

        if progress_callback and total_dirs > 0:
            progress_callback.start()
            progress_callback.total = total_dirs

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
            if progress_callback:
                progress_callback.update(f"Indexed {count}/{total_dirs} audiobooks")
            elif verbose and count % 100 == 0:
                print(f"  Indexed {count} audiobooks...")

        self.conn.commit()

        if progress_callback:
            progress_callback.done(f"Indexed {count} audiobooks")
        elif verbose:
            console.print(f"[green]✅ Indexed {count} audiobooks[/green]")

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
            console.print(f"[yellow]Rebuilding database indexes...[/yellow]")

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
            console.print(f"[green]✅ Indexes rebuilt in {elapsed:.2f}s[/green]")

        return {"elapsed": elapsed}

    def clean_orphaned_entries(self, verbose: bool = False) -> Dict[str, int]:
        """Remove entries for audiobooks that no longer exist on disk"""
        if verbose:
            console.print(f"[yellow]Cleaning orphaned catalog entries...[/yellow]")

        cursor = self.conn.execute("SELECT id, path FROM items")
        orphaned = []

        for row in cursor:
            if not Path(row["path"]).exists():
                orphaned.append(row["id"])

        if not orphaned:
            if verbose:
                console.print(f"[green]✅ No orphaned entries found[/green]")
            return {"removed": 0, "checked": len(list(cursor))}

        # Remove orphaned entries
        placeholders = ",".join("?" * len(orphaned))
        self.conn.execute(f"DELETE FROM items WHERE id IN ({placeholders})", orphaned)
        self.conn.commit()

        if verbose:
            console.print(f"[green]✅ Removed {len(orphaned)} orphaned entries[/green]")

        return {"removed": len(orphaned), "checked": len(list(cursor))}

    def optimize_database(self, verbose: bool = False) -> Dict[str, Any]:
        """Run database optimization routines"""
        if verbose:
            console.print(f"[yellow]Optimizing database...[/yellow]")

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
            console.print(f"[green]✅ Database optimized in {elapsed:.2f}s[/green]")

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
            console.print(f"[yellow]Vacuuming database...[/yellow]")

        start_size = DB_FILE.stat().st_size if DB_FILE.exists() else 0

        self.conn.execute("VACUUM")

        end_size = DB_FILE.stat().st_size if DB_FILE.exists() else 0
        space_saved = start_size - end_size

        if verbose:
            console.print(
                f"[green]✅ Reclaimed {space_saved / (1024*1024):.1f} MB[/green]"
            )

        return {"space_saved": space_saved, "final_size": end_size}

    def verify_integrity(self, verbose: bool = False) -> Dict[str, Any]:
        """Verify database integrity and FTS5 consistency"""
        if verbose:
            console.print(f"[yellow]Verifying database integrity...[/yellow]")

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
            color = "[green]" if all(v is not False for v in results.values() if v is not None) else "[red]"
            console.print(f"{color}{status}[/{color}]")

        return results

    def close(self):
        self.conn.close()
