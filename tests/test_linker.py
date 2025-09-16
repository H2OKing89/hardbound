"""
Tests for core hardlinking functionality
"""

from pathlib import Path

from hardbound.linker import (
    EXCLUDE_DEST_EXTS,
    EXCLUDE_DEST_NAMES,
    clean_base_name,
    dest_is_excluded,
    normalize_weird_ext,
    zero_pad_vol,
)


class TestZeroPadVol:
    """Test volume number padding functionality"""

    def test_zero_pad_basic(self):
        """Test basic zero padding"""
        assert zero_pad_vol("vol_4") == "vol_04"
        assert zero_pad_vol("vol_10") == "vol_10"
        assert zero_pad_vol("vol_123") == "vol_123"

    def test_zero_pad_custom_width(self):
        """Test custom width padding"""
        assert zero_pad_vol("vol_4", width=3) == "vol_004"
        assert zero_pad_vol("vol_10", width=3) == "vol_010"

    def test_zero_pad_no_change(self):
        """Test strings that don't need padding"""
        assert zero_pad_vol("volume_4") == "volume_4"
        assert zero_pad_vol("vol_04") == "vol_04"
        assert zero_pad_vol("no_vol_here") == "no_vol_here"

    def test_zero_pad_multiple(self):
        """Test multiple volume numbers in one string"""
        assert zero_pad_vol("vol_1_vol_2") == "vol_01_vol_02"


class TestNormalizeWeirdExt:
    """Test weird extension normalization"""

    def test_normalize_cue_extensions(self):
        """Test normalizing .cue extensions"""
        assert normalize_weird_ext("file.cue.jpg") == "file.jpg"
        assert normalize_weird_ext("file.cue.jpeg") == "file.jpeg"
        assert normalize_weird_ext("file.cue.png") == "file.png"
        assert normalize_weird_ext("file.cue.m4b") == "file.m4b"
        assert normalize_weird_ext("file.cue.mp3") == "file.mp3"

    def test_normalize_no_weird_ext(self):
        """Test files without weird extensions"""
        assert normalize_weird_ext("file.jpg") == "file.jpg"
        assert normalize_weird_ext("file.mp3") == "file.mp3"
        assert normalize_weird_ext("file.txt") == "file.txt"


class TestCleanBaseName:
    """Test base name cleaning functionality"""

    def test_clean_user_tags(self):
        """Test removing user tags from filenames"""
        assert clean_base_name("Book Title [UserName]") == "Book Title"
        assert clean_base_name("Another Book [H2OKing]") == "Another Book"
        assert clean_base_name("Series Vol 1 [2023]") == "Series Vol 1"

    def test_clean_no_tags(self):
        """Test filenames without tags"""
        assert clean_base_name("Clean Book Title") == "Clean Book Title"
        assert clean_base_name("Another Clean Title") == "Another Clean Title"

    def test_clean_multiple_spaces(self):
        """Test handling of multiple spaces"""
        assert clean_base_name("Book Title   [User]  ") == "Book Title"


class TestDestIsExcluded:
    """Test destination exclusion logic"""

    def test_exclude_by_name(self):
        """Test exclusion by filename"""
        for excluded_name in EXCLUDE_DEST_NAMES:
            path = Path("/test") / excluded_name
            assert dest_is_excluded(path)

    def test_exclude_by_extension(self):
        """Test exclusion by file extension"""
        for excluded_ext in EXCLUDE_DEST_EXTS:
            path = Path(f"/test/file{excluded_ext}")
            assert dest_is_excluded(path)

    def test_not_excluded(self):
        """Test files that should not be excluded"""
        assert not dest_is_excluded(Path("/test/file.mp3"))
        assert not dest_is_excluded(Path("/test/file.m4b"))
        assert not dest_is_excluded(Path("/test/file.jpg"))
        assert not dest_is_excluded(Path("/test/metadata.txt"))
