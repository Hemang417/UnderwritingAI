"""Run this once before the first live MAHARERA lookup, or whenever the
session token expires (~100 minutes).

Opens a visible Chrome window. YOU must solve the CAPTCHA within 90
seconds -- this script never attempts it. Once solved, the resulting
session token is saved to config/maharera_token.json; the live adapter
reads it fresh on every request, so no restart or .env edit is needed
afterward.

Usage:
    python scripts/setup_maharera_session.py
"""

import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.adapters.maha_rera_session import SessionSetupError, setup_session  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def main() -> None:
    logger.info("Starting MAHARERA session setup...")
    logger.info("A Chrome window will open. Solve the CAPTCHA yourself, then press Submit.")
    try:
        token = setup_session()
    except SessionSetupError as exc:
        logger.error("Session setup failed: %s", exc)
        sys.exit(1)

    logger.info("Session setup complete -- token saved.")
    logger.info("Token preview: %s...", token[:40])
    logger.info("Live MAHARERA search is ready to use now -- no restart needed.")


if __name__ == "__main__":
    main()
