# Makefile - Development tasks for hardbound
# Use 'make <target>' or 'make' for the default target

.PHONY: help bootstrap activate lint fix test test-quick coverage release

# Default target
test: 
	pytest -q

help:
	@echo "Available commands:"
	@echo "  bootstrap   - Run the bootstrap script"
	@echo "  activate    - Show activation command"
	@echo "  lint        - Run linting checks"
	@echo "  fix         - Auto-fix linting and formatting issues"
	@echo "  test        - Run all tests"
	@echo "  test-quick  - Run quick tests (skip slow ones)"
	@echo "  coverage    - Run tests with coverage report"
	@echo "  release     - Create a new release"

bootstrap:
	./scripts/bootstrap.sh

activate:
	@echo 'source .venv/bin/activate'

lint:
	ruff check .
	mypy .

fix:
	ruff check --fix .
	ruff format .

test-quick:
	pytest -q -m "not slow"

coverage:
	pytest --cov=hardbound --cov-report=term-missing

release:
	cz bump --changelog