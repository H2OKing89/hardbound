"""
Display utilities and formatting
"""
import shutil
import re
from pathlib import Path

class Sty:
    """ANSI color codes for terminal output"""
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