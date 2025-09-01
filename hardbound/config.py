"""
Configuration management with validation and migration
"""

import json
from pathlib import Path
from typing import Dict, Any, Optional
from .utils.validation import PathValidator

CONFIG_DIR = Path.home() / ".config" / "hardbound"
CONFIG_FILE = CONFIG_DIR / "config.json"

# Configuration schema with defaults and validation
DEFAULT_CONFIG = {
    "version": "1.0",
    "first_run": True,
    "library_path": "",
    "torrent_path": "",
    "zero_pad": True,
    "also_cover": False,
    "recent_sources": [],
    "system_search_paths": [
        "/mnt/user/data/audio/audiobooks",
        "/mnt/user/data/downloads"
    ],
    "search_history_size": 100,
    "ui_theme": "default",
    "auto_update_catalog": True,
    "parallel_processing": True,
    "max_parallel_jobs": 4
}

CONFIG_VALIDATORS = {
    "library_path": lambda x: PathValidator.validate_library_path(x) is not None,
    "torrent_path": lambda x: PathValidator.validate_destination_path(x) is not None,
    "zero_pad": lambda x: isinstance(x, bool),
    "also_cover": lambda x: isinstance(x, bool),
    "recent_sources": lambda x: isinstance(x, list),
    "system_search_paths": lambda x: isinstance(x, list) and all(isinstance(p, str) for p in x),
    "search_history_size": lambda x: isinstance(x, int) and x > 0,
    "ui_theme": lambda x: isinstance(x, str) and x in ["default", "dark", "light"],
    "auto_update_catalog": lambda x: isinstance(x, bool),
    "parallel_processing": lambda x: isinstance(x, bool),
    "max_parallel_jobs": lambda x: isinstance(x, int) and 1 <= x <= 16
}


class ConfigManager:
    """Enhanced configuration manager with validation and migration"""

    def __init__(self):
        self.config = {}

    def load_config(self) -> Dict[str, Any]:
        """Load configuration with validation and migration"""
        if CONFIG_FILE.exists():
            try:
                loaded_config = json.loads(CONFIG_FILE.read_text())
                self.config = self._migrate_config(loaded_config)
                self._validate_config()
                return self.config
            except Exception as e:
                print(f"Warning: Could not load config file: {e}")
                print("Using default configuration...")

        self.config = DEFAULT_CONFIG.copy()
        return self.config

    def save_config(self, config_data: Dict[str, Any]):
        """Save configuration with validation"""
        # Validate before saving
        self._validate_config_data(config_data)

        # Ensure version is set
        config_data["version"] = DEFAULT_CONFIG["version"]

        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(config_data, indent=2))
        self.config = config_data

    def _migrate_config(self, loaded_config: Dict[str, Any]) -> Dict[str, Any]:
        """Migrate configuration from older versions"""
        version = loaded_config.get("version", "0.0")

        # Start with defaults
        migrated = DEFAULT_CONFIG.copy()

        # Copy existing valid values
        for key, value in loaded_config.items():
            if key in migrated:
                migrated[key] = value

        # Version-specific migrations
        if version == "0.0":
            # Migrate from old format
            if "library" in loaded_config:
                migrated["library_path"] = loaded_config["library"]
            if "torrent" in loaded_config:
                migrated["torrent_path"] = loaded_config["torrent"]

        migrated["version"] = DEFAULT_CONFIG["version"]
        return migrated

    def _validate_config(self):
        """Validate current configuration"""
        self._validate_config_data(self.config)

    def _validate_config_data(self, config_data: Dict[str, Any]):
        """Validate configuration data against schema"""
        errors = []

        for key, validator in CONFIG_VALIDATORS.items():
            if key in config_data:
                try:
                    if not validator(config_data[key]):
                        errors.append(f"Invalid value for '{key}': {config_data[key]}")
                except Exception as e:
                    errors.append(f"Validation error for '{key}': {e}")

        if errors:
            error_msg = "Configuration validation errors:\n" + "\n".join(f"  • {e}" for e in errors)
            raise ValueError(error_msg)

    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value with default"""
        return self.config.get(key, DEFAULT_CONFIG.get(key, default))

    def set(self, key: str, value: Any):
        """Set configuration value with validation"""
        if key in CONFIG_VALIDATORS:
            if not CONFIG_VALIDATORS[key](value):
                raise ValueError(f"Invalid value for '{key}': {value}")

        self.config[key] = value

    def reset_to_defaults(self):
        """Reset configuration to defaults"""
        self.config = DEFAULT_CONFIG.copy()


# Global config manager instance
config_manager = ConfigManager()


def load_config():
    """Load configuration (backward compatibility)"""
    return config_manager.load_config()


def save_config(config_data):
    """Save configuration (backward compatibility)"""
    config_manager.save_config(config_data)
