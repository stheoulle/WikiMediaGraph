import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    database_url: str
    kafka_bootstrap_servers: str
    kafka_topic: str
    kafka_group_id: str
    sse_url: str
    sse_user_agent: str
    log_level: str



def load_settings() -> Settings:
    return Settings(
        database_url=os.getenv("DATABASE_URL", "postgresql://wikimedia:wikimedia@postgres:5432/wikimedia"),
        kafka_bootstrap_servers=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "redpanda:9092"),
        kafka_topic=os.getenv("KAFKA_TOPIC", "edits.raw"),
        kafka_group_id=os.getenv("KAFKA_GROUP_ID", "wikimedia-consumer-v1"),
        sse_url=os.getenv("SSE_URL", "https://stream.wikimedia.org/v2/stream/recentchange"),
        sse_user_agent=os.getenv(
            "SSE_USER_AGENT",
            "WikiMediaMilestone1/0.1 (course project) requests",
        ),
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
