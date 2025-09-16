"""
Core hardlinking functionality
"""

import os
import re
import sys
from pathlib import Path

from rich.console import Console

from .config import ConfigManager
from .display import Sty, row
from .red_paths import build_dst_paths, parse_tokens
from .utils.logging import get_logger
from .utils.timing import log_step

# Global console instance
console = Console()

# Get logger for this module
log = get_logger(__name__)


def _enforce_asin_policy(folder_name: str, filename: str, asin: str) -> None:
    """
    Enforce policy that ASIN must be present in both folder and file names.

    Args:
        folder_name: Destination folder name
        filename: Destination file name
        asin: Expected ASIN (e.g., "{ASIN.B0CW3NF5NY}")

    Raises:
        ValueError: If ASIN is missing from folder or file
    """
    in_folder = asin in folder_name
    in_file = asin in filename

    if not in_folder or not in_file:
        log.error(
            "policy.asin_missing",
            asin=asin,
            in_folder=in_folder,
            in_file=in_file,
            folder=folder_name,
            file=filename,
            message="ASIN must be present in both folder and file names for RED compliance",
        )
        raise ValueError(f"ASIN policy violation: {asin} missing from folder or file")


def set_file_permissions_and_ownership(file_path: Path):
    """Set file permissions and ownership based on configuration"""
    config_manager = ConfigManager()
    config = config_manager.load_config()

    logger = log.bind(file_path=str(file_path))

    if config.get("set_permissions", False):
        file_perms = config.get("file_permissions", 0o644)
        if isinstance(file_perms, int):
            try:
                os.chmod(file_path, file_perms)
                logger.debug("permissions.file_set", permissions=oct(file_perms))
            except OSError as e:
                logger.error(
                    "permissions.file_failed", error=str(e), permissions=oct(file_perms)
                )
        else:
            logger.warning("permissions.file_invalid", configured_perms=file_perms)

    if config.get("set_ownership", False):
        owner_user = config.get("owner_user", "")
        owner_group = config.get("owner_group", "")

        if (isinstance(owner_user, str) and owner_user) or (
            isinstance(owner_group, str) and owner_group
        ):
            try:
                import grp
                import pwd

                # Handle numeric user ID or username
                if isinstance(owner_user, str) and owner_user:
                    if owner_user.isdigit():
                        uid = int(owner_user)
                    else:
                        uid = pwd.getpwnam(owner_user).pw_uid
                else:
                    uid = -1

                # Handle numeric group ID or groupname
                if isinstance(owner_group, str) and owner_group:
                    if owner_group.isdigit():
                        gid = int(owner_group)
                    else:
                        gid = grp.getgrnam(owner_group).gr_gid
                else:
                    gid = -1

                os.chown(file_path, uid, gid)
                logger.debug(
                    "ownership.file_set",
                    user=owner_user,
                    group=owner_group,
                    uid=uid,
                    gid=gid,
                )
            except (KeyError, OSError, ValueError) as e:
                logger.error(
                    "ownership.file_failed",
                    error=str(e),
                    user=owner_user,
                    group=owner_group,
                )
                console.print(f"[yellow]⚠️  Ownership setting failed: {e}[/yellow]")


def set_dir_permissions_and_ownership(dir_path: Path):
    """Set directory permissions and ownership based on configuration"""
    config_manager = ConfigManager()
    config = config_manager.load_config()

    if config.get("set_dir_permissions", False):
        dir_perms = config.get("dir_permissions", 0o755)
        if isinstance(dir_perms, int):
            try:
                os.chmod(dir_path, dir_perms)
                console.print(f"[dim]  📁 chmod {oct(dir_perms)[-3:]} (dir)[/dim]")
            except OSError as e:
                console.print(
                    f"[yellow]⚠️  Directory permission setting failed: {e}[/yellow]"
                )

    if config.get("set_ownership", False):
        owner_user = config.get("owner_user", "")
        owner_group = config.get("owner_group", "")
        if (isinstance(owner_user, str) and owner_user) or (
            isinstance(owner_group, str) and owner_group
        ):
            try:
                import grp
                import pwd

                # Handle numeric user ID or username
                if isinstance(owner_user, str) and owner_user:
                    if owner_user.isdigit():
                        uid = int(owner_user)
                    else:
                        uid = pwd.getpwnam(owner_user).pw_uid
                else:
                    uid = -1

                # Handle numeric group ID or groupname
                if isinstance(owner_group, str) and owner_group:
                    if owner_group.isdigit():
                        gid = int(owner_group)
                    else:
                        gid = grp.getgrnam(owner_group).gr_gid
                else:
                    gid = -1

                os.chown(dir_path, uid, gid)
                console.print(f"[dim]  👤 chown {owner_user}:{owner_group} (dir)[/dim]")
            except (OSError, KeyError, ValueError) as e:
                console.print(
                    f"[yellow]⚠️  Directory ownership setting failed: {e}[/yellow]"
                )


# Exclusions
EXCLUDE_DEST_NAMES = {"cover.jpg", "metadata.json"}
EXCLUDE_DEST_EXTS = {".epub"}

WEIRD_SUFFIXES = [
    (".cue.jpg", ".jpg"),
    (".cue.jpeg", ".jpeg"),
    (".cue.png", ".png"),
    (".cue.m4b", ".m4b"),
    (".cue.mp3", ".mp3"),
]

IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp"}
DOC_EXTS = {".pdf", ".txt", ".nfo"}
AUDIO_EXTS = {".m4b", ".mp3", ".flac", ".m4a"}


def zero_pad_vol(name: str, width: int = 2) -> str:
    """Turn 'vol_4' into 'vol_04' (width=2) only in the basename string provided."""

    def pad(match):
        num = match.group(1)
        return f"vol_{int(num):0{width}d}"

    return re.sub(r"vol_(\d+)", pad, name)


def normalize_weird_ext(src_name: str) -> str:
    """Normalize weird suffixes like *.cue.jpg -> *.jpg and *.cue.m4b -> *.m4b."""
    for bad, good in WEIRD_SUFFIXES:
        if src_name.endswith(bad):
            return src_name[: -len(bad)] + good
    return src_name


def clean_base_name(name: str) -> str:
    """Remove user tags from base name but preserve ASIN for RED compliance"""
    # Remove user tags like [H2OKing], [UserName] but preserve {ASIN.B09CVBWLZT}
    import re

    # First extract and preserve any ASIN tag
    asin_match = re.search(r"\{ASIN\.[A-Z0-9]+\}", name)
    asin_tag = asin_match.group(0) if asin_match else ""

    # Remove all bracket and curly brace tags at the end
    cleaned = re.sub(r"(\s*[\[\{][^\]\}]+[\]\}]\s*)+$", "", name)

    # Re-add the ASIN tag if it was present
    if asin_tag:
        cleaned = f"{cleaned} {asin_tag}"

    return cleaned.strip()


def dest_is_excluded(p: Path) -> bool:
    """Check if destination should be excluded"""
    name = p.name.casefold()
    if name in EXCLUDE_DEST_NAMES:
        return True
    if p.suffix.lower() in EXCLUDE_DEST_EXTS:
        return True
    return False


def same_inode(a: Path, b: Path) -> bool:
    try:
        sa = a.stat()
        sb = b.stat()
        return (sa.st_ino == sb.st_ino) and (sa.st_dev == sb.st_dev)
    except FileNotFoundError:
        return False


def ensure_dir(p: Path, dry_run: bool, stats: dict):
    if p.exists():
        return
    if dry_run:
        row("📁", Sty.YELLOW, "mkdir", Path("—"), p, dry_run)
        stats["skipped"] += 0  # just noise control
    else:
        p.mkdir(parents=True, exist_ok=True)
        row("📁", Sty.BLUE, "mkdir", Path("—"), p, dry_run)
        # Apply directory permissions and ownership
        set_dir_permissions_and_ownership(p)


def choose_base_outputs(dest_dir: Path, base_name: str):
    """Return canonical dest paths for common types."""
    # Remove user tags from file names while keeping them in folder names
    clean_file_base = clean_base_name(base_name)

    return {
        "cue": dest_dir / f"{clean_file_base}.cue",
        "jpg": dest_dir / f"{clean_file_base}.jpg",
        "m4b": dest_dir / f"{clean_file_base}.m4b",
        "mp3": dest_dir / f"{clean_file_base}.mp3",
        "flac": dest_dir / f"{clean_file_base}.flac",
        "pdf": dest_dir / f"{clean_file_base}.pdf",
        "txt": dest_dir / f"{clean_file_base}.txt",
        "nfo": dest_dir / f"{clean_file_base}.nfo",
    }


def do_link(src: Path, dst: Path, force: bool, dry_run: bool, stats: dict):
    """Create hardlink from src to dst with proper error handling and logging"""
    logger = log.bind(src=str(src), dst=str(dst), force=force, dry_run=dry_run)

    # Safety: ensure we have a valid source
    if src is None or not isinstance(src, Path):
        logger.warning(
            "link.skip_invalid_src", reason="invalid_source", src=str(src), dst=str(dst)
        )
        row("🚫", Sty.GREY, "skip", Path("—"), dst, dry_run)
        stats["skipped"] += 1
        return

    if not dry_run and not src.exists():
        logger.warning(
            "link.skip_missing_src",
            reason="source_not_found",
            src=str(src),
            dst=str(dst),
        )
        row("⚠️ ", Sty.YELLOW, "skip", src, dst, dry_run)
        stats["skipped"] += 1
        return

    # Respect destination exclusions
    if dest_is_excluded(dst):
        logger.debug(
            "link.skip_excluded",
            reason="destination_excluded",
            src=str(src),
            dst=str(dst),
        )
        row("🚫", Sty.GREY, "excl.", src, dst, dry_run)
        stats["excluded"] += 1
        return

    # Already hardlinked?
    if dst.exists() and same_inode(src, dst):
        logger.debug(
            "link.skip_already_linked", reason="same_inode", src=str(src), dst=str(dst)
        )
        row("✓", Sty.GREY, "ok", src, dst, dry_run)
        stats["already"] += 1
        return

    # Replace if exists & force
    if dst.exists() and force:
        if dry_run:
            logger.info(
                "link.replaced",
                action="replace",
                mode="dry_run",
                src=str(src),
                dst=str(dst),
            )
            row("↻", Sty.YELLOW, "repl", src, dst, dry_run)
            stats["replaced"] += 1
        else:
            try:
                dst.unlink()
                os.link(src, dst)
                set_file_permissions_and_ownership(dst)
                logger.info(
                    "link.replaced",
                    action="replace",
                    mode="commit",
                    src=str(src),
                    dst=str(dst),
                )
                row("↻", Sty.BLUE, "repl", src, dst, dry_run)
                stats["replaced"] += 1
            except OSError as e:
                logger.error(
                    "link.error",
                    action="replace",
                    error=str(e),
                    src=str(src),
                    dst=str(dst),
                )
                row("💥", Sty.RED, "err", src, dst, dry_run)
                print(
                    f"\x1b[31m    {e}\x1b[0m", file=sys.stderr
                )  # Keep ANSI for stderr
                stats["errors"] += 1
        return

    # Don't overwrite without force
    if dst.exists() and not force:
        logger.debug(
            "link.exists",
            reason="destination_exists_no_force",
            src=str(src),
            dst=str(dst),
        )
        row("⏭️", Sty.YELLOW, "exist", src, dst, dry_run)
        stats["exists"] += 1
        return

    # Create link
    if dry_run:
        logger.info(
            "link.created", action="create", mode="dry_run", src=str(src), dst=str(dst)
        )
        row("🔗", Sty.YELLOW, "link", src, dst, dry_run)
        stats["linked"] += 1
    else:
        try:
            os.link(src, dst)
            set_file_permissions_and_ownership(dst)
            logger.info(
                "link.created",
                action="create",
                mode="commit",
                src=str(src),
                dst=str(dst),
            )
            row("🔗", Sty.GREEN, "link", src, dst, dry_run)
            stats["linked"] += 1
        except OSError as e:
            logger.error(
                "link.error", action="create", error=str(e), src=str(src), dst=str(dst)
            )
            row("💥", Sty.RED, "err", src, dst, dry_run)


@log_step("linker.plan_red")
def plan_and_link_red(
    src_dir: Path,
    dst_root: Path,
    also_cover: bool,
    zero_pad: bool,
    force: bool,
    dry_run: bool,
    stats: dict,
):
    """RED-compliant version of plan_and_link using path shortening"""
    logger = log.bind(
        src_dir=str(src_dir), dst_root=str(dst_root), force=force, dry_run=dry_run
    )

    # Use RED path system to determine destination
    dst_dir, dst_file = build_dst_paths(src_dir, dst_root)

    # Extract ASIN from source for validation

    tokens = parse_tokens(src_dir.name, dst_file.suffix)
    asin = tokens.asin

    # Bind content context for this book
    book_logger = logger.bind(
        asin=asin,
        title=tokens.title,
        volume=f"vol_{tokens.volume}" if tokens.volume else None,
    )

    # Enforce ASIN policy: must be in both folder and file
    _enforce_asin_policy(dst_dir.name, dst_file.name, asin)

    book_logger.debug(
        "linker.red_paths_processed",
        original_src=str(src_dir),
        trimmed_dst_dir=str(dst_dir),
        trimmed_filename=str(dst_file),
        policy_validated=True,
    )

    # Extract base name from the generated filename (without extension)
    base_name = dst_file.stem

    # Call the original plan_and_link with trimmed paths
    plan_and_link(
        src_dir, dst_dir, base_name, also_cover, zero_pad, force, dry_run, stats
    )


@log_step("linker.plan")
def plan_and_link(
    src_dir: Path,
    dst_dir: Path,
    base_name: str,
    also_cover: bool,
    zero_pad: bool,
    force: bool,
    dry_run: bool,
    stats: dict,
):
    """Main linking function with structured logging and context binding"""
    logger = log.bind(
        src_dir=str(src_dir),
        dst_dir=str(dst_dir),
        base_name=base_name,
        force=force,
        dry_run=dry_run,
        also_cover=also_cover,
    )

    if zero_pad:
        base_name = zero_pad_vol(base_name)
        logger.debug("linker.name_zero_padded", new_base_name=base_name)

    ensure_dir(dst_dir, dry_run, stats)
    outputs = choose_base_outputs(dst_dir, base_name)
    logger.debug(
        "linker.outputs_planned", output_paths=[str(p) for p in outputs.values()]
    )

    # Gather source files
    try:
        files = list(src_dir.iterdir())
        logger.debug("linker.files_discovered", file_count=len(files))
    except FileNotFoundError:
        logger.error("linker.src_dir_not_found", src_dir=str(src_dir))
        print(
            f"\x1b[31m[ERR] Source directory not found: {src_dir}\x1b[0m",
            file=sys.stderr,
        )
        stats["errors"] += 1
        return

    if not files:
        logger.warning("linker.no_files_found", src_dir=str(src_dir))
        console.print(f"[yellow][WARN] No files found in {src_dir}[/yellow]")
        return

    # Categorize and normalize weird suffixes
    normalized = []
    for p in files:
        fixed_name = normalize_weird_ext(p.name)
        normalized.append((p, fixed_name))

    logger.debug(
        "linker.files_normalized",
        original_count=len(files),
        normalized_count=len(normalized),
    )

    # Prioritize linking: cue, audio, image, docs
    for src_path, fixed_name in normalized:
        ext = Path(fixed_name).suffix.lower()
        if ext not in (AUDIO_EXTS | IMG_EXTS | DOC_EXTS | {".cue"}):
            continue

        if ext == ".cue":
            dst = outputs["cue"]
        elif ext in AUDIO_EXTS:
            if ext == ".m4b":
                dst = outputs["m4b"]
            elif ext == ".mp3":
                dst = outputs["mp3"]
            elif ext == ".flac":
                dst = outputs["flac"]
            elif ext == ".m4a":
                dst = dst_dir / f"{base_name}.m4a"
            else:
                continue
        elif ext in IMG_EXTS:
            dst = outputs["jpg"]  # canonical .jpg name regardless of source img ext
        elif ext in DOC_EXTS:
            if ext == ".pdf":
                dst = outputs["pdf"]
            elif ext == ".txt":
                dst = outputs["txt"]
            elif ext == ".nfo":
                dst = outputs["nfo"]
            else:
                continue
        else:
            continue

        do_link(src_path, dst, force=force, dry_run=dry_run, stats=stats)

    # Optionally make a plain cover.jpg as well — but only if not excluded
    if also_cover:
        named_cover = outputs["jpg"]
        plain_cover = dst_dir / "cover.jpg"
        if not dest_is_excluded(plain_cover):
            if named_cover.exists() or dry_run:
                # If dry-run and not created yet, pick source image to show intent
                src_img = None
                if not named_cover.exists():
                    src_img = next(
                        (
                            p
                            for p, n in normalized
                            if normalize_weird_ext(n)
                            .lower()
                            .endswith((".jpg", ".jpeg", ".png"))
                        ),
                        None,
                    )
                do_link(
                    src_img if src_img is not None else named_cover,
                    plain_cover,
                    force=force,
                    dry_run=dry_run,
                    stats=stats,
                )
                logger.debug(
                    "linker.cover_link_attempted",
                    named_cover=str(named_cover),
                    plain_cover=str(plain_cover),
                )
        else:
            logger.debug("linker.cover_excluded", plain_cover=str(plain_cover))
            row("🚫", Sty.GREY, "excl.", named_cover, plain_cover, dry_run)


def preflight_checks(src: Path, dst: Path) -> bool:
    """Run preflight checks before linking"""
    # Check if paths exist
    if not src.exists():
        console.print(f"[red]❌ Source doesn't exist: {src}[/red]")
        return False

    # Check same filesystem
    try:
        if src.stat().st_dev != dst.parent.stat().st_dev:
            console.print("[red]❌ Cross-device link error[/red]")
            console.print("   Source and destination must be on same filesystem")
            console.print(f"   Source: {src}")
            console.print(f"   Dest:   {dst}")
            return False
    except FileNotFoundError:
        pass  # Destination doesn't exist yet, that's ok

    # Check for Unraid user/disk mixing
    src_str, dst_str = str(src), str(dst)
    if ("/mnt/user/" in src_str and "/mnt/disk" in dst_str) or (
        "/mnt/disk" in src_str and "/mnt/user/" in dst_str
    ):
        console.print("[red]❌ Unraid user/disk mixing detected[/red]")
        console.print("   Hardlinks won't work between /mnt/user and /mnt/disk paths")
        return False

    return True


def run_batch(batch_file: Path, also_cover, zero_pad, force, dry_run):
    """Process batch file with src|dst pairs"""
    from .display import section

    logger = log.bind(
        batch_file=str(batch_file),
        also_cover=also_cover,
        zero_pad=zero_pad,
        force=force,
        dry_run=dry_run,
    )

    logger.info("batch.start", operation="run_batch")

    stats = {
        "linked": 0,
        "replaced": 0,
        "already": 0,
        "exists": 0,
        "excluded": 0,
        "skipped": 0,
        "errors": 0,
    }

    try:
        with batch_file.open() as fh:
            line_count = 0
            processed_count = 0

            for line in fh:
                line_count += 1
                line = line.strip()
                if not line or line.startswith("#"):
                    continue

                try:
                    src_s, dst_s = (x.strip() for x in line.split("|", 1))
                    processed_count += 1
                except ValueError:
                    logger.warning(
                        "batch.bad_line", line_number=line_count, content=line
                    )
                    console.print(
                        f"[yellow][WARN] bad line (expected 'SRC|DST'): {line}[/yellow]"
                    )
                    continue

                src = Path(src_s)
                dst = Path(dst_s)
                base = dst.name

                # Bind context for this book
                from .utils.logging import bind_audiobook_context

                bind_audiobook_context(asin=base, title=base, volume="")
                logger.debug(
                    "batch.processing_book", src=str(src), dst=str(dst), base=base
                )
                section(f"🎧 {base}")
                plan_and_link(
                    src, dst, base, also_cover, zero_pad, force, dry_run, stats
                )

        logger.info(
            "batch.complete",
            operation="run_batch",
            lines_read=line_count,
            books_processed=processed_count,
            **stats,
        )

    except FileNotFoundError:
        logger.error("batch.file_not_found", batch_file=str(batch_file))
        console.print(f"[red]❌ Batch file not found: {batch_file}[/red]")
        stats["errors"] += 1
    except Exception as e:
        logger.error(
            "batch.unexpected_error", error=str(e), error_type=type(e).__name__
        )
        console.print(f"[red]❌ Unexpected error processing batch: {e}[/red]")
        stats["errors"] += 1

    return stats
