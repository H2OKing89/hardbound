"""
Integration tests for Hardbound audiobook hardlink manager
"""

import shutil
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from hardbound.catalog import AudiobookCatalog
from hardbound.config import load_config, save_config
from hardbound.linker import plan_and_link


@pytest.mark.integration
class TestCatalogIntegration:
    """Integration tests for catalog operations"""

    def test_full_catalog_workflow(self):
        """Test complete catalog indexing and search workflow"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create mock audiobook structure
            library_dir = temp_path / "audiobooks"
            library_dir.mkdir()

            # Create some mock audiobook directories
            book1 = library_dir / "Author One - Book One"
            book1.mkdir()
            (book1 / "Book One.m4b").write_text("mock audio")

            book2 = library_dir / "Author Two - Book Two"
            book2.mkdir()
            (book2 / "Book Two.mp3").write_text("mock audio")

            # Mock the database to use a temporary location
            test_db = temp_path / "test.db"
            with patch("hardbound.catalog.DB_FILE", test_db):
                # Test catalog creation and indexing
                catalog = AudiobookCatalog()
                count = catalog.index_directory(library_dir, verbose=False)
                assert count == 2

                # Test search functionality
                results = catalog.search("Author One")
                assert len(results) == 1
                assert results[0]["author"] == "Author One"

                # Test search with multiple results
                results = catalog.search("*")
                assert len(results) == 2

                catalog.close()

    def test_catalog_persistence(self):
        """Test that catalog data persists between sessions"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            db_path = temp_path / "test_catalog.db"

            # Mock the database path
            with patch("hardbound.catalog.DB_FILE", db_path):
                # First session
                catalog1 = AudiobookCatalog()
                # Add some mock data by indexing a directory
                mock_dir = temp_path / "mock_library"
                mock_dir.mkdir()
                mock_book = mock_dir / "Test Author - Test Book"
                mock_book.mkdir()
                (mock_book / "Test Book.m4b").write_text("mock")

                catalog1.index_directory(mock_dir, verbose=False)
                catalog1.close()

                # Second session - verify data persists
                catalog2 = AudiobookCatalog()
                results = catalog2.search("*")
                assert len(results) == 1
                # The parsing logic extracts author from the parent directory name
                assert "Test Author" in results[0]["path"]

                catalog2.close()


@pytest.mark.integration
class TestLinkingIntegration:
    """Integration tests for linking operations"""

    def test_full_linking_workflow(self):
        """Test complete linking workflow from source to destination"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)

            # Create source audiobook
            src_dir = temp_path / "source" / "Test Author - Test Book"
            src_dir.mkdir(parents=True)
            src_file = src_dir / "Test Book.m4b"
            src_file.write_text("mock audio content")

            # Create destination
            dst_root = temp_path / "destination"
            dst_root.mkdir()

            # Test linking
            stats = {
                "linked": 0,
                "replaced": 0,
                "already": 0,
                "exists": 0,
                "excluded": 0,
                "skipped": 0,
                "errors": 0,
            }

            plan_and_link(
                src_dir,
                dst_root / "Test Book",
                "Test Book",
                False,
                False,
                False,
                False,
                stats,
            )

            # Verify results
            assert stats["linked"] == 1
            assert (dst_root / "Test Book" / "Test Book.m4b").exists()

            # Verify it's a hardlink
            src_stat = src_file.stat()
            dst_stat = (dst_root / "Test Book" / "Test Book.m4b").stat()
            assert src_stat.st_ino == dst_stat.st_ino


@pytest.mark.integration
class TestConfigIntegration:
    """Integration tests for configuration system"""

    def test_config_workflow(self):
        """Test complete configuration load/save workflow"""
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            config_dir = temp_path / ".config" / "hardbound"
            config_file = config_dir / "config.json"

            # Mock the config paths
            with patch("hardbound.config.CONFIG_DIR", config_dir), patch(
                "hardbound.config.CONFIG_FILE", config_file
            ):

                # Test default config
                config = load_config()
                assert config["first_run"] is True
                assert config["library_path"] == ""

                # Test saving config
                config["library_path"] = str(
                    temp_path
                )  # Use the temp directory which exists
                config["torrent_path"] = str(temp_path)  # Set torrent path too
                config["first_run"] = False
                save_config(config)

                # Test loading saved config
                loaded_config = load_config()
                assert loaded_config["library_path"] == str(temp_path)
                assert loaded_config["first_run"] is False


@pytest.mark.integration
class TestCliIntegration:
    """Integration tests for CLI operations"""

    def test_help_command(self):
        """Test that help command works"""
        import subprocess
        import sys
        from pathlib import Path

        # Get the path to hardbound.py
        hardbound_path = Path(__file__).parent.parent / "hardbound.py"

        result = subprocess.run(
            [sys.executable, str(hardbound_path), "--help"],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "Hardbound" in result.stdout
        assert "usage:" in result.stdout

    def test_invalid_command_handling(self):
        """Test that invalid commands are handled gracefully"""
        import subprocess
        import sys
        from pathlib import Path

        hardbound_path = Path(__file__).parent.parent / "hardbound.py"

        result = subprocess.run(
            [sys.executable, str(hardbound_path), "--invalid-flag"],
            capture_output=True,
            text=True,
        )

        # Should exit with error but not crash
        assert result.returncode != 0
