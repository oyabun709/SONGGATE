"""
Vercel entry point for the Songgate FastAPI application.

Vercel's Python runtime looks for an `app` (ASGI) or `handler` (WSGI) export.
The project root is apps/api/ so relative imports work as expected.
"""
import sys
import os

# Ensure the api root is on sys.path (Vercel may invoke from a different cwd)
_api_root = os.path.dirname(os.path.dirname(__file__))
if _api_root not in sys.path:
    sys.path.insert(0, _api_root)

from main import app  # noqa: F401, E402 — re-export for Vercel
