"""
pytest configuration for apps/api tests.

Adds the api root to sys.path so that `from services.ddex.validator import ...`
resolves correctly when running pytest from the repo root or from apps/api.
"""

import sys
from pathlib import Path

# Insert apps/api at the front of sys.path
API_ROOT = Path(__file__).parent.parent
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))
