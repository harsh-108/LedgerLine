"""Single source of truth for filesystem locations.

Every path in the app derives from these anchors, so the server can be
started from ANY working directory without creating stray databases or
missing the .env file.
"""
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[2]      # .../backend
ROOT_DIR = BACKEND_DIR.parent                          # project root
FRONTEND_DIR = ROOT_DIR / "frontend"
REACT_DIST = ROOT_DIR / "frontend-react" / "dist"   # built by `npm run build`
DATA_DIR = ROOT_DIR / "data"
ENV_FILE = ROOT_DIR / ".env"

DATA_DIR.mkdir(exist_ok=True)
