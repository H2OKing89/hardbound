#!/usr/bin/env python3
import argparse, os, re, sys, shutil
from pathlib import Path
from time import perf_counter

# -------------------------
# Exclusions (DESTINATION)
# -------------------------
# These destination basenames will NEVER be created.
# We still allow using a source "cover.jpg" to build the canonical
# "<base>.jpg" in the destination; we just don't create a plain "cover.jpg".
EXCLUDE_DEST_NAMES = {"cover.jpg", "metadata.json", ".epub"}

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

# ---------- Styling ----------
class Sty:
    RESET = "\x1b[0m"
    BOLD = "\x1b[1m"
    DIM = "\x1b[2m"
    ITAL = "\x1b[3m"
    GREY = "\x1b[90m"
    RED = "\x1b[31m"
    GREEN = "\x1b[32m"
    YELLOW = "\x1b[33m"
    BLUE = "\x1b[34m"
    MAGENTA = "\x1b[35m"
    CYAN = "\x1b[36m"
    WHITE = "\x1b[37m"

    enabled = True

    @classmethod
    def off(cls):
        cls.enabled = False
        for k, v in cls.__dict__.items():
            if isinstance(v, str) and v.startswith("\x1b"):
                setattr(cls, k, "")

def term_width(default=100):
    try:
        return shutil.get_terminal_size().columns
    except Exception:
        return default

def ellipsize(s: str, limit: int) -> str:
    if len(s) <= limit:
        return s
    if limit <= 10:
        return s[:max(0, limit - 1)] + "…"
    keep = (limit - 1) // 2
    return s[:keep] + "… " + s[-(limit - keep - 2):]

def banner(title: str, mode: str):
    w = term_width()
    line = "─" * max(4, w - 2)
    label = f"{Sty.BOLD}{Sty.CYAN} {title} {Sty.RESET}"
    mode_tag = f"{Sty.YELLOW}[DRY-RUN]{Sty.RESET}" if mode == "dry" else f"{Sty.GREEN}[COMMIT]{Sty.RESET}"
    print(f"┌{line}┐")
    print(f"│ {label}{mode_tag}".ljust(w - 1) + "│")
    print(f"└{line}┘")

def section(title: str):
    w = term_width()
    line = "─" * max(4, w - 2)
    print(f"{Sty.MAGENTA}{title}{Sty.RESET}")
    print(line)

def row(status_icon: str, status_color: str, kind: str, src: Path, dst: Path, dry: bool):
    w = term_width()
    left = f"{status_icon} {status_color}{kind:<6}{Sty.RESET}"
    middle = f"{Sty.GREY}{src}{Sty.RESET} {Sty.DIM}→{Sty.RESET} {dst}"
    usable = max(20, w - len(strip_ansi(left)) - 6)
    print(f"{left}  {ellipsize(middle, usable)}")

def strip_ansi(s: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", s)

def summary_table(stats: dict, elapsed: float):
    w = term_width()
    line = "─" * max(4, w - 2)
    print(line)
    def cell(label, n, color):
        return f"{color}{label}:{Sty.RESET} {n}"
    cells = [
        cell("linked", stats["linked"], Sty.GREEN),
        cell("replaced", stats["replaced"], Sty.BLUE),
        cell("already", stats["already"], Sty.GREY),
        cell("exists", stats["exists"], Sty.YELLOW),
        cell("excluded", stats["excluded"], Sty.GREY),
        cell("skipped", stats["skipped"], Sty.GREY),
        cell("errors", stats["errors"], Sty.RED),
    ]
    s = "  |  ".join(cells)
    print(s)
    print(f"{Sty.CYAN}elapsed{Sty.RESET}: {elapsed:.3f}s")
    print(line)

# ---------- Core helpers ----------
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

def choose_base_outputs(dest_dir: Path, base_name: str):
    """Return canonical dest paths for common types."""
    return {
        "cue": dest_dir / f"{base_name}.cue",
        "jpg": dest_dir / f"{base_name}.jpg",
        "m4b": dest_dir / f"{base_name}.m4b",
        "mp3": dest_dir / f"{base_name}.mp3",
        "flac": dest_dir / f"{base_name}.flac",
        "pdf": dest_dir / f"{base_name}.pdf",
        "txt": dest_dir / f"{base_name}.txt",
        "nfo": dest_dir / f"{base_name}.nfo",
    }

def dest_is_excluded(p: Path) -> bool:
    return p.name.casefold() in EXCLUDE_DEST_NAMES

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

def do_link(src: Path, dst: Path, force: bool, dry_run: bool, stats: dict):
    # Safety: ensure we have a valid source
    if src is None or not isinstance(src, Path):
        row("🚫", Sty.GREY, "skip", Path("—"), dst, dry_run)
        stats["skipped"] += 1
        return

    if not dry_run and not src.exists():
        row("⚠️ ", Sty.YELLOW, "skip", src, dst, dry_run)
        stats["skipped"] += 1
        return

    # Respect destination exclusions
    if dest_is_excluded(dst):
        row("🚫", Sty.GREY, "excl.", src, dst, dry_run)
        stats["excluded"] += 1
        return

    # Already hardlinked?
    if dst.exists() and same_inode(src, dst):
        row("✓", Sty.GREY, "ok", src, dst, dry_run)
        stats["already"] += 1
        return

    # Replace if exists & force
    if dst.exists() and force:
        if dry_run:
            row("↻", Sty.YELLOW, "repl", src, dst, dry_run)
            stats["replaced"] += 1
        else:
            try:
                dst.unlink()
                os.link(src, dst)
                row("↻", Sty.BLUE, "repl", src, dst, dry_run)
                stats["replaced"] += 1
            except OSError as e:
                row("💥", Sty.RED, "err", src, dst, dry_run)
                print(f"{Sty.RED}    {e}{Sty.RESET}", file=sys.stderr)
                stats["errors"] += 1
        return

    # Don’t overwrite without force
    if dst.exists() and not force:
        row("⏭️", Sty.YELLOW, "exist", src, dst, dry_run)
        stats["exists"] += 1
        return

    # Create link
    if dry_run:
        row("🔗", Sty.YELLOW, "link", src, dst, dry_run)
        stats["linked"] += 1
    else:
        try:
            os.link(src, dst)
            row("🔗", Sty.GREEN, "link", src, dst, dry_run)
            stats["linked"] += 1
        except OSError as e:
            row("💥", Sty.RED, "err", src, dst, dry_run)
            print(f"{Sty.RED}    {e}{Sty.RESET}", file=sys.stderr)
            stats["errors"] += 1

def plan_and_link(src_dir: Path,
                  dst_dir: Path,
                  base_name: str,
                  also_cover: bool,
                  zero_pad: bool,
                  force: bool,
                  dry_run: bool,
                  stats: dict):
    if zero_pad:
        base_name = zero_pad_vol(base_name)

    ensure_dir(dst_dir, dry_run, stats)
    outputs = choose_base_outputs(dst_dir, base_name)

    # Gather source files
    try:
        files = list(src_dir.iterdir())
    except FileNotFoundError:
        print(f"{Sty.RED}[ERR] Source directory not found: {src_dir}{Sty.RESET}", file=sys.stderr)
        stats["errors"] += 1
        return

    if not files:
        print(f"{Sty.YELLOW}[WARN] No files found in {src_dir}{Sty.RESET}")
        return

    # Categorize and normalize weird suffixes
    normalized = []
    for p in files:
        fixed_name = normalize_weird_ext(p.name)
        normalized.append((p, fixed_name))

    # Prioritize linking: cue, audio, image, docs
    for src_path, fixed_name in normalized:
        ext = Path(fixed_name).suffix.lower()
        if ext not in (AUDIO_EXTS | IMG_EXTS | DOC_EXTS | {".cue"}):
            continue

        if ext == ".cue":
            dst = outputs["cue"]
            kind = "cue"
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
            kind = "audio"
        elif ext in IMG_EXTS:
            dst = outputs["jpg"]  # canonical .jpg name regardless of source img ext
            kind = "image"
        elif ext in DOC_EXTS:
            if ext == ".pdf":
                dst = outputs["pdf"]
            elif ext == ".txt":
                dst = outputs["txt"]
            elif ext == ".nfo":
                dst = outputs["nfo"]
            else:
                continue
            kind = "doc"
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
                        (p for p, n in normalized
                         if normalize_weird_ext(n).lower().endswith((".jpg", ".jpeg", ".png"))),
                        None
                    )
                do_link(src_img if src_img is not None else named_cover,
                        plain_cover, force=force, dry_run=dry_run, stats=stats)
        else:
            row("🚫", Sty.GREY, "excl.", named_cover, plain_cover, dry_run)

def run_batch(batch_file: Path, also_cover, zero_pad, force, dry_run):
    stats = {"linked":0, "replaced":0, "already":0, "exists":0, "excluded":0, "skipped":0, "errors":0}
    with batch_file.open() as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                src_s, dst_s = [x.strip() for x in line.split("|", 1)]
            except ValueError:
                print(f"{Sty.YELLOW}[WARN] bad line (expected 'SRC|DST'): {line}{Sty.RESET}")
                continue
            src = Path(src_s)
            dst = Path(dst_s)
            base = dst.name
            section(f"🎧 {base}")
            plan_and_link(src, dst, base, also_cover, zero_pad, force, dry_run, stats)
    return stats

def main():
    ap = argparse.ArgumentParser(
        description="Hardlink audiobook album folder to a torrent/seed folder with clean naming."
    )
    ap.add_argument("--src", type=Path, help="Source album directory (library/working copy).")
    ap.add_argument("--dst", type=Path, help="Destination album directory (seed/torrent folder).")
    ap.add_argument("--base-name", type=str,
                    help="Destination base filename (defaults to the dest folder name).")
    ap.add_argument("--zero-pad-vol", action="store_true",
                    help="Normalize 'vol_4' -> 'vol_04' inside the base name.")
    ap.add_argument("--also-cover", action="store_true",
                    help="Also create a 'cover.jpg' hardlink alongside the named .jpg (unless excluded).")
    ap.add_argument("--force", action="store_true",
                    help="Overwrite existing dest files.")
    ap.add_argument("--commit", action="store_true",
                    help="Actually create links.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Preview actions without making changes (default unless --commit).")
    ap.add_argument("--batch-file", type=Path,
                    help="Process many albums. Each line: 'SRC_DIR|DST_DIR'.")
    ap.add_argument("--no-color", action="store_true", help="Disable ANSI colors/icons.")
    ap.add_argument("--dst-root", type=Path,
                    help="Root folder under which a per-album directory will be created as DST_ROOT/<base-name>.")
    args = ap.parse_args()

    # Color control
    if args.no_color or not sys.stdout.isatty():
        Sty.off()

    # optional env fallbacks so you can export SRC/DST once in your shell
    if not args.src:
        env_src = os.getenv("SRC") or os.getenv("ABHL_SRC")
        if env_src:
            args.src = Path(env_src)

    if not args.dst and not args.dst_root:
        env_dst_root = os.getenv("DST") or os.getenv("DST_ROOT") or os.getenv("ABHL_DST_ROOT")
        if env_dst_root:
            args.dst_root = Path(env_dst_root)

    # sanity: don't allow both --dst and --dst-root
    if args.dst and args.dst_root:
        print(f"{Sty.RED}[ERR] Use either --dst or --dst-root, not both.{Sty.RESET}", file=sys.stderr)
        sys.exit(2)

    # Mutually-aware run mode
    if args.commit and args.dry_run:
        print(f"{Sty.RED}[ERR] Use either --commit or --dry-run, not both.{Sty.RESET}", file=sys.stderr)
        sys.exit(2)
    dry = args.dry_run or (not args.commit)

    start = perf_counter()
    banner("Audiobook Hardlinker", "dry" if dry else "commit")

    if args.batch_file:
        if any([args.src, args.dst, args.base_name]):
            print(f"{Sty.RED}[ERR] Use --batch-file OR single --src/--dst, not both.{Sty.RESET}", file=sys.stderr)
            sys.exit(2)
        if not args.batch_file.exists():
            print(f"{Sty.RED}[ERR] Batch file not found: {args.batch_file}{Sty.RESET}", file=sys.stderr)
            sys.exit(2)
        stats = run_batch(args.batch_file, args.also_cover, args.zero_pad_vol, args.force, dry)
        summary_table(stats, perf_counter() - start)
        return

    # Single run
    if not args.src or (not args.dst and not args.dst_root):
        print(f"{Sty.YELLOW}[HINT]{Sty.RESET} Provide --src and either --dst or --dst-root (or use --batch-file).")
        print()
        ap.print_help()
        sys.exit(2)

    if not args.src.exists():
        print(f"{Sty.RED}[ERR] Source not found: {args.src}{Sty.RESET}", file=sys.stderr)
        sys.exit(2)

    # If using dst-root, compute the real destination folder and base name
    if args.dst_root:
        base = args.base_name or args.src.name
        dst_dir = args.dst_root / base
    else:
        dst_dir = args.dst
        base = args.base_name or args.dst.name

    section("Plan")
    print(f"{Sty.BOLD} SRC{Sty.RESET}: {args.src}")
    print(f"{Sty.BOLD} DST{Sty.RESET}: {dst_dir}")
    print(f"{Sty.BOLD} BASE{Sty.RESET}: {base}")
    print(f"{Sty.BOLD} MODE{Sty.RESET}: {'DRY-RUN' if dry else 'COMMIT'}")
    print(f"{Sty.BOLD} OPTS{Sty.RESET}: zero_pad_vol={args.zero_pad_vol}  also_cover={args.also_cover}  force={args.force}")
    print()

    stats = {"linked":0, "replaced":0, "already":0, "exists":0, "excluded":0, "skipped":0, "errors":0}
    plan_and_link(args.src, dst_dir, base, args.also_cover, args.zero_pad_vol, args.force, dry, stats)
    summary_table(stats, perf_counter() - start)

if __name__ == "__main__":
    main()
