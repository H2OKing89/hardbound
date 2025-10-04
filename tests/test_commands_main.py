"""Tests for command functions (Phase 4.2: Command Functions)

Tests index_command, manage_command, search_command, and select_command.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch, call
from argparse import Namespace

import pytest

from hardbound.commands import (
    index_command,
    manage_command,
    search_command,
    select_command,
    load_config,
    save_config,
)


class TestConfigFunctions:
    """Test config loading and saving"""

    def test_load_config_nonexistent(self, tmp_path: Path, monkeypatch) -> None:
        """Test loading config when file doesn't exist"""
        config_file = tmp_path / "config.json"
        monkeypatch.setattr("hardbound.commands.CONFIG_FILE", config_file)

        config = load_config()

        assert config["first_run"] is True
        assert "library_path" in config
        assert "torrent_path" in config

    def test_load_config_existing(self, tmp_path: Path, monkeypatch) -> None:
        """Test loading existing config file"""
        config_file = tmp_path / "config.json"
        config_data = {"first_run": False, "library_path": "/path/to/library"}
        config_file.write_text(json.dumps(config_data))

        monkeypatch.setattr("hardbound.commands.CONFIG_FILE", config_file)

        config = load_config()

        assert config["first_run"] is False
        assert config["library_path"] == "/path/to/library"

    def test_load_config_invalid_json(self, tmp_path: Path, monkeypatch) -> None:
        """Test loading config with invalid JSON (should return defaults)"""
        config_file = tmp_path / "config.json"
        config_file.write_text("invalid json{")

        monkeypatch.setattr("hardbound.commands.CONFIG_FILE", config_file)

        config = load_config()

        # Should return defaults when JSON is invalid
        assert config["first_run"] is True

    def test_save_config(self, tmp_path: Path, monkeypatch) -> None:
        """Test saving config to file"""
        config_dir = tmp_path / "config"
        config_file = config_dir / "config.json"

        monkeypatch.setattr("hardbound.commands.CONFIG_DIR", config_dir)
        monkeypatch.setattr("hardbound.commands.CONFIG_FILE", config_file)

        config_data = {"first_run": False, "library_path": "/new/path"}
        save_config(config_data)

        assert config_file.exists()
        loaded = json.loads(config_file.read_text())
        assert loaded["first_run"] is False
        assert loaded["library_path"] == "/new/path"


class TestIndexCommand:
    """Test index_command function"""

    @patch("hardbound.commands.AudiobookCatalog")
    def test_index_command_default_roots(self, mock_catalog_class) -> None:
        """Test index command with default roots"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.index_directory.return_value = 10
        mock_catalog.get_stats.return_value = {
            "total": 100,
            "authors": 50,
            "series": 30,
            "total_size": 1024**3 * 50,  # 50 GB
        }

        args = Namespace(roots=[], quiet=False)

        index_command(args)

        # Should have called index_directory for default roots
        assert mock_catalog.index_directory.call_count >= 1
        mock_catalog.get_stats.assert_called_once()
        mock_catalog.close.assert_called_once()

    @patch("hardbound.commands.AudiobookCatalog")
    def test_index_command_custom_roots(self, mock_catalog_class, tmp_path: Path) -> None:
        """Test index command with custom roots"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.index_directory.return_value = 25

        # Create a real directory to index
        test_dir = tmp_path / "audiobooks"
        test_dir.mkdir()

        args = Namespace(roots=[test_dir], quiet=True)

        index_command(args)

        mock_catalog.index_directory.assert_called_once_with(test_dir, verbose=False)
        mock_catalog.close.assert_called_once()

    @patch("hardbound.commands.AudiobookCatalog")
    def test_index_command_nonexistent_root(self, mock_catalog_class, tmp_path: Path) -> None:
        """Test index command with nonexistent root (should skip)"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog

        nonexistent = tmp_path / "does_not_exist"
        args = Namespace(roots=[nonexistent], quiet=True)

        index_command(args)

        # Should not have called index_directory
        mock_catalog.index_directory.assert_not_called()
        mock_catalog.close.assert_called_once()

    @patch("hardbound.commands.AudiobookCatalog")
    def test_index_command_multiple_roots(self, mock_catalog_class, tmp_path: Path) -> None:
        """Test index command with multiple roots"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.index_directory.return_value = 10
        mock_catalog.get_stats.return_value = {
            "total": 100,
            "authors": 50,
            "series": 30,
            "total_size": 1024**3 * 50,
        }

        dir1 = tmp_path / "audiobooks1"
        dir1.mkdir()
        dir2 = tmp_path / "audiobooks2"
        dir2.mkdir()

        args = Namespace(roots=[dir1, dir2], quiet=False)

        index_command(args)

        assert mock_catalog.index_directory.call_count == 2
        mock_catalog.close.assert_called_once()


class TestManageCommand:
    """Test manage_command function"""

    @patch("hardbound.commands.AudiobookCatalog")
    def test_manage_rebuild(self, mock_catalog_class) -> None:
        """Test manage command with rebuild action"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.rebuild_indexes.return_value = {"success": True}

        args = Namespace(action="rebuild", quiet=False)

        manage_command(args)

        mock_catalog.rebuild_indexes.assert_called_once_with(True)
        mock_catalog.close.assert_called_once()

    @patch("hardbound.commands.AudiobookCatalog")
    def test_manage_clean(self, mock_catalog_class) -> None:
        """Test manage command with clean action"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.clean_orphaned_entries.return_value = {"removed": 5}

        args = Namespace(action="clean", quiet=False)

        manage_command(args)

        mock_catalog.clean_orphaned_entries.assert_called_once_with(True)
        mock_catalog.close.assert_called_once()

    @patch("hardbound.commands.AudiobookCatalog")
    def test_manage_optimize(self, mock_catalog_class) -> None:
        """Test manage command with optimize action"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.optimize_database.return_value = {
            "space_saved": 10 * 1024 * 1024,
            "elapsed": 2.5,
        }

        args = Namespace(action="optimize", quiet=False)

        manage_command(args)

        mock_catalog.optimize_database.assert_called_once_with(True)
        mock_catalog.close.assert_called_once()

    @patch("hardbound.commands.AudiobookCatalog")
    def test_manage_stats(self, mock_catalog_class, capsys) -> None:
        """Test manage command with stats action"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.get_db_stats.return_value = {
            "db_size": 50 * 1024 * 1024,
            "items_rows": 100,
            "items_fts_rows": 100,
            "indexes": ["idx1", "idx2"],
            "fts_integrity": True,
        }

        args = Namespace(action="stats", quiet=False)

        manage_command(args)

        mock_catalog.get_db_stats.assert_called_once()
        mock_catalog.get_index_stats.assert_called_once()
        mock_catalog.close.assert_called_once()

        captured = capsys.readouterr()
        assert "Database Statistics" in captured.out
        assert "50.0 MB" in captured.out
        assert "100 rows" in captured.out

    @patch("hardbound.commands.AudiobookCatalog")
    def test_manage_vacuum(self, mock_catalog_class) -> None:
        """Test manage command with vacuum action"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.vacuum_database.return_value = {
            "space_saved": 5 * 1024 * 1024,
        }

        args = Namespace(action="vacuum", quiet=False)

        manage_command(args)

        mock_catalog.vacuum_database.assert_called_once_with(True)
        mock_catalog.close.assert_called_once()

    @patch("hardbound.commands.AudiobookCatalog")
    def test_manage_verify(self, mock_catalog_class, capsys) -> None:
        """Test manage command with verify action"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.verify_integrity.return_value = {
            "sqlite_integrity": True,
            "fts_integrity": True,
            "orphaned_fts_count": 0,
            "missing_fts_count": 0,
        }

        args = Namespace(action="verify", quiet=False)

        manage_command(args)

        mock_catalog.verify_integrity.assert_called_once_with(True)
        mock_catalog.close.assert_called_once()

        captured = capsys.readouterr()
        assert "Integrity Check Results" in captured.out
        assert "✅ OK" in captured.out

    @patch("hardbound.commands.AudiobookCatalog")
    def test_manage_error_handling(self, mock_catalog_class, capsys) -> None:
        """Test manage command error handling"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.rebuild_indexes.side_effect = Exception("Database error")

        args = Namespace(action="rebuild", quiet=False)

        manage_command(args)

        captured = capsys.readouterr()
        assert "Error during rebuild" in captured.out
        mock_catalog.close.assert_called_once()


class TestSearchCommand:
    """Test search_command function"""

    @patch("hardbound.commands.AudiobookCatalog")
    def test_search_basic_query(self, mock_catalog_class, capsys) -> None:
        """Test basic search with query"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.search.return_value = [
            {"author": "Author 1", "series": "Series 1", "book": "Book 1", "path": "/path/1"},
            {"author": "Author 2", "series": "", "book": "Book 2", "path": "/path/2"},
        ]

        args = Namespace(
            query=["tolkien"],
            author=None,
            series=None,
            book=None,
            limit=100,
            json=False,
        )

        search_command(args)

        mock_catalog.search.assert_called_once_with("tolkien", limit=100)
        mock_catalog.close.assert_called_once()

        captured = capsys.readouterr()
        assert "Author 1" in captured.out
        assert "Series 1" in captured.out
        assert "Book 1" in captured.out

    @patch("hardbound.commands.AudiobookCatalog")
    def test_search_with_filters(self, mock_catalog_class) -> None:
        """Test search with author/series/book filters"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.search.return_value = []

        args = Namespace(
            query=[],
            author="Tolkien",
            series="Lord of the Rings",
            book="Fellowship",
            limit=50,
            json=False,
        )

        search_command(args)

        # Should construct query with filters
        call_args = mock_catalog.search.call_args
        query = call_args[0][0]
        assert 'author:"Tolkien"' in query
        assert 'series:"Lord of the Rings"' in query
        assert 'book:"Fellowship"' in query
        assert call_args[1]["limit"] == 50

    @patch("hardbound.commands.AudiobookCatalog")
    def test_search_json_output(self, mock_catalog_class, capsys) -> None:
        """Test search with JSON output"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.search.return_value = [
            {"author": "Author 1", "book": "Book 1", "path": "/path/1"},
        ]

        args = Namespace(
            query=["test"],
            author=None,
            series=None,
            book=None,
            limit=100,
            json=True,
        )

        search_command(args)

        captured = capsys.readouterr()
        # Should output valid JSON
        output = json.loads(captured.out)
        assert len(output) == 1
        assert output[0]["author"] == "Author 1"

    @patch("hardbound.commands.AudiobookCatalog")
    def test_search_empty_results(self, mock_catalog_class, capsys) -> None:
        """Test search with no results"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.search.return_value = []

        args = Namespace(
            query=["nonexistent"],
            author=None,
            series=None,
            book=None,
            limit=100,
            json=False,
        )

        search_command(args)

        captured = capsys.readouterr()
        # Output should be empty (no results found)
        assert captured.out.strip() == "" or "No" in captured.out


class TestSelectCommand:
    """Test select_command function"""

    @patch("hardbound.commands.AudiobookCatalog")
    @patch("hardbound.commands.fzf_pick")
    def test_select_basic(self, mock_fzf, mock_catalog_class) -> None:
        """Test basic select without linking"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.search.return_value = [
            {"author": "Author 1", "book": "Book 1", "path": "/path/1"},
        ]
        mock_fzf.return_value = ["/path/1"]

        args = Namespace(
            query=["test"],
            multi=True,
            link=False,
            integration=None,
            dst_root=None,
        )

        select_command(args)

        mock_catalog.search.assert_called_once()
        mock_fzf.assert_called_once()
        mock_catalog.close.assert_called_once()

    @patch("hardbound.commands.AudiobookCatalog")
    def test_select_no_candidates(self, mock_catalog_class, capsys) -> None:
        """Test select with no search results"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.search.return_value = []

        args = Namespace(
            query=["nonexistent"],
            multi=True,
            link=False,
            integration=None,
            dst_root=None,
        )

        select_command(args)

        captured = capsys.readouterr()
        assert "No audiobooks found" in captured.out
        mock_catalog.close.assert_called_once()

    @patch("hardbound.commands.AudiobookCatalog")
    @patch("hardbound.commands.fzf_pick")
    def test_select_no_selection_made(self, mock_fzf, mock_catalog_class, capsys) -> None:
        """Test select when user cancels selection"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.search.return_value = [
            {"author": "Author 1", "book": "Book 1", "path": "/path/1"},
        ]
        mock_fzf.return_value = []  # No selection

        args = Namespace(
            query=["test"],
            multi=True,
            link=False,
            integration=None,
            dst_root=None,
        )

        select_command(args)

        captured = capsys.readouterr()
        assert "No selection made" in captured.out


class TestCommandsIntegration:
    """Integration tests for command workflows"""

    @patch("hardbound.commands.AudiobookCatalog")
    def test_index_then_search_workflow(self, mock_catalog_class, tmp_path: Path, capsys) -> None:
        """Test workflow of indexing then searching"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog

        # Index
        test_dir = tmp_path / "audiobooks"
        test_dir.mkdir()
        mock_catalog.index_directory.return_value = 5
        mock_catalog.get_stats.return_value = {
            "total": 5,
            "authors": 3,
            "series": 2,
            "total_size": 1024**3 * 10,
        }

        index_args = Namespace(roots=[test_dir], quiet=False)
        index_command(index_args)

        # Search
        mock_catalog.search.return_value = [
            {"author": "Author 1", "series": "Series 1", "book": "Book 1", "path": "/path/1"},
        ]

        search_args = Namespace(
            query=["author1"],
            author=None,
            series=None,
            book=None,
            limit=100,
            json=False,
        )
        search_command(search_args)

        # Verify both commands executed
        mock_catalog.index_directory.assert_called_once()
        mock_catalog.search.assert_called_once()

    @patch("hardbound.commands.AudiobookCatalog")
    def test_manage_clean_then_vacuum(self, mock_catalog_class) -> None:
        """Test workflow of cleaning then vacuuming database"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.clean_orphaned_entries.return_value = {"removed": 3}
        mock_catalog.vacuum_database.return_value = {"space_saved": 2 * 1024 * 1024}

        # Clean
        clean_args = Namespace(action="clean", quiet=True)
        manage_command(clean_args)

        # Vacuum
        vacuum_args = Namespace(action="vacuum", quiet=True)
        manage_command(vacuum_args)

        mock_catalog.clean_orphaned_entries.assert_called_once()
        mock_catalog.vacuum_database.assert_called_once()
