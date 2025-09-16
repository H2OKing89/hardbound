#!/usr/bin/env python3
"""
Hardbound - Scalable audiobook hardlink manager
Entry point for the application
"""

import argparse
import sys
from pathlib import Path
from time import perf_counter

from rich.console import Console

from hardbound.commands import (
    index_command,
    manage_command,
    search_command,
    select_command,
)
from hardbound.config import load_config

# Import from package
from hardbound.display import Sty, banner, section, summary_table
from hardbound.interactive import interactive_mode
from hardbound.linker import (
    plan_and_link,
    plan_and_link_red,
    preflight_checks,
    run_batch,
)
from hardbound.utils.logging import bind, get_logger, setup_logging

# Global console instance
console = Console()


def _classic_cli_mode(args):
    """Handle classic CLI arguments for backward compatibility"""
    # Mutually-aware run mode
    if args.commit and args.dry_run:
        print(
            "\x1b[31m[ERR] Use either --commit or --dry-run, not both.\x1b[0m",
            file=sys.stderr,
        )
        sys.exit(2)
    dry = args.dry_run or (not args.commit)

    # Handle batch file mode
    if args.batch_file:
        if any([args.src, args.dst, args.base_name]):
            print(
                "\x1b[31m[ERR] Use --batch-file OR single --src/--dst, not both.\x1b[0m",
                file=sys.stderr,
            )
            sys.exit(2)
        if not args.batch_file.exists():
            print(
                f"\x1b[31m[ERR] Batch file not found: {args.batch_file}\x1b[0m",
                file=sys.stderr,
            )
            sys.exit(2)

        start = perf_counter()
        banner("Audiobook Hardlinker", "dry" if dry else "commit")
        stats = run_batch(
            args.batch_file, args.also_cover, args.zero_pad_vol, args.force, dry
        )
        summary_table(stats, perf_counter() - start)
        return

    # Single run mode
    if not args.src or (not args.dst and not args.dst_root):
        console.print(
            "[yellow][HINT][/yellow] Provide --src and either --dst or --dst-root (or use --batch-file)."
        )
        sys.exit(2)

    if not args.src.exists():
        print(f"\x1b[31m[ERR] Source not found: {args.src}\x1b[0m", file=sys.stderr)
        sys.exit(2)

    # Sanity check: don't allow both --dst and --dst-root
    if args.dst and args.dst_root:
        print(
            "\x1b[31m[ERR] Use either --dst or --dst-root, not both.\x1b[0m",
            file=sys.stderr,
        )
        sys.exit(2)

    # If using dst-root, compute the real destination folder and base name
    if args.dst_root:
        # Use RED-compliant linking when dst_root is provided
        start = perf_counter()
        banner("Audiobook Hardlinker", "dry" if dry else "commit")

        section("Plan")
        console.print(f"[bold] SRC[/bold]: {args.src}")
        console.print(f"[bold] DST_ROOT[/bold]: {args.dst_root}")
        console.print(
            f"[bold] MODE[/bold]: {'DRY-RUN' if dry else 'COMMIT'} (RED-compliant)"
        )
        console.print(
            f"[bold] OPTS[/bold]: zero_pad_vol={args.zero_pad_vol}  also_cover={args.also_cover}  force={args.force}"
        )
        print()

        stats = {
            "linked": 0,
            "replaced": 0,
            "already": 0,
            "exists": 0,
            "excluded": 0,
            "skipped": 0,
            "errors": 0,
        }
        plan_and_link_red(
            args.src,
            args.dst_root,
            args.also_cover,
            args.zero_pad_vol,
            args.force,
            dry,
            stats,
        )
        summary_table(stats, perf_counter() - start)
        return
    else:
        # Traditional mode for explicit dst directory
        dst_dir = args.dst
        base = args.base_name or args.dst.name

        # Run preflight checks
        if not preflight_checks(args.src, dst_dir):
            sys.exit(1)

        start = perf_counter()
        banner("Audiobook Hardlinker", "dry" if dry else "commit")

        section("Plan")
        console.print(f"[bold] SRC[/bold]: {args.src}")
        console.print(f"[bold] DST[/bold]: {dst_dir}")
        console.print(f"[bold] BASE[/bold]: {base}")
        console.print(
            f"[bold] MODE[/bold]: {'DRY-RUN' if dry else 'COMMIT'} (traditional)"
        )
        console.print(
            f"[bold] OPTS[/bold]: zero_pad_vol={args.zero_pad_vol}  also_cover={args.also_cover}  force={args.force}"
        )
        print()

        stats = {
            "linked": 0,
            "replaced": 0,
            "already": 0,
            "exists": 0,
            "excluded": 0,
            "skipped": 0,
            "errors": 0,
        }
        plan_and_link(
            args.src,
            dst_dir,
            base,
            args.also_cover,
            args.zero_pad_vol,
            args.force,
            dry,
            stats,
        )
        summary_table(stats, perf_counter() - start)


def main():
    """Main program entry point"""
    # Load configuration first
    config = load_config()

    # Initialize structured logging
    logging_config = config.get("logging", {})
    setup_logging(
        level=logging_config.get("level", "INFO"),
        file_enabled=logging_config.get("file_enabled", True),
        console_enabled=logging_config.get("console_enabled", True),
        json_file=logging_config.get("json_file", True),
        log_path=Path(
            logging_config.get(
                "path", "/mnt/cache/scripts/hardbound/logs/hardbound.log"
            )
        ),
        rotate_max_bytes=logging_config.get("rotate_max_bytes", 10 * 1024 * 1024),
        rotate_backups=logging_config.get("rotate_backups", 5),
        rich_tracebacks=logging_config.get("rich_tracebacks", True),
        show_path=logging_config.get("show_path", False),
    )

    # Set global context with schema versioning and correlation ID
    from uuid import uuid4

    job_id = str(uuid4())
    bind(
        app="hardbound",
        schema="1.0",
        app_version="2.0.0",
        run_id=str(uuid4()),
        job_id=job_id,
    )
    log = get_logger(__name__)
    log.info("startup", logger_level=logging_config.get("level", "INFO"))

    ap = argparse.ArgumentParser(
        description="Hardbound - Scalable audiobook hardlink manager",
        epilog="Examples:\n"
        "  hardbound                    # Interactive mode\n"
        "  hardbound index              # Build search catalog\n"
        "  hardbound select -m          # Search and multi-select\n"
        "  hardbound manage optimize    # Database maintenance\n"
        "  hardbound --src X --dst Y    # Classic single link",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = ap.add_subparsers(dest="command", help="Commands")

    # Index command
    index_parser = subparsers.add_parser("index", help="Build/update audiobook catalog")
    index_parser.add_argument(
        "roots", nargs="*", type=Path, help="Directories to index"
    )
    index_parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")

    # Search command
    search_parser = subparsers.add_parser("search", help="Search audiobook catalog")
    search_parser.add_argument("query", nargs="*", help="Search terms")
    search_parser.add_argument("--author", help="Filter by author")
    search_parser.add_argument("--series", help="Filter by series")
    search_parser.add_argument("--book", help="Filter by book name")
    search_parser.add_argument("--limit", type=int, default=100, help="Max results")
    search_parser.add_argument("--json", action="store_true", help="Output as JSON")

    # Select command
    select_parser = subparsers.add_parser(
        "select", help="Interactive selection with fzf"
    )
    select_parser.add_argument("query", nargs="*", help="Initial search filter")
    select_parser.add_argument(
        "-m", "--multi", action="store_true", help="Multi-select mode"
    )
    select_parser.add_argument(
        "--link", action="store_true", help="Link selected items"
    )
    select_parser.add_argument(
        "--dst-root", type=Path, help="Destination root for linking"
    )
    select_parser.add_argument(
        "--integration",
        choices=["torrent", "red"],
        help="Use specific integration for linking",
    )
    select_parser.add_argument("--dry-run", action="store_true", help="Preview only")

    # Manage command
    manage_parser = subparsers.add_parser("manage", help="Database index management")
    manage_parser.add_argument(
        "action",
        choices=["rebuild", "clean", "optimize", "stats", "vacuum", "verify"],
        help="Management action to perform",
    )
    manage_parser.add_argument("-q", "--quiet", action="store_true", help="Quiet mode")

    # Classic arguments (for backward compatibility)
    ap.add_argument("--src", type=Path, help="Source album directory")
    ap.add_argument("--dst", type=Path, help="Destination album directory")
    ap.add_argument("--dst-root", type=Path, help="Destination root (creates subdir)")
    ap.add_argument("--base-name", type=str, help="Destination base filename")
    ap.add_argument(
        "--zero-pad-vol", action="store_true", help="Normalize vol_4 → vol_04"
    )
    ap.add_argument("--also-cover", action="store_true", help="Also create cover.jpg")
    ap.add_argument("--force", action="store_true", help="Overwrite existing files")
    ap.add_argument("--commit", action="store_true", help="Actually create links")
    ap.add_argument("--dry-run", action="store_true", help="Preview only (default)")
    ap.add_argument("--batch-file", type=Path, help="Process batch file")
    ap.add_argument("--no-color", action="store_true", help="Disable colors")

    args = ap.parse_args()

    # Color control
    if args.no_color or not sys.stdout.isatty():
        Sty.off()

    # Route to appropriate handler
    if args.command == "index":
        index_command(args)
    elif args.command == "search":
        search_command(args)
    elif args.command == "select":
        select_command(args)
    elif args.command == "manage":
        manage_command(args)
    elif args.src or args.batch_file:
        # Classic CLI mode
        _classic_cli_mode(args)
    else:
        # Interactive mode (default)
        interactive_mode()


if __name__ == "__main__":
    main()
    """Handle classic CLI arguments for backward compatibility"""
