#!/usr/bin/env python3#!/usr/bin/env python3    # Test the RED path generation

"""Test script to verify interactive mode now uses RED path compliance"""    dst_folder, dst_file = build_dst_paths(src_path, dst_root, ".m4b")

    

import sys    print(f"Generated RED-compliant folder: {dst_folder.name}")

from pathlib import Path    print(f"Folder length: {len(dst_folder.name)} chars")

    print()

# Add the hardbound package to path    

sys.path.insert(0, "/mnt/cache/scripts/hardbound")    # Test the filename

    relative_path = f"{dst_folder.name}/{dst_file.name}"

from hardbound.red_paths import build_dst_paths    print(f"Sample file path: {relative_path}")

    print(f"Full path length: {len(relative_path)} chars")

def test_red_compliance_for_interactive():    print(f"Under 180 char limit: {'✓ YES' if len(relative_path) <= 180 else '✗ NO'}")

    """Test that we can generate RED-compliant paths for the real-world example"""    print()to verify interactive mode now uses RED path compliance"""

    

    # This is the same example from your logs that was exceeding 180 charsimport sys

    src_path = Path("/mnt/user/data/audio/audiobooks/Kugane Maruyama/Overlord/Overlord - vol_11 - The Dwarven Crafter (2024) (Kugane Maruyama) {ASIN.B0CG76RFQQ}")from pathlib import Path

    dst_root = Path("/mnt/user/data/downloads/torrents/qbittorrent/seedvault/audiobooks/redacted")

    # Add the hardbound package to path

    print(f"Source: {src_path.name}")sys.path.insert(0, "/mnt/cache/scripts/hardbound")

    print(f"Source length: {len(src_path.name)} chars")

    print()from hardbound.red_paths import build_dst_paths

    

    # Test the RED path generationdef test_red_compliance_for_interactive():

    dst_folder, dst_file = build_dst_paths(src_path, dst_root, ".m4b")    """Test that we can generate RED-compliant paths for the real-world example"""

        

    print(f"Generated RED-compliant folder: {dst_folder.name}")    # This is the same example from your logs that was exceeding 180 chars

    print(f"Folder length: {len(dst_folder.name)} chars")    src_path = Path("/mnt/user/data/audio/audiobooks/Kugane Maruyama/Overlord/Overlord - vol_11 - The Dwarven Crafter (2024) (Kugane Maruyama) {ASIN.B0CG76RFQQ}")

    print()    dst_root = Path("/mnt/user/data/downloads/torrents/qbittorrent/seedvault/audiobooks/redacted")

        

    # Test the filename    print(f"Source: {src_path.name}")

    relative_path = f"{dst_folder.name}/{dst_file.name}"    print(f"Source length: {len(src_path.name)} chars")

    print(f"Sample file path: {relative_path}")    print()

    print(f"Full path length: {len(relative_path)} chars")    

    print(f"Under 180 char limit: {'✓ YES' if len(relative_path) <= 180 else '✗ NO'}")    # Test the RED path generation

    print()    dst_folder, dst_files = build_dst_paths(src_path, dst_root)

        

    print("=" * 60)    print(f"Generated RED-compliant folder: {dst_folder.name}")

    print()    print(f"Folder length: {len(dst_folder.name)} chars")

    print()

if __name__ == "__main__":    

    test_red_compliance_for_interactive()    # Test a sample filename
    for filepath in dst_files:
        if filepath.name.endswith('.m4b'):
            relative_path = f"{dst_folder.name}/{filepath.name}"
            print(f"Sample file path: {relative_path}")
            print(f"Full path length: {len(relative_path)} chars")
            print(f"Under 180 char limit: {'✓ YES' if len(relative_path) <= 180 else '✗ NO'}")
            break
    
    print()
    print("=" * 60)
    print()

if __name__ == "__main__":
    test_red_compliance_for_interactive()