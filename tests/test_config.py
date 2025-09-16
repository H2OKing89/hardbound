"""
Tests for configuration management
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from hardbound.config import load_config, save_config


class TestConfig:
    """Test configuration loading and saving"""

    def test_load_config_default(self) -> None:
        """Test loading default config when no file exists"""
        with patch("pathlib.Path.exists", return_value=False):
            config = load_config()
            # Check that we have the expected keys (not the full dict since it has more defaults now)
            assert config["first_run"] is True
            assert config["library_path"] == ""
            assert config["torrent_path"] == ""
            assert config["zero_pad"] is True
            assert config["also_cover"] is False
            assert isinstance(config["recent_sources"], list)
            # New config keys
            assert "auto_update_catalog" in config
            assert "parallel_processing" in config
            assert "system_search_paths" in config

    def test_load_config_from_file(self) -> None:
        """Test loading config from existing file"""
        test_config = {
            "first_run": False,
            "library_path": "/tmp",  # Use a valid path for testing
            "torrent_path": "/tmp",
            "zero_pad": False,
            "also_cover": True,
            "recent_sources": ["/path1", "/path2"],
        }

        with (
            patch("pathlib.Path.exists", return_value=True),
            patch("pathlib.Path.read_text", return_value=json.dumps(test_config)),
        ):
            config = load_config()
            assert config["first_run"] is False
            assert config["library_path"] == "/tmp"
            assert config["zero_pad"] is False
            assert config["also_cover"] is True
            assert config["recent_sources"] == ["/path1", "/path2"]

    def test_load_config_invalid_json(self) -> None:
        """Test loading config with invalid JSON falls back to defaults"""
        with (
            patch("pathlib.Path.exists", return_value=True),
            patch(
                "pathlib.Path.read_text",
                side_effect=json.JSONDecodeError("Invalid", "", 0),
            ),
        ):
            config = load_config()
            assert config["first_run"] is True  # Should be default

    def test_save_config(self) -> None:
        """Test saving config to file"""
        test_config = {"test_key": "test_value"}

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_config_dir = Path(temp_dir) / ".config" / "hardbound"
            temp_config_file = temp_config_dir / "config.json"

            with (
                patch("hardbound.config.CONFIG_DIR", temp_config_dir),
                patch("hardbound.config.CONFIG_FILE", temp_config_file),
            ):
                save_config(test_config)

                assert temp_config_file.exists()
                saved_data = json.loads(temp_config_file.read_text())
                assert saved_data == test_config

    def test_save_config_creates_directory(self) -> None:
        """Test that save_config creates parent directory if needed"""
        test_config = {"test_key": "test_value"}

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_config_dir = Path(temp_dir) / ".config" / "hardbound"
            temp_config_file = temp_config_dir / "config.json"

            with (
                patch("hardbound.config.CONFIG_DIR", temp_config_dir),
                patch("hardbound.config.CONFIG_FILE", temp_config_file),
            ):
                assert not temp_config_dir.exists()
                save_config(test_config)
                assert temp_config_dir.exists()
                assert temp_config_file.exists()
