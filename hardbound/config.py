"""
Configuration management with validation and migration
"""

import json
import copy
from pathlib import Path
from typing import Any, Dict, Optional, cast
from dataclasses import dataclass

from .utils.validation import PathValidator

CONFIG_DIR = Path.home() / ".config" / "hardbound"
CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_LOG_DIR = Path("/mnt/cache/scripts/hardbound/logs")

@dataclass
class LoggingConfig:
    """Configuration for structured logging with Rich console and JSON file output"""
    level: str = "INFO"          # DEBUG, INFO, WARNING, ERROR
    file_enabled: bool = True
    console_enabled: bool = True
    json_file: bool = True
    path: Path = DEFAULT_LOG_DIR / "hardbound.log"
    rotate_max_bytes: int = 10 * 1024 * 1024  # 10 MiB
    rotate_backups: int = 5
    rich_tracebacks: bool = True
    show_path: bool = False       # rich console "path=…" decoration

# Configuration schema with defaults and validation
DEFAULT_CONFIG = {
    "version": "1.1",
    "first_run": True,
    "library_path": "",
    "torrent_path": "",
    "integrations": {
        "torrent": {
            "path": "",
            "path_limit": None,  # No limit for regular torrents
            "enabled": True
        },
        "red": {
            "path": "/mnt/user/data/downloads/torrents/qbittorrent/seedvault/audiobooks/redacted",
            "path_limit": 180,
            "enabled": False
        }
    },
    "zero_pad": True,
    "also_cover": False,
    "set_permissions": False,
    "file_permissions": 0o644,
    "set_dir_permissions": False,
    "dir_permissions": 0o755,
    "set_ownership": False,
    "owner_user": "",
    "owner_group": "",
    "recent_sources": [],
    "system_search_paths": [
        "/mnt/user/data/audio/audiobooks",
        "/mnt/user/data/downloads",
    ],
    "search_history_size": 100,
    "ui_theme": "default",
    "auto_update_catalog": True,
    "parallel_processing": True,
    "max_parallel_jobs": 4,
    "logging": {
        "level": "INFO",
        "file_enabled": True,
        "console_enabled": True,
        "json_file": True,
        "path": str(DEFAULT_LOG_DIR / "hardbound.log"),
        "rotate_max_bytes": 10 * 1024 * 1024,  # 10 MiB
        "rotate_backups": 5,
        "rich_tracebacks": True,
        "show_path": False
    }
}

CONFIG_VALIDATORS = {
    "library_path": lambda x: PathValidator.validate_library_path(x) is not None,
    "torrent_path": lambda x: PathValidator.validate_destination_path(x) is not None,
    "integrations": lambda x: isinstance(x, dict) and all(
        isinstance(k, str) and isinstance(v, dict) and
        "path" in v and "path_limit" in v and "enabled" in v and
        isinstance(v["enabled"], bool) and
        (v["path_limit"] is None or isinstance(v["path_limit"], int))
        for k, v in x.items()
    ),
    "zero_pad": lambda x: isinstance(x, bool),
    "also_cover": lambda x: isinstance(x, bool),
    "set_permissions": lambda x: isinstance(x, bool),
    "file_permissions": lambda x: isinstance(x, int) and 0 <= x <= 0o777,
    "set_ownership": lambda x: isinstance(x, bool),
    "owner_user": lambda x: isinstance(x, str),
    "owner_group": lambda x: isinstance(x, str),
    "recent_sources": lambda x: isinstance(x, list),
    "system_search_paths": lambda x: isinstance(x, list)
    and all(isinstance(p, str) for p in x),
    "search_history_size": lambda x: isinstance(x, int) and x > 0,
    "ui_theme": lambda x: isinstance(x, str) and x in ["default", "dark", "light"],
    "auto_update_catalog": lambda x: isinstance(x, bool),
    "parallel_processing": lambda x: isinstance(x, bool),
    "max_parallel_jobs": lambda x: isinstance(x, int) and 1 <= x <= 16,
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

        # Start with defaults (deep copy to avoid reference issues)
        migrated = copy.deepcopy(DEFAULT_CONFIG)
        assert isinstance(migrated["integrations"], dict)  # Tell Pylance it's a dict

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

        # Migrate from version 1.0 to 1.1 - add integrations structure
        if version in ["0.0", "1.0"]:
            # Preserve existing torrent_path in new integrations structure
            torrent_path = loaded_config.get("torrent_path", "")
            if torrent_path:
                integrations_config = cast(Dict[str, Any], migrated["integrations"])
                torrent_config = cast(Dict[str, Any], integrations_config["torrent"])
                torrent_config["path"] = torrent_path
                torrent_config["enabled"] = True

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
            error_msg = "Configuration validation errors:\n" + "\n".join(
                f"  • {e}" for e in errors
            )
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
        self.config = copy.deepcopy(DEFAULT_CONFIG)

    def get_integration(self, name: str) -> Optional[Dict[str, Any]]:
        """Get integration configuration by name"""
        integrations = self.config.get("integrations", {})
        if isinstance(integrations, dict):
            integration = integrations.get(name)
            if isinstance(integration, dict):
                return integration
        return None

    def get_enabled_integrations(self) -> Dict[str, Dict[str, Any]]:
        """Get all enabled integrations"""
        integrations = self.config.get("integrations", {})
        if not isinstance(integrations, dict):
            return {}
        return {name: config for name, config in integrations.items() 
                if isinstance(config, dict) and config.get("enabled", False)}

    def set_integration_path(self, name: str, path: str):
        """Set path for a specific integration"""
        if "integrations" not in self.config:
            self.config["integrations"] = copy.deepcopy(DEFAULT_CONFIG["integrations"])
        
        integrations = self.config["integrations"]
        if isinstance(integrations, dict) and name in integrations:
            if isinstance(integrations[name], dict):
                integration_config = cast(Dict[str, Any], integrations[name])
                integration_config["path"] = path
        else:
            raise ValueError(f"Unknown integration: {name}")

    def enable_integration(self, name: str, enabled: bool = True):
        """Enable or disable an integration"""
        if "integrations" not in self.config:
            self.config["integrations"] = copy.deepcopy(DEFAULT_CONFIG["integrations"])
            
        integrations = self.config["integrations"]
        if isinstance(integrations, dict) and name in integrations:
            if isinstance(integrations[name], dict):
                integration_config = cast(Dict[str, Any], integrations[name])
                integration_config["enabled"] = enabled
        else:
            raise ValueError(f"Unknown integration: {name}")

    def validate_path_length(self, name: str, path_str: str) -> bool:
        """Validate path length for a specific integration"""
        integration = self.get_integration(name)
        if not integration:
            return True  # No integration found, no validation needed
            
        path_limit = integration.get("path_limit")
        if path_limit is None:
            return True  # No limit set
            
        return len(path_str) <= path_limit


# Global config manager instance
config_manager = ConfigManager()


def load_config():
    """Load configuration (backward compatibility)"""
    return config_manager.load_config()


def save_config(config_data):
    """Save configuration (backward compatibility)"""
    config_manager.save_config(config_data)
