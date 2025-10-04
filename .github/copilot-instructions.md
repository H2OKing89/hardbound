# Hardbound - AI Coding Agent Instructions

## Project Overview

Hardbound is a CLI tool for managing large audiobook libraries through hardlinks. It creates hardlinks from organized libraries to torrent directories, enabling seeding without file duplication. The project emphasizes **RED (tracker) compliance** with strict 180-character path limits and ASIN preservation.

**Key Technologies**: Python 3.13+, SQLite FTS5, Rich (TUI), structlog, pytest

## Architecture & Core Components

### Three-Layer Structure

1. **Entry Point** (`hardbound.py`): CLI argument parsing, mode routing (classic vs interactive)
2. **Core Modules** (`hardbound/`): Business logic separated by concern
3. **UI Package** (`hardbound/ui/`): Rich-based menus, feedback, progress indicators

### Critical Modules

- **`catalog.py`**: SQLite FTS5 full-text search engine for 1000+ audiobooks. Uses FTS5 virtual tables with triggers for auto-sync. Path parsing extracts author/series/book from directory structure and ASIN from filenames using regex patterns `{ASIN.B0C34GQRYZ}`, `[ASIN.B0C34GQRYZ]`, `[B0C34GQRYZ]`.

- **`linker.py`**: Core hardlinking with preflight checks (same filesystem via `os.stat().st_dev`), batch processing, and `plan_and_link_red()` for RED-compliant operations. Never mutates source files.

- **`red_paths.py`**: RED compliance engine. Implements token-based path shortening with strict invariants: ASIN must appear in both folder and filename, 180-char cap for `folder/file` (torrent-internal path only, not OS prefix). Trimming order: filename-first, then folder. Token priority: `ASIN → title → volume → subtitle → tag → author → year`. See `RED_PATH_SPEC.md` for full specification.

- **`interactive.py`**: 2187-line interactive mode with wizards, fzf integration (with fallback), multi-selection parsing (`1,3,5` or `1-5`), and operations history.

- **`config.py`**: JSON-based config with validation, migration, and multi-integration support (`torrent`, `red` with separate path limits). Stored at `./config.json` (portable, not user home).

- **`utils/logging.py`**: Structured logging via structlog with Rich console renderer + JSON file output. Supports context binding (`log.bind(asin=..., title=...)`) for request tracing.

## Development Workflows

### Setup & Testing

```bash
# Initial setup (creates venv, installs deps, pre-commit hooks)
./scripts/bootstrap.sh
source .venv/bin/activate

# Fast tests (skip slow integration tests)
pytest -q -m "not slow"

# Full test suite with coverage (80% minimum)
pytest --cov=hardbound --cov-report=term-missing

# Lint & format (auto-runs on commit via pre-commit)
ruff check --fix . && ruff format .
mypy .
```

### Test Markers
- `@pytest.mark.slow`: Integration tests with I/O
- `@pytest.mark.unit`: Fast unit tests
- `@pytest.mark.integration`: Cross-module tests

### Common Tasks

```bash
make test          # Run tests (default target)
make test-quick    # Skip slow tests
make fix           # Lint + format
make coverage      # Tests with HTML report
```

## Project-Specific Conventions

### Path Handling
- **Never mutate source files**: Hardbound is read-only on library paths
- **Filesystem checks**: Always verify `st_dev` matches before hardlinking (cross-filesystem links fail)
- **Path storage**: Use `Path` objects internally, convert to strings for display/config only
- **Torrent paths**: RED measures internal torrent paths (`folder/file`), not OS paths (`/mnt/user/...`)

### ASIN Policy (RED Compliance)
```python
# ASIN must appear in BOTH folder and filename
# Enforced by _enforce_asin_policy() in linker.py
folder: "Book Title vol_01 {ASIN.B0ABC123}"
file:   "Book Title vol_01 {ASIN.B0ABC123} [H2OKing].m4b"
```

### Volume Normalization
- Always use `vol_XX` format (zero-padded)
- Handles decimals: `vol_13.5` → `vol_13.5` (preserved)
- Input variants: `vol_13`, `vol.13`, `volume 13`, `v.13`, `13`

### Database Operations
- **Catalog location**: `./catalog.db` (script directory for portability)
- **FTS5 triggers**: Auto-maintain `items_fts` table on INSERT/UPDATE/DELETE
- **Maintenance**: Run `./hardbound.py manage stats` to check index health
- **Cleanup**: `manage clean` removes orphaned entries, `manage vacuum` reclaims space

### Configuration Management
- **Location**: `./config.json` (not `~/.config/`)
- **Multi-integration**: Support both regular torrents and RED with separate `path_limit` settings
- **Validation**: Use `PathValidator` for path checks, `ConfigManager.validate()` for schema
- **Migration**: Auto-migrate old configs via `_migrate_config()` in `config.py`

### Logging Patterns
```python
from hardbound.utils.logging import get_logger, bind

log = get_logger(__name__)

# Bind context for a job
bound_log = log.bind(asin="{ASIN.B0ABC123}", title="Book Title", job_id="link-123")
bound_log.info("processing.start", path=str(src_path))
bound_log.error("processing.failed", error=str(e))
```

### Error Handling
- **Preflight checks**: `preflight_checks()` validates before any I/O
- **Dry-run default**: `--dry-run` is default, `--commit` required for actual linking
- **User feedback**: Use Rich console (`console.print()`) for user-facing output, structlog for tracing

## Testing Guidelines

### Fixtures (tests/conftest.py)
- Minimal test setup - no heavy fixtures to avoid slow tests
- Use `tmp_path` (pytest built-in) for filesystem tests

### Test Structure
```python
def test_zero_pad_basic() -> None:
    """Test basic volume padding"""
    result = zero_pad("vol_4")
    assert result == "vol_04"
```

### Coverage Targets
- Minimum 80% coverage (enforced in `pyproject.toml`)
- Focus on `hardbound/` package, exclude `tests/`, `setup.py`
- HTML reports: `htmlcov/index.html`

## Key Integration Points

### External Dependencies
- **fzf**: Optional fuzzy finder, graceful fallback to hierarchical browser
- **SQLite**: FTS5 extension (usually included, check with `pragma compile_options`)
- **Rich**: All TUI rendering, progress bars, table formatting

### Filesystem Assumptions
- Unix-like paths (works on Windows via pathlib abstraction)
- Hardlinks require same filesystem (`st_dev` check)
- Permission management (optional): `file_permissions`, `dir_permissions`, `owner_user/group` in config

## Anti-Patterns to Avoid

❌ **Don't** modify source audiobook files  
❌ **Don't** use OS-specific path separators directly (use `Path`)  
❌ **Don't** count full OS paths for RED limit (only `folder/file`)  
❌ **Don't** skip ASIN validation for RED operations  
❌ **Don't** add slow tests without `@pytest.mark.slow`  
❌ **Don't** use print() for user output (use Rich console)  
❌ **Don't** store config in user home directory (use script directory)

## Quick Reference

### File Extensions
- Primary: `.m4b`, `.mp3`, `.flac`, `.opus`
- Cover: `.jpg`, `.png`
- Metadata: `.nfo`, `.txt`
- Exclude: `.cue`, `.url`, `.jpg.import`, `.sfv`

### Directory Structure Patterns
```
Author/Series/Book/          ← Full hierarchy
Author/Book/                 ← Direct mapping
torrent_destination/         ← Excluded from catalog
```

### RED Token Structure
```
<title> vol_XX [subtitle] (year) (author) {ASIN.xxxxx} [tag].ext
```

### Bootstrap Script Actions
1. Creates `.venv` with Python 3.13
2. Installs all dependencies (`.[all]` includes dev tools)
3. Sets up pre-commit hooks (ruff, mypy, detect-secrets)
4. Initializes commitizen for conventional commits
