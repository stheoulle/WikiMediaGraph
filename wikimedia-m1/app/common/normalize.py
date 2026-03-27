import hashlib
from datetime import datetime, timezone
from typing import Any

from dateutil import parser as dt_parser



def canonical_title(title: str) -> str:
    return title.strip().replace(" ", "_")



def parse_event_time(payload: dict[str, Any]) -> datetime:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
    dt_raw = meta.get("dt") or payload.get("timestamp")

    if isinstance(dt_raw, (int, float)):
        return datetime.fromtimestamp(float(dt_raw), tz=timezone.utc)

    if isinstance(dt_raw, str) and dt_raw:
        return dt_parser.isoparse(dt_raw)

    return datetime.now(tz=timezone.utc)



def stable_event_id(payload: dict[str, Any]) -> str:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}

    candidate_ids = [
        meta.get("id"),
        payload.get("id"),
        payload.get("revision"),
        payload.get("rev_id"),
    ]
    for value in candidate_ids:
        if value is not None and str(value).strip():
            return str(value)

    title = str(payload.get("title", ""))
    ts = str(meta.get("dt", payload.get("timestamp", "")))
    user = str(payload.get("user", ""))
    signature = f"{title}|{ts}|{user}".encode("utf-8")
    return hashlib.sha256(signature).hexdigest()



def normalize_wikimedia_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        return None

    normalized = {
        "event_id": stable_event_id(payload),
        "title": title.strip(),
        "canonical_title": canonical_title(title),
        "event_time": parse_event_time(payload),
        "user_name": str(payload.get("user", "")) if payload.get("user") is not None else None,
        "comment": str(payload.get("comment", "")) if payload.get("comment") is not None else None,
        "raw_payload": payload,
    }

    return normalized
