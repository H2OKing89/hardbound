"""
Tests for display utilities
"""

import shutil
from unittest.mock import patch

from hardbound.display import Sty, banner, ellipsize, section, summary_table, term_width


class TestSty:
    """Test ANSI color styling"""

    def test_sty_colors_enabled(self):
        """Test that colors are enabled by default"""
        assert Sty.enabled is True
        assert Sty.RED == "red"
        assert Sty.RESET == ""

    def test_sty_off(self):
        """Test disabling colors"""
        # Save original state
        original_enabled = Sty.enabled
        original_red = Sty.RED

        try:
            Sty.off()
            assert Sty.enabled is False
            assert Sty.RED == "red"  # Colors remain the same, just disabled flag
            assert Sty.RESET == ""
        finally:
            # Restore original state
            Sty.enabled = original_enabled
            Sty.RED = original_red


class TestTermWidth:
    """Test terminal width detection"""

    def test_term_width_success(self):
        """Test successful terminal width detection"""
        with patch("shutil.get_terminal_size") as mock_size:
            mock_size.return_value.columns = 80
            assert term_width() == 80

    def test_term_width_fallback(self):
        """Test fallback when terminal size detection fails"""
        with patch("shutil.get_terminal_size", side_effect=Exception("No terminal")):
            assert term_width() == 100  # default

    def test_term_width_custom_default(self):
        """Test custom default width"""
        with patch("shutil.get_terminal_size", side_effect=Exception("No terminal")):
            assert term_width(default=120) == 120


class TestEllipsize:
    """Test string ellipsization"""

    def test_no_ellipsize_needed(self):
        """Test strings that don't need ellipsizing"""
        assert ellipsize("short", 10) == "short"
        assert ellipsize("exactly", 7) == "exactly"

    def test_ellipsize_long_string(self):
        """Test ellipsizing long strings"""
        result = ellipsize("very long string that needs to be shortened", 20)
        assert len(result) <= 20
        assert "…" in result

    def test_ellipsize_very_short_limit(self):
        """Test ellipsizing with very short limit"""
        result = ellipsize("longstring", 5)
        assert len(result) <= 5
        assert result.endswith("…")

    def test_ellipsize_empty_string(self):
        """Test ellipsizing empty string"""
        assert ellipsize("", 10) == ""


class TestBanner:
    """Test banner display function"""

    @patch("hardbound.display.term_width")
    @patch("hardbound.display.console.print")
    def test_banner_dry_run(self, mock_print, mock_width):
        """Test banner display for dry run mode"""
        mock_width.return_value = 50
        banner("Test Title", "dry")

        # Should have printed something
        assert mock_print.called

    @patch("hardbound.display.term_width")
    @patch("hardbound.display.console.print")
    def test_banner_commit(self, mock_print, mock_width):
        """Test banner display for commit mode"""
        mock_width.return_value = 50
        banner("Test Title", "commit")

        assert mock_print.called


class TestSection:
    """Test section display function"""

    @patch("hardbound.display.console.print")
    def test_section_display(self, mock_print):
        """Test section header display"""
        section("Test Section")
        # Should print the title and a separator line
        assert mock_print.call_count >= 2
        # Check that the title was printed with magenta color
        calls = [call.args[0] for call in mock_print.call_args_list]
        assert any("Test Section" in call for call in calls)


class TestSummaryTable:
    """Test summary table display"""

    @patch("hardbound.display.console.print")
    def test_summary_table_display(self, mock_print):
        """Test summary table display"""
        stats = {
            "linked": 5,
            "replaced": 2,
            "already": 1,
            "exists": 0,
            "excluded": 3,
            "skipped": 2,
            "errors": 1,
        }
        summary_table(stats, 1.23)

        # Should print multiple lines
        assert mock_print.call_count > 1
