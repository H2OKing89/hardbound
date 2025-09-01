"""
Tests for main hardbound application argument parsing
"""

import subprocess
import sys
from pathlib import Path

import pytest


class TestArgumentParsing:
    """Test argument parsing logic via subprocess calls"""

    def test_help_output(self):
        """Test that --help produces expected output"""
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent.parent / "hardbound.py"),
                "--help",
            ],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0
        assert "Hardbound" in result.stdout
        assert "usage:" in result.stdout

    def test_version_output(self):
        """Test version information is available"""
        # Since there's no --version flag, we'll just test basic execution
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent.parent / "hardbound.py"),
                "--no-color",
            ],
            capture_output=True,
            text=True,
            input="q\n",
        )  # Send 'q' to quit interactive mode

        # Should not crash
        assert (
            result.returncode == 0 or result.returncode == 1
        )  # 1 is ok for interrupted interactive mode

    def test_invalid_args_error(self):
        """Test that invalid arguments produce errors"""
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent.parent / "hardbound.py"),
                "--src",
                "/nonexistent",
                "--dst",
                "/dst",
                "--commit",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
        )

        # Should exit with error code
        assert result.returncode == 2
        assert "Use either --commit or --dry-run" in result.stderr
