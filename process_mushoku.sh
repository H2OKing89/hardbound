#!/bin/bash

# Set the paths
SRC_BASE="/mnt/user/data/audio/audiobooks/Rifujin na Magonote/Mushoku Tensei - Jobless Reincarnation"
DST_ROOT="/mnt/user/data/downloads/torrents/qbittorrent/seedvault/audiobooks"

# Find all Mushoku Tensei volumes and process them
find "$SRC_BASE" -maxdepth 1 -type d -name "*vol_*" | sort | while read -r src_dir; do
    src_basename=$(basename "$src_dir")
    # Remove [H2OKing] from the base name for files, but keep it for the directory
    base_name="${src_basename% [H2OKing]}"
    
    echo "Processing: $src_basename"
    echo "Directory: $src_basename"
    echo "File base: $base_name"
    ./hardbound.py --src "$src_dir" --dst-root "$DST_ROOT" --base-name "$base_name" --dry-run
    echo "---"
done
