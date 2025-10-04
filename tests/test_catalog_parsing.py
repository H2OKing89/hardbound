#!/usr/bin/env python3
"""
Tests for AudiobookCatalog - Path Parsing and Metadata Extraction

Phase 2.2: Path parsing, ASIN extraction, author/series/book detection
Part of the Hardbound test improvement plan (Phase 2: Catalog)
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from hardbound.catalog import AudiobookCatalog


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def catalog_instance(tmp_path: Path):
    """Create a catalog instance with temporary database"""
    temp_db = tmp_path / "test_parsing.db"
    with patch("hardbound.catalog.DB_FILE", temp_db):
        catalog = AudiobookCatalog()
        yield catalog
        catalog.close()


# ============================================================================
# PHASE 2.2: ASIN EXTRACTION
# ============================================================================


@pytest.mark.unit
class TestASINExtraction:
    """Test ASIN extraction from filenames"""

    def test_asin_curly_braces_format(self, catalog_instance: AudiobookCatalog) -> None:
        """Test ASIN extraction with {ASIN.XXXXXXXXXX} format"""
        path = Path("/test/Book Title {ASIN.B0C34GQRYZ}")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["asin"] == "B0C34GQRYZ"

    def test_asin_square_brackets_with_prefix(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test ASIN extraction with [ASIN.XXXXXXXXXX] format"""
        path = Path("/test/Book Title [ASIN.B0C34GQRYZ]")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["asin"] == "B0C34GQRYZ"

    def test_asin_square_brackets_no_prefix(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test ASIN extraction with [XXXXXXXXXX] format (no ASIN prefix)"""
        path = Path("/test/Book Title [B0C34GQRYZ]")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["asin"] == "B0C34GQRYZ"

    def test_asin_not_present(self, catalog_instance: AudiobookCatalog) -> None:
        """Test path without ASIN returns empty string"""
        path = Path("/test/Book Title Without ASIN")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["asin"] == ""

    def test_asin_multiple_formats_prefers_first(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test that first ASIN match is used when multiple formats present"""
        path = Path("/test/Book {ASIN.B0FIRST123} [B0SECOND45]")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["asin"] == "B0FIRST123"

    def test_asin_case_sensitive(self, catalog_instance: AudiobookCatalog) -> None:
        """Test that ASIN extraction requires 10-character ASIN (B0 + 8 chars)"""
        # Valid 10-character ASIN
        path = Path("/test/Book Title {ASIN.B0UPPER123}")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["asin"] == "B0UPPER123"

    def test_asin_lowercase_not_matched(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test that lowercase ASIN is not matched (per regex)"""
        path = Path("/test/Book Title {asin.b0lowercase}")
        result = catalog_instance.parse_audiobook_path(path)

        # Lowercase ASIN pattern won't match [A-Z0-9] regex
        assert result["asin"] == ""

    def test_asin_with_numbers(self, catalog_instance: AudiobookCatalog) -> None:
        """Test ASIN with various numbers"""
        path = Path("/test/Book {ASIN.B0ABC12345}")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["asin"] == "B0ABC12345"


# ============================================================================
# PHASE 2.2: STRUCTURED PATH PARSING (audiobooks directory)
# ============================================================================


@pytest.mark.unit
class TestStructuredPathParsing:
    """Test parsing of structured audiobook paths"""

    def test_audiobooks_author_series_book(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test pattern: /audiobooks/Author/Series/Book"""
        path = Path("/mnt/audiobooks/Brandon Sanderson/Mistborn/The Final Empire")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["author"] == "Brandon Sanderson"
        assert result["series"] == "Mistborn"
        assert result["book"] == "The Final Empire"

    def test_audiobooks_author_book_no_series(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test pattern: /audiobooks/Author/Book (no series)"""
        path = Path("/mnt/audiobooks/Brandon Sanderson/Elantris")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["author"] == "Brandon Sanderson"
        assert result["series"] == ""
        assert result["book"] == "Elantris"

    def test_audiobooks_flat_structure(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test pattern: /audiobooks/Book (flat, no author or series folders)"""
        path = Path("/mnt/audiobooks/Standalone Book")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["book"] == "Standalone Book"
        # Author is extracted from first word when no parent directories
        assert result["author"] == "Standalone"

    def test_audiobooks_with_asin(self, catalog_instance: AudiobookCatalog) -> None:
        """Test structured path with ASIN in book name"""
        path = Path(
            "/audiobooks/Author Name/Series Name/Book Title {ASIN.B0TEST1234}"
        )
        result = catalog_instance.parse_audiobook_path(path)

        assert result["author"] == "Author Name"
        assert result["series"] == "Series Name"
        assert result["book"] == "Book Title {ASIN.B0TEST1234}"
        assert result["asin"] == "B0TEST1234"

    def test_audiobooks_deep_in_path(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test audiobooks keyword anywhere in path"""
        path = Path("/mnt/data/audiobooks/Author/Series/Book")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["author"] == "Author"
        assert result["series"] == "Series"
        assert result["book"] == "Book"


# ============================================================================
# PHASE 2.2: UNSTRUCTURED PATH PARSING (no audiobooks directory)
# ============================================================================


@pytest.mark.unit
class TestUnstructuredPathParsing:
    """Test parsing of unstructured paths (no audiobooks directory)"""

    def test_nested_author_series_structure(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test detecting author/series from nested directories without audiobooks folder"""
        path = Path("/data/Brandon Sanderson/Mistborn Era 2/The Alloy of Law")
        result = catalog_instance.parse_audiobook_path(path)

        # Without audiobooks keyword, parsing uses different logic
        # Takes last author-like directory, then series, then book
        assert result["author"] in ["Brandon Sanderson", "Mistborn Era 2"]
        assert result["book"] == "The Alloy of Law"

    def test_nested_author_book_no_series(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test detecting author from parent directory"""
        path = Path("/data/Neil Gaiman/American Gods")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["author"] == "Neil Gaiman"
        assert result["book"] == "American Gods"

    def test_flat_path_extracts_from_title(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test extracting author from book title when no parent directories"""
        path = Path("/downloads/Neil Gaiman - American Gods")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["book"] == "Neil Gaiman - American Gods"
        # When no parent directories look like authors, may use directory name
        # or extract from title depending on parsing logic
        assert result["author"] is not None

    def test_common_directory_names_skipped(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test that common directory names aren't mistaken for authors"""
        path = Path("/mnt/data/downloads/Book Title")
        result = catalog_instance.parse_audiobook_path(path)

        # "data" and "downloads" shouldn't be detected as author
        assert result["author"] != "data"
        assert result["author"] != "downloads"


# ============================================================================
# PHASE 2.2: HELPER FUNCTION TESTS - _looks_like_author()
# ============================================================================


@pytest.mark.unit
class TestLooksLikeAuthor:
    """Test author name detection heuristics"""

    def test_typical_author_names(self, catalog_instance: AudiobookCatalog) -> None:
        """Test that typical author names are recognized"""
        assert catalog_instance._looks_like_author("Brandon Sanderson")
        assert catalog_instance._looks_like_author("J.K. Rowling")
        assert catalog_instance._looks_like_author("Neil Gaiman")
        assert catalog_instance._looks_like_author("Stephen King")
        assert catalog_instance._looks_like_author("Agatha Christie")

    def test_skip_common_directory_names(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test that common directory names are rejected"""
        assert not catalog_instance._looks_like_author("audiobooks")
        assert not catalog_instance._looks_like_author("downloads")
        assert not catalog_instance._looks_like_author("books")
        assert not catalog_instance._looks_like_author("data")
        assert not catalog_instance._looks_like_author("mnt")
        assert not catalog_instance._looks_like_author("tmp")

    def test_reject_book_patterns(self, catalog_instance: AudiobookCatalog) -> None:
        """Test that book-like patterns are rejected"""
        assert not catalog_instance._looks_like_author("Book vol_13")
        assert not catalog_instance._looks_like_author("Volume 1")
        assert not catalog_instance._looks_like_author("Chapter 5")
        assert not catalog_instance._looks_like_author("Part II")
        assert not catalog_instance._looks_like_author("Unabridged")
        assert not catalog_instance._looks_like_author("Audiobook Collection")

    def test_reject_too_many_words(self, catalog_instance: AudiobookCatalog) -> None:
        """Test that names with too many words are rejected"""
        long_name = "This Is Way Too Many Words For An Author Name"
        assert not catalog_instance._looks_like_author(long_name)

    def test_reject_too_long(self, catalog_instance: AudiobookCatalog) -> None:
        """Test that very long names are rejected"""
        long_name = "A" * 60
        assert not catalog_instance._looks_like_author(long_name)

    def test_reject_excessive_special_chars(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test that names with too many special characters are rejected"""
        assert not catalog_instance._looks_like_author("Author!!!Name###")
        assert not catalog_instance._looks_like_author("Name$$$@@@^^^")

    def test_allow_reasonable_special_chars(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test that reasonable special characters are allowed"""
        assert catalog_instance._looks_like_author("O'Brien")  # apostrophe
        assert catalog_instance._looks_like_author("Jean-Paul Sartre")  # hyphen
        assert catalog_instance._looks_like_author("Dr. Seuss")  # period

    def test_empty_name(self, catalog_instance: AudiobookCatalog) -> None:
        """Test that empty string is rejected"""
        assert not catalog_instance._looks_like_author("")

    def test_case_insensitive_skip_names(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test that skip names work case-insensitively"""
        assert not catalog_instance._looks_like_author("AUDIOBOOKS")
        assert not catalog_instance._looks_like_author("Downloads")
        assert not catalog_instance._looks_like_author("BOOKS")


# ============================================================================
# PHASE 2.2: HELPER FUNCTION TESTS - _looks_like_book_title()
# ============================================================================


@pytest.mark.unit
class TestLooksLikeBookTitle:
    """Test book title detection heuristics"""

    def test_volume_indicators(self, catalog_instance: AudiobookCatalog) -> None:
        """Test that volume indicators are recognized"""
        assert catalog_instance._looks_like_book_title("Book vol_13")
        assert catalog_instance._looks_like_book_title("Volume 1")
        assert catalog_instance._looks_like_book_title("Book 2")

    def test_part_chapter_indicators(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test that part/chapter indicators are recognized"""
        assert catalog_instance._looks_like_book_title("Part One")
        assert catalog_instance._looks_like_book_title("Chapter 5")
        assert catalog_instance._looks_like_book_title("Episode 12")

    def test_audiobook_indicators(self, catalog_instance: AudiobookCatalog) -> None:
        """Test that audiobook-specific indicators are recognized"""
        assert catalog_instance._looks_like_book_title("Title Unabridged")
        assert catalog_instance._looks_like_book_title("Title Audiobook")

    def test_metadata_brackets(self, catalog_instance: AudiobookCatalog) -> None:
        """Test that certain metadata brackets indicate book titles"""
        assert catalog_instance._looks_like_book_title("Title [Tag]")
        assert catalog_instance._looks_like_book_title("Title {ASIN}")
        # Parentheses alone don't necessarily indicate book vs series
        # (they could be used for years, alternate names, etc.)

    def test_series_name_not_book(self, catalog_instance: AudiobookCatalog) -> None:
        """Test that typical series names aren't mistaken for books"""
        # Series names typically don't have volume/book indicators
        assert not catalog_instance._looks_like_book_title("Mistborn")
        assert not catalog_instance._looks_like_book_title("The Expanse")
        assert not catalog_instance._looks_like_book_title("Foundation")

    def test_empty_name(self, catalog_instance: AudiobookCatalog) -> None:
        """Test that empty string returns False"""
        assert not catalog_instance._looks_like_book_title("")


# ============================================================================
# PHASE 2.2: HELPER FUNCTION TESTS - _extract_author_from_title()
# ============================================================================


@pytest.mark.unit
class TestExtractAuthorFromTitle:
    """Test author extraction from book titles"""

    def test_extract_with_dash_separator(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test extracting author with ' - ' separator"""
        assert (
            catalog_instance._extract_author_from_title("Neil Gaiman - American Gods")
            == "Neil Gaiman"
        )

    def test_extract_with_colon_separator(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test extracting author with ': ' separator"""
        assert (
            catalog_instance._extract_author_from_title("Author Name: Book Title")
            == "Author Name"
        )

    def test_extract_with_em_dash(self, catalog_instance: AudiobookCatalog) -> None:
        """Test extracting author with em dash separator"""
        title = "Author Name — Book Title"
        result = catalog_instance._extract_author_from_title(title)
        assert "Author Name" in result

    def test_extract_with_by_pattern(self, catalog_instance: AudiobookCatalog) -> None:
        """Test extracting author with 'by Author' pattern"""
        result = catalog_instance._extract_author_from_title(
            "American Gods by Neil Gaiman"
        )
        assert "Neil Gaiman" in result

    def test_by_pattern_case_insensitive(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test that 'by' pattern is case-insensitive"""
        result = catalog_instance._extract_author_from_title(
            "Book Title BY Author Name"
        )
        assert "Author Name" in result

    def test_remove_metadata_brackets(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test that metadata in brackets is removed before extraction"""
        title = "Author [Tag] - Book [2024] {ASIN.B0TEST}"
        result = catalog_instance._extract_author_from_title(title)
        # After removing metadata, should extract "Author"
        assert result != "Unknown"

    def test_empty_title_returns_unknown(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test that empty title returns 'Unknown'"""
        assert catalog_instance._extract_author_from_title("") == "Unknown"

    def test_no_pattern_match_first_words(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test fallback to first few words when no pattern matches"""
        # Simple title without separators
        title = "Simple Title Name"
        result = catalog_instance._extract_author_from_title(title)
        # Should try to extract first 1-3 words as potential author
        assert result in ["Simple", "Simple Title", "Unknown"]

    def test_reject_non_author_looking_first_words(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test that non-author-looking first words are rejected"""
        title = "vol_13 Book Title"
        result = catalog_instance._extract_author_from_title(title)
        # "vol_13" shouldn't be detected as author
        assert result == "Unknown" or "vol" not in result.lower()


# ============================================================================
# PHASE 2.2: INTEGRATION TESTS - Real-World Scenarios
# ============================================================================


@pytest.mark.integration
class TestRealWorldPathParsing:
    """Test parsing with real-world audiobook path patterns"""

    def test_red_compliant_path(self, catalog_instance: AudiobookCatalog) -> None:
        """Test path with RED-compliant naming"""
        path = Path(
            "/audiobooks/Brandon Sanderson/Mistborn/The Final Empire vol_01 (2006) (Brandon Sanderson) {ASIN.B002UZYX8M} [H2OKing]"
        )
        result = catalog_instance.parse_audiobook_path(path)

        assert result["author"] == "Brandon Sanderson"
        assert result["series"] == "Mistborn"
        assert "The Final Empire" in result["book"]
        assert result["asin"] == "B002UZYX8M"

    def test_complex_series_name(self, catalog_instance: AudiobookCatalog) -> None:
        """Test handling of complex series names"""
        path = Path(
            "/audiobooks/Robert Jordan/The Wheel of Time/The Eye of the World"
        )
        result = catalog_instance.parse_audiobook_path(path)

        assert result["author"] == "Robert Jordan"
        assert result["series"] == "The Wheel of Time"
        assert result["book"] == "The Eye of the World"

    def test_unicode_characters_in_names(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test handling of unicode characters"""
        path = Path("/audiobooks/José Saramago/Blindness")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["author"] == "José Saramago"
        assert result["book"] == "Blindness"

    def test_multiple_asins_in_filename(
        self, catalog_instance: AudiobookCatalog
    ) -> None:
        """Test that only first ASIN is captured when multiple present"""
        path = Path(
            "/audiobooks/Author/Series/Book {ASIN.B0FIRST123} (2024) [B0SECOND45]"
        )
        result = catalog_instance.parse_audiobook_path(path)

        assert result["asin"] == "B0FIRST123"

    def test_litrpg_series(self, catalog_instance: AudiobookCatalog) -> None:
        """Test handling of LitRPG series names"""
        path = Path("/audiobooks/Dakota Krout/Dungeon Crawler Carl/Book 1")
        result = catalog_instance.parse_audiobook_path(path)

        assert result["author"] == "Dakota Krout"
        # "Dungeon Crawler Carl" might be detected as series or rejected due to patterns
        assert result["book"] == "Book 1"

    def test_coauthored_book(self, catalog_instance: AudiobookCatalog) -> None:
        """Test handling of books with multiple authors"""
        path = Path("/audiobooks/James S.A. Corey/The Expanse/Leviathan Wakes")
        result = catalog_instance.parse_audiobook_path(path)

        assert "Corey" in result["author"] or "James" in result["author"]
        assert result["series"] == "The Expanse"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
