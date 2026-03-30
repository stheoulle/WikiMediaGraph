import logging
import time

import psycopg

from app.common.config import load_settings
from app.common.db import db_connection
from app.common.logging_utils import configure_logging
from app.common.recent_activity import recompute_recent_activity

logger = logging.getLogger("recent-activity")



def run_forever(interval_seconds: int = 60) -> None:
    settings = load_settings()
    configure_logging(settings.log_level)

    logger.info("Recent activity worker started (interval=%ss)", interval_seconds)

    while True:
        try:
            with db_connection(settings.database_url) as conn:
                updated = recompute_recent_activity(conn)
                logger.info("Recent activity recomputed: rows updated=%s", updated)
            time.sleep(interval_seconds)
        except KeyboardInterrupt:
            logger.info("Recent activity worker interrupted")
            break
        except psycopg.Error as exc:
            logger.error("Database error in recent activity worker: %s", exc)
            time.sleep(3)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected recent activity error: %s", exc)
            time.sleep(3)


if __name__ == "__main__":
    run_forever()
