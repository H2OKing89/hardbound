"""Tests for interactive module (Phase 5.1: Core Functions)

Tests parse_selection_input, display_selection_review, have_fzf, and helper functions.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from hardbound.interactive import (
    parse_selection_input,
    display_selection_review,
    have_fzf,
    _get_recent_sources,
)


class TestGetRecentSources:
    """Test _get_recent_sources helper function"""

    def test_get_recent_sources_valid_list(self) -> None:
        """Test with valid list of sources"""
        config = {"recent_sources": ["/path/1", "/path/2", "/path/3"]}
        result = _get_recent_sources(config)
        assert result == ["/path/1", "/path/2", "/path/3"]

    def test_get_recent_sources_empty_list(self) -> None:
        """Test with empty list"""
        config = {"recent_sources": []}
        result = _get_recent_sources(config)
        assert result == []

    def test_get_recent_sources_missing_key(self) -> None:
        """Test with missing recent_sources key"""
        config = {"other_key": "value"}
        result = _get_recent_sources(config)
        assert result == []

    def test_get_recent_sources_not_a_list(self) -> None:
        """Test with non-list value (should return empty list)"""
        config = {"recent_sources": "not a list"}
        result = _get_recent_sources(config)
        assert result == []

    def test_get_recent_sources_none(self) -> None:
        """Test with None value"""
        config = {"recent_sources": None}
        result = _get_recent_sources(config)
        assert result == []


class TestParseSelectionInput:
    """Test parse_selection_input function"""

    def test_single_number(self) -> None:
        """Test parsing single number"""
        result = parse_selection_input("3", max_items=10)
        assert result == [2]  # 0-based index

    def test_multiple_numbers_comma_separated(self) -> None:
        """Test parsing comma-separated numbers"""
        result = parse_selection_input("1,3,5", max_items=10)
        assert result == [0, 2, 4]  # 0-based indices

    def test_range(self) -> None:
        """Test parsing range"""
        result = parse_selection_input("1-5", max_items=10)
        assert result == [0, 1, 2, 3, 4]

    def test_mixed_ranges_and_numbers(self) -> None:
        """Test parsing mixed ranges and individual numbers"""
        result = parse_selection_input("1-3,7,9-11", max_items=15)
        assert result == [0, 1, 2, 6, 8, 9, 10]

    def test_reverse_range(self) -> None:
        """Test that reverse ranges work (5-1 same as 1-5)"""
        result = parse_selection_input("5-1", max_items=10)
        assert result == [0, 1, 2, 3, 4]

    def test_out_of_bounds_ignored(self) -> None:
        """Test that out-of-bounds numbers are ignored"""
        result = parse_selection_input("1,20,3", max_items=10)
        assert result == [0, 2]

    def test_invalid_numbers_ignored(self) -> None:
        """Test that invalid input is ignored"""
        result = parse_selection_input("1,abc,3", max_items=10)
        assert result == [0, 2]

    def test_empty_string(self) -> None:
        """Test empty string returns empty list"""
        result = parse_selection_input("", max_items=10)
        assert result == []

    def test_spaces_ignored(self) -> None:
        """Test that spaces are properly ignored"""
        result = parse_selection_input("1, 3, 5", max_items=10)
        assert result == [0, 2, 4]

    def test_duplicate_removal(self) -> None:
        """Test that duplicates are removed"""
        result = parse_selection_input("1,3,1,3", max_items=10)
        assert result == [0, 2]

    def test_overlapping_ranges(self) -> None:
        """Test overlapping ranges are merged"""
        result = parse_selection_input("1-5,3-7", max_items=10)
        assert result == [0, 1, 2, 3, 4, 5, 6]


class TestDisplaySelectionReview:
    """Test display_selection_review function"""

    def test_empty_list(self, capsys) -> None:
        """Test with empty list does nothing"""
        display_selection_review([])
        captured = capsys.readouterr()
        assert captured.out == ""

    def test_single_book_with_series(self, capsys) -> None:
        """Test displaying single book with series"""
        books = [
            {
                "book": "The Fellowship of the Ring",
                "author": "J.R.R. Tolkien",
                "series": "The Lord of the Rings",
                "size": 500 * 1024 * 1024,  # 500 MB
                "has_m4b": True,
            }
        ]
        display_selection_review(books)
        captured = capsys.readouterr()

        assert "SELECTION REVIEW" in captured.out
        assert "1 audiobook" in captured.out
        assert "J.R.R. Tolkien" in captured.out
        assert "The Fellowship of the Ring" in captured.out

    def test_single_book_without_series(self, capsys) -> None:
        """Test displaying single book without series"""
        books = [
            {
                "book": "The Hobbit",
                "author": "J.R.R. Tolkien",
                "series": "—",
                "size": 300 * 1024 * 1024,
                "has_m4b": True,
            }
        ]
        display_selection_review(books)
        captured = capsys.readouterr()

        assert "The Hobbit" in captured.out
        assert "J.R.R. Tolkien" in captured.out

    def test_multiple_books(self, capsys) -> None:
        """Test displaying multiple books"""
        books = [
            {
                "book": "Book 1",
                "author": "Author 1",
                "series": "Series 1",
                "size": 100 * 1024 * 1024,
                "has_m4b": True,
            },
            {
                "book": "Book 2",
                "author": "Author 2",
                "series": "",
                "size": 200 * 1024 * 1024,
                "has_m4b": False,
            },
        ]
        display_selection_review(books)
        captured = capsys.readouterr()

        assert "2 audiobook" in captured.out
        assert "Book 1" in captured.out
        assert "Book 2" in captured.out


class TestHaveFzf:
    """Test have_fzf function"""

    def test_have_fzf_returns_bool(self) -> None:
        """Test that have_fzf returns a boolean"""
        result = have_fzf()
        assert isinstance(result, bool)

    @patch("shutil.which")
    def test_have_fzf_found(self, mock_which) -> None:
        """Test when fzf is available"""
        mock_which.return_value = "/usr/bin/fzf"
        result = have_fzf()
        assert result is True
        mock_which.assert_called_once_with("fzf")

    @patch("shutil.which")
    def test_have_fzf_not_found(self, mock_which) -> None:
        """Test when fzf is not available"""
        mock_which.return_value = None
        result = have_fzf()
        assert result is False
        mock_which.assert_called_once_with("fzf")


class TestInteractiveUtilsIntegration:
    """Integration tests for interactive utility functions"""

    def test_parse_and_display_workflow(self, capsys) -> None:
        """Test workflow of parsing selection and displaying review"""
        # Simulate selecting items 1,3,5 from a list
        all_books = [
            {"book": f"Book {i}", "author": "Author", "series": "", "size": 100 * 1024 * 1024, "has_m4b": True}
            for i in range(1, 11)
        ]

        # Parse selection
        indices = parse_selection_input("1,3,5", max_items=10)
        selected_books = [all_books[i] for i in indices]

        # Display review
        display_selection_review(selected_books)
        captured = capsys.readouterr()

        assert "3 audiobook" in captured.out
        assert "Book 1" in captured.out
        assert "Book 3" in captured.out
        assert "Book 5" in captured.out

    def test_config_and_recent_sources(self) -> None:
        """Test configuration handling with recent sources"""
        # Empty config
        config1 = {}
        sources1 = _get_recent_sources(config1)
        assert sources1 == []

        # Valid config
        config2 = {"recent_sources": ["/path/a", "/path/b"]}
        sources2 = _get_recent_sources(config2)
        assert len(sources2) == 2
        assert "/path/a" in sources2

        # Invalid config (not a list)
        config3 = {"recent_sources": {"not": "a list"}}
        sources3 = _get_recent_sources(config3)
        assert sources3 == []
