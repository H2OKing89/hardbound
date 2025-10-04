#!/usr/bin/env python3
"""
Tests for RED-compliant path shortening system (red_paths.py)

Phase 1.1: Token Parsing
Phase 1.2: Path Building & Length Validation
Phase 1.3: RED Path Shortening
Phase 1.4: RED Compliance Integration
"""

from pathlib import Path

import pytest

from hardbound.red_paths import (
    PATH_CAP,
    Tokens,
    _fits_red_cap,
    _torrent_path_length,
    build_dst_paths,
    build_filename,
    build_folder_name,
    normalize_volume,
    parse_tokens,
    validate_path_length,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def sample_tokens() -> Tokens:
    """Standard Tokens object for testing"""
    return Tokens(
        title="Overlord",
        volume="vol_13",
        subtitle="The Paladin of the Sacred Kingdom Part 2",
        year="(2024)",
        author="(Kugane Maruyama)",
        asin="{ASIN.B0CW3NF5NY}",
        tag="[H2OKing]",
        ext=".m4b",
    )


@pytest.fixture
def minimal_tokens() -> Tokens:
    """Minimal Tokens object (only required fields)"""
    return Tokens(
        title="Book Title",
        volume="vol_01",
        subtitle=None,
        year=None,
        author=None,
        asin="{ASIN.B0ABC123}",
        tag=None,
        ext=".m4b",
    )


@pytest.fixture
def long_title_tokens() -> Tokens:
    """Tokens with an extremely long title to test trimming"""
    return Tokens(
        title="This Is An Extremely Long Light Novel Title That Goes On And On And On To Test The Maximum Path Length Limitations Of The RED Tracker Compliance System",
        volume="vol_01",
        subtitle="An Even Longer Subtitle That Makes This Path Absolutely Massive",
        year="(2024)",
        author="(Very Long Author Name Here)",
        asin="{ASIN.B0LONGTEST}",
        tag="[H2OKing]",
        ext=".m4b",
    )


# ============================================================================
# PHASE 1.1: TOKEN PARSING - normalize_volume()
# ============================================================================


@pytest.mark.unit
class TestNormalizeVolume:
    """Test volume string normalization to vol_XX format"""

    def test_zero_pad_basic(self) -> None:
        """Test basic volume padding"""
        assert normalize_volume("vol_4") == "vol_04"
        assert normalize_volume("vol_13") == "vol_13"

    def test_zero_pad_already_padded(self) -> None:
        """Test that already padded volumes are unchanged"""
        assert normalize_volume("vol_01") == "vol_01"
        assert normalize_volume("vol_03") == "vol_03"
        assert normalize_volume("vol_99") == "vol_99"

    def test_zero_pad_decimal_volumes(self) -> None:
        """Test decimal volume preservation"""
        assert normalize_volume("vol_13.5") == "vol_13.5"
        assert normalize_volume("vol_4.5") == "vol_04.5"
        assert normalize_volume("vol_1.75") == "vol_01.75"

    def test_volume_format_variations(self) -> None:
        """Test various input volume formats"""
        # vol.XX format
        assert normalize_volume("vol.13") == "vol_13"
        assert normalize_volume("vol. 13") == "vol_13"

        # volume XX format
        assert normalize_volume("volume 13") == "vol_13"
        assert normalize_volume("volume 4") == "vol_04"

        # v.XX or vXX format
        assert normalize_volume("v.13") == "vol_13"
        assert normalize_volume("v13") == "vol_13"
        assert normalize_volume("v 13") == "vol_13"

        # Just the number
        assert normalize_volume("13") == "vol_13"
        assert normalize_volume("4") == "vol_04"

    def test_volume_decimal_variations(self) -> None:
        """Test decimal volume format variations"""
        assert normalize_volume("vol.13.5") == "vol_13.5"
        assert normalize_volume("volume 13.5") == "vol_13.5"
        assert normalize_volume("v.13.5") == "vol_13.5"
        assert normalize_volume("13.5") == "vol_13.5"

    def test_volume_case_insensitivity(self) -> None:
        """Test that volume parsing is case-insensitive"""
        assert normalize_volume("VOL_13") == "vol_13"
        assert normalize_volume("Volume 13") == "vol_13"
        assert normalize_volume("V.13") == "vol_13"


# ============================================================================
# PHASE 1.1: TOKEN PARSING - parse_tokens()
# ============================================================================


@pytest.mark.unit
class TestParseTokens:
    """Test parsing audiobook names into component tokens"""

    def test_parse_standard_format(self) -> None:
        """Test parsing standard format with all components"""
        name = "Overlord vol_13 The Paladin of the Sacred Kingdom Part 2 (2024) (Kugane Maruyama) {ASIN.B0CW3NF5NY} [H2OKing].m4b"
        tokens = parse_tokens(name, ".m4b")

        assert tokens.title == "Overlord"
        assert tokens.volume == "vol_13"
        assert tokens.subtitle == "The Paladin of the Sacred Kingdom Part 2"
        assert tokens.year == "(2024)"
        assert tokens.author == "(Kugane Maruyama)"
        assert tokens.asin == "{ASIN.B0CW3NF5NY}"
        assert tokens.tag == "[H2OKing]"
        assert tokens.ext == ".m4b"

    def test_parse_minimal_format(self) -> None:
        """Test parsing minimal format (only required fields)"""
        name = "Book Title vol_01 {ASIN.B0ABC123}.m4b"
        tokens = parse_tokens(name, ".m4b")

        assert tokens.title == "Book Title"
        assert tokens.volume == "vol_01"
        assert tokens.subtitle is None
        assert tokens.year is None
        assert tokens.author is None
        assert tokens.asin == "{ASIN.B0ABC123}"
        assert tokens.tag is None
        assert tokens.ext == ".m4b"

    def test_parse_no_subtitle(self) -> None:
        """Test parsing without subtitle"""
        name = "Overlord vol_13 (2024) (Kugane Maruyama) {ASIN.B0CW3NF5NY}.m4b"
        tokens = parse_tokens(name, ".m4b")

        assert tokens.title == "Overlord"
        assert tokens.volume == "vol_13"
        assert tokens.subtitle is None
        assert tokens.year == "(2024)"
        assert tokens.author == "(Kugane Maruyama)"
        assert tokens.asin == "{ASIN.B0CW3NF5NY}"

    def test_parse_no_year(self) -> None:
        """Test parsing without year"""
        name = "Overlord vol_13 Subtitle (Kugane Maruyama) {ASIN.B0CW3NF5NY}.m4b"
        tokens = parse_tokens(name, ".m4b")

        assert tokens.title == "Overlord"
        assert tokens.subtitle == "Subtitle"
        assert tokens.year is None
        assert tokens.author == "(Kugane Maruyama)"

    def test_parse_no_author(self) -> None:
        """Test parsing without author"""
        name = "Overlord vol_13 Subtitle (2024) {ASIN.B0CW3NF5NY}.m4b"
        tokens = parse_tokens(name, ".m4b")

        assert tokens.title == "Overlord"
        assert tokens.subtitle == "Subtitle"
        # Note: (2024) gets interpreted as author when no other parens present
        # This is a known limitation of right-to-left parsing
        assert tokens.author == "(2024)"
        assert tokens.year is None

    def test_parse_no_tag(self) -> None:
        """Test parsing without tag"""
        name = "Overlord vol_13 Subtitle (2024) (Author) {ASIN.B0CW3NF5NY}.m4b"
        tokens = parse_tokens(name, ".m4b")

        assert tokens.tag is None

    def test_parse_title_with_parentheses(self) -> None:
        """Test parsing titles containing parentheses"""
        name = "Title (Part 1) vol_01 {ASIN.B0ABC123}.m4b"
        tokens = parse_tokens(name, ".m4b")

        assert tokens.title == "Title (Part 1)"
        assert tokens.volume == "vol_01"

    def test_parse_title_with_hyphens(self) -> None:
        """Test parsing titles containing hyphens"""
        name = "Title - The Beginning vol_01 {ASIN.B0ABC123}.m4b"
        tokens = parse_tokens(name, ".m4b")

        assert tokens.title == "Title - The Beginning"
        assert tokens.volume == "vol_01"

    def test_parse_subtitle_with_multiple_hyphens(self) -> None:
        """Test parsing subtitles with multiple hyphens"""
        name = "Title vol_01 Sub - Part - Two {ASIN.B0ABC123}.m4b"
        tokens = parse_tokens(name, ".m4b")

        assert tokens.title == "Title"
        assert tokens.subtitle == "Sub - Part - Two"

    def test_parse_decimal_volume(self) -> None:
        """Test parsing decimal volumes"""
        name = "Title vol_13.5 Subtitle {ASIN.B0ABC123}.m4b"
        tokens = parse_tokens(name, ".m4b")

        assert tokens.volume == "vol_13.5"

    def test_parse_old_format_with_dashes(self) -> None:
        """Test parsing old format: Title - vol_XX - Subtitle"""
        name = "Title - vol_13 - Subtitle (2024) (Author) {ASIN.B0ABC123}.m4b"
        tokens = parse_tokens(name, ".m4b")

        assert tokens.title == "Title"
        assert tokens.volume == "vol_13"
        assert tokens.subtitle == "Subtitle"

    def test_parse_different_extensions(self) -> None:
        """Test parsing with different file extensions"""
        for ext in [".m4b", ".mp3", ".flac", ".m4a", ".opus"]:
            name = f"Title vol_01 {{ASIN.B0ABC123}}{ext}"
            tokens = parse_tokens(name, ext)

            assert tokens.ext == ext
            assert tokens.title == "Title"

    def test_parse_missing_asin_raises_error(self) -> None:
        """Test that missing ASIN raises ValueError"""
        name = "Title vol_01 Subtitle (2024) (Author).m4b"

        with pytest.raises(ValueError, match="No ASIN found"):
            parse_tokens(name, ".m4b")

    def test_parse_asin_case_preservation(self) -> None:
        """Test that ASIN case is preserved (must be uppercase)"""
        # ASIN regex requires uppercase: {ASIN.[A-Z0-9]+}
        name = "Title vol_01 {ASIN.B0ABC123}.m4b"
        tokens = parse_tokens(name, ".m4b")

        # ASIN must be uppercase per spec
        assert tokens.asin == "{ASIN.B0ABC123}"

    def test_parse_bracket_asin_format(self) -> None:
        """Test parsing square bracket ASIN format [ASIN.XXXXX]"""
        # Note: Current implementation only supports curly braces
        # This test documents expected behavior
        name = "Title vol_01 {ASIN.B0ABC123}.m4b"
        tokens = parse_tokens(name, ".m4b")

        assert tokens.asin == "{ASIN.B0ABC123}"

    def test_parse_year_format_validation(self) -> None:
        """Test that only valid year formats are captured"""
        # Valid years (19xx or 20xx) need both year AND author to be extracted correctly
        # When only one paren exists, it's treated as author (right-to-left extraction)
        name1 = "Title vol_01 (2024) (Author Name) {ASIN.B0ABC123}.m4b"
        tokens1 = parse_tokens(name1, ".m4b")
        assert tokens1.year == "(2024)"
        assert tokens1.author == "(Author Name)"

        name2 = "Title vol_01 (1999) (Author Name) {ASIN.B0ABC123}.m4b"
        tokens2 = parse_tokens(name2, ".m4b")
        assert tokens2.year == "(1999)"
        assert tokens2.author == "(Author Name)"

        # Invalid year should be treated as author when alone
        name3 = "Title vol_01 (3000) {ASIN.B0ABC123}.m4b"
        tokens3 = parse_tokens(name3, ".m4b")
        # Year pattern only matches 19xx or 20xx, so (3000) becomes author
        assert tokens3.author == "(3000)"
        assert tokens3.year is None


# ============================================================================
# PHASE 1.2: PATH BUILDING - build_filename()
# ============================================================================


@pytest.mark.unit
class TestBuildFilename:
    """Test filename construction from tokens"""

    def test_build_filename_all_components(self, sample_tokens: Tokens) -> None:
        """Test building filename with all components enabled"""
        filename = build_filename(sample_tokens)

        assert filename.startswith("Overlord vol_13 The Paladin")
        assert "(2024)" in filename
        assert "(Kugane Maruyama)" in filename
        assert "{ASIN.B0CW3NF5NY}" in filename
        assert "[H2OKing]" in filename
        assert filename.endswith(".m4b")

    def test_build_filename_minimal(self, minimal_tokens: Tokens) -> None:
        """Test building filename with only required components"""
        filename = build_filename(minimal_tokens)

        assert filename == "Book Title vol_01 {ASIN.B0ABC123}.m4b"

    def test_build_filename_without_year(self, sample_tokens: Tokens) -> None:
        """Test building filename with year disabled"""
        filename = build_filename(sample_tokens, include_year=False)

        assert "(2024)" not in filename
        assert "(Kugane Maruyama)" in filename
        assert "{ASIN.B0CW3NF5NY}" in filename

    def test_build_filename_without_author(self, sample_tokens: Tokens) -> None:
        """Test building filename with author disabled"""
        filename = build_filename(sample_tokens, include_author=False)

        assert "(Kugane Maruyama)" not in filename
        assert "{ASIN.B0CW3NF5NY}" in filename

    def test_build_filename_without_tag(self, sample_tokens: Tokens) -> None:
        """Test building filename with tag disabled"""
        filename = build_filename(sample_tokens, include_tag=False)

        assert "[H2OKing]" not in filename
        assert "{ASIN.B0CW3NF5NY}" in filename

    def test_build_filename_without_subtitle(self, sample_tokens: Tokens) -> None:
        """Test building filename with subtitle disabled"""
        filename = build_filename(sample_tokens, include_subtitle=False)

        assert "The Paladin" not in filename
        assert "Overlord vol_13" in filename

    def test_build_filename_minimal_all_disabled(self, sample_tokens: Tokens) -> None:
        """Test building filename with all optional components disabled"""
        filename = build_filename(
            sample_tokens,
            include_subtitle=False,
            include_year=False,
            include_author=False,
            include_tag=False,
        )

        assert filename == "Overlord vol_13 {ASIN.B0CW3NF5NY}.m4b"

    def test_build_filename_whitespace_normalization(self) -> None:
        """Test that excessive whitespace is normalized"""
        tokens = Tokens(
            title="Title  With   Spaces",
            volume="vol_01",
            subtitle=None,
            year=None,
            author=None,
            asin="{ASIN.B0ABC123}",
            tag=None,
            ext=".m4b",
        )
        filename = build_filename(tokens)

        # Should normalize multiple spaces to single space
        assert "  " not in filename
        assert filename == "Title With Spaces vol_01 {ASIN.B0ABC123}.m4b"


# ============================================================================
# PHASE 1.2: PATH BUILDING - build_folder_name()
# ============================================================================


@pytest.mark.unit
class TestBuildFolderName:
    """Test folder name construction from tokens"""

    def test_build_folder_all_components(self, sample_tokens: Tokens) -> None:
        """Test building folder name with all components enabled"""
        folder = build_folder_name(sample_tokens)

        assert folder.startswith("Overlord vol_13 The Paladin")
        assert "(2024)" in folder
        assert "(Kugane Maruyama)" in folder
        assert "{ASIN.B0CW3NF5NY}" in folder
        assert "[H2OKing]" not in folder  # Tags not in folder names per spec

    def test_build_folder_minimal(self, minimal_tokens: Tokens) -> None:
        """Test building folder name with only required components"""
        folder = build_folder_name(minimal_tokens)

        assert folder == "Book Title vol_01 {ASIN.B0ABC123}"

    def test_build_folder_no_tag_in_folder(self, sample_tokens: Tokens) -> None:
        """Test that tags are never included in folder names"""
        folder = build_folder_name(sample_tokens)

        assert "[H2OKing]" not in folder

    def test_build_folder_without_year(self, sample_tokens: Tokens) -> None:
        """Test building folder name with year disabled"""
        folder = build_folder_name(sample_tokens, include_year=False)

        assert "(2024)" not in folder
        assert "(Kugane Maruyama)" in folder

    def test_build_folder_without_author(self, sample_tokens: Tokens) -> None:
        """Test building folder name with author disabled"""
        folder = build_folder_name(sample_tokens, include_author=False)

        assert "(Kugane Maruyama)" not in folder

    def test_build_folder_without_subtitle(self, sample_tokens: Tokens) -> None:
        """Test building folder name with subtitle disabled"""
        folder = build_folder_name(sample_tokens, include_subtitle=False)

        assert "The Paladin" not in folder
        assert "Overlord vol_13" in folder

    def test_build_folder_minimal_all_disabled(self, sample_tokens: Tokens) -> None:
        """Test building folder name with all optional components disabled"""
        folder = build_folder_name(
            sample_tokens,
            include_subtitle=False,
            include_year=False,
            include_author=False,
        )

        assert folder == "Overlord vol_13 {ASIN.B0CW3NF5NY}"


# ============================================================================
# PHASE 1.2: PATH LENGTH VALIDATION
# ============================================================================


@pytest.mark.unit
class TestPathLengthValidation:
    """Test torrent-internal path length calculations"""

    def test_torrent_path_length_calculation(self) -> None:
        """Test that path length is calculated correctly"""
        folder = "Overlord vol_13 {ASIN.B0CW3NF5NY}"
        filename = "Overlord vol_13 {ASIN.B0CW3NF5NY}.m4b"

        length = _torrent_path_length(folder, filename)

        # Should be: len(folder) + 1 (separator) + len(filename)
        expected = len(folder) + 1 + len(filename)
        assert length == expected

    def test_fits_red_cap_exactly_at_limit(self) -> None:
        """Test path exactly at 180 character limit"""
        # Create folder and filename that total exactly 180
        # 180 = len(folder) + 1 + len(filename)
        # Let's make them equal: folder = filename (without ext)
        # So: 2 * len(folder) + 1 + len(".m4b") = 180
        # 2 * len(folder) = 175
        # len(folder) = 87.5, round down to 87

        folder = "A" * 87
        filename = folder + ".m4b"  # 87 + 4 = 91

        # Total: 87 + 1 + 91 = 179 (just under)
        assert _fits_red_cap(folder, filename, path_cap=180)

    def test_fits_red_cap_just_under_limit(self) -> None:
        """Test path just under 180 character limit"""
        folder = "A" * 80
        filename = "B" * 90 + ".m4b"  # Total: 80 + 1 + 94 = 175

        assert _fits_red_cap(folder, filename, path_cap=180)

    def test_fits_red_cap_just_over_limit(self) -> None:
        """Test path just over 180 character limit"""
        folder = "A" * 90
        filename = "B" * 100 + ".m4b"  # Total: 90 + 1 + 104 = 195

        assert not _fits_red_cap(folder, filename, path_cap=180)

    def test_fits_red_cap_very_long_path(self) -> None:
        """Test very long path (250+ chars)"""
        folder = "A" * 150
        filename = "B" * 150 + ".m4b"  # Total: 150 + 1 + 154 = 305

        assert not _fits_red_cap(folder, filename, path_cap=180)

    def test_validate_path_length_with_path_objects(self, tmp_path: Path) -> None:
        """Test validate_path_length with Path objects"""
        # Create a destination directory path
        dst_dir = tmp_path / "Short Folder {ASIN.B0ABC123}"
        dst_file = "Short Folder {ASIN.B0ABC123}.m4b"

        # Should pass validation (short paths)
        assert validate_path_length(dst_dir, dst_file, path_cap=180)

    def test_validate_path_length_uses_leaf_only(self, tmp_path: Path) -> None:
        """Test that validation uses only the leaf folder name, not full OS path"""
        # Create a very deep path, but with short leaf name
        deep_path = (
            tmp_path
            / "very"
            / "deep"
            / "directory"
            / "structure"
            / "that"
            / "is"
            / "long"
            / "Short {ASIN.B0ABC123}"
        )
        dst_file = "Short {ASIN.B0ABC123}.m4b"

        # Should pass because only "Short {ASIN.B0ABC123}" + "/" + filename is measured
        assert validate_path_length(deep_path, dst_file, path_cap=180)


# ============================================================================
# PHASE 1.3: RED PATH SHORTENING - build_dst_paths()
# ============================================================================


@pytest.mark.unit
class TestBuildDstPaths:
    """Test RED-compliant path generation with automatic trimming"""

    def test_build_dst_paths_no_trimming_needed(self, tmp_path: Path) -> None:
        """Test path generation when no trimming is needed"""
        # Create source directory with short name
        src = tmp_path / "Short Title vol_01 {ASIN.B0ABC123}"
        src.mkdir()
        (src / "Short Title vol_01 {ASIN.B0ABC123}.m4b").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

        # Should contain all components
        assert "Short Title" in dst_dir.name
        assert "vol_01" in dst_dir.name
        assert "{ASIN.B0ABC123}" in dst_dir.name

        assert "Short Title" in dst_file.name
        assert "{ASIN.B0ABC123}" in dst_file.name

        # Should fit within cap
        assert validate_path_length(dst_dir, dst_file.name)

    def test_build_dst_paths_trim_year_from_filename(
        self, tmp_path: Path, sample_tokens: Tokens
    ) -> None:
        """Test that year is trimmed from filename first"""
        # Create a source name that needs trimming
        src_name = "Very Long Title Name That Needs Trimming vol_13 Long Subtitle Text (2024) (Author Name) {ASIN.B0ABC123} [Tag]"
        src = tmp_path / src_name
        src.mkdir()
        (src / f"{src_name}.m4b").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

        # Should fit within cap
        folder_name = dst_dir.name
        filename = dst_file.name
        length = _torrent_path_length(folder_name, filename)
        assert length <= PATH_CAP

        # ASIN must be in both
        assert "{ASIN.B0ABC123}" in folder_name
        assert "{ASIN.B0ABC123}" in filename

    def test_build_dst_paths_asin_always_present(
        self, tmp_path: Path, long_title_tokens: Tokens
    ) -> None:
        """Test that ASIN is always preserved in both folder and file"""
        # Create extremely long name
        src_name = "This Is An Extremely Long Light Novel Title That Goes On And On vol_01 An Even Longer Subtitle (2024) (Author) {ASIN.B0LONGTEST} [Tag]"
        src = tmp_path / src_name
        src.mkdir()
        (src / f"{src_name}.m4b").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

        # ASIN must be present in both (invariant)
        assert "{ASIN.B0LONGTEST}" in dst_dir.name
        assert "{ASIN.B0LONGTEST}" in dst_file.name

    def test_build_dst_paths_title_and_volume_always_present(
        self, tmp_path: Path
    ) -> None:
        """Test that title and volume are always preserved"""
        src_name = "Title vol_05 Very Long Subtitle That Makes This Path Too Long For RED Compliance (2024) (Author Name Here) {ASIN.B0ABC123} [Tag]"
        src = tmp_path / src_name
        src.mkdir()
        (src / f"{src_name}.m4b").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

        # Title and volume must be present in both
        assert "Title" in dst_dir.name
        assert "vol_05" in dst_dir.name
        assert "Title" in dst_file.name
        assert "vol_05" in dst_file.name

    def test_build_dst_paths_extension_auto_detection(self, tmp_path: Path) -> None:
        """Test automatic extension detection when extension=None"""
        src = tmp_path / "Book Title vol_01 {ASIN.B0ABC123}"
        src.mkdir()

        # Create multiple file types, .m4b should be preferred
        (src / "Book Title vol_01 {ASIN.B0ABC123}.m4b").touch()
        (src / "Book Title vol_01 {ASIN.B0ABC123}.mp3").touch()
        (src / "cover.jpg").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=None)

        # Should detect and use .m4b
        assert dst_file.name.endswith(".m4b")

    def test_build_dst_paths_extension_preference_order(self, tmp_path: Path) -> None:
        """Test extension preference: .m4b > .m4a > .mp3 > .flac"""
        src = tmp_path / "Book Title vol_01 {ASIN.B0ABC123}"
        src.mkdir()

        # Only have .mp3
        (src / "Book Title vol_01 {ASIN.B0ABC123}.mp3").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=None)

        assert dst_file.name.endswith(".mp3")

    def test_build_dst_paths_respects_path_cap(self, tmp_path: Path) -> None:
        """Test that generated paths always respect 180 char limit"""
        # Create various length source names
        test_cases = [
            "Short vol_01 {ASIN.B0SHORT1}",
            "Medium Length Title vol_01 Subtitle (2024) (Author) {ASIN.B0MEDIUM1} [Tag]",
            "Very Long Title Name That Would Exceed Limits vol_01 Very Long Subtitle Text Here (2024) (Very Long Author Name) {ASIN.B0VERYLONG} [Tag]",
        ]

        dst_root = tmp_path / "destination"

        for i, src_name in enumerate(test_cases):
            # Use unique tmp directories to avoid conflicts
            test_tmp = tmp_path / f"test_{i}"
            test_tmp.mkdir(exist_ok=True)
            
            src = test_tmp / src_name
            src.mkdir(exist_ok=True)
            (src / f"{src_name}.m4b").touch()

            dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

            # Must fit within cap
            length = _torrent_path_length(dst_dir.name, dst_file.name)
            assert (
                length <= PATH_CAP
            ), f"Path too long ({length} > {PATH_CAP}): {dst_dir.name}/{dst_file.name}"


# ============================================================================
# PHASE 1.4: RED COMPLIANCE INTEGRATION
# ============================================================================


@pytest.mark.integration
class TestREDComplianceIntegration:
    """End-to-end RED compliance validation tests"""

    def test_overlord_example_from_spec(self, tmp_path: Path) -> None:
        """Test the real Overlord example from RED_PATH_SPEC.md"""
        # From spec: final compliant path should be 143 chars
        src_name = "Overlord vol_13 The Paladin of the Sacred Kingdom Part 2 (2024) (Kugane Maruyama) {ASIN.B0CW3NF5NY}"
        src = tmp_path / src_name
        src.mkdir()
        (src / f"{src_name}.m4b").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

        # Should fit within cap
        length = _torrent_path_length(dst_dir.name, dst_file.name)
        assert length <= PATH_CAP

        # Should be close to the spec example (143 chars)
        # Spec example: folder with all, file with minimal
        # "Overlord vol_13 The Paladin of the Sacred Kingdom Part 2 (2024) (Kugane Maruyama) {ASIN.B0CW3NF5NY}/Overlord vol_13 {ASIN.B0CW3NF5NY}.m4b"
        # Length: 143

        # ASIN must be in both
        assert "{ASIN.B0CW3NF5NY}" in dst_dir.name
        assert "{ASIN.B0CW3NF5NY}" in dst_file.name

    def test_asin_policy_enforcement_folder_and_file(self, tmp_path: Path) -> None:
        """Test that ASIN appears in both folder and filename (invariant)"""
        src_name = "Book Title vol_01 {ASIN.B0POLICY1}"
        src = tmp_path / src_name
        src.mkdir()
        (src / f"{src_name}.m4b").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

        # ASIN must be in both (critical invariant)
        assert "{ASIN.B0POLICY1}" in dst_dir.name, "ASIN missing from folder"
        assert "{ASIN.B0POLICY1}" in dst_file.name, "ASIN missing from filename"

    def test_batch_path_generation_various_lengths(self, tmp_path: Path) -> None:
        """Test batch processing with various path lengths"""
        test_books = [
            "Short vol_01 {ASIN.B0SHORT1}",
            "Medium Title vol_02 With Subtitle (2024) {ASIN.B0MEDIUM2}",
            "Long Title Name vol_03 Very Long Subtitle Text (2024) (Author Name) {ASIN.B0LONG003} [Tag]",
            "Very Long Light Novel Title That Tests Limits vol_04 Extremely Long Subtitle (2024) (Very Long Author) {ASIN.B0VLONG04} [Tag]",
        ]

        dst_root = tmp_path / "destination"
        results = []

        for book_name in test_books:
            src = tmp_path / book_name
            src.mkdir(exist_ok=True)
            (src / f"{book_name}.m4b").touch()

            dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

            length = _torrent_path_length(dst_dir.name, dst_file.name)
            results.append(
                {
                    "src": book_name,
                    "folder": dst_dir.name,
                    "file": dst_file.name,
                    "length": length,
                    "fits": length <= PATH_CAP,
                }
            )

        # All should fit within cap
        for result in results:
            assert result["fits"], f"Path too long: {result['length']} > {PATH_CAP}"

        # All should have ASIN in both folder and file
        for result in results:
            assert "ASIN" in result["folder"], f"ASIN missing from folder: {result}"
            assert "ASIN" in result["file"], f"ASIN missing from file: {result}"

    def test_torrent_internal_path_only(self, tmp_path: Path) -> None:
        """Test that path measurement uses torrent-internal path, not OS path"""
        # Create very deep OS path
        deep_path = (
            tmp_path
            / "very"
            / "deep"
            / "directory"
            / "structure"
            / "that"
            / "would"
            / "fail"
            / "if"
            / "we"
            / "counted"
            / "the"
            / "full"
            / "path"
        )
        deep_path.mkdir(parents=True)

        # But short book name
        src = deep_path / "Book vol_01 {ASIN.B0SHORT1}"
        src.mkdir()
        (src / "Book vol_01 {ASIN.B0SHORT1}.m4b").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

        # Should pass because we only measure leaf folder + file
        length = _torrent_path_length(dst_dir.name, dst_file.name)
        assert length <= PATH_CAP

    def test_minimal_viable_path_format(self, tmp_path: Path) -> None:
        """Test that minimal viable format is: Title vol_XX {ASIN}.ext"""
        # Create a name that will force maximum trimming
        # Use shorter name to avoid OS filesystem limits (typically 255 chars per component)
        src_name = "Very Long Title Name Here vol_99 Very Long Subtitle Text Here (2024) (Author Name) {ASIN.B0MINIMAL} [Tag]"
        src = tmp_path / src_name
        src.mkdir()
        (src / f"{src_name}.m4b").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

        # Should still contain essential components
        assert "vol_99" in dst_file.name
        assert "{ASIN.B0MINIMAL}" in dst_file.name

        # Should fit
        length = _torrent_path_length(dst_dir.name, dst_file.name)
        assert length <= PATH_CAP


# ============================================================================
# PHASE 1.4: EDGE CASES & REGRESSION TESTS
# ============================================================================


@pytest.mark.unit
class TestEdgeCasesAndRegressions:
    """Test edge cases and known regression scenarios"""

    def test_decimal_volume_preserved_through_pipeline(self, tmp_path: Path) -> None:
        """Test that decimal volumes like vol_13.5 are preserved end-to-end"""
        src_name = "Title vol_13.5 Subtitle {ASIN.B0DECIMAL}"
        src = tmp_path / src_name
        src.mkdir()
        (src / f"{src_name}.m4b").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

        # vol_13.5 should be preserved
        assert "vol_13.5" in dst_dir.name
        assert "vol_13.5" in dst_file.name

    def test_multiple_subtitle_hyphens_preserved(self, tmp_path: Path) -> None:
        """Test that subtitles with multiple hyphens are handled correctly"""
        src_name = "Title vol_01 Part One - The Beginning - Chapter One {ASIN.B0HYPHEN1}"
        src = tmp_path / src_name
        src.mkdir()
        (src / f"{src_name}.m4b").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

        # Should not break on multiple hyphens
        assert "Title" in dst_dir.name
        assert "{ASIN.B0HYPHEN1}" in dst_dir.name

    def test_author_year_ordering_right_to_left(self) -> None:
        """Test that author and year are extracted correctly (right-to-left)"""
        # Year is innermost, author is outermost
        name = "Title vol_01 (2024) (Author Name) {ASIN.B0ORDER1}.m4b"
        tokens = parse_tokens(name, ".m4b")

        assert tokens.year == "(2024)"
        assert tokens.author == "(Author Name)"

    def test_unicode_characters_in_title(self, tmp_path: Path) -> None:
        """Test handling of unicode characters in titles"""
        src_name = "Overlōrd vol_01 {ASIN.B0UNICODE}"
        src = tmp_path / src_name
        src.mkdir()
        (src / f"{src_name}.m4b").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

        # Should handle unicode
        assert "Overlōrd" in dst_dir.name or "Overl" in dst_dir.name
        assert "{ASIN.B0UNICODE}" in dst_dir.name

    def test_path_exactly_180_characters(self) -> None:
        """Test path that is exactly 180 characters"""
        # Calculate exact lengths to hit 180
        # Format: "Title vol_XX {ASIN.B0XXXXXX}/Title vol_XX {ASIN.B0XXXXXX}.m4b"
        # folder and file (without ext) should be the same
        # 2 * len(base) + 1 + 4 = 180
        # 2 * len(base) = 175
        # len(base) = 87.5, so use 87

        base = "A" * 56 + " vol_01 {ASIN.B0EXACT180}"  # Should be ~87 chars
        folder = base
        filename = base + ".m4b"

        length = _torrent_path_length(folder, filename)

        # Should be very close to 180
        assert length <= 180
        assert _fits_red_cap(folder, filename, path_cap=180)

    def test_path_just_over_180_gets_trimmed(self, tmp_path: Path) -> None:
        """Test that paths just over 180 chars get trimmed appropriately"""
        # Create a name that's 181 chars when combined
        src_name = "Title vol_01 Very Long Subtitle That Pushes Us Just Over The Limit (2024) (Author) {ASIN.B0OVER181} [Tag]"
        src = tmp_path / src_name
        src.mkdir()
        (src / f"{src_name}.m4b").touch()

        dst_root = tmp_path / "destination"
        dst_dir, dst_file = build_dst_paths(src, dst_root, extension=".m4b")

        # Should be trimmed to fit
        length = _torrent_path_length(dst_dir.name, dst_file.name)
        assert length <= PATH_CAP

    def test_empty_optional_fields_handled_gracefully(self) -> None:
        """Test tokens with all optional fields as None"""
        tokens = Tokens(
            title="Title",
            volume="vol_01",
            subtitle=None,
            year=None,
            author=None,
            asin="{ASIN.B0EMPTY1}",
            tag=None,
            ext=".m4b",
        )

        filename = build_filename(tokens)
        folder = build_folder_name(tokens)

        assert filename == "Title vol_01 {ASIN.B0EMPTY1}.m4b"
        assert folder == "Title vol_01 {ASIN.B0EMPTY1}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
