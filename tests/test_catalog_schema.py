#!/usr/bin/env python3
"""
Tests for AudiobookCatalog - Database Schema and Initialization

Phase 2.1: Database Schema, FTS5 setup, Triggers, Indexes
Part of the Hardbound test improvement plan (Phase 2: Catalog)
"""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from hardbound.catalog import AudiobookCatalog, DB_FILE


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def temp_db_path(tmp_path: Path) -> Path:
    """Provide a temporary database path for testing"""
    return tmp_path / "test_catalog.db"


@pytest.fixture
def catalog_with_temp_db(temp_db_path: Path):
    """Create a catalog instance with a temporary database"""
    with patch("hardbound.catalog.DB_FILE", temp_db_path):
        catalog = AudiobookCatalog()
        yield catalog
        catalog.close()
        # Cleanup
        if temp_db_path.exists():
            temp_db_path.unlink()


# ============================================================================
# PHASE 2.1: DATABASE SCHEMA & INITIALIZATION
# ============================================================================


@pytest.mark.unit
class TestDatabaseInitialization:
    """Test database schema creation and initialization"""

    def test_database_file_created(self, temp_db_path: Path) -> None:
        """Test that database file is created on initialization"""
        assert not temp_db_path.exists()

        with patch("hardbound.catalog.DB_FILE", temp_db_path):
            catalog = AudiobookCatalog()
            assert temp_db_path.exists()
            assert temp_db_path.is_file()
            catalog.close()

    def test_items_table_schema(self, catalog_with_temp_db: AudiobookCatalog) -> None:
        """Test that items table has correct schema"""
        cursor = catalog_with_temp_db.conn.execute("PRAGMA table_info(items)")
        columns = {row[1]: row[2] for row in cursor.fetchall()}

        # Required columns
        assert "id" in columns
        assert "author" in columns
        assert "series" in columns
        assert "book" in columns
        assert "path" in columns
        assert "asin" in columns
        assert "mtime" in columns
        assert "size" in columns
        assert "file_count" in columns
        assert "has_m4b" in columns
        assert "has_mp3" in columns

        # Verify types
        assert columns["id"] == "INTEGER"
        assert columns["author"] == "TEXT"
        assert columns["path"] == "TEXT"
        assert columns["mtime"] == "REAL"
        assert columns["size"] == "INTEGER"

    def test_items_table_constraints(
        self, catalog_with_temp_db: AudiobookCatalog
    ) -> None:
        """Test that items table has correct constraints"""
        cursor = catalog_with_temp_db.conn.execute("PRAGMA table_info(items)")
        columns = list(cursor.fetchall())

        # Check id is primary key
        id_col = next(col for col in columns if col[1] == "id")
        assert id_col[5] == 1  # pk column is 1 for primary key

        # Check path is unique (SQLite shows this in index list)
        cursor = catalog_with_temp_db.conn.execute("PRAGMA index_list(items)")
        indexes = list(cursor.fetchall())
        # There should be at least one unique index on path
        path_indexes = [idx for idx in indexes if "path" in idx[1].lower()]
        assert len(path_indexes) > 0

    def test_fts5_virtual_table_created(
        self, catalog_with_temp_db: AudiobookCatalog
    ) -> None:
        """Test that FTS5 virtual table is created"""
        cursor = catalog_with_temp_db.conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='items_fts'
        """
        )
        result = cursor.fetchone()
        assert result is not None
        assert result[0] == "items_fts"

    def test_fts5_table_columns(self, catalog_with_temp_db: AudiobookCatalog) -> None:
        """Test that FTS5 table has correct columns"""
        # FTS5 tables don't show up in PRAGMA table_info the same way
        # Test by trying to query the expected columns
        try:
            catalog_with_temp_db.conn.execute(
                """
                SELECT author, series, book, asin FROM items_fts LIMIT 0
            """
            )
            # If no exception, columns exist
            success = True
        except sqlite3.OperationalError:
            success = False

        assert success, "FTS5 table missing expected columns"

    def test_indexes_created(self, catalog_with_temp_db: AudiobookCatalog) -> None:
        """Test that required indexes are created"""
        cursor = catalog_with_temp_db.conn.execute("PRAGMA index_list(items)")
        indexes = {row[1] for row in cursor.fetchall()}

        # Check for specific indexes
        assert "idx_mtime" in indexes
        assert "idx_path" in indexes

    def test_index_on_mtime(self, catalog_with_temp_db: AudiobookCatalog) -> None:
        """Test that mtime index is configured correctly"""
        cursor = catalog_with_temp_db.conn.execute("PRAGMA index_info(idx_mtime)")
        index_cols = [row[2] for row in cursor.fetchall()]

        assert "mtime" in index_cols

    def test_index_on_path(self, catalog_with_temp_db: AudiobookCatalog) -> None:
        """Test that path index is configured correctly"""
        cursor = catalog_with_temp_db.conn.execute("PRAGMA index_info(idx_path)")
        index_cols = [row[2] for row in cursor.fetchall()]

        assert "path" in index_cols


@pytest.mark.unit
class TestFTS5Triggers:
    """Test FTS5 automatic synchronization triggers"""

    def test_insert_trigger_exists(self, catalog_with_temp_db: AudiobookCatalog) -> None:
        """Test that INSERT trigger is created"""
        cursor = catalog_with_temp_db.conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='trigger' AND name='items_ai'
        """
        )
        result = cursor.fetchone()
        assert result is not None

    def test_update_trigger_exists(self, catalog_with_temp_db: AudiobookCatalog) -> None:
        """Test that UPDATE trigger is created"""
        cursor = catalog_with_temp_db.conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='trigger' AND name='items_au'
        """
        )
        result = cursor.fetchone()
        assert result is not None

    def test_delete_trigger_exists(self, catalog_with_temp_db: AudiobookCatalog) -> None:
        """Test that DELETE trigger is created"""
        cursor = catalog_with_temp_db.conn.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type='trigger' AND name='items_ad'
        """
        )
        result = cursor.fetchone()
        assert result is not None

    def test_insert_trigger_syncs_to_fts(
        self, catalog_with_temp_db: AudiobookCatalog
    ) -> None:
        """Test that INSERT trigger automatically updates FTS table"""
        # Insert into main table
        catalog_with_temp_db.conn.execute(
            """
            INSERT INTO items (author, series, book, path, asin, mtime, size, file_count, has_m4b, has_mp3)
            VALUES ('Test Author', 'Test Series', 'Test Book', '/test/path', 'B0TEST123', 0, 0, 0, 1, 0)
        """
        )
        catalog_with_temp_db.conn.commit()

        # Check FTS table was updated
        cursor = catalog_with_temp_db.conn.execute(
            """
            SELECT author, series, book, asin FROM items_fts
            WHERE author = 'Test Author'
        """
        )
        result = cursor.fetchone()

        assert result is not None
        assert result[0] == "Test Author"
        assert result[1] == "Test Series"
        assert result[2] == "Test Book"
        assert result[3] == "B0TEST123"

    def test_update_trigger_syncs_to_fts(
        self, catalog_with_temp_db: AudiobookCatalog
    ) -> None:
        """Test that UPDATE trigger automatically updates FTS table"""
        # Insert initial data
        catalog_with_temp_db.conn.execute(
            """
            INSERT INTO items (author, series, book, path, asin, mtime, size, file_count, has_m4b, has_mp3)
            VALUES ('Old Author', 'Old Series', 'Old Book', '/test/path', 'B0OLD1234', 0, 0, 0, 1, 0)
        """
        )
        catalog_with_temp_db.conn.commit()

        # Update the record
        catalog_with_temp_db.conn.execute(
            """
            UPDATE items SET author = 'New Author', book = 'New Book'
            WHERE path = '/test/path'
        """
        )
        catalog_with_temp_db.conn.commit()

        # Check FTS table was updated
        cursor = catalog_with_temp_db.conn.execute(
            """
            SELECT author, book FROM items_fts
            WHERE rowid = (SELECT id FROM items WHERE path = '/test/path')
        """
        )
        result = cursor.fetchone()

        assert result is not None
        assert result[0] == "New Author"
        assert result[1] == "New Book"

    def test_delete_trigger_syncs_to_fts(
        self, catalog_with_temp_db: AudiobookCatalog
    ) -> None:
        """Test that DELETE trigger automatically removes from FTS table"""
        # Insert initial data
        catalog_with_temp_db.conn.execute(
            """
            INSERT INTO items (author, series, book, path, asin, mtime, size, file_count, has_m4b, has_mp3)
            VALUES ('Delete Author', 'Delete Series', 'Delete Book', '/delete/path', 'B0DEL1234', 0, 0, 0, 1, 0)
        """
        )
        catalog_with_temp_db.conn.commit()

        # Get the rowid before deletion
        cursor = catalog_with_temp_db.conn.execute(
            "SELECT id FROM items WHERE path = '/delete/path'"
        )
        item_id = cursor.fetchone()[0]

        # Delete the record
        catalog_with_temp_db.conn.execute(
            "DELETE FROM items WHERE path = '/delete/path'"
        )
        catalog_with_temp_db.conn.commit()

        # Check FTS table was updated
        cursor = catalog_with_temp_db.conn.execute(
            f"SELECT * FROM items_fts WHERE rowid = {item_id}"
        )
        result = cursor.fetchone()

        assert result is None, "FTS entry should be deleted"

    def test_trigger_maintains_consistency(
        self, catalog_with_temp_db: AudiobookCatalog
    ) -> None:
        """Test that triggers maintain consistency between tables"""
        # Insert multiple items
        for i in range(5):
            catalog_with_temp_db.conn.execute(
                """
                INSERT INTO items (author, series, book, path, asin, mtime, size, file_count, has_m4b, has_mp3)
                VALUES (?, ?, ?, ?, ?, 0, 0, 0, 1, 0)
            """,
                (f"Author {i}", f"Series {i}", f"Book {i}", f"/path/{i}", f"B0TST{i:04d}"),
            )
        catalog_with_temp_db.conn.commit()

        # Count items in both tables
        cursor = catalog_with_temp_db.conn.execute("SELECT COUNT(*) FROM items")
        items_count = cursor.fetchone()[0]

        cursor = catalog_with_temp_db.conn.execute("SELECT COUNT(*) FROM items_fts")
        fts_count = cursor.fetchone()[0]

        assert items_count == fts_count == 5


@pytest.mark.unit
class TestDatabaseConnectivity:
    """Test database connection and lifecycle"""

    def test_connection_row_factory(
        self, catalog_with_temp_db: AudiobookCatalog
    ) -> None:
        """Test that row_factory is set correctly for dict-like access"""
        # Insert test data
        catalog_with_temp_db.conn.execute(
            """
            INSERT INTO items (author, series, book, path, asin, mtime, size, file_count, has_m4b, has_mp3)
            VALUES ('Test', 'Test', 'Test', '/test', 'B0TEST123', 0, 0, 0, 1, 0)
        """
        )
        catalog_with_temp_db.conn.commit()

        # Query and check row_factory behavior
        cursor = catalog_with_temp_db.conn.execute("SELECT * FROM items LIMIT 1")
        row = cursor.fetchone()

        # Should be accessible by column name
        assert row["author"] == "Test"
        assert row["path"] == "/test"
        assert row["asin"] == "B0TEST123"

    def test_close_connection(self, temp_db_path: Path) -> None:
        """Test that connection can be closed properly"""
        with patch("hardbound.catalog.DB_FILE", temp_db_path):
            catalog = AudiobookCatalog()
            catalog.close()

            # After close, operations should fail
            with pytest.raises(sqlite3.ProgrammingError):
                catalog.conn.execute("SELECT 1")

    def test_multiple_instances_same_db(self, temp_db_path: Path) -> None:
        """Test that multiple catalog instances can access the same database"""
        with patch("hardbound.catalog.DB_FILE", temp_db_path):
            # First instance creates and writes
            catalog1 = AudiobookCatalog()
            catalog1.conn.execute(
                """
                INSERT INTO items (author, series, book, path, asin, mtime, size, file_count, has_m4b, has_mp3)
                VALUES ('Multi Test', 'Multi', 'Multi', '/multi', 'B0MULTI12', 0, 0, 0, 1, 0)
            """
            )
            catalog1.conn.commit()
            catalog1.close()

            # Second instance reads
            catalog2 = AudiobookCatalog()
            cursor = catalog2.conn.execute("SELECT author FROM items WHERE path = '/multi'")
            result = cursor.fetchone()

            assert result is not None
            assert result["author"] == "Multi Test"
            catalog2.close()


@pytest.mark.unit
class TestDatabaseLocationAndPermissions:
    """Test database file location and permission handling"""

    def test_database_in_script_directory(self) -> None:
        """Test that default database is in script directory, not user home"""
        # Default DB_FILE should be relative to the script, not ~/.config
        assert "hardbound" in str(DB_FILE)
        assert DB_FILE.name == "catalog.db"
        assert DB_FILE.is_absolute()

    def test_database_directory_creation(self, tmp_path: Path) -> None:
        """Test that parent directories are created if needed"""
        nested_path = tmp_path / "deep" / "nested" / "path" / "catalog.db"
        nested_dir = nested_path.parent

        with patch("hardbound.catalog.DB_FILE", nested_path), patch(
            "hardbound.catalog.DB_DIR", nested_dir
        ):
            catalog = AudiobookCatalog()
            assert nested_path.exists()
            assert nested_path.parent.exists()
            catalog.close()

    def test_database_writable(self, catalog_with_temp_db: AudiobookCatalog) -> None:
        """Test that database is writable (can perform INSERT)"""
        try:
            catalog_with_temp_db.conn.execute(
                """
                INSERT INTO items (author, series, book, path, asin, mtime, size, file_count, has_m4b, has_mp3)
                VALUES ('Write Test', 'Write', 'Write', '/write', 'B0WRITE12', 0, 0, 0, 1, 0)
            """
            )
            catalog_with_temp_db.conn.commit()
            success = True
        except sqlite3.OperationalError:
            success = False

        assert success, "Database should be writable"


@pytest.mark.unit
class TestDatabaseIntegrity:
    """Test database integrity and validation"""

    def test_integrity_check_on_new_db(
        self, catalog_with_temp_db: AudiobookCatalog
    ) -> None:
        """Test that newly created database passes integrity check"""
        cursor = catalog_with_temp_db.conn.execute("PRAGMA integrity_check")
        result = cursor.fetchone()

        assert result[0] == "ok", "Database integrity check should pass"

    def test_foreign_key_support(self, catalog_with_temp_db: AudiobookCatalog) -> None:
        """Test that foreign key support is available (even if not used)"""
        cursor = catalog_with_temp_db.conn.execute("PRAGMA foreign_keys")
        # Should return 0 or 1, not error
        result = cursor.fetchone()
        assert result is not None

    def test_fts5_extension_available(
        self, catalog_with_temp_db: AudiobookCatalog
    ) -> None:
        """Test that FTS5 extension is available in SQLite"""
        cursor = catalog_with_temp_db.conn.execute("PRAGMA compile_options")
        options = [row[0] for row in cursor.fetchall()]

        # FTS5 should be enabled
        fts5_enabled = any("FTS5" in opt for opt in options)
        assert fts5_enabled, "SQLite must be compiled with FTS5 support"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
