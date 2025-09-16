#!/usr/bin/env python3
"""
RED-compliant path shortening system
Ensures paths fit within 180-character limit while preserving ASIN tags
"""

import re
from dataclasses import dataclass
from pathlib import Path

from .utils.logging import get_logger

# RED full-path limit
PATH_CAP = 180
TORRENT_PATH_SEPARATOR = "/"  # RED counts internal torrent paths, not OS paths

# Get logger for this module
log = get_logger(__name__)


@dataclass(frozen=True)
class Tokens:
    """Parsed tokens from audiobook name"""

    title: str
    volume: str  # normalized: "vol_00"
    subtitle: str | None
    year: str | None  # "(2024)" if present, else None
    author: str | None  # "(Kugane Maruyama)" if present, else None
    asin: str  # "{ASIN.B0CW3NF5NY}"
    tag: str | None  # e.g. "[H2OKing]"
    ext: str  # ".m4b"


def normalize_volume(volume_str: str) -> str:
    """Normalize volume string to vol_XX format"""
    # Handle various volume formats
    patterns = [
        r"vol_(\d+)",  # vol_13
        r"vol\.?\s*(\d+)",  # vol.13, vol 13
        r"volume\s+(\d+)",  # volume 13
        r"v\.?\s*(\d+)",  # v.13, v13
        r"(\d+)",  # just "13"
    ]

    volume_str = volume_str.lower().strip()

    for pattern in patterns:
        match = re.search(pattern, volume_str, re.IGNORECASE)
        if match:
            num = int(match.group(1))
            return f"vol_{num:02d}"

    # If no pattern matches, return as-is but try to format
    return f"vol_{volume_str.zfill(2)}"


def parse_tokens(name: str, extension: str = ".m4b") -> Tokens:
    """
    Parse audiobook name into component tokens

    Expected format:
    <title> - <vol_00> - <subtitle> (year) (author) {ASIN.B0XXXXXX} [tag]
    """
    # Remove extension if present
    if name.endswith(extension):
        name = name[: -len(extension)]

    # Extract ASIN (required)
    asin_pattern = r"\{ASIN\.[A-Z0-9]+\}"
    asin_match = re.search(asin_pattern, name)
    if not asin_match:
        raise ValueError(f"No ASIN found in name: {name}")
    asin = asin_match.group(0)

    # Extract trailing tag [xxx] (keep brackets, strictly at end)
    tag_pattern = r"\s*\[[^\]]+\]\s*$"
    tag_match = re.search(tag_pattern, name)
    tag = tag_match.group(0).strip() if tag_match else None

    # Remove ASIN and tag from working string
    working = name
    working = re.sub(asin_pattern, "", working).strip()
    if tag:
        working = re.sub(tag_pattern, "", working).strip()

    # Extract from right to left: author first (outermost), then year (next inner)
    # Extract trailing author "(Name Name)" if present; keep parens
    author_pattern = r"\s*\(([^)]+)\)\s*$"
    author_match = re.search(author_pattern, working)
    author = author_match.group(0).strip() if author_match else None
    if author_match:
        working = working[: author_match.start()].strip()

    # Now extract trailing year "(2024)" if present; keep parens
    year_pattern = r"\s*\((19|20)\d{2}\)\s*$"
    year_match = re.search(year_pattern, working)
    year = year_match.group(0).strip() if year_match else None
    if year_match:
        working = working[: year_match.start()].rstrip()

    # Parse the new format: <title> vol_XX <subtitle>
    # Look for volume pattern in the working string
    vol_pattern = r"\b(vol_\d+)\b"
    vol_match = re.search(vol_pattern, working, re.IGNORECASE)

    if vol_match:
        volume_str = vol_match.group(1)
        volume = normalize_volume(volume_str)

        # Split around the volume to get title and subtitle
        vol_start, vol_end = vol_match.span()
        title_part = working[:vol_start].strip()
        subtitle_part = working[vol_end:].strip()

        # Clean up old format markers if present
        # Remove trailing " -" from title and leading "- " from subtitle
        if title_part.endswith(" -"):
            title_part = title_part[:-2].strip()
        if subtitle_part.startswith("- "):
            subtitle_part = subtitle_part[2:].strip()

        title = title_part
        subtitle = subtitle_part if subtitle_part else None
    else:
        # Fallback: no volume found, try old format or default
        parts = [p.strip() for p in working.split(" - ") if p.strip()]

        if len(parts) >= 2:
            # Try old format: title - vol_XX - subtitle
            title = parts[0]
            volume_part = parts[1]
            volume = normalize_volume(volume_part)
            subtitle = " - ".join(parts[2:]) if len(parts) > 2 else None
        else:
            # Last resort: assume first part is title, default volume
            title = parts[0] if parts else working
            volume = "vol_01"  # Default
            subtitle = None

    return Tokens(
        title=title.strip(),
        volume=volume,
        subtitle=subtitle,
        year=year,
        author=author,
        asin=asin,
        tag=tag,
        ext=extension,
    )


def _series_str(tokens: Tokens, include_subtitle: bool = True) -> str:
    """
    Build the left-hand 'series' part using space joiners:
    <title> <vol_00> [<subtitle>]
    """
    parts = [tokens.title, tokens.volume]
    if include_subtitle and tokens.subtitle:
        parts.append(tokens.subtitle)
    return " ".join(parts)


def build_filename(
    tokens: Tokens,
    include_subtitle: bool = True,
    include_year: bool = True,
    include_author: bool = True,
    include_tag: bool = True,
) -> str:
    """Build filename from tokens with optional components."""
    left = _series_str(tokens, include_subtitle=include_subtitle)
    right: list[str] = []
    if include_year and tokens.year:
        right.append(tokens.year)
    if include_author and tokens.author:
        right.append(tokens.author)
    right.append(tokens.asin)
    if include_tag and tokens.tag:
        right.append(tokens.tag)
    filename = (
        f"{left} {' '.join(right)}{tokens.ext}" if right else f"{left}{tokens.ext}"
    )
    # Normalize whitespace
    filename = re.sub(r"\s+", " ", filename).strip()

    return filename


def build_folder_name(
    tokens: Tokens,
    include_subtitle: bool = True,
    include_year: bool = True,
    include_author: bool = True,
) -> str:
    """Build folder name from tokens with optional components."""
    left = _series_str(tokens, include_subtitle=include_subtitle)
    right: list[str] = []
    if include_year and tokens.year:
        right.append(tokens.year)
    if include_author and tokens.author:
        right.append(tokens.author)
    right.append(tokens.asin)
    folder_name = f"{left} {' '.join(right)}" if right else left
    # Normalize whitespace
    folder_name = re.sub(r"\s+", " ", folder_name).strip()

    return folder_name


def build_dst_paths(
    src: Path, dst_root: Path, extension: str | None = None
) -> tuple[Path, Path]:
    """
    Build destination paths with RED compliance (180 char limit)

    Returns (dst_dir, dst_file) such that:
    - src is never modified
    - dst_dir and dst_file both contain ASIN
    - full path len(dst_dir / dst_file) <= PATH_CAP
    - Two-stage trimming: filename first, then folder

    Args:
        src: Source path (folder containing audiobook)
        dst_root: Root destination directory
        extension: File extension (auto-detected if None)

    Returns:
        tuple[Path, Path]: (destination_directory, destination_filename)
    """
    if extension is None:
        # Prefer common audiobook types in a deterministic order
        preferred_exts = [".m4b", ".m4a", ".mp3", ".flac"]
        lower_files = [f.suffix.lower() for f in src.iterdir() if f.is_file()]
        for ext in preferred_exts:
            if ext in lower_files:
                extension = ext
                break
        if extension is None:
            extension = ".m4b"  # Default

    # Parse tokens from source name
    tokens = parse_tokens(src.name, extension)

    # Bind context for logging
    logger = log.bind(
        asin=tokens.asin,
        title=tokens.title,
        src_name=src.name,
        extension=extension,
        dst_root=str(dst_root),
    )

    logger.debug(
        "trim.start",
        subtitle=tokens.subtitle,
        year=tokens.year,
        author=tokens.author,
        tag=tokens.tag,
    )

    # Stage A: Try different filename trimming levels
    filename_configs = [
        # Full filename (all components)
        {
            "include_subtitle": True,
            "include_year": True,
            "include_author": True,
            "include_tag": True,
        },
        # Remove year from filename
        {
            "include_subtitle": True,
            "include_year": False,
            "include_author": True,
            "include_tag": True,
        },
        # Remove year and author from filename
        {
            "include_subtitle": True,
            "include_year": False,
            "include_author": False,
            "include_tag": True,
        },
        # Remove year, author, and tag from filename
        {
            "include_subtitle": True,
            "include_year": False,
            "include_author": False,
            "include_tag": False,
        },
        # Remove everything optional from filename (minimal)
        {
            "include_subtitle": False,
            "include_year": False,
            "include_author": False,
            "include_tag": False,
        },
    ]

    # Start with full folder name
    folder_configs = [
        # Full folder name
        {"include_subtitle": True, "include_year": True, "include_author": True},
        # Remove year from folder
        {"include_subtitle": True, "include_year": False, "include_author": True},
        # Remove year and author from folder
        {"include_subtitle": True, "include_year": False, "include_author": False},
        # Remove everything optional from folder (minimal)
        {"include_subtitle": False, "include_year": False, "include_author": False},
    ]

    logger.debug("trim.phase_a.start", phase="filename_trimming")

    # Try each filename configuration with full folder first
    for i, filename_config in enumerate(filename_configs):
        filename = build_filename(tokens, **filename_config)
        folder_name = build_folder_name(tokens, **folder_configs[0])  # Full folder

        dst_dir = dst_root / folder_name
        torrent_length = _torrent_path_length(folder_name, filename)

        logger.debug(
            "trim.try_filename",
            attempt=i + 1,
            config=filename_config,
            filename=filename,
            folder=folder_name,
            path_len=torrent_length,
            path_cap=PATH_CAP,
            within=torrent_length <= PATH_CAP,
        )

        if _fits_red_cap(folder_name, filename):
            trim_steps = []
            if not filename_config.get("include_year", True):
                trim_steps.append("drop year")
            if not filename_config.get("include_author", True):
                trim_steps.append("drop author")
            if not filename_config.get("include_tag", True):
                trim_steps.append("drop tag")

            logger.info(
                "trim.ok",
                phase="filename",
                attempt=i + 1,
                folder=folder_name,
                file=filename,
                path_len=torrent_length,
                path_cap=PATH_CAP,
                within=True,
                trim_steps=trim_steps,
                trim_level=f"filename_config_{i}",
            )
            return dst_dir, Path(filename)

    logger.debug("trim.phase_b.start", phase="folder_trimming")

    # Stage B: If still too long, try folder trimming with minimal filename
    minimal_filename = build_filename(
        tokens,
        include_subtitle=False,
        include_year=False,
        include_author=False,
        include_tag=False,
    )

    for j, folder_config in enumerate(folder_configs):
        folder_name = build_folder_name(tokens, **folder_config)
        dst_dir = dst_root / folder_name
        torrent_length = _torrent_path_length(folder_name, minimal_filename)

        logger.debug(
            "trim.try_folder",
            attempt=j + 1,
            config=folder_config,
            filename=minimal_filename,
            folder=folder_name,
            path_len=torrent_length,
            path_cap=PATH_CAP,
            within=torrent_length <= PATH_CAP,
        )

        if _fits_red_cap(folder_name, minimal_filename):
            folder_trim_steps = [
                "drop year",
                "drop author",
                "drop tag",
                "drop subtitle(file)",
            ]  # Already applied minimal filename
            if not folder_config.get("include_year", True):
                folder_trim_steps.append("drop year(folder)")
            if not folder_config.get("include_author", True):
                folder_trim_steps.append("drop author(folder)")
            if not folder_config.get("include_subtitle", True):
                folder_trim_steps.append("drop subtitle(folder)")

            logger.info(
                "trim.ok",
                phase="folder",
                attempt=j + 1,
                folder=folder_name,
                file=minimal_filename,
                path_len=torrent_length,
                path_cap=PATH_CAP,
                within=True,
                trim_steps=folder_trim_steps,
                trim_level=f"folder_config_{j}",
            )
            return dst_dir, Path(minimal_filename)

    # Phase C: Title truncation as final fallback
    logger.debug("trim.phase_c.start", phase="title_truncation")

    # Calculate how much space we need for the essential parts
    # Format will be: "Title... - vol_XX {ASIN.XXXXXXX}"
    essential_parts = f" - {tokens.volume} {tokens.asin}"
    extension = tokens.ext
    # Need space for folder/filename (same content) + separator
    # folder_name + "/" + filename = 2 * (title + essential_parts) + 1 + len(extension)

    # Calculate max title length to fit under PATH_CAP
    # 2 * (max_title_len + len(essential_parts)) + 1 + len(extension) <= PATH_CAP
    # max_title_len <= (PATH_CAP - 1 - len(extension) - 2 * len(essential_parts)) / 2
    max_title_len = (PATH_CAP - 1 - len(extension) - 2 * len(essential_parts)) // 2

    if len(tokens.title) > max_title_len:
        # Truncate title, but leave room for "..." indicator
        truncated_title = tokens.title[: max_title_len - 3] + "..."
        logger.debug(
            "trim.title_truncate",
            original_title=tokens.title,
            original_len=len(tokens.title),
            truncated_title=truncated_title,
            truncated_len=len(truncated_title),
            max_allowed=max_title_len,
        )
    else:
        truncated_title = tokens.title

    # Build final truncated version
    truncated_folder = f"{truncated_title} - {tokens.volume} {tokens.asin}"
    truncated_filename = (
        f"{truncated_title} - {tokens.volume} {tokens.asin}{tokens.ext}"
    )

    dst_dir = dst_root / truncated_folder
    final_length = _torrent_path_length(truncated_folder, truncated_filename)

    if final_length <= PATH_CAP:
        logger.info(
            "trim.ok",
            phase="title_truncation",
            folder=truncated_folder,
            file=truncated_filename,
            path_len=final_length,
            path_cap=PATH_CAP,
            within=True,
            trim_steps=[
                "drop year",
                "drop author",
                "drop tag",
                "drop subtitle(file)",
                "drop year(folder)",
                "drop author(folder)",
                "drop subtitle(folder)",
                "truncate title",
            ],
            original_title_len=len(tokens.title),
            truncated_title_len=len(truncated_title),
            trim_level="title_truncation",
        )
        return dst_dir, Path(truncated_filename)
    else:
        # This should never happen with reasonable ASIN lengths, but just in case
        logger.error(
            "trim.failed",
            folder=truncated_folder,
            file=truncated_filename,
            path_len=final_length,
            path_cap=PATH_CAP,
            within=False,
            message="Even with maximum title truncation, path exceeds limit. Check ASIN length.",
        )
        return dst_dir, Path(truncated_filename)


def _torrent_path_length(folder_name: str, filename: str) -> int:
    """Length of the path inside the .torrent (folder/filename), not the OS path."""
    return len(folder_name) + len(TORRENT_PATH_SEPARATOR) + len(filename)


def _fits_red_cap(folder_name: str, filename: str, path_cap: int = PATH_CAP) -> bool:
    return _torrent_path_length(folder_name, filename) <= path_cap


def validate_path_length(
    dst_dir: Path, dst_file: str, path_cap: int = PATH_CAP
) -> bool:
    """
    Validate full torrent-internal path is within the RED 180-char cap.
    Uses the final folder name (leaf) + '/' + file name.
    """
    folder_name = dst_dir.name
    filename = Path(dst_file).name
    return _fits_red_cap(folder_name, filename, path_cap)
