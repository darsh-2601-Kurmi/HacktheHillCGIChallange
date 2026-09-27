"""Vercel entry point: the whole OneCase app (API + pages) as one Python function. See vercel.json."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api import app  # noqa: E402,F401  (Vercel serves this ASGI app)
