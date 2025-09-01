#!/usr/bin/env python3
"""
Test runner script for Hardbound
"""
import subprocess
import sys
from pathlib import Path

def run_tests(args=None):
    """Run pytest with given arguments"""
    if args is None:
        args = []

    cmd = [sys.executable, "-m", "pytest"] + args
    print(f"Running: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=Path(__file__).parent)

def main():
    """Main test runner"""
    import argparse

    parser = argparse.ArgumentParser(description="Run Hardbound tests")
    parser.add_argument("--coverage", action="store_true", help="Run with coverage")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")
    parser.add_argument("--quick", action="store_true", help="Run only fast tests")
    parser.add_argument("pytest_args", nargs="*", help="Additional pytest arguments")

    args = parser.parse_args()

    test_args = []

    if args.coverage:
        test_args.extend(["--cov=hardbound", "--cov-report=term-missing"])

    if args.verbose:
        test_args.append("-v")

    if args.quick:
        test_args.extend(["-m", "not slow"])

    test_args.extend(args.pytest_args)

    result = run_tests(test_args)
    sys.exit(result.returncode)

if __name__ == "__main__":
    main()
