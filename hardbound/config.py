"""
Configuration management
"""

import json
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "hardbound"
CONFIG_FILE = CONFIG_DIR / "config.json"


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
