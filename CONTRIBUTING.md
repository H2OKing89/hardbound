# Contributing to hardbound

3. **Make your changes** with tests
4. **Test locally**: `pytest` or `pytest -q -m "not slow"`
5. **Lint and format**: `ruff check --fix . && ruff format .` (or just commit - pre-commit hooks will handle it)Quick start (Python 3.13+)

1. Install Python 3.13.
2. Clone the repo and open a terminal in the project root.
3. Run the bootstrap:
   - Linux/macOS: `./scripts/bootstrap.sh`
   - Windows (PowerShell): `./scripts/bootstrap.ps1`
4. Activate the venv:
   - Linux/macOS: `source .venv/bin/activate`
   - Windows: `.venv\Scripts\Activate.ps1`
5. Check it works: `pytest -q` (or `python -m pytest`)

## Common commands

- `ruff check --fix . && ruff format .` — auto-format + lint fixes
- `pytest` — run the full tests
- `pytest -q -m "not slow"` — skip slow tests
- `cz commit` — guided Conventional Commit message
- `cz bump --changelog` — version + changelog

PRs must pass pre-commit hooks (installed during bootstrap) and CI.

## Development workflow

1. **Fork and clone** the repository
2. **Create a feature branch**: `git checkout -b my-feature`
3. **Run the bootstrap** to set up your environment
4. **Make your changes** with tests
5. **Test locally**: `just test` or `just test-quick`
6. **Lint and format**: `just fix` (or just commit - pre-commit hooks will handle it)
7. **Commit with conventional commits**: `cz commit` or use the format:
   - `feat: add new feature`
   - `fix: resolve bug`
   - `docs: update documentation`
   - `style: format code`
   - `refactor: restructure code`
   - `test: add tests`
   - `chore: update dependencies`
8. **Push and create a PR**

## Project structure

```
hardbound/
├── hardbound/           # Main package
│   ├── __init__.py
│   ├── commands.py      # CLI commands
│   ├── config.py        # Configuration management
│   ├── interactive.py   # Interactive mode
│   ├── linker.py        # File linking logic
│   ├── red_paths.py     # RED-compliant path handling
│   ├── catalog.py       # Audiobook catalog
│   ├── display.py       # Display utilities
│   └── utils/           # Utility modules
├── tests/               # Test suite
├── scripts/             # Development scripts
├── .github/workflows/   # CI/CD
└── docs/                # Documentation
```

## Testing

We use pytest with several test categories:

- **Quick tests**: `pytest -q -m "not slow"` - fast unit tests
- **All tests**: `pytest` - includes integration tests
- **With coverage**: `pytest --cov=hardbound --cov-report=term-missing`

Mark slow tests with `@pytest.mark.slow` decorator.

## Code style

We use several tools to maintain consistent code quality:

- **Ruff** - Fast Python linter and formatter (replaces flake8, black, isort)
- **MyPy** - Static type checking
- **Pre-commit hooks** - Automatic formatting and checks
- **Conventional commits** - Structured commit messages

The pre-commit hooks will automatically format your code, but you can run `just fix` manually.

## Adding dependencies

- **Runtime dependencies**: Add to `pyproject.toml` under `dependencies`
- **Development dependencies**: Add to `pyproject.toml` under `optional-dependencies.all`
- **Type stubs**: Add to mypy's `additional_dependencies` in `.pre-commit-config.yaml`

## Release process

We use [Commitizen](https://commitizen-tools.github.io/commitizen/) for automated versioning:

1. Make sure all changes are committed with conventional commit messages
2. Run `cz bump --changelog` to:
   - Bump the version based on commit types
   - Generate/update CHANGELOG.md
   - Create a git tag
3. Push with tags: `git push --follow-tags`
4. GitHub Actions will handle the rest

## Getting help

- **Issues**: Check existing issues or create a new one
- **Discussions**: Use GitHub Discussions for questions
- **Documentation**: See README.md and inline docstrings
- **Code examples**: Check the `examples/` directory

## Code of conduct

Be respectful, inclusive, and constructive. We want this to be a welcoming community for all contributors.
