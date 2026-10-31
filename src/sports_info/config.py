"""Settings loaded from the environment (and a .env file at the project root).

On Streamlit Cloud, root-level entries in the app's Secrets are exported as environment
variables before the app starts, so they are read here the same way.
"""

import os
from datetime import timedelta
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(PROJECT_ROOT / ".env")

DATA_DIR = Path(os.getenv("SPORTS_INFO_DATA_DIR") or PROJECT_ROOT / "data")
DB_PATH = DATA_DIR / "sports_info.db"
# Hosted Postgres (e.g. a Neon connection string). Unset: the SQLite file at DB_PATH.
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
# Any long random string; users' own API keys are encrypted with it before they're stored.
KEYS_ENCRYPTION_KEY = os.getenv("KEYS_ENCRYPTION_KEY", "").strip()

MODELS_DIR = DATA_DIR / "models"

FOOTBALL_DATA_API_KEY = os.getenv("FOOTBALL_DATA_API_KEY", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
# The "latest" alias follows Google's newest Flash release; set e.g. gemini-flash-lite-latest
# for higher free-tier limits.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "").strip() or "gemini-flash-latest"

# Local embedding model (runs on CPU via ONNX, ~70 MB download on first use).
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

# How long cached API data is considered fresh before we fetch again.
CATALOG_TTL = timedelta(days=7)
EVENTS_TTL = timedelta(hours=6)

NEWS_TTL = timedelta(hours=1)

# How far back the "recent results" sections look.
RESULTS_LOOKBACK = timedelta(days=21)

# Articles older than this are deleted; questions search the most recent NEWS_SEARCH_WINDOW.
NEWS_RETENTION = timedelta(days=30)
NEWS_SEARCH_WINDOW = timedelta(days=14)
