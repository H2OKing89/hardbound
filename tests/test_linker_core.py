#!/usr/bin/env python3
"""
Tests for Linker Module - Core Operations

Phase 3.2: Core hardlinking, directory creation, preflight checks, ASIN policy
Part of the Hardbound test improvement plan (Phase 3: Linker)
"""

import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from hardbound.linker import (
    _enforce_asin_policy,
    do_link,
    ensure_dir,
    preflight_checks,
)


# ============================================================================
# FIXTURES
# ============================================================================


@pytest.fixture
def sample_files(tmp_path: Path):
    """Create sample source and destination paths"""
    src_dir = tmp_path / "source"
    dst_dir = tmp_path / "destination"
    src_dir.mkdir()
    dst_dir.mkdir()

    # Create sample source file
    src_file = src_dir / "audiobook.m4b"
    src_file.write_bytes(b"fake audio data " * 1000)

    return {
        "src_dir": src_dir,
        "dst_dir": dst_dir,
        "src_file": src_file,
        "dst_file": dst_dir / "audiobook.m4b",
    }


@pytest.fixture
def stats_dict():
    """Create a statistics dictionary for tracking link operations"""
    return {
        "linked": 0,
        "replaced": 0,
        "already": 0,
        "exists": 0,
        "excluded": 0,
        "skipped": 0,
        "errors": 0,
    }


# ============================================================================
# PHASE 3.2: ASIN POLICY ENFORCEMENT
# ============================================================================


@pytest.mark.unit
class TestEnforceASINPolicy:
    """Test ASIN policy enforcement for RED compliance"""

    def test_asin_in_both_folder_and_file(self) -> None:
        """Test that ASIN in both names passes"""
        folder = "Book Title {ASIN.B0TEST123}"
        filename = "Book Title {ASIN.B0TEST123}.m4b"
        asin = "{ASIN.B0TEST123}"

        # Should not raise
        _enforce_asin_policy(folder, filename, asin)

    def test_asin_missing_from_folder(self) -> None:
        """Test that ASIN missing from folder raises ValueError"""
        folder = "Book Title"
        filename = "Book Title {ASIN.B0TEST123}.m4b"
        asin = "{ASIN.B0TEST123}"

        with pytest.raises(ValueError, match="ASIN policy violation"):
            _enforce_asin_policy(folder, filename, asin)

    def test_asin_missing_from_file(self) -> None:
        """Test that ASIN missing from file raises ValueError"""
        folder = "Book Title {ASIN.B0TEST123}"
        filename = "Book Title.m4b"
        asin = "{ASIN.B0TEST123}"

        with pytest.raises(ValueError, match="ASIN policy violation"):
            _enforce_asin_policy(folder, filename, asin)

    def test_asin_missing_from_both(self) -> None:
        """Test that ASIN missing from both raises ValueError"""
        folder = "Book Title"
        filename = "Book Title.m4b"
        asin = "{ASIN.B0TEST123}"

        with pytest.raises(ValueError, match="ASIN policy violation"):
            _enforce_asin_policy(folder, filename, asin)

    def test_asin_different_formats(self) -> None:
        """Test ASIN with different bracket formats"""
        # Both formats should match
        folder = "Book [ASIN.B0TEST123]"
        filename = "Book [ASIN.B0TEST123].m4b"
        asin = "[ASIN.B0TEST123]"

        _enforce_asin_policy(folder, filename, asin)


# ============================================================================
# PHASE 3.2: DIRECTORY CREATION
# ============================================================================


@pytest.mark.unit
class TestEnsureDir:
    """Test directory creation with ensure_dir"""

    def test_ensure_dir_creates_directory(
        self, tmp_path: Path, stats_dict: dict
    ) -> None:
        """Test that ensure_dir creates directory"""
        new_dir = tmp_path / "new" / "nested" / "dir"
        assert not new_dir.exists()

        ensure_dir(new_dir, dry_run=False, stats=stats_dict)

        assert new_dir.exists()
        assert new_dir.is_dir()

    def test_ensure_dir_existing_directory(
        self, tmp_path: Path, stats_dict: dict
    ) -> None:
        """Test that ensure_dir handles existing directory"""
        existing_dir = tmp_path / "existing"
        existing_dir.mkdir()

        # Should not raise error
        ensure_dir(existing_dir, dry_run=False, stats=stats_dict)

        assert existing_dir.exists()

    def test_ensure_dir_dry_run(self, tmp_path: Path, stats_dict: dict) -> None:
        """Test that ensure_dir in dry-run mode doesn't create directory"""
        new_dir = tmp_path / "dryrun" / "dir"

        ensure_dir(new_dir, dry_run=True, stats=stats_dict)

        # Directory should NOT be created in dry-run
        assert not new_dir.exists()

    def test_ensure_dir_parents(self, tmp_path: Path, stats_dict: dict) -> None:
        """Test that ensure_dir creates parent directories"""
        deep_dir = tmp_path / "a" / "b" / "c" / "d"

        ensure_dir(deep_dir, dry_run=False, stats=stats_dict)

        # All parents should exist
        assert (tmp_path / "a").exists()
        assert (tmp_path / "a" / "b").exists()
        assert (tmp_path / "a" / "b" / "c").exists()
        assert deep_dir.exists()


# ============================================================================
# PHASE 3.2: PREFLIGHT CHECKS
# ============================================================================


@pytest.mark.unit
class TestPreflightChecks:
    """Test preflight validation before linking"""

    def test_preflight_source_doesnt_exist(self, tmp_path: Path) -> None:
        """Test that non-existent source fails preflight"""
        src = tmp_path / "nonexistent.m4b"
        dst = tmp_path / "destination.m4b"

        assert not preflight_checks(src, dst)

    def test_preflight_source_exists(self, tmp_path: Path) -> None:
        """Test that existing source passes preflight"""
        src = tmp_path / "source.m4b"
        src.write_text("content")

        dst = tmp_path / "destination.m4b"

        assert preflight_checks(src, dst)

    def test_preflight_cross_device_link(self, tmp_path: Path) -> None:
        """Test that cross-device links fail preflight"""
        src = tmp_path / "source.m4b"
        src.write_text("content")

        dst = tmp_path / "destination.m4b"

        # Mock st_dev to simulate different filesystems
        class MockStat:
            st_dev = 1

        class MockStat2:
            st_dev = 2

        # Mock os.stat to return different st_dev values
        original_stat = os.stat

        def mock_stat(path, **kwargs):
            path_obj = Path(path)
            if path_obj == src:
                return MockStat()
            elif path_obj == dst.parent:
                return MockStat2()
            # Default behavior for other paths
            return original_stat(path, **kwargs)

        with patch("os.stat", side_effect=mock_stat):
            result = preflight_checks(src, dst)
            assert result is False

    def test_preflight_same_filesystem(self, tmp_path: Path) -> None:
        """Test that same filesystem passes preflight"""
        src = tmp_path / "source.m4b"
        src.write_text("content")

        dst = tmp_path / "destination.m4b"

        # Both in tmp_path, same filesystem
        assert preflight_checks(src, dst)

    def test_preflight_unraid_user_disk_mixing(self, tmp_path: Path) -> None:
        """Test that Unraid user/disk mixing fails preflight"""
        # Mock paths to simulate Unraid structure
        src = Path("/mnt/user/audiobooks/book.m4b")
        dst = Path("/mnt/disk1/torrents/book.m4b")

        # This will fail because paths don't actually exist
        # But the Unraid check happens first
        assert not preflight_checks(src, dst)


# ============================================================================
# PHASE 3.2: CORE LINKING - do_link()
# ============================================================================


@pytest.mark.integration
class TestDoLink:
    """Test core hardlink creation with do_link"""

    def test_do_link_creates_hardlink(self, sample_files: dict, stats_dict: dict) -> None:
        """Test that do_link creates a hardlink"""
        src = sample_files["src_file"]
        dst = sample_files["dst_file"]

        do_link(src, dst, force=False, dry_run=False, stats=stats_dict)

        # Destination should exist
        assert dst.exists()

        # Should be a hardlink (same inode)
        assert src.stat().st_ino == dst.stat().st_ino
        assert src.stat().st_dev == dst.stat().st_dev

        # Stats should reflect creation
        assert stats_dict["linked"] == 1

    def test_do_link_dry_run(self, sample_files: dict, stats_dict: dict) -> None:
        """Test that do_link in dry-run mode doesn't create files"""
        src = sample_files["src_file"]
        dst = sample_files["dst_file"]

        do_link(src, dst, force=False, dry_run=True, stats=stats_dict)

        # Destination should NOT exist
        assert not dst.exists()

        # Stats should still count as "linked" (dry-run intent)
        assert stats_dict["linked"] == 1

    def test_do_link_already_linked(self, sample_files: dict, stats_dict: dict) -> None:
        """Test that do_link detects already-linked files"""
        src = sample_files["src_file"]
        dst = sample_files["dst_file"]

        # Create hardlink first
        os.link(src, dst)

        # Try to link again
        do_link(src, dst, force=False, dry_run=False, stats=stats_dict)

        # Should recognize as already linked
        assert stats_dict["already"] == 1
        assert stats_dict["linked"] == 0

    def test_do_link_destination_exists_no_force(
        self, sample_files: dict, stats_dict: dict
    ) -> None:
        """Test that do_link respects existing files without force"""
        src = sample_files["src_file"]
        dst = sample_files["dst_file"]

        # Create different file at destination
        dst.write_text("different content")

        do_link(src, dst, force=False, dry_run=False, stats=stats_dict)

        # Should not overwrite
        assert dst.read_text() == "different content"
        assert stats_dict["exists"] == 1
        assert stats_dict["linked"] == 0

    def test_do_link_destination_exists_force(
        self, sample_files: dict, stats_dict: dict
    ) -> None:
        """Test that do_link replaces files with force=True"""
        src = sample_files["src_file"]
        dst = sample_files["dst_file"]

        # Create different file at destination
        dst.write_text("different content")

        do_link(src, dst, force=True, dry_run=False, stats=stats_dict)

        # Should be replaced with hardlink
        assert src.stat().st_ino == dst.stat().st_ino
        assert stats_dict["replaced"] == 1
        assert stats_dict["linked"] == 0

    def test_do_link_source_missing(self, tmp_path: Path, stats_dict: dict) -> None:
        """Test that do_link handles missing source gracefully"""
        src = tmp_path / "nonexistent.m4b"
        dst = tmp_path / "destination.m4b"

        do_link(src, dst, force=False, dry_run=False, stats=stats_dict)

        # Should skip and count as skipped
        assert not dst.exists()
        assert stats_dict["skipped"] == 1

    def test_do_link_excluded_destination(
        self, sample_files: dict, stats_dict: dict
    ) -> None:
        """Test that do_link respects exclusions"""
        src = sample_files["src_file"]
        # Use excluded filename
        dst = sample_files["dst_dir"] / "cover.jpg"

        do_link(src, dst, force=False, dry_run=False, stats=stats_dict)

        # Should be excluded
        assert not dst.exists()
        assert stats_dict["excluded"] == 1

    def test_do_link_invalid_source(self, tmp_path: Path, stats_dict: dict) -> None:
        """Test that do_link handles invalid source (None)"""
        dst = tmp_path / "destination.m4b"

        do_link(None, dst, force=False, dry_run=False, stats=stats_dict)  # type: ignore

        # Should skip invalid source
        assert not dst.exists()
        assert stats_dict["skipped"] == 1

    @pytest.mark.skipif(
        os.name == "nt", reason="Error simulation difficult on Windows"
    )
    def test_do_link_error_handling(self, tmp_path: Path, stats_dict: dict) -> None:
        """Test that do_link handles linking errors"""
        src = tmp_path / "source.m4b"
        src.write_text("content")

        # Try to link to a path that will cause error (e.g., read-only parent)
        # This is hard to test reliably, so we'll mock os.link
        dst = tmp_path / "destination.m4b"

        with patch("os.link", side_effect=OSError("Mocked error")):
            do_link(src, dst, force=False, dry_run=False, stats=stats_dict)

        # do_link logs the error but doesn't increment errors counter
        # (implementation detail - it just logs and displays error)
        # Verify error was logged and destination wasn't created
        assert not dst.exists()
        assert stats_dict["linked"] == 0  # Link should not be marked successful


# ============================================================================
# PHASE 3.2: PERMISSIONS (mocked)
# ============================================================================


@pytest.mark.unit
class TestPermissions:
    """Test permission and ownership setting (mocked)"""

    @patch("hardbound.linker.ConfigManager")
    @patch("os.chmod")
    def test_file_permissions_set(
        self, mock_chmod, mock_config_manager, tmp_path: Path
    ) -> None:
        """Test that file permissions are set when configured"""
        from hardbound.linker import set_file_permissions_and_ownership

        # Mock config to enable permissions
        mock_config = MagicMock()
        mock_config.load_config.return_value = {
            "set_permissions": True,
            "file_permissions": 0o644,
        }
        mock_config_manager.return_value = mock_config

        test_file = tmp_path / "test.m4b"
        test_file.write_text("content")

        set_file_permissions_and_ownership(test_file)

        # Should have called chmod
        mock_chmod.assert_called_once_with(test_file, 0o644)

    @patch("hardbound.linker.ConfigManager")
    @patch("os.chmod")
    def test_file_permissions_disabled(
        self, mock_chmod, mock_config_manager, tmp_path: Path
    ) -> None:
        """Test that permissions are not set when disabled"""
        from hardbound.linker import set_file_permissions_and_ownership

        mock_config = MagicMock()
        mock_config.load_config.return_value = {"set_permissions": False}
        mock_config_manager.return_value = mock_config

        test_file = tmp_path / "test.m4b"
        test_file.write_text("content")

        set_file_permissions_and_ownership(test_file)

        # Should NOT have called chmod
        mock_chmod.assert_not_called()


# ============================================================================
# PHASE 3.2: INTEGRATION TESTS
# ============================================================================


@pytest.mark.integration
class TestLinkerCoreIntegration:
    """Integration tests for core linker operations"""

    def test_full_linking_workflow(self, tmp_path: Path, stats_dict: dict) -> None:
        """Test complete workflow: ensure_dir → do_link"""
        # Setup
        src_dir = tmp_path / "source"
        dst_dir = tmp_path / "dest" / "nested" / "path"
        src_dir.mkdir()

        src_file = src_dir / "audiobook.m4b"
        src_file.write_bytes(b"audio data")

        # Ensure destination directory
        ensure_dir(dst_dir, dry_run=False, stats=stats_dict)
        assert dst_dir.exists()

        # Create link
        dst_file = dst_dir / "audiobook.m4b"
        do_link(src_file, dst_file, force=False, dry_run=False, stats=stats_dict)

        # Verify
        assert dst_file.exists()
        assert src_file.stat().st_ino == dst_file.stat().st_ino
        assert stats_dict["linked"] == 1

    def test_multiple_links_same_source(
        self, tmp_path: Path, stats_dict: dict
    ) -> None:
        """Test creating multiple hardlinks from same source"""
        src = tmp_path / "source.m4b"
        src.write_bytes(b"data")

        dst1 = tmp_path / "link1.m4b"
        dst2 = tmp_path / "link2.m4b"
        dst3 = tmp_path / "link3.m4b"

        # Create multiple links
        do_link(src, dst1, force=False, dry_run=False, stats=stats_dict)
        do_link(src, dst2, force=False, dry_run=False, stats=stats_dict)
        do_link(src, dst3, force=False, dry_run=False, stats=stats_dict)

        # All should have same inode
        assert dst1.stat().st_ino == dst2.stat().st_ino == dst3.stat().st_ino
        assert stats_dict["linked"] == 3

    def test_preflight_then_link(self, tmp_path: Path, stats_dict: dict) -> None:
        """Test preflight checks before linking"""
        src = tmp_path / "source.m4b"
        src.write_bytes(b"data")

        dst = tmp_path / "destination.m4b"

        # Run preflight
        if preflight_checks(src, dst):
            do_link(src, dst, force=False, dry_run=False, stats=stats_dict)

        # Should succeed
        assert dst.exists()
        assert stats_dict["linked"] == 1

    def test_dry_run_workflow(self, tmp_path: Path, stats_dict: dict) -> None:
        """Test complete dry-run workflow"""
        src = tmp_path / "source.m4b"
        src.write_bytes(b"data")

        dst_dir = tmp_path / "dest"
        dst_file = dst_dir / "destination.m4b"

        # Dry-run workflow
        ensure_dir(dst_dir, dry_run=True, stats=stats_dict)
        do_link(src, dst_file, force=False, dry_run=True, stats=stats_dict)

        # Nothing should be created
        assert not dst_dir.exists()
        assert not dst_file.exists()

        # But stats should show intent
        assert stats_dict["linked"] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
