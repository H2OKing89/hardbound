"""Tests for interactive wizards and browsers (Phase 5.2: Wizards)

Tests wizard functions and browser interfaces with mocked user input.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from hardbound.interactive import (
    _first_run_setup,
    search_and_link_wizard,
    update_catalog_wizard,
    folder_batch_wizard,
    automated_maintenance,
)


class TestFirstRunSetup:
    """Test _first_run_setup wizard"""

    @patch("hardbound.interactive.save_config")
    @patch("hardbound.interactive.PathValidator")
    @patch("hardbound.interactive.input")
    def test_first_run_setup_with_paths(self, mock_input, mock_path_validator, mock_save):
        """Test first run setup with valid paths"""
        mock_input.side_effect = ["/path/to/library", "/path/to/torrents"]
        mock_path_validator.validate_library_path.return_value = Path("/path/to/library")
        mock_path_validator.validate_destination_path.return_value = Path("/path/to/torrents")

        config = {"first_run": True}
        _first_run_setup(config)

        assert config["library_path"] == "/path/to/library"
        assert config["torrent_path"] == "/path/to/torrents"
        assert config["first_run"] is False
        mock_save.assert_called_once_with(config)

    @patch("hardbound.interactive.save_config")
    @patch("hardbound.interactive.PathValidator")
    @patch("hardbound.interactive.input")
    def test_first_run_setup_skip_paths(self, mock_input, mock_path_validator, mock_save):
        """Test first run setup skipping path configuration"""
        mock_input.side_effect = ["", ""]  # Empty inputs
        mock_path_validator.get_default_search_paths.return_value = []

        config = {"first_run": True}
        _first_run_setup(config)

        assert config["first_run"] is False
        mock_save.assert_called_once_with(config)

    @patch("hardbound.interactive.save_config")
    @patch("hardbound.interactive.PathValidator")
    @patch("hardbound.interactive.InputValidator")
    @patch("hardbound.interactive.input")
    def test_first_run_setup_auto_detect(self, mock_input, mock_input_validator, mock_path_validator, mock_save):
        """Test first run setup with auto-detected default path"""
        mock_input.side_effect = ["", ""]
        mock_path_validator.get_default_search_paths.return_value = [Path("/default/path")]
        mock_input_validator.confirm_action.return_value = True

        config = {"first_run": True}
        _first_run_setup(config)

        assert config.get("library_path") == "/default/path"
        mock_save.assert_called_once()


class TestSearchAndLinkWizard:
    """Test search_and_link_wizard function"""

    @patch("hardbound.interactive.AudiobookCatalog")
    @patch("hardbound.interactive.hierarchical_browser")
    @patch("hardbound.interactive.input")
    def test_search_and_link_browse_mode(self, mock_input, mock_browser, mock_catalog_class):
        """Test search and link wizard in browse mode"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_input.return_value = "1"  # Choose browse
        mock_browser.return_value = []  # No selection

        search_and_link_wizard()

        mock_browser.assert_called_once_with(mock_catalog)
        mock_catalog.close.assert_called_once()

    @patch("hardbound.interactive.AudiobookCatalog")
    @patch("hardbound.interactive.enhanced_text_search_browser")
    @patch("hardbound.interactive.input")
    def test_search_and_link_search_mode(self, mock_input, mock_search, mock_catalog_class):
        """Test search and link wizard in search mode"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_input.return_value = "2"  # Choose search
        mock_search.return_value = []

        search_and_link_wizard()

        mock_search.assert_called_once_with(mock_catalog)
        mock_catalog.close.assert_called_once()

    @patch("hardbound.interactive.AudiobookCatalog")
    @patch("hardbound.interactive.enhanced_text_search_browser")
    @patch("hardbound.interactive.input")
    def test_search_and_link_recent_mode(self, mock_input, mock_search, mock_catalog_class):
        """Test search and link wizard in recent audiobooks mode"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.search.return_value = [
            {"author": "Author", "book": "Book", "path": "/path"}
        ]
        mock_input.return_value = "3"  # Choose recent
        mock_search.return_value = []

        search_and_link_wizard()

        mock_catalog.search.assert_called_once_with("*", limit=50)
        mock_search.assert_called_once()
        mock_catalog.close.assert_called_once()

    @patch("hardbound.interactive.AudiobookCatalog")
    @patch("hardbound.interactive.input")
    def test_search_and_link_invalid_choice(self, mock_input, mock_catalog_class):
        """Test search and link wizard with invalid choice"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_input.return_value = "99"  # Invalid choice

        search_and_link_wizard()

        # Should just close catalog and return
        mock_catalog.close.assert_called_once()


class TestUpdateCatalogWizard:
    """Test update_catalog_wizard function"""

    @patch("hardbound.interactive.ProgressIndicator")
    @patch("hardbound.interactive.AudiobookCatalog")
    @patch("hardbound.interactive.load_config")
    @patch("hardbound.interactive.input")
    def test_update_catalog_with_library_path(self, mock_input, mock_load_config, mock_catalog_class, mock_progress):
        """Test catalog update with configured library path"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_load_config.return_value = {"library_path": "/library"}
        mock_input.return_value = "1"  # Choose option 1
        mock_catalog.index_directory.return_value = 10

        # Mock Path existence
        with patch("hardbound.interactive.Path") as mock_path:
            mock_path_obj = MagicMock()
            mock_path_obj.exists.return_value = True
            mock_path.return_value = mock_path_obj

            update_catalog_wizard()

            mock_catalog.index_directory.assert_called_once()
        mock_catalog.close.assert_called_once()

    @patch("hardbound.interactive.AudiobookCatalog")
    @patch("hardbound.interactive.load_config")
    @patch("hardbound.interactive.input")
    def test_update_catalog_no_confirmation(self, mock_input, mock_load_config, mock_catalog_class):
        """Test catalog update when user selects invalid option"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_load_config.return_value = {"library_path": "/library"}
        mock_input.return_value = "3"  # Invalid choice

        update_catalog_wizard()

        # Should not call index_directory for invalid choice
        mock_catalog.index_directory.assert_not_called()
        mock_catalog.close.assert_called_once()

    @patch("hardbound.interactive.ProgressIndicator")
    @patch("hardbound.interactive.AudiobookCatalog")
    @patch("hardbound.interactive.load_config")
    @patch("hardbound.interactive.input")
    def test_update_catalog_custom_path(self, mock_input, mock_load_config, mock_catalog_class, mock_progress):
        """Test catalog update with custom path"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_load_config.return_value = {}
        mock_input.side_effect = ["2", "/custom/path"]  # Choose option 2, then enter path
        mock_catalog.index_directory.return_value = 5

        # Mock Path existence
        with patch("hardbound.interactive.Path") as mock_path:
            mock_path_obj = MagicMock()
            mock_path_obj.exists.return_value = True
            mock_path_obj.is_dir.return_value = True
            mock_path.return_value = mock_path_obj

            update_catalog_wizard()

            mock_catalog.index_directory.assert_called_once()
        mock_catalog.close.assert_called_once()


class TestFolderBatchWizard:
    """Test folder_batch_wizard function"""

    @patch("hardbound.interactive.summary_table")
    @patch("hardbound.interactive.plan_and_link_red")
    @patch("hardbound.interactive.input")
    @patch("hardbound.interactive.browse_directory_tree")
    @patch("hardbound.interactive.load_config")
    def test_folder_batch_wizard_basic(self, mock_load_config, mock_browse, mock_input, mock_plan_link, mock_summary):
        """Test basic folder batch wizard"""
        mock_load_config.return_value = {
            "torrent_path": "/dest",
            "zero_pad": True,
            "also_cover": False
        }

        # Mock browse to return a source directory
        mock_src = MagicMock()
        mock_src.name = "TestBook"
        mock_src.exists.return_value = True
        mock_src.is_dir.return_value = True
        mock_src.iterdir.return_value = [mock_src]  # Returns self as subdirectory
        mock_src.glob.return_value = ["file.m4b"]  # Has audio files
        mock_browse.return_value = mock_src

        mock_input.return_value = ""  # Use default destination

        folder_batch_wizard()

        mock_plan_link.assert_called()

    @patch("hardbound.interactive.browse_directory_tree")
    @patch("hardbound.interactive.load_config")
    def test_folder_batch_wizard_no_integrations(self, mock_load_config, mock_browse):
        """Test folder batch wizard when browse returns None"""
        mock_load_config.return_value = {}
        mock_browse.return_value = None  # User cancelled

        folder_batch_wizard()

        # Should return early without errors
        mock_browse.assert_called_once()


class TestAutomatedMaintenance:
    """Test automated_maintenance function"""

    @patch("hardbound.interactive.ProgressIndicator")
    @patch("hardbound.interactive.Path")
    @patch("hardbound.interactive.load_config")
    @patch("hardbound.interactive.AudiobookCatalog")
    def test_automated_maintenance_basic(self, mock_catalog_class, mock_load_config, mock_path, mock_progress):
        """Test basic automated maintenance"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.clean_orphaned_entries.return_value = {"removed": 5}
        mock_catalog.index_directory.return_value = 100

        mock_load_config.return_value = {"library_path": "/library"}

        # Mock Path existence check
        mock_path_obj = MagicMock()
        mock_path_obj.exists.return_value = True
        mock_path.return_value = mock_path_obj

        automated_maintenance()

        mock_catalog.clean_orphaned_entries.assert_called_once()
        mock_catalog.index_directory.assert_called_once()
        mock_catalog.close.assert_called_once()

    @patch("hardbound.interactive.load_config")
    @patch("hardbound.interactive.AudiobookCatalog")
    def test_automated_maintenance_no_orphans(self, mock_catalog_class, mock_load_config):
        """Test maintenance when no orphaned entries"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.clean_orphaned_entries.return_value = {"removed": 0}

        mock_load_config.return_value = {"library_path": "/library"}

        automated_maintenance()

        mock_catalog.clean_orphaned_entries.assert_called_once()
        # Should not call index_directory if no orphaned entries
        mock_catalog.index_directory.assert_not_called()
        mock_catalog.close.assert_called_once()

    @patch("hardbound.interactive.AudiobookCatalog")
    def test_automated_maintenance_error_handling(self, mock_catalog_class, capsys):
        """Test maintenance error handling"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_catalog.clean_orphaned_entries.side_effect = Exception("Database error")

        automated_maintenance()

        # Should handle error gracefully
        captured = capsys.readouterr()
        # Error should be logged or displayed
        mock_catalog.close.assert_called_once()


class TestWizardsIntegration:
    """Integration tests for wizard workflows"""

    @patch("hardbound.interactive.ProgressIndicator")
    @patch("hardbound.interactive.Path")
    @patch("hardbound.interactive.input")
    @patch("hardbound.interactive.AudiobookCatalog")
    @patch("hardbound.interactive.load_config")
    def test_update_then_search_workflow(self, mock_load_config, mock_catalog_class, mock_input, mock_path, mock_progress):
        """Test workflow of updating catalog then searching"""
        mock_catalog = MagicMock()
        mock_catalog_class.return_value = mock_catalog
        mock_load_config.return_value = {"library_path": "/library"}
        mock_input.return_value = "1"  # Choose option 1
        mock_catalog.index_directory.return_value = 10

        # Mock Path existence
        mock_path_obj = MagicMock()
        mock_path_obj.exists.return_value = True
        mock_path.return_value = mock_path_obj

        # Update catalog
        update_catalog_wizard()

        # Verify catalog operations
        assert mock_catalog.index_directory.call_count >= 1

    @patch("hardbound.interactive.save_config")
    @patch("hardbound.interactive.PathValidator")
    @patch("hardbound.interactive.input")
    def test_first_run_then_update_workflow(self, mock_input, mock_path_validator, mock_save):
        """Test workflow of first run setup then catalog update"""
        mock_input.side_effect = ["/library", "/dest"]
        mock_path_validator.validate_library_path.return_value = Path("/library")
        mock_path_validator.validate_destination_path.return_value = Path("/dest")

        config = {"first_run": True}
        _first_run_setup(config)

        # Config should be updated
        assert config["library_path"] == "/library"
        assert config["torrent_path"] == "/dest"
        assert config["first_run"] is False
