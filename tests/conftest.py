"""
Pytest configuration and fixtures
"""
import sys
from pathlib import Path

# Add the project root to Python path for testing
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))
