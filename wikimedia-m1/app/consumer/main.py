import json
import logging
import time
from datetime import datetime
from typing import Any

import psycopg
from confluent_kafka import Consumer, KafkaException, Message
from psycopg.types.json import Json

from app.common.config import load_settings
from app.common.db import db_connection
from app.common.logging_utils import configure_logging

logger = logging.getLogger("consumer")



def make_consumer(bootstrap_servers: str, group_id: str) -> Consumer:
    return Consumer(
        {
            "bootstrap.servers": bootstrap_servers,
            "group.id": group_id,
            "enable.auto.commit": False,
            "auto.offset.reset": "latest",
            "client.id": "wikimedia-counter-consumer",
        }
    )



def persist_event(conn: psycopg.Connection, event: dict[str, Any]) -> bool:
    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO pages (title, canonical_title, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (title)
                DO UPDATE SET
                    canonical_title = EXCLUDED.canonical_title,
                    updated_at = NOW()
                RETURNING id
                """,
                (event["title"], event["canonical_title"]),
            )
            page_id = cur.fetchone()[0]

            cur.execute(
                """
                INSERT INTO edit_events (event_id, page_id, event_time, user_name, comment, raw_payload)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING id
                """,
                (
                    event["event_id"],
                    page_id,
                    event["event_time"],
                    event.get("user_name"),
                    event.get("comment"),
                    Json(event["raw_payload"]),
                ),
            )

            inserted = cur.fetchone()
            if not inserted:
                return False

            cur.execute(
                """
                INSERT INTO page_stats (page_id, total_edits, last_edit_time, updated_at)
                VALUES (%s, 1, %s, NOW())
                ON CONFLICT (page_id)
                DO UPDATE SET
                    total_edits = page_stats.total_edits + 1,
                    last_edit_time = GREATEST(page_stats.last_edit_time, EXCLUDED.last_edit_time),
                    updated_at = NOW()
                """,
                (page_id, event["event_time"]),
            )

    return True



def process_message(conn: psycopg.Connection, message: Message) -> tuple[bool, str]:
    try:
        payload = json.loads(message.value().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        return False, f"Invalid JSON payload: {exc}"

    required = ["event_id", "title", "canonical_title", "event_time", "raw_payload"]
    missing = [k for k in required if k not in payload]
    if missing:
        return False, f"Missing required fields: {','.join(missing)}"

    if isinstance(payload["event_time"], str):
        payload["event_time"] = datetime.fromisoformat(payload["event_time"].replace("Z", "+00:00"))

    was_inserted = persist_event(conn, payload)
    if was_inserted:
        return True, "applied"
    return True, "duplicate"



def consume_forever() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)

    consumer = make_consumer(settings.kafka_bootstrap_servers, settings.kafka_group_id)
    consumer.subscribe([settings.kafka_topic])

    logger.info("Consumer started for topic=%s group=%s", settings.kafka_topic, settings.kafka_group_id)

    with db_connection(settings.database_url) as conn:
        while True:
            try:
                msg = consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    raise KafkaException(msg.error())

                ok, reason = process_message(conn, msg)
                if ok:
                    consumer.commit(message=msg, asynchronous=False)
                    if reason == "duplicate":
                        logger.debug("Duplicate event ignored")
                else:
                    logger.warning("Skipping message: %s", reason)
                    consumer.commit(message=msg, asynchronous=False)

            except KeyboardInterrupt:
                logger.info("Consumer interrupted")
                break
            except (psycopg.Error, KafkaException) as exc:
                logger.error("Retryable runtime error: %s", exc)
                time.sleep(2)
            except Exception as exc:  # noqa: BLE001
                logger.exception("Unexpected consumer error: %s", exc)
                time.sleep(2)

    consumer.close()


if __name__ == "__main__":
    consume_forever()
