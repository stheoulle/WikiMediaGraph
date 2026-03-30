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


def _is_wikipedia_event(payload: dict[str, Any]) -> bool:
    meta = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}

    domain = meta.get("domain") or payload.get("server_name")
    if isinstance(domain, str) and domain.strip():
        return domain.strip().lower().endswith(".wikipedia.org")

    wiki = payload.get("wiki")
    if isinstance(wiki, str) and wiki.strip():
        wiki_project = wiki.strip().lower()
        excluded_projects = (
            "commons",
            "wikidata",
            "wiktionary",
            "wikibooks",
            "wikinews",
            "wikiquote",
            "wikisource",
            "wikiversity",
            "wikivoyage",
            "species",
            "mediawiki",
            "meta",
        )
        if not wiki_project.endswith("wiki"):
            return False
        return not any(project in wiki_project for project in excluded_projects)

    return False


def _is_media_file_event(payload: dict[str, Any], title: str) -> bool:
    namespace = payload.get("namespace")
    if namespace == 6 or namespace == "6":
        return True

    lowered_title = title.strip().lower()
    return lowered_title.startswith("file:") or lowered_title.startswith("image:")



def normalize_wikimedia_event(payload: dict[str, Any]) -> dict[str, Any] | None:
    title = payload.get("title")
    if not isinstance(title, str) or not title.strip():
        return None

    if not _is_wikipedia_event(payload):
        return None

    if _is_media_file_event(payload, title):
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
