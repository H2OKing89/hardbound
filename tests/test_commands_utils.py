"""Tests for commands module (Phase 4.1: Utility Functions)

Tests parse_selection_input, display_selection_review, and other utility functions.
"""

import pytest

from hardbound.commands import (
    parse_selection_input,
    display_selection_review,
    have_fzf,
    time_since,
)


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

    def test_zero_not_valid(self) -> None:
        """Test that 0 is not a valid selection (1-based input)"""
        result = parse_selection_input("0,1,2", max_items=10)
        assert result == [0, 1]  # Only 1 and 2 are valid

    def test_single_item_range(self) -> None:
        """Test range with same start and end"""
        result = parse_selection_input("5-5", max_items=10)
        assert result == [4]

    def test_complex_input(self) -> None:
        """Test complex real-world input"""
        result = parse_selection_input("1-3,10,12-15,20", max_items=25)
        assert result == [0, 1, 2, 9, 11, 12, 13, 14, 19]


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
        assert "The Lord of the Rings" in captured.out
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
        # Series should not be prominently displayed for "—"

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

    def test_missing_fields(self, capsys) -> None:
        """Test with missing book fields (uses defaults)"""
        books = [
            {
                "size": 100 * 1024 * 1024,
                "has_m4b": True,
            }
        ]
        display_selection_review(books)
        captured = capsys.readouterr()

        assert "Unknown Title" in captured.out
        assert "Unknown Author" in captured.out


class TestHaveFzf:
    """Test have_fzf function"""

    def test_have_fzf_returns_bool(self) -> None:
        """Test that have_fzf returns a boolean"""
        result = have_fzf()
        assert isinstance(result, bool)

    def test_have_fzf_checks_command(self) -> None:
        """Test that have_fzf checks for fzf command availability"""
        # This is an integration test - actual result depends on system
        result = have_fzf()
        # Just verify it doesn't crash and returns bool
        assert result in (True, False)


class TestTimeSince:
    """Test time_since function"""

    def test_time_since_seconds(self) -> None:
        """Test time_since with recent timestamp (rounds to minutes)"""
        import time

        timestamp = time.time() - 30  # 30 seconds ago
        result = time_since(timestamp)
        # Function rounds to minutes, so 30 seconds shows as "0m ago"
        assert "m ago" in result

    def test_time_since_minutes(self) -> None:
        """Test time_since with minutes ago"""
        import time

        timestamp = time.time() - (5 * 60)  # 5 minutes ago
        result = time_since(timestamp)
        assert "5m ago" in result or "minute" in result.lower()

    def test_time_since_hours(self) -> None:
        """Test time_since with hours ago"""
        import time

        timestamp = time.time() - (3 * 3600)  # 3 hours ago
        result = time_since(timestamp)
        assert "3h ago" in result or "hour" in result.lower()

    def test_time_since_days(self) -> None:
        """Test time_since with days ago"""
        import time

        timestamp = time.time() - (2 * 86400)  # 2 days ago
        result = time_since(timestamp)
        assert "2d ago" in result or "day" in result.lower()

    def test_time_since_future(self) -> None:
        """Test time_since with future timestamp"""
        import time

        timestamp = time.time() + 3600  # 1 hour in future
        result = time_since(timestamp)
        # Should handle gracefully (either "now" or negative time)
        assert isinstance(result, str)


class TestUtilityFunctionsIntegration:
    """Integration tests for utility functions"""

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

    def test_range_selection_and_display(self, capsys) -> None:
        """Test range selection and display"""
        all_books = [
            {"book": f"Book {i}", "author": "Author", "series": "Series", "size": 100 * 1024 * 1024, "has_m4b": True}
            for i in range(1, 11)
        ]

        # Parse range selection
        indices = parse_selection_input("5-8", max_items=10)
        selected_books = [all_books[i] for i in indices]

        # Should have 4 books (5, 6, 7, 8)
        assert len(selected_books) == 4

        # Display review
        display_selection_review(selected_books)
        captured = capsys.readouterr()

        assert "4 audiobook" in captured.out
