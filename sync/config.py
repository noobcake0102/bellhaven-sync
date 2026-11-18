"""Settings. Everything environment-specific lives here (or in .env)."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Tiny .env loader so there is no extra dependency. Real env vars win.
_env = ROOT / ".env"
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SITE_BASE = os.environ.get("SITE_BASE", "https://analyst-assessment-production.up.railway.app")
API_BASE = os.environ.get("API_BASE", SITE_BASE + "/api/v1")
CRM_TOKEN = os.environ.get("CRM_TOKEN", "")
DB_PATH = Path(os.environ.get("DB_PATH", ROOT / "state" / "sync.db"))
REVIEWER = os.environ.get("REVIEWER", "reviewer")

# The operator we are syncing. The parent account is found by name at run time,
# so nothing here is tied to one sandbox's ids.
OPERATOR_NAME = "Bellhaven Senior Living"

# Website wording -> CRM vocabulary for care_type.
CARE_MAP = {
    "Assisted Living": "Assisted Living",
    "Memory Support": "Memory Care",
    "Short-Term Rehabilitation & Nursing": "Skilled Nursing",
    "Independent Living": "Independent Living",
}

# Safety valve: if the scrape returns fewer than this share of the previous
# run's locations, assume the site (or our parser) broke and stop before
# proposing that half the portfolio was sold.
MIN_SCRAPE_RATIO = 0.7
