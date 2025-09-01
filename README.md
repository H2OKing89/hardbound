# Hardbound - Scalable Audiobook Hardlink Manager

Hardbound is a powerful command-line tool for managing large audiobook libraries. It creates hardlinks from your organized library to torrent directories, saving disk space while allowing you to seed without duplicating files.

## Features

- **Search-First Workflow**: Build a searchable catalog of 1000+ audiobooks for instant fuzzy search
- **Interactive Selection**: Use fzf for fuzzy finding and multi-selection, or fallback to hierarchical browser
- **Batch Operations**: Link entire authors, series, or custom filters at once
- **Watch Folders**: Automatically link new audiobooks as they appear
- **Duplicate Detection**: Find and manage duplicate audiobooks
- **Favorites System**: Bookmark frequently accessed audiobooks
- **Dashboard**: Overview of library statistics and recent activity
- **Undo Functionality**: Rollback recent operations with history tracking
- **Progress Indicators**: Visual feedback for long operations
- **Cross-Platform**: Works on Linux, macOS, and Windows

## Quick Start

### Installation

1. Clone or download the script:
   ```bash
   git clone https://github.com/yourusername/hardbound.git
   cd hardbound
   ```

2. Make executable:
   ```bash
   chmod +x hardbound.py
   ```

3. Optional: Install fzf for enhanced fuzzy search:
   ```bash
   # Ubuntu/Debian
   sudo apt install fzf

   # macOS
   brew install fzf

   # Or download from https://github.com/junegunn/fzf
   ```

### Basic Usage

1. **Build Search Catalog** (recommended for large libraries):
   ```bash
   ./hardbound.py index /path/to/audiobooks
   ```

2. **Interactive Search and Link**:
   ```bash
   ./hardbound.py select -m --link --dst-root /path/to/torrents
   ```

3. **Classic Single Link**:
   ```bash
   ./hardbound.py --src /path/to/book --dst-root /path/to/torrents --commit
   ```

## Commands

### Catalog Management
- `index [paths...]`: Build/update searchable catalog
- `search [terms]`: Search catalog with filters
- `select [terms]`: Interactive selection with fzf
- `manage <command>`: Database maintenance and index management

### Index Management Commands
- `manage rebuild`: Rebuild database indexes for optimal performance
- `manage clean`: Remove orphaned entries and clean up database
- `manage optimize`: Optimize database structure and indexes
- `manage stats`: Display database statistics and index information
- `manage vacuum`: Reclaim disk space and defragment database
- `manage verify`: Verify database integrity and consistency

## Index Management

Hardbound includes comprehensive database maintenance tools to keep your audiobook catalog running smoothly:

### Database Maintenance
```bash
# Rebuild indexes for optimal search performance
./hardbound.py manage rebuild

# Clean up orphaned entries and remove invalid paths
./hardbound.py manage clean

# Optimize database structure and indexes
./hardbound.py manage optimize

# View database statistics and index information
./hardbound.py manage stats

# Reclaim disk space and defragment database
./hardbound.py manage vacuum

# Verify database integrity
./hardbound.py manage verify
```

### Automatic Maintenance
The system automatically handles:
- **Path parsing**: Correctly identifies author/series/book structure
- **ASIN extraction**: Supports multiple ASIN formats ({ASIN.B0C34GQRYZ}, [ASIN.B0CN7M36GD])
- **Duplicate detection**: Prevents duplicate catalog entries
- **Orphaned cleanup**: Removes entries for deleted audiobooks
- **Index optimization**: Maintains search performance for large libraries

### Directory Structure Support
Hardbound intelligently parses audiobook directory structures:
- `Author/Series/Book/` - Full hierarchical organization
- `Author/Book/` - Direct author-to-book mapping
- Automatic exclusion of torrent destination folders
- Pattern-based author and series detection

### Interactive Mode
Run without arguments for full interactive menu:
```bash
./hardbound.py
```

Features include:
- Dashboard with library statistics
- Advanced search with filters and sorting
- Batch operations wizard
- Favorites management
- Watch folder configuration
- Duplicate finder
- Undo operations
- Settings management

### Classic CLI Mode
```bash
./hardbound.py --src /source/dir --dst-root /dest/root --commit
```

Options:
- `--dry-run`: Preview changes (default)
- `--commit`: Actually create links
- `--force`: Overwrite existing files
- `--zero-pad-vol`: Normalize vol_4 → vol_04
- `--also-cover`: Create additional cover.jpg
- `--batch-file`: Process multiple links from file

## Configuration

Configuration is stored in `~/.config/hardbound/config.json`:

```json
{
  "library_path": "/mnt/user/data/audio/audiobooks",
  "torrent_path": "/mnt/user/data/downloads",
  "zero_pad": true,
  "also_cover": false,
  "force": false,
  "auto_index": true,
  "show_progress": true
}
```

## Requirements

- Python 3.8+
- SQLite3 (usually included with Python)
- Optional: fzf for enhanced fuzzy search
- Optional: tqdm for progress bars

## Safety Features

- **Dry-run by default**: Preview all changes before committing
- **Filesystem checks**: Ensures source and destination are on same filesystem
- **Unraid compatibility**: Handles user/disk path mixing detection
- **History tracking**: Log all operations for undo functionality
- **Duplicate detection**: Identify and manage duplicate audiobooks

## File Structure

```
hardbound/
├── hardbound.py          # Main script
├── README.md            # This file
├── LICENSE              # MIT License
├── .gitignore          # Git ignore rules
├── requirements.txt    # Python dependencies
└── example_batch.txt   # Batch file example
```

## Examples

### Link all books by an author:
```bash
./hardbound.py select --author "Neil Gaiman" -m --link --dst-root /torrents
```

### Link a complete series:
```bash
./hardbound.py select --series "The Wheel of Time" -m --link --dst-root /torrents
```

### Batch file format:
```
# Batch file: one link per line
# Format: source_path|destination_path
/mnt/library/Author/Book1|/mnt/torrents/Book1
/mnt/library/Author/Book2|/mnt/torrents/Book2
```

### Watch folder setup:
Configure automatic linking of new downloads:
```bash
./hardbound.py  # Then select option 6 for watch folders
```

## Troubleshooting

### Common Issues

1. **"Cross-device link error"**
   - Source and destination must be on same filesystem
   - For Unraid: Use /mnt/user paths consistently

2. **Permission denied**
   - Ensure read access to source directories
   - Ensure write access to destination directories

3. **No fzf found**
   - Install fzf or use hierarchical browser fallback
   - The script will automatically detect and adapt

4. **Database locked**
   - Close other instances of hardbound
   - The catalog uses SQLite with proper locking

### Performance Tips

- **Large libraries**: Use `index` command to build catalog first
- **Slow searches**: Rebuild catalog with `index --force`
- **Memory usage**: SQLite handles large catalogs efficiently
- **Network drives**: Ensure proper filesystem support for hardlinks

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test thoroughly
5. Submit a pull request

## Development

### Testing

Hardbound includes a comprehensive test suite to ensure reliability and catch regressions.

#### Running Tests

```bash
# Run all tests
./run_tests.sh

# Run with coverage report
./run_tests.sh --coverage

# Run specific test file
python -m pytest tests/test_config.py -v

# Run tests in parallel (requires pytest-xdist)
python -m pytest tests/ -n auto

# Run with coverage and HTML report
pytest --cov=hardbound --cov-report=html
```

#### Test Structure

- `tests/test_config.py`: Configuration management tests
- `tests/test_display.py`: Display and formatting utilities tests
- `tests/test_linker.py`: Core hardlinking functionality tests
- `tests/test_main.py`: Main application and CLI tests

#### Writing Tests

Tests use pytest with the following conventions:
- Test files: `test_*.py` or `*_test.py`
- Test classes: `Test*`
- Test functions: `test_*`
- Fixtures and mocks for dependency isolation

#### Coverage

The test suite aims for high code coverage. Current coverage report:
- Core utilities: ~90% coverage
- Main business logic: ~10-20% coverage (room for improvement)

### Code Quality

Hardbound maintains high code quality standards:

- **Static Analysis**: Uses Pylance for comprehensive type checking
- **Linting**: Automated code quality checks in CI/CD pipeline
- **Type Safety**: Full type annotations throughout the codebase
- **Documentation**: Inline documentation and comprehensive README

### CI/CD Pipeline

Automated testing and quality checks via GitHub Actions:
- **Multi-Python Support**: Tests on Python 3.8 through 3.13
- **Coverage Reporting**: Automated coverage analysis with Codecov
- **Quality Gates**: Static analysis and linting checks
- **Automated Releases**: Streamlined deployment process

### Contributing

1. Fork the repository
2. Create a feature branch
3. Write tests for new functionality
4. Ensure all tests pass
5. Run static analysis: `python -m mypy hardbound/` (if mypy configured)
6. Submit a pull request

## License

MIT License - see LICENSE file for details

## Support

- GitHub Issues: Report bugs and request features
- Documentation: This README and inline help (`./hardbound.py --help`)
- Community: Check GitHub discussions for tips and tricks

---

**Happy listening! 🎧**
