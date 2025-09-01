"""
Pytest configuration and fixtures
"""

import sys
import pytest
from pathlib import Path

# Add the project root to Python path for testing
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


# Register custom markers
def pytest_configure(config):
    """Register custom pytest markers"""
    config.addinivalue_line("markers", "slow: marks tests as slow (deselect with '-m \"not slow\"')")
    config.addinivalue_line("markers", "integration: marks tests as integration tests")
    config.addinivalue_line("markers", "unit: marks tests as unit tests")
