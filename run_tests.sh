#!/usr/bin/env bash
# Test runner script for Hardbound

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if we're in the right directory
if [ ! -f "pyproject.toml" ]; then
    print_error "pyproject.toml not found. Please run from the project root."
    exit 1
fi

# Check if virtual environment exists
if [ ! -d ".venv" ]; then
    print_warning "Virtual environment not found. Creating one..."
    python -m venv .venv
    source .venv/bin/activate
    pip install -e ".[testing]"
else
    source .venv/bin/activate
fi

# Parse command line arguments
COVERAGE=false
VERBOSE=false
QUICK=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --coverage|-c)
            COVERAGE=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --quick|-q)
            QUICK=true
            shift
            ;;
        --help|-h)
            echo "Usage: $0 [OPTIONS]"
            echo ""
            echo "Options:"
            echo "  -c, --coverage    Run with coverage report"
            echo "  -v, --verbose     Verbose output"
            echo "  -q, --quick       Run only fast tests (skip slow tests)"
            echo "  -h, --help        Show this help message"
            exit 0
            ;;
        *)
            print_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Build pytest command
PYTEST_CMD=("python" "-m" "pytest" "tests/")

if [ "$COVERAGE" = true ]; then
    PYTEST_CMD+=("--cov=hardbound" "--cov-report=term-missing" "--cov-report=html:htmlcov")
fi

if [ "$VERBOSE" = true ]; then
    PYTEST_CMD+=("-v")
fi

if [ "$QUICK" = true ]; then
    PYTEST_CMD+=("-m" "not slow")
fi

# Run tests
print_status "Running tests..."
print_status "Command: ${PYTEST_CMD[*]}"

if "${PYTEST_CMD[@]}"; then
    print_status "All tests passed! ✅"
    if [ "$COVERAGE" = true ]; then
        print_status "Coverage report generated in htmlcov/"
    fi
else
    print_error "Some tests failed! ❌"
    exit 1
fi
