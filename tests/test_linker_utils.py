#!/usr/bin/env python3
"""
Tests for Linker Module - Utility Functions

Phase 3.1: Helper functions for file naming, path normalization, exclusions
Part of the Hardbound test improvement plan (Phase 3: Linker)
"""

from pathlib import Path

import pytest

from hardbound.linker import (
    clean_base_name,
    dest_is_excluded,
    normalize_weird_ext,
    same_inode,
    zero_pad_vol,
)


# ============================================================================
# PHASE 3.1: VOLUME PADDING
# ============================================================================


@pytest.mark.unit
class TestZeroPadVol:
    """Test volume number zero-padding"""

    def test_zero_pad_single_digit(self) -> None:
        """Test padding single-digit volume numbers"""
        assert zero_pad_vol("vol_4") == "vol_04"
        assert zero_pad_vol("vol_7") == "vol_07"
        assert zero_pad_vol("vol_9") == "vol_09"

    def test_zero_pad_already_padded(self) -> None:
        """Test that already-padded volumes are unchanged"""
        assert zero_pad_vol("vol_04") == "vol_04"
        assert zero_pad_vol("vol_07") == "vol_07"
        assert zero_pad_vol("vol_13") == "vol_13"

    def test_zero_pad_decimal_volumes(self) -> None:
        """Test padding decimal volumes (e.g., vol_7.5)"""
        assert zero_pad_vol("vol_7.5") == "vol_07.5"
        assert zero_pad_vol("vol_13.5") == "vol_13.5"
        assert zero_pad_vol("vol_4.75") == "vol_04.75"

    def test_zero_pad_within_string(self) -> None:
        """Test padding volume within a longer string"""
        result = zero_pad_vol("Book Title vol_4 Subtitle")
        assert "vol_04" in result
        assert result == "Book Title vol_04 Subtitle"

    def test_zero_pad_multiple_volumes(self) -> None:
        """Test padding multiple volumes in one string"""
        result = zero_pad_vol("vol_1 and vol_2 combined")
        assert "vol_01" in result
        assert "vol_02" in result

    def test_zero_pad_custom_width(self) -> None:
        """Test padding with custom width"""
        assert zero_pad_vol("vol_4", width=3) == "vol_004"
        assert zero_pad_vol("vol_42", width=3) == "vol_042"

    def test_zero_pad_no_volume(self) -> None:
        """Test string without volume numbers"""
        assert zero_pad_vol("Book Title") == "Book Title"
        assert zero_pad_vol("No volumes here") == "No volumes here"

    def test_zero_pad_preserves_other_text(self) -> None:
        """Test that non-volume text is preserved"""
        result = zero_pad_vol("The Final Empire vol_1 {ASIN.B0TEST}")
        assert result == "The Final Empire vol_01 {ASIN.B0TEST}"

    def test_zero_pad_edge_case_empty(self) -> None:
        """Test empty string"""
        assert zero_pad_vol("") == ""

    def test_zero_pad_invalid_volume_format(self) -> None:
        """Test that invalid volume formats are unchanged"""
        # Not matching the vol_N pattern
        assert zero_pad_vol("volume 4") == "volume 4"
        assert zero_pad_vol("v4") == "v4"


# ============================================================================
# PHASE 3.1: FILENAME NORMALIZATION
# ============================================================================


@pytest.mark.unit
class TestNormalizeWeirdExt:
    """Test normalization of weird file extensions"""

    def test_normalize_cue_jpg(self) -> None:
        """Test normalizing .cue.jpg to .jpg"""
        assert normalize_weird_ext("cover.cue.jpg") == "cover.jpg"

    def test_normalize_cue_jpeg(self) -> None:
        """Test normalizing .cue.jpeg to .jpeg"""
        assert normalize_weird_ext("image.cue.jpeg") == "image.jpeg"

    def test_normalize_cue_png(self) -> None:
        """Test normalizing .cue.png to .png"""
        assert normalize_weird_ext("cover.cue.png") == "cover.png"

    def test_normalize_cue_m4b(self) -> None:
        """Test normalizing .cue.m4b to .m4b"""
        assert normalize_weird_ext("audiobook.cue.m4b") == "audiobook.m4b"

    def test_normalize_cue_mp3(self) -> None:
        """Test normalizing .cue.mp3 to .mp3"""
        assert normalize_weird_ext("track.cue.mp3") == "track.mp3"

    def test_normalize_normal_ext(self) -> None:
        """Test that normal extensions are unchanged"""
        assert normalize_weird_ext("file.jpg") == "file.jpg"
        assert normalize_weird_ext("audio.m4b") == "audio.m4b"
        assert normalize_weird_ext("doc.pdf") == "doc.pdf"

    def test_normalize_preserves_path(self) -> None:
        """Test that path before extension is preserved"""
        assert (
            normalize_weird_ext("path/to/file.cue.jpg")
            == "path/to/file.jpg"
        )

    def test_normalize_empty_string(self) -> None:
        """Test empty string"""
        assert normalize_weird_ext("") == ""

    def test_normalize_no_extension(self) -> None:
        """Test filename without extension"""
        assert normalize_weird_ext("filename") == "filename"


# ============================================================================
# PHASE 3.1: BASE NAME CLEANING
# ============================================================================


@pytest.mark.unit
class TestCleanBaseName:
    """Test cleaning of base names (removing user tags)"""

    def test_clean_user_tag_square_brackets(self) -> None:
        """Test removing user tags in square brackets"""
        assert (
            clean_base_name("Book Title [H2OKing]") == "Book Title"
        )
        assert (
            clean_base_name("Book Title [UserName]") == "Book Title"
        )

    def test_clean_user_tag_curly_braces(self) -> None:
        """Test removing tags in curly braces (except ASIN)"""
        assert (
            clean_base_name("Book Title {UserTag}") == "Book Title"
        )

    def test_clean_preserves_asin(self) -> None:
        """Test that ASIN tags are preserved"""
        result = clean_base_name("Book Title {ASIN.B09CVBWLZT}")
        assert "ASIN.B09CVBWLZT" in result
        assert result == "Book Title {ASIN.B09CVBWLZT}"

    def test_clean_removes_user_but_keeps_asin(self) -> None:
        """Test removing user tag while keeping ASIN"""
        result = clean_base_name("Book Title [H2OKing] {ASIN.B09CVBWLZT}")
        assert "[H2OKing]" not in result
        assert "ASIN.B09CVBWLZT" in result

    def test_clean_multiple_tags(self) -> None:
        """Test removing multiple user tags"""
        result = clean_base_name("Book [Tag1] [Tag2] [Tag3]")
        assert result == "Book"

    def test_clean_mixed_brackets(self) -> None:
        """Test mixed bracket types"""
        result = clean_base_name("Book [Square] {Curly}")
        assert result == "Book"

    def test_clean_no_tags(self) -> None:
        """Test that names without tags are unchanged"""
        assert clean_base_name("Simple Book Title") == "Simple Book Title"

    def test_clean_empty_string(self) -> None:
        """Test empty string"""
        assert clean_base_name("") == ""

    def test_clean_tags_in_middle(self) -> None:
        """Test that tags in middle of name are preserved"""
        # Only removes tags at the END
        result = clean_base_name("Book [Middle] Title")
        assert "[Middle]" in result  # Not at end, so kept

    def test_clean_whitespace_handling(self) -> None:
        """Test proper whitespace handling"""
        result = clean_base_name("Book Title  [Tag]")
        assert result == "Book Title"  # Trailing spaces removed


# ============================================================================
# PHASE 3.1: DESTINATION EXCLUSIONS
# ============================================================================


@pytest.mark.unit
class TestDestIsExcluded:
    """Test destination exclusion logic"""

    def test_exclude_cover_jpg(self) -> None:
        """Test that cover.jpg is excluded"""
        assert dest_is_excluded(Path("cover.jpg"))
        assert dest_is_excluded(Path("/path/to/cover.jpg"))

    def test_exclude_metadata_json(self) -> None:
        """Test that metadata.json is excluded"""
        assert dest_is_excluded(Path("metadata.json"))
        assert dest_is_excluded(Path("/path/to/metadata.json"))

    def test_exclude_epub(self) -> None:
        """Test that .epub files are excluded"""
        assert dest_is_excluded(Path("book.epub"))
        assert dest_is_excluded(Path("/path/to/book.epub"))

    def test_exclude_case_insensitive(self) -> None:
        """Test that exclusions are case-insensitive"""
        assert dest_is_excluded(Path("COVER.JPG"))
        assert dest_is_excluded(Path("Cover.Jpg"))
        assert dest_is_excluded(Path("METADATA.JSON"))
        assert dest_is_excluded(Path("Book.EPUB"))

    def test_not_excluded_normal_files(self) -> None:
        """Test that normal files are not excluded"""
        assert not dest_is_excluded(Path("book.m4b"))
        assert not dest_is_excluded(Path("audiobook.mp3"))
        assert not dest_is_excluded(Path("document.pdf"))
        assert not dest_is_excluded(Path("image.jpg"))  # Not named "cover.jpg"

    def test_not_excluded_similar_names(self) -> None:
        """Test that similar but different names are not excluded"""
        assert not dest_is_excluded(Path("mycover.jpg"))  # Not exactly "cover.jpg"
        assert not dest_is_excluded(Path("metadata.txt"))  # Not .json


# ============================================================================
# PHASE 3.1: INODE COMPARISON
# ============================================================================


@pytest.mark.unit
class TestSameInode:
    """Test inode comparison for hardlinks"""

    def test_same_inode_identical_file(self, tmp_path: Path) -> None:
        """Test that same file returns True"""
        file = tmp_path / "test.txt"
        file.write_text("content")

        assert same_inode(file, file)

    def test_same_inode_hardlink(self, tmp_path: Path) -> None:
        """Test that hardlinked files return True"""
        import os

        original = tmp_path / "original.txt"
        original.write_text("content")

        hardlink = tmp_path / "hardlink.txt"
        os.link(original, hardlink)

        assert same_inode(original, hardlink)

    def test_same_inode_different_files(self, tmp_path: Path) -> None:
        """Test that different files return False"""
        file1 = tmp_path / "file1.txt"
        file2 = tmp_path / "file2.txt"
        file1.write_text("content1")
        file2.write_text("content2")

        assert not same_inode(file1, file2)

    def test_same_inode_nonexistent_file(self, tmp_path: Path) -> None:
        """Test that non-existent files return False"""
        existing = tmp_path / "existing.txt"
        existing.write_text("content")

        nonexistent = tmp_path / "nonexistent.txt"

        assert not same_inode(existing, nonexistent)
        assert not same_inode(nonexistent, existing)
        assert not same_inode(nonexistent, nonexistent)

    def test_same_inode_symlink(self, tmp_path: Path) -> None:
        """Test that symlinks resolve to same inode as target (stat follows symlinks)"""
        original = tmp_path / "original.txt"
        original.write_text("content")

        symlink = tmp_path / "symlink.txt"
        symlink.symlink_to(original)

        # stat() follows symlinks, so they appear as same inode
        assert same_inode(original, symlink)


# ============================================================================
# PHASE 3.1: INTEGRATION TESTS
# ============================================================================


@pytest.mark.integration
class TestLinkerUtilsIntegration:
    """Integration tests for linker utility functions"""

    def test_full_filename_processing_pipeline(self) -> None:
        """Test complete filename processing pipeline"""
        # Start with weird extension and user tags
        original = "Book Title vol_4 [H2OKing].cue.m4b"

        # Normalize extension
        normalized = normalize_weird_ext(original)
        assert normalized == "Book Title vol_4 [H2OKing].m4b"

        # Extract base name (without extension)
        base_name = Path(normalized).stem
        assert base_name == "Book Title vol_4 [H2OKing]"

        # Clean user tags
        cleaned = clean_base_name(base_name)
        assert cleaned == "Book Title vol_4"

        # Zero pad volume
        padded = zero_pad_vol(cleaned)
        assert padded == "Book Title vol_04"

    def test_red_compliant_filename_processing(self) -> None:
        """Test processing RED-compliant filenames with ASIN"""
        original = "Book vol_7 (2024) {ASIN.B0TEST123} [H2OKing].m4b"

        # Extract base name
        base_name = Path(original).stem

        # Clean but preserve ASIN
        cleaned = clean_base_name(base_name)
        assert "ASIN.B0TEST123" in cleaned
        assert "[H2OKing]" not in cleaned

        # Zero pad
        padded = zero_pad_vol(cleaned)
        assert "vol_07" in padded

    def test_exclusion_with_path_operations(self, tmp_path: Path) -> None:
        """Test exclusions work with actual Path objects"""
        # Create test files
        excluded_files = [
            tmp_path / "cover.jpg",
            tmp_path / "metadata.json",
            tmp_path / "book.epub",
        ]

        included_files = [
            tmp_path / "audiobook.m4b",
            tmp_path / "chapter01.mp3",
            tmp_path / "info.pdf",
        ]

        # Test exclusions
        for f in excluded_files:
            assert dest_is_excluded(f), f"Should exclude {f.name}"

        for f in included_files:
            assert not dest_is_excluded(f), f"Should not exclude {f.name}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
