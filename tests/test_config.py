"""
Tests for configuration management
"""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from hardbound.config import load_config, save_config, CONFIG_DIR, CONFIG_FILE


class TestConfig:
    """Test configuration loading and saving"""

    def test_load_config_default(self):
        """Test loading default config when no file exists"""
        with patch('pathlib.Path.exists', return_value=False):
            config = load_config()
            expected = {
                "first_run": True,
                "library_path": "",
                "torrent_path": "",
                "zero_pad": True,
                "also_cover": False,
                "recent_sources": []
            }
            assert config == expected

    def test_load_config_from_file(self):
        """Test loading config from existing file"""
        test_config = {
            "first_run": False,
            "library_path": "/test/path",
            "zero_pad": False,
            "also_cover": True,
            "recent_sources": ["/path1", "/path2"]
        }

        with patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.read_text', return_value=json.dumps(test_config)):
            config = load_config()
            assert config == test_config

    def test_load_config_invalid_json(self):
        """Test loading config with invalid JSON falls back to defaults"""
        with patch('pathlib.Path.exists', return_value=True), \
             patch('pathlib.Path.read_text', side_effect=json.JSONDecodeError("Invalid", "", 0)):
            config = load_config()
            assert config["first_run"] is True  # Should be default

    def test_save_config(self):
        """Test saving config to file"""
        test_config = {"test_key": "test_value"}

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_config_dir = Path(temp_dir) / ".config" / "hardbound"
            temp_config_file = temp_config_dir / "config.json"

            with patch('hardbound.config.CONFIG_DIR', temp_config_dir), \
                 patch('hardbound.config.CONFIG_FILE', temp_config_file):
                save_config(test_config)

                assert temp_config_file.exists()
                saved_data = json.loads(temp_config_file.read_text())
                assert saved_data == test_config

    def test_save_config_creates_directory(self):
        """Test that save_config creates the config directory if it doesn't exist"""
        test_config = {"test_key": "test_value"}

        with tempfile.TemporaryDirectory() as temp_dir:
            temp_config_dir = Path(temp_dir) / ".config" / "hardbound"
            temp_config_file = temp_config_dir / "config.json"

            with patch('hardbound.config.CONFIG_DIR', temp_config_dir), \
                 patch('hardbound.config.CONFIG_FILE', temp_config_file):
                assert not temp_config_dir.exists()
                save_config(test_config)
                assert temp_config_dir.exists()
                assert temp_config_file.exists()
