import json
import logging
import time
from typing import Any

import requests
from confluent_kafka import Producer
from confluent_kafka.admin import AdminClient, NewTopic

from app.common.config import load_settings
from app.common.logging_utils import configure_logging
from app.common.normalize import normalize_wikimedia_event

logger = logging.getLogger("producer")



def ensure_topic(bootstrap_servers: str, topic: str) -> None:
    admin = AdminClient({"bootstrap.servers": bootstrap_servers})
    metadata = admin.list_topics(timeout=10)
    if topic in metadata.topics:
        logger.info("Kafka topic already exists: %s", topic)
        return

    fs = admin.create_topics([NewTopic(topic, num_partitions=3, replication_factor=1)])
    for _, future in fs.items():
        future.result(timeout=10)
    logger.info("Kafka topic created: %s", topic)



def make_producer(bootstrap_servers: str) -> Producer:
    return Producer(
        {
            "bootstrap.servers": bootstrap_servers,
            "client.id": "wikimedia-sse-producer",
            "acks": "all",
            "linger.ms": 50,
            "compression.type": "lz4",
        }
    )



def delivery_report(err: Exception | None, msg: Any) -> None:
    if err is not None:
        logger.error("Delivery failed: %s", err)



def stream_sse(producer: Producer, sse_url: str, topic: str, sse_user_agent: str) -> None:
    reconnect_delay = 2

    while True:
        try:
            logger.info("Connecting to SSE: %s", sse_url)
            with requests.get(
                sse_url,
                headers={
                    "Accept": "text/event-stream",
                    "User-Agent": sse_user_agent,
                    "Cache-Control": "no-cache",
                },
                stream=True,
                timeout=60,
            ) as response:
                response.raise_for_status()
                logger.info("SSE connected")

                for line in response.iter_lines(decode_unicode=True):
                    if line is None:
                        continue
                    line = line.strip()
                    if not line or line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue

                    payload_raw = line[len("data:") :].strip()
                    if not payload_raw:
                        continue

                    try:
                        payload = json.loads(payload_raw)
                    except json.JSONDecodeError:
                        logger.debug("Skipping non-JSON SSE data")
                        continue

                    normalized = normalize_wikimedia_event(payload)
                    if normalized is None:
                        continue

                    producer.produce(
                        topic=topic,
                        key=normalized["canonical_title"],
                        value=json.dumps(normalized, default=str),
                        callback=delivery_report,
                    )
                    producer.poll(0)

        except requests.RequestException as exc:
            logger.warning("SSE connection failed: %s", exc)
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)
            continue
        except KeyboardInterrupt:
            logger.info("Producer interrupted")
            break
        except Exception as exc:  # noqa: BLE001
            logger.exception("Unexpected producer error: %s", exc)
            time.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)
            continue



def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)

    ensure_topic(settings.kafka_bootstrap_servers, settings.kafka_topic)
    producer = make_producer(settings.kafka_bootstrap_servers)

    try:
        stream_sse(
            producer,
            settings.sse_url,
            settings.kafka_topic,
            settings.sse_user_agent,
        )
    finally:
        producer.flush(10)


if __name__ == "__main__":
    main()
