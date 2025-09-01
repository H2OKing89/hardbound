#!/usr/bin/env python3
"""
DEPRECATED shim: all features have been merged into hardbound.py.
This lightweight wrapper exists to preserve legacy entrypoints and will
delegate execution to hardbound.main().
"""
import sys

try:
    import hardbound
except Exception as e:
    print("ERROR: failed to import hardbound.py. Please run hardbound.py directly.", file=sys.stderr)
    raise

if __name__ == "__main__":
    # Delegate to the canonical script
    hardbound.main()
