from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import psycopg
import requests


@dataclass(frozen=True)
class LinkResolverConfig:
    wiki_api_url: str
    link_ttl_minutes: int
    request_timeout_seconds: int



def _canonical_title(title: str) -> str:
    return title.strip().replace(" ", "_")



def _upsert_page(cur: psycopg.Cursor, title: str) -> int:
    canonical = _canonical_title(title)
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
        (title, canonical),
    )
    return cur.fetchone()[0]



def _fetch_links_from_wikipedia(
    title: str,
    config: LinkResolverConfig,
) -> list[tuple[str, str]]:
    # Returns list of (target_title, relation_type) with relation_type in {link, redirect}.
    session = requests.Session()
    headers = {
        "User-Agent": "WikiMediaMilestone1/0.1 (course project)",
    }
    results: dict[str, str] = {}

    params: dict[str, Any] = {
        "action": "query",
        "titles": title,
        "prop": "links|redirects",
        "pllimit": "max",
        "rdlimit": "max",
        "format": "json",
        "formatversion": "2",
    }

    while True:
        resp = session.get(
            config.wiki_api_url,
            params=params,
            headers=headers,
            timeout=config.request_timeout_seconds,
        )
        resp.raise_for_status()
        payload = resp.json()

        pages = payload.get("query", {}).get("pages", [])
        for page in pages:
            for link in page.get("links", []) or []:
                target = link.get("title")
                if target:
                    results.setdefault(target, "link")

            for redir in page.get("redirects", []) or []:
                target = redir.get("title")
                if target:
                    # Redirect wins if a target appears in both categories.
                    results[target] = "redirect"

        cont = payload.get("continue")
        if not cont:
            break

        for key, value in cont.items():
            if key == "continue":
                continue
            params[key] = value

    return sorted(results.items(), key=lambda x: x[0].lower())



def links_are_fresh(conn: psycopg.Connection, source_page_id: int) -> bool:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT 1
            FROM page_links
            WHERE source_page_id = %s
              AND freshness_expires_at > NOW()
            LIMIT 1
            """,
            (source_page_id,),
        )
        return cur.fetchone() is not None



def refresh_links_for_page(
    conn: psycopg.Connection,
    page_title: str,
    config: LinkResolverConfig,
) -> dict[str, int]:
    link_rows = _fetch_links_from_wikipedia(page_title, config)
    now_utc = datetime.now(timezone.utc)
    expiry = now_utc + timedelta(minutes=config.link_ttl_minutes)

    with conn.transaction():
        with conn.cursor() as cur:
            source_page_id = _upsert_page(cur, page_title)

            cur.execute("DELETE FROM page_links WHERE source_page_id = %s", (source_page_id,))

            inserted = 0
            for target_title, relation_type in link_rows:
                target_page_id = _upsert_page(cur, target_title)

                if source_page_id == target_page_id:
                    continue

                cur.execute(
                    """
                    INSERT INTO page_links (
                        source_page_id,
                        target_page_id,
                        relation_type,
                        discovered_at,
                        freshness_expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (source_page_id, target_page_id)
                    DO UPDATE SET
                        relation_type = EXCLUDED.relation_type,
                        discovered_at = EXCLUDED.discovered_at,
                        freshness_expires_at = EXCLUDED.freshness_expires_at
                    """,
                    (source_page_id, target_page_id, relation_type, now_utc, expiry),
                )
                inserted += 1

    return {
        "source_page_id": source_page_id,
        "inserted_links": inserted,
    }



def ensure_page_exists(conn: psycopg.Connection, page_title: str) -> int:
    with conn.transaction():
        with conn.cursor() as cur:
            return _upsert_page(cur, page_title)
