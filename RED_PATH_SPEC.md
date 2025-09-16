# RED Path Shortening & Naming Guardrails — Design, Usage, Tests, & Edge Cases

## Purpose

Produce torrent-internal paths (`<folder>/<file>`) that **always**:

* Fit within **180 characters** (RED's cap).
* Preserve **ASIN** in **both** the folder and the file.
* Never rename or mutate **source** files (src is read-only).
* Keep the canonical series structure: `title - vol_XX [- subtitle]` with metadata appended in a space-separated tail.

---

## Invariants (Non-Negotiables)

1. **ASIN required** and must appear in both:
   * Folder name (destination directory leaf).
   * File name (destination filename).

2. **Title** and **volume** must be present in both folder and file.

3. **Volume** normalized to `vol_XX` (zero-padded).

4. **Token priority for keeping (highest → lowest):**
   `ASIN → title → volume → subtitle → tag → author → year`

5. **Trimming order** (right-to-left):
   **Filename first**, then **folder** if still over cap.

6. **Never** partial-truncate tokens; only remove whole tokens in the specified order.

7. **Measure length as the torrent-internal path only:**
   `len(folder_name) + 1 + len(filename)`; **do not** count OS prefixes like `/mnt/...`.

---

## Canonical Shapes

### Folder (destination directory leaf)

```bash
<title> <vol_XX> [<subtitle>] [(year)] [(author)] {ASIN.xxxxx}
```

### File (destination filename)

```bash
<title> <vol_XX> [<subtitle>] [(year)] [(author)] {ASIN.xxxxx} [H2OKing]<ext>
```

* Spaces separate **title / volume / subtitle**.
* Space-separated tail holds `(year) (author) {ASIN} [tag]`.
* Tag is optional and **last**.

---

## Trimming Strategy (Deterministic)

### Stage A — Filename

Remove tokens in this order until the full path fits:

1. `(year)`
2. `(author)`
3. `[tag]`
4. `- <subtitle>`

Stop as soon as the path ≤ 180.

### Stage B — Folder (if still too long)

Remove in this order:

1. `(year)`
2. `(author)`
3. `- <subtitle>`

Stop as soon as the path ≤ 180.

> Resulting "minimum viable" forms:
>
> * **File:** `<title> - <vol_XX> {ASIN}<ext>`
> * **Folder:** `<title> - <vol_XX> {ASIN}`

---

## API Surface (the essentials you already have)

* `Tokens`: parsed tokens model.
* `normalize_volume(str) -> "vol_XX"`
* `parse_tokens(name, extension=".m4b") -> Tokens`
* `_series_str(tokens, include_subtitle=True) -> str`
* `build_filename(tokens, include_subtitle=True, include_year=True, include_author=True, include_tag=True) -> str`
* `build_folder_name(tokens, include_subtitle=True, include_year=True, include_author=True) -> str`
* `build_dst_paths(src: Path, dst_root: Path, extension: Optional[str]) -> tuple[Path, Path]`
* `validate_path_length(dst_dir: Path, dst_file: str, path_cap=180) -> bool`

### Internal helpers

* `_torrent_path_length(folder_name: str, filename: str) -> int`
* `_fits_red_cap(folder_name: str, filename: str, path_cap=180) -> bool`

### Deterministic extension choice

When `extension is None`, prefer:
`.m4b` → `.m4a` → `.mp3` → `.flac`

---

## Parsing Rules (Right-to-Left, Safe)

1. Remove `{ASIN.X…}` (required, captured exactly).
2. Remove trailing `[tag]` if present (kept as is when enabled).
3. Remove trailing `(author)` if present (captures the **last** parenthesized chunk).
4. Remove trailing `(year)` if present (only `(19xx|20xx)` at end).
5. Split the remaining **series** left-hand side on `" - "`:
   * `title = parts[0]`
   * `volume = normalize(parts[1]) → vol_XX`
   * `subtitle = ' - '.join(parts[2:])` if any

Edge-safe notes:

* Parentheses **inside** title/subtitle are untouched (not trailing).
* Tag and ASIN can contain uppercase/lowercase—ASIN regex is strict for `{ASIN.[A-Z0-9]+}`.

---

## Examples

### 1) Long LN name (your Overlord case)

**Input (non-compliant):**

```bash
Overlord vol_13 The Paladin of the Sacred Kingdom Part 2 (2024) (Kugane Maruyama) {ASIN.B0CW3NF5NY}/Overlord vol_13 The Paladin of the Sacred Kingdom Part 2 (2024) (Kugane Maruyama) {ASIN.B0CW3NF5NY}.m4b
```

**Trim path to compliant:**

* Filename trims `(year)`, `(author)`, and `subtitle` →
  `Overlord vol_13 {ASIN.B0CW3NF5NY}.m4b`
* Folder remains full or trims down as needed. A fully compliant example you provided:

  ```bash
  Overlord vol_13 The Paladin of the Sacred Kingdom Part 2 (2024) (Kugane Maruyama) {ASIN.B0CW3NF5NY}/Overlord vol_13 {ASIN.B0CW3NF5NY}.m4b
  ```

  **Length:** 143 (compliant under 180).

### 2) With a tag

* If space allows:
  `Title vol_05 Subtitle (2021) (Author) {ASIN.B0XXXXX} [H2OKing].m4b`
* If trimming needed, tag drops **before** subtitle drops in the file (per priority).

### 3) Minimal viable (very long titles)

* File: `Title - vol_07 {ASIN.B0XXXXX}.m4b`
* Folder: `Title - vol_07 {ASIN.B0XXXXX}`

---

## Property-Style Guarantees (Great for Tests)

* **Presence:** ASIN, title, volume are always present in both folder and file.
* **Length:** `_fits_red_cap(folder, file)` is `True` for returned pair.
* **Order:** Hyphens only join title/volume[/subtitle]; year/author/tag live in the spaced tail.
* **Idempotency:** Rebuilding with the same tokens and config yields the same strings.
* **No partial truncates:** Tokens are either intact or omitted—no mid-word slicing.

---

## Suggested Unit Tests (pytest)

```python
import pytest
from pathlib import Path
from hardbound.red_paths import (
    parse_tokens, build_filename, build_folder_name,
    build_dst_paths, validate_path_length, _fits_red_cap
)

def test_minimal_invariants():
    name = "Book - vol_01 (2023) (Author) {ASIN.B0ABC123}[H2OKing]"
    t = parse_tokens(name, ".m4b")
    f = build_filename(t, include_subtitle=False, include_year=False, include_author=False, include_tag=False)
    d = build_folder_name(t, include_subtitle=False, include_year=False, include_author=False)
    assert "{ASIN." in f and "{ASIN." in d
    assert " - vol_" in f and " - vol_" in d
    assert " - " in f.split(" (")[0]  # hyphen joiners in series
    assert f.endswith(".m4b")

def test_overlord_trimming():
    src = Path("/src/Overlord vol_13 The Paladin of the Sacred Kingdom Part 2 (2024) (Kugane Maruyama) {ASIN.B0CW3NF5NY}")
    dst_root = Path("/dst")
    dst_dir, dst_file = build_dst_paths(src, dst_root, ".m4b")
    folder, file = dst_dir.name, dst_file.name
    assert "{ASIN.B0CW3NF5NY}" in folder and "{ASIN.B0CW3NF5NY}" in file
    assert _fits_red_cap(folder, file)
    assert " - " in folder and " - " in file  # series joiners
    # ensure year/author/subtitle trimming is allowed but not required
    assert "vol_" in file

def test_trailing_paren_safety():
    tricky = "Title (2020) In Name vol_02 (Tricky) Sub (2024) (Real Author) {ASIN.B0XYZ}"
    t = parse_tokens(tricky, ".m4b")
    # inner parens preserved in title/subtitle; trailing tokens extracted
    assert t.year == "(2024)"
    assert t.author == "(Real Author)"
    assert "In Name" in t.title
    assert "(Tricky) Sub" == (t.subtitle or "")

def test_space_separation():
    """Test that series parts use spaces, not hyphens"""
    name = "Test Series vol_05 Long Subtitle (2023) (Author) {ASIN.B0TEST}"
    t = parse_tokens(name, ".m4b")
    filename = build_filename(t)
    folder = build_folder_name(t)

    # Both should have "Test Series vol_05 Long Subtitle" at the start
    assert filename.startswith("Test Series vol_05 Long Subtitle")
    assert folder.startswith("Test Series vol_05 Long Subtitle")

def test_deterministic_extension():
    """Test that extension selection follows deterministic priority"""
    import tempfile

    with tempfile.TemporaryDirectory() as tmpdir:
        test_dir = Path(tmpdir) / "Test {ASIN.B0TEST}"
        test_dir.mkdir()

        # Create files in reverse priority order
        (test_dir / "book.flac").touch()
        (test_dir / "book.mp3").touch()
        (test_dir / "book.m4a").touch()
        (test_dir / "book.m4b").touch()

        dst_dir, dst_file = build_dst_paths(test_dir, Path("/dest"))
        assert dst_file.suffix == ".m4b"  # Highest priority wins

def test_torrent_path_measurement():
    """Test that we measure torrent paths, not OS paths"""
    from hardbound.red_paths import _torrent_path_length

    # OS path should be irrelevant
    folder = "Short"
    filename = "short.m4b"

    # Only the folder/filename matters
    expected = len(folder) + 1 + len(filename)  # +1 for "/"
    actual = _torrent_path_length(folder, filename)
    assert actual == expected
    assert actual == 15  # "Short" + "/" + "short.m4b" = 5 + 1 + 9

def test_volume_normalization():
    """Test various volume formats normalize to vol_XX"""
    from hardbound.red_paths import normalize_volume

    assert normalize_volume("vol_13") == "vol_13"
    assert normalize_volume("vol.13") == "vol_13"
    assert normalize_volume("vol 13") == "vol_13"
    assert normalize_volume("volume 13") == "vol_13"
    assert normalize_volume("v.13") == "vol_13"
    assert normalize_volume("v13") == "vol_13"
    assert normalize_volume("13") == "vol_13"

    # Zero padding
    assert normalize_volume("vol_5") == "vol_05"
    assert normalize_volume("5") == "vol_05"

def test_path_cap_enforcement():
    """Test that paths never exceed the cap"""
    # Create a very long name that would exceed 180 chars
    long_name = f"{'Very ' * 20}Long Title vol_01 {'Super ' * 10}Long Subtitle (2024) (Very Long Author Name) {{ASIN.B0VERYLONGASIN}}"

    src = Path(f"/src/{long_name}")
    dst_root = Path("/dst")

    dst_dir, dst_file = build_dst_paths(src, dst_root, ".m4b")

    # Must fit within cap
    from hardbound.red_paths import _fits_red_cap
    assert _fits_red_cap(dst_dir.name, dst_file.name)

    # Must still have required elements
    assert "{ASIN." in dst_dir.name
    assert "{ASIN." in dst_file.name
    assert " - vol_" in dst_dir.name
    assert " - vol_" in dst_file.name
```

---

## CLI Wrapper (handy utility)

```python
#!/usr/bin/env python3
"""
CLI wrapper for RED path generation - useful for testing and dry runs
"""

import argparse
import json
from pathlib import Path
from hardbound.red_paths import build_dst_paths, validate_path_length, _torrent_path_length

def main():
    p = argparse.ArgumentParser(description="Generate RED-compliant paths for audiobook directories")
    p.add_argument("src_dir", type=Path, help="Source book directory (name must contain {ASIN.*})")
    p.add_argument("dst_root", type=Path, help="Destination root directory")
    p.add_argument("--ext", default=None, help="Force extension (e.g., .m4b)")
    p.add_argument("--dry-run", action="store_true", help="Show paths without creating anything")
    p.add_argument("--json", action="store_true", help="Output as JSON")
    args = p.parse_args()

    try:
        dst_dir, dst_file = build_dst_paths(args.src_dir, args.dst_root, args.ext)
        folder_name = dst_dir.name
        file_name = dst_file.name
        torrent_length = _torrent_path_length(folder_name, file_name)
        is_valid = validate_path_length(dst_dir, file_name)

        if args.json:
            result = {
                "src": str(args.src_dir),
                "dst_folder": folder_name,
                "dst_file": file_name,
                "torrent_path": f"{folder_name}/{file_name}",
                "length": torrent_length,
                "cap": 180,
                "valid": is_valid,
                "dry_run": args.dry_run
            }
            print(json.dumps(result, indent=2))
        else:
            print(f"Source:   {args.src_dir.name}")
            print(f"→ Folder: {folder_name}")
            print(f"→ File:   {file_name}")
            print(f"→ Path:   {folder_name}/{file_name}")
            print(f"→ Length: {torrent_length} chars")
            print(f"→ Valid:  {is_valid} (≤ 180)")

            if not is_valid:
                print("⚠️  WARNING: Path exceeds 180 character limit!")

        if not args.dry_run and is_valid:
            # Create destination directory
            dst_dir.mkdir(parents=True, exist_ok=True)
            print(f"Created directory: {dst_dir}")
            # Note: Actual hardlinking/copying would happen here in your pipeline

    except Exception as e:
        if args.json:
            print(json.dumps({"error": str(e)}, indent=2))
        else:
            print(f"Error: {e}")
        exit(1)

if __name__ == "__main__":
    main()
```

Save as `cli_red_paths.py` and make executable:

```bash
chmod +x cli_red_paths.py

# Usage examples:
./cli_red_paths.py "/src/Long Book Name {ASIN.B0TEST}" "/dst" --dry-run
./cli_red_paths.py "/src/Book {ASIN.B0TEST}" "/dst" --json --ext .m4b
```

---

## Integration Notes (Hardlink Pipeline)

### Source Protection

* **Src is sacred**: read only. Build dst names; then **hardlink** or **copy** from source audio into the computed dst directory.
* Never modify source files or directories - they remain exactly as-is.

### Filesystem Constraints

* **Hardlink constraints**: ensure the dst root resides on the same filesystem device as src; otherwise fallback to copy.
* Use `os.path.samefile()` or compare `st_dev` to detect cross-filesystem scenarios.

### Atomic Operations

* **Atomic finalization**: stage with temp name → move into place (especially if your uploader scans the directory concurrently).
* Example pattern:

  ```python
  temp_dst = dst_dir / f".tmp_{dst_file.name}"
  # Create hardlink to temp name
  os.link(src_audio_file, temp_dst)
  # Atomic rename
  temp_dst.rename(dst_dir / dst_file.name)
  ```

### Safety Margins

* **Safety margin (optional)**: consider trimming to ≤ 175 to leave headroom for tracker-side quirks.
* Some trackers may have additional restrictions or encoding differences.

### Permissions and Ownership

* Preserve or set appropriate permissions on destination files and directories.
* The hardbound system handles this via configurable permission settings.

---

## Logging / Audit (JSONL recommended)

Emit one line per processed source for operational visibility:

```json
{
  "timestamp": "2025-09-15T00:00:00Z",
  "src_path": "/mnt/user/audiobooks/Overlord vol_13 The Paladin of the Sacred Kingdom Part 2 (2024) (Kugane Maruyama) {ASIN.B0CW3NF5NY}",
  "src_name": "Overlord vol_13 The Paladin of the Sacred Kingdom Part 2 (2024) (Kugane Maruyama) {ASIN.B0CW3NF5NY}",
  "dst_folder": "Overlord vol_13 The Paladin of the Sacred Kingdom Part 2 (2024) (Kugane Maruyama) {ASIN.B0CW3NF5NY}",
  "dst_file": "Overlord vol_13 {ASIN.B0CW3NF5NY}.m4b",
  "torrent_path": "Overlord vol_13 The Paladin of the Sacred Kingdom Part 2 (2024) (Kugane Maruyama) {ASIN.B0CW3NF5NY}/Overlord vol_13 {ASIN.B0CW3NF5NY}.m4b",
  "length": 143,
  "cap": 180,
  "trim_steps": ["filename: drop year", "filename: drop author", "filename: drop subtitle"],
  "ext_detected": ".m4b",
  "ext_used": ".m4b",
  "tokens": {
    "title": "Overlord",
    "volume": "vol_13",
    "subtitle": "The Paladin of the Sacred Kingdom Part 2",
    "year": "(2024)",
    "author": "(Kugane Maruyama)",
    "asin": "{ASIN.B0CW3NF5NY}",
    "tag": null
  },
  "valid": true,
  "operation": "hardlink",
  "status": "success"
}
```

This makes it trivial to:

* Diff behaviors between runs
* Audit why something was shortened
* Debug parsing issues
* Track which files were processed
* Monitor system performance

---

## Edge Cases & How They're Handled

### Missing Components

* **Missing subtitle/author/year**: builder simply omits empty slots; keeps required series + ASIN.
* **Missing volume**: defaults to `vol_01` if no volume pattern found.

### Volume Variations

* **Weird volume forms**: `Volume 7`, `vol.7`, `V7`, `7` → all normalize to `vol_07`.
* **Non-numeric volumes**: `vol_special` → handled as-is but zero-padding skipped.

### Parsing Ambiguity

* **Internal parentheses**: only the **trailing** `(year)` and `(author)` are extracted; any others remain in the series part.
* **Multiple ASIN-like patterns**: uses the first match (should be unique in well-formed names).

### File System Edge Cases

* **Multiple audio files**: extension picker is deterministic; it selects the best available based on preference order.
* **No audio files**: defaults to `.m4b` extension.
* **Case sensitivity**: extension matching is case-insensitive (`.M4B` → `.m4b`).

### Character Encoding

* **Emoji/Unicode**: strings are treated as-is; length is Python string length.
* **Combining characters**: consider **NFC** normalization upstream for consistency if needed.
* **Control characters**: generally avoided but not explicitly filtered.

### Filesystem Compatibility

* **Illegal filesystem characters**: torrent-internal paths aren't OS-validated, but your hardlink destination **is**.
* **Windows compatibility**: If targeting Windows, sanitize `<>:"/\\|?*` and reserved device names (`CON`, `PRN`, etc.).
* **Linux compatibility**: mostly fine—just avoid control chars and nulls.

### Length Edge Cases

* **Extremely long titles**: system will trim to minimum viable form (title + volume + ASIN).
* **Very short names**: no minimum length enforced; system preserves all available tokens if under cap.
* **Unicode length vs byte length**: Python string length used (character count, not bytes).

---

## Optional Power-Ups (Configurable Extensions)

### Configurable Limits

* **`path_cap: int`** — default 180; keep open if tracker policy changes.
* **`safety_margin: int`** — target cap minus N (e.g., 5–10 chars) for extra safety.

### Enhanced Trimming

* **`keep_tag_when_possible: bool`** — true by default; tag drops before subtitle during filename trimming.
* **`preserve_subtitle_in_folder: bool`** — prefer keeping subtitle in folder over file when trimming.

### Abbreviation Mode (Advanced)

* **`abbreviation_mode: bool` (opt-in)** — reversible, safe abbreviations in **subtitle only**:
  * `Part → Pt`, `Volume → Vol`, `and → &`
  * Remove articles ("the", "a", "an") from subtitle only
  * **Never** abbreviate title, volume token, or ASIN
  * Must be reversible for round-trip compatibility

### Custom Extension Preferences

* **`ext_priority: List[str]`** — override default `.m4b → .m4a → .mp3 → .flac` ordering.
* **`fallback_ext: str`** — override default `.m4b` fallback.

---

## Quick Troubleshooting Checklist

When something looks off, verify:

* ✅ Does the **folder and file** both contain `{ASIN...}`?
* ✅ Do both start with **`title - vol_XX`** and use `" - "` hyphens?
* ✅ Is the **torrent path length** (folder + "/" + file) ≤ **180**?
* ✅ Were tokens dropped **in order** (year → author → tag → subtitle for file; year → author → subtitle for folder)?
* ✅ Did the extension resolve deterministically (.m4b preferred)?
* ✅ Did we avoid partial truncation (whole tokens only)?
* ✅ Are we measuring torrent path, not OS path?
* ✅ Did trailing parentheses extract correctly (year/author only)?

### Debug Commands

```python
# Test parsing
from hardbound.red_paths import parse_tokens
tokens = parse_tokens("Your Book Name Here {ASIN.B0TEST}", ".m4b")
print(f"Parsed: {tokens}")

# Test length calculation
from hardbound.red_paths import _torrent_path_length, _fits_red_cap
length = _torrent_path_length("folder", "file.m4b")
fits = _fits_red_cap("folder", "file.m4b")
print(f"Length: {length}, Fits: {fits}")

# Full path generation
from hardbound.red_paths import build_dst_paths
dst_dir, dst_file = build_dst_paths(Path("/src/Book {ASIN.B0TEST}"), Path("/dst"))
print(f"Generated: {dst_dir.name}/{dst_file.name}")
```

---

## Performance Notes

* **Parsing complexity**: O(1) regex operations, very fast.
* **Path generation**: O(1) string operations with small constant factors.
* **File system operations**: Extension detection requires directory listing (O(n) where n = files in directory).
* **Memory usage**: Minimal - works with string operations, no large data structures.

The system is designed to handle thousands of audiobooks efficiently without performance concerns.

---

## Version Compatibility

This specification assumes:

* Python 3.8+ (for `pathlib` and type hints)
* No external dependencies beyond Python standard library
* Cross-platform compatibility (Windows, Linux, macOS)
* Forward compatibility with future RED policy changes via configurable limits

---

*This specification serves as the definitive reference for the RED path shortening system. Keep it updated as the system evolves.*
