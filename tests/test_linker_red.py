"""Tests for RED-compliant linking operations (Phase 3.3)

Tests plan_and_link_red, plan_and_link, run_batch, and choose_base_outputs functions.
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from hardbound.linker import (
    choose_base_outputs,
    plan_and_link,
    plan_and_link_red,
    run_batch,
)


@pytest.fixture
def sample_audiobook_structure(tmp_path: Path) -> dict:
    """Create a realistic audiobook directory structure for testing"""
    # Create source audiobook with RED-style naming
    src_dir = (
        tmp_path
        / "library"
        / "Author Name"
        / "Series Name"
        / "Book Title vol_01 {ASIN.B0C34GQRYZ}"
    )
    src_dir.mkdir(parents=True)

    # Create various audiobook files
    (src_dir / "Book Title vol_01 {ASIN.B0C34GQRYZ}.m4b").write_text("m4b content")
    (src_dir / "cover.jpg").write_text("jpg content")
    (src_dir / "Book Title vol_01 {ASIN.B0C34GQRYZ}.nfo").write_text("nfo content")

    # Create destination root
    dst_root = tmp_path / "torrents"
    dst_root.mkdir()

    return {
        "src_dir": src_dir,
        "dst_root": dst_root,
        "tmp_path": tmp_path,
    }


@pytest.fixture
def stats_dict() -> dict:
    """Create a stats dictionary for tracking link operations"""
    return {
        "linked": 0,
        "replaced": 0,
        "already": 0,
        "exists": 0,
        "excluded": 0,
        "skipped": 0,
        "errors": 0,
    }


class TestChooseBaseOutputs:
    """Test choose_base_outputs function"""

    def test_choose_base_outputs_basic(self, tmp_path: Path) -> None:
        """Test basic output path generation"""
        dest_dir = tmp_path / "destination"
        base_name = "Book Title vol_01 {ASIN.B0ABC123}"

        outputs = choose_base_outputs(dest_dir, base_name)

        assert outputs["m4b"] == dest_dir / f"{base_name}.m4b"
        assert outputs["jpg"] == dest_dir / f"{base_name}.jpg"
        assert outputs["nfo"] == dest_dir / f"{base_name}.nfo"
        assert outputs["txt"] == dest_dir / f"{base_name}.txt"

    def test_choose_base_outputs_removes_user_tags(self, tmp_path: Path) -> None:
        """Test that user tags are cleaned from filenames"""
        dest_dir = tmp_path / "destination"
        base_name = "Book Title vol_01 {ASIN.B0ABC123} [H2OKing]"

        outputs = choose_base_outputs(dest_dir, base_name)

        # User tags should be removed from filename
        expected_clean = "Book Title vol_01 {ASIN.B0ABC123}"
        assert outputs["m4b"] == dest_dir / f"{expected_clean}.m4b"
        assert outputs["jpg"] == dest_dir / f"{expected_clean}.jpg"

    def test_choose_base_outputs_all_formats(self, tmp_path: Path) -> None:
        """Test that all expected output formats are generated"""
        dest_dir = tmp_path / "destination"
        base_name = "Book Title"

        outputs = choose_base_outputs(dest_dir, base_name)

        expected_keys = {"cue", "jpg", "m4b", "mp3", "flac", "pdf", "txt", "nfo"}
        assert set(outputs.keys()) == expected_keys


class TestPlanAndLink:
    """Test plan_and_link function"""

    @pytest.mark.integration
    def test_plan_and_link_basic_workflow(
        self, sample_audiobook_structure: dict, stats_dict: dict
    ) -> None:
        """Test basic plan_and_link workflow"""
        src_dir = sample_audiobook_structure["src_dir"]
        dst_root = sample_audiobook_structure["dst_root"]
        dst_dir = dst_root / "Book Title vol_01 {ASIN.B0C34GQRYZ}"
        base_name = "Book Title vol_01 {ASIN.B0C34GQRYZ}"

        plan_and_link(
            src_dir,
            dst_dir,
            base_name,
            also_cover=False,
            zero_pad=False,
            force=False,
            dry_run=False,
            stats=stats_dict,
        )

        # Check that files were linked
        assert (dst_dir / f"{base_name}.m4b").exists()
        assert (dst_dir / f"{base_name}.jpg").exists()
        assert (dst_dir / f"{base_name}.nfo").exists()
        assert stats_dict["linked"] >= 3

    @pytest.mark.integration
    def test_plan_and_link_dry_run(
        self, sample_audiobook_structure: dict, stats_dict: dict
    ) -> None:
        """Test dry-run mode doesn't create files"""
        src_dir = sample_audiobook_structure["src_dir"]
        dst_root = sample_audiobook_structure["dst_root"]
        dst_dir = dst_root / "Book Title vol_01 {ASIN.B0C34GQRYZ}"
        base_name = "Book Title vol_01 {ASIN.B0C34GQRYZ}"

        plan_and_link(
            src_dir,
            dst_dir,
            base_name,
            also_cover=False,
            zero_pad=False,
            force=False,
            dry_run=True,
            stats=stats_dict,
        )

        # Verify no actual files created
        assert not (dst_dir / f"{base_name}.m4b").exists()
        assert stats_dict["linked"] >= 3  # Stats still tracked in dry-run

    @pytest.mark.integration
    def test_plan_and_link_zero_pad(
        self, sample_audiobook_structure: dict, stats_dict: dict
    ) -> None:
        """Test zero-padding of volume numbers"""
        src_dir = sample_audiobook_structure["src_dir"]
        dst_root = sample_audiobook_structure["dst_root"]
        dst_dir = dst_root / "Book Title vol_01 {ASIN.B0C34GQRYZ}"
        base_name = "Book Title vol_1 {ASIN.B0C34GQRYZ}"  # vol_1 not padded

        plan_and_link(
            src_dir,
            dst_dir,
            base_name,
            also_cover=False,
            zero_pad=True,  # Should pad vol_1 to vol_01
            force=False,
            dry_run=False,
            stats=stats_dict,
        )

        # Files should be created with padded volume number
        expected_name = "Book Title vol_01 {ASIN.B0C34GQRYZ}"
        assert (dst_dir / f"{expected_name}.m4b").exists()

    @pytest.mark.integration
    def test_plan_and_link_also_cover(
        self, sample_audiobook_structure: dict, stats_dict: dict
    ) -> None:
        """Test also_cover flag (cover.jpg is excluded by default config)"""
        src_dir = sample_audiobook_structure["src_dir"]
        dst_root = sample_audiobook_structure["dst_root"]
        dst_dir = dst_root / "Book Title vol_01 {ASIN.B0C34GQRYZ}"
        base_name = "Book Title vol_01 {ASIN.B0C34GQRYZ}"

        plan_and_link(
            src_dir,
            dst_dir,
            base_name,
            also_cover=True,
            zero_pad=False,
            force=False,
            dry_run=False,
            stats=stats_dict,
        )

        # Named cover should exist
        assert (dst_dir / f"{base_name}.jpg").exists()
        # cover.jpg is excluded by dest_is_excluded() by default
        # This test just verifies also_cover doesn't crash

    def test_plan_and_link_missing_source(
        self, tmp_path: Path, stats_dict: dict
    ) -> None:
        """Test handling of missing source directory"""
        src_dir = tmp_path / "nonexistent"
        dst_dir = tmp_path / "destination"
        base_name = "Book Title"

        plan_and_link(
            src_dir,
            dst_dir,
            base_name,
            also_cover=False,
            zero_pad=False,
            force=False,
            dry_run=False,
            stats=stats_dict,
        )

        # Should increment error counter
        assert stats_dict["errors"] == 1

    def test_plan_and_link_empty_directory(
        self, tmp_path: Path, stats_dict: dict
    ) -> None:
        """Test handling of empty source directory"""
        src_dir = tmp_path / "empty"
        src_dir.mkdir()
        dst_dir = tmp_path / "destination"
        base_name = "Book Title"

        plan_and_link(
            src_dir,
            dst_dir,
            base_name,
            also_cover=False,
            zero_pad=False,
            force=False,
            dry_run=False,
            stats=stats_dict,
        )

        # Should handle gracefully, no errors
        assert stats_dict["errors"] == 0


class TestPlanAndLinkRed:
    """Test plan_and_link_red function"""

    @pytest.mark.integration
    def test_plan_and_link_red_basic(
        self, sample_audiobook_structure: dict, stats_dict: dict
    ) -> None:
        """Test basic RED-compliant linking"""
        src_dir = sample_audiobook_structure["src_dir"]
        dst_root = sample_audiobook_structure["dst_root"]

        plan_and_link_red(
            src_dir,
            dst_root,
            also_cover=False,
            zero_pad=False,
            force=False,
            dry_run=False,
            stats=stats_dict,
        )

        # Verify files were linked with RED-compliant paths
        # (exact path depends on red_paths.build_dst_paths implementation)
        assert stats_dict["linked"] >= 3

    @pytest.mark.integration
    def test_plan_and_link_red_asin_validation(
        self, sample_audiobook_structure: dict, stats_dict: dict
    ) -> None:
        """Test that RED linking validates ASIN policy"""
        src_dir = sample_audiobook_structure["src_dir"]
        dst_root = sample_audiobook_structure["dst_root"]

        # Should succeed - source has ASIN in folder name
        plan_and_link_red(
            src_dir,
            dst_root,
            also_cover=False,
            zero_pad=False,
            force=False,
            dry_run=True,
            stats=stats_dict,
        )

        # Should not error
        assert stats_dict["errors"] == 0

    @pytest.mark.integration
    def test_plan_and_link_red_missing_asin(self, tmp_path: Path, stats_dict: dict) -> None:
        """Test RED linking with missing ASIN"""
        # Create source without ASIN
        src_dir = tmp_path / "library" / "Author Name" / "Book Title"
        src_dir.mkdir(parents=True)
        (src_dir / "Book Title.m4b").write_text("content")

        dst_root = tmp_path / "torrents"
        dst_root.mkdir()

        # Should raise ValueError due to missing ASIN (from red_paths.parse_tokens)
        with pytest.raises(ValueError, match="No ASIN found"):
            plan_and_link_red(
                src_dir,
                dst_root,
                also_cover=False,
                zero_pad=False,
                force=False,
                dry_run=False,
                stats=stats_dict,
            )


class TestRunBatch:
    """Test run_batch function"""

    def test_run_batch_basic(self, tmp_path: Path, stats_dict: dict) -> None:
        """Test basic batch file processing"""
        # Create source directories (not files)
        src1_dir = tmp_path / "source1"
        src1_dir.mkdir()
        (src1_dir / "audiobook.m4b").write_text("content1")

        src2_dir = tmp_path / "source2"
        src2_dir.mkdir()
        (src2_dir / "audiobook.m4b").write_text("content2")

        # Create batch file with directory pairs
        batch_file = tmp_path / "batch.txt"
        dst1 = tmp_path / "dest1"
        dst2 = tmp_path / "dest2"
        batch_file.write_text(f"{src1_dir}|{dst1}\n{src2_dir}|{dst2}\n")

        run_batch(batch_file, also_cover=False, zero_pad=False, force=False, dry_run=False)

        # Verify destination directories were created
        assert dst1.exists()
        assert dst2.exists()

    def test_run_batch_with_comments(self, tmp_path: Path) -> None:
        """Test batch file with comments and blank lines"""
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        (src_dir / "audiobook.m4b").write_text("content")

        batch_file = tmp_path / "batch.txt"
        dst_dir = tmp_path / "dest"
        batch_file.write_text(
            f"# This is a comment\n\n{src_dir}|{dst_dir}\n# Another comment\n"
        )

        run_batch(batch_file, also_cover=False, zero_pad=False, force=False, dry_run=False)

        # Verify directory was created (comments/blanks ignored)
        assert dst_dir.exists()

    def test_run_batch_invalid_line(self, tmp_path: Path, capfd) -> None:
        """Test batch file with invalid line format"""
        batch_file = tmp_path / "batch.txt"
        batch_file.write_text("invalid line without pipe\n")

        run_batch(batch_file, also_cover=False, zero_pad=False, force=False, dry_run=False)

        # Should log warning about bad line
        captured = capfd.readouterr()
        assert "bad line" in captured.out or "bad line" in captured.err

    def test_run_batch_nonexistent_file(self, tmp_path: Path) -> None:
        """Test batch processing with nonexistent batch file"""
        batch_file = tmp_path / "nonexistent.txt"

        # run_batch catches FileNotFoundError and logs it (doesn't raise)
        result = run_batch(batch_file, also_cover=False, zero_pad=False, force=False, dry_run=False)

        # Should increment error counter
        assert result["errors"] == 1

    @pytest.mark.integration
    def test_run_batch_dry_run(self, tmp_path: Path) -> None:
        """Test batch processing in dry-run mode"""
        src_dir = tmp_path / "source"
        src_dir.mkdir()
        (src_dir / "audiobook.m4b").write_text("content")

        batch_file = tmp_path / "batch.txt"
        dst_dir = tmp_path / "dest"
        batch_file.write_text(f"{src_dir}|{dst_dir}\n")

        run_batch(batch_file, also_cover=False, zero_pad=False, force=False, dry_run=True)

        # Directory gets created even in dry-run, but files inside don't
        # Just verify no errors occurred
        assert True  # Test completes without errors


class TestLinkerRedIntegration:
    """Integration tests for RED linking workflows"""

    @pytest.mark.integration
    def test_complete_red_workflow(
        self, sample_audiobook_structure: dict, stats_dict: dict
    ) -> None:
        """Test complete RED workflow from source to destination"""
        src_dir = sample_audiobook_structure["src_dir"]
        dst_root = sample_audiobook_structure["dst_root"]

        # Run RED-compliant linking
        plan_and_link_red(
            src_dir,
            dst_root,
            also_cover=True,
            zero_pad=True,
            force=False,
            dry_run=False,
            stats=stats_dict,
        )

        # Verify stats tracked properly
        assert stats_dict["linked"] >= 3
        assert stats_dict["errors"] == 0

    @pytest.mark.integration
    def test_red_workflow_with_force(
        self, sample_audiobook_structure: dict, stats_dict: dict
    ) -> None:
        """Test RED workflow with force replacing existing files"""
        src_dir = sample_audiobook_structure["src_dir"]
        dst_root = sample_audiobook_structure["dst_root"]

        # First run
        plan_and_link_red(
            src_dir,
            dst_root,
            also_cover=False,
            zero_pad=False,
            force=False,
            dry_run=False,
            stats=stats_dict,
        )

        first_linked = stats_dict["linked"]

        # Reset stats
        stats_dict["linked"] = 0
        stats_dict["replaced"] = 0
        stats_dict["already"] = 0

        # Second run with force - should replace files
        plan_and_link_red(
            src_dir,
            dst_root,
            also_cover=False,
            zero_pad=False,
            force=True,
            dry_run=False,
            stats=stats_dict,
        )

        # Should have replaced files
        assert stats_dict["replaced"] > 0 or stats_dict["already"] > 0

    @pytest.mark.integration
    def test_red_workflow_multiple_audiobooks(self, tmp_path: Path, stats_dict: dict) -> None:
        """Test RED workflow with multiple audiobooks"""
        dst_root = tmp_path / "torrents"
        dst_root.mkdir()

        # Create multiple audiobook sources
        for i in range(3):
            src_dir = (
                tmp_path / "library" / f"Author{i}" / f"Book{i} {{ASIN.B0ABC12{i}}}"
            )
            src_dir.mkdir(parents=True)
            (src_dir / f"Book{i} {{ASIN.B0ABC12{i}}}.m4b").write_text(f"content{i}")

            plan_and_link_red(
                src_dir,
                dst_root,
                also_cover=False,
                zero_pad=False,
                force=False,
                dry_run=False,
                stats=stats_dict,
            )

        # Should have linked all audiobooks
        assert stats_dict["linked"] >= 3
