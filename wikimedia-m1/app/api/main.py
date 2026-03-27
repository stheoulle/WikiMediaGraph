from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from app.common.config import load_settings
from app.common.db import db_connection
from app.common.link_resolver import (
    LinkResolverConfig,
    ensure_page_exists,
    links_are_fresh,
    refresh_links_for_page,
)

app = FastAPI(title="WikiMedia Milestone 3 API", version="0.2.0")
settings = load_settings()


def _link_config() -> LinkResolverConfig:
    return LinkResolverConfig(
        wiki_api_url=settings.wiki_api_url,
        link_ttl_minutes=settings.link_ttl_minutes,
        request_timeout_seconds=settings.wiki_http_timeout_seconds,
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/metrics")
def metrics() -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    window_start = now_utc - timedelta(hours=1)

    with db_connection(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM pages")
            total_pages = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM edit_events WHERE event_time >= %s", (window_start,))
            events_last_hour = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM page_recent_activity WHERE edits_last_hour > 0")
            active_pages_last_hour = cur.fetchone()[0]

    return {
        "total_pages": total_pages,
        "events_last_hour": events_last_hour,
        "active_pages_last_hour": active_pages_last_hour,
        "window_start": window_start.isoformat(),
        "window_end": now_utc.isoformat(),
    }


@app.get("/api/recent/pages")
def recent_pages(limit: int = Query(default=50, ge=1, le=200)) -> dict[str, Any]:
    with db_connection(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.id,
                    p.title,
                    COALESCE(pra.edits_last_hour, 0) AS edits_last_hour,
                    COALESCE(ps.total_edits, 0) AS total_edits,
                    ps.last_edit_time
                FROM pages p
                LEFT JOIN page_recent_activity pra ON pra.page_id = p.id
                LEFT JOIN page_stats ps ON ps.page_id = p.id
                WHERE COALESCE(pra.edits_last_hour, 0) > 0
                ORDER BY pra.edits_last_hour DESC, ps.total_edits DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = cur.fetchall()

    return {
        "count": len(rows),
        "items": [
            {
                "page_id": r[0],
                "title": r[1],
                "edits_last_hour": r[2],
                "total_edits": r[3],
                "last_edit_time": r[4].isoformat() if r[4] else None,
            }
            for r in rows
        ],
    }


@app.get("/api/pages/{title}/activity")
def page_activity(title: str) -> dict[str, Any]:
    with db_connection(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.id,
                    p.title,
                    COALESCE(pra.edits_last_hour, 0) AS edits_last_hour,
                    COALESCE(ps.total_edits, 0) AS total_edits,
                    ps.last_edit_time,
                    pra.window_start,
                    pra.window_end
                FROM pages p
                LEFT JOIN page_recent_activity pra ON pra.page_id = p.id
                LEFT JOIN page_stats ps ON ps.page_id = p.id
                WHERE p.title = %s
                LIMIT 1
                """,
                (title,),
            )
            row = cur.fetchone()

    if row is None:
        raise HTTPException(status_code=404, detail="Page not found")

    return {
        "page_id": row[0],
        "title": row[1],
        "edits_last_hour": row[2],
        "total_edits": row[3],
        "last_edit_time": row[4].isoformat() if row[4] else None,
        "window_start": row[5].isoformat() if row[5] else None,
        "window_end": row[6].isoformat() if row[6] else None,
        "has_recent_modifications": row[2] > 0,
    }


@app.post("/api/pages/{title}/links/refresh")
def refresh_page_links(title: str) -> dict[str, Any]:
    config = _link_config()
    try:
        with db_connection(settings.database_url) as conn:
            result = refresh_links_for_page(conn, title, config)
            return {
                "title": title,
                "source_page_id": result["source_page_id"],
                "inserted_links": result["inserted_links"],
                "link_ttl_minutes": config.link_ttl_minutes,
            }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Link refresh failed: {exc}") from exc


@app.get("/api/graph")
def one_hop_graph(
    page_title: str = Query(..., min_length=1),
    refresh: bool = Query(default=False),
    limit: int = Query(default=80, ge=1, le=300),
) -> dict[str, Any]:
    config = _link_config()

    with db_connection(settings.database_url) as conn:
        center_page_id = ensure_page_exists(conn, page_title)

        if refresh or not links_are_fresh(conn, center_page_id):
            try:
                refresh_links_for_page(conn, page_title, config)
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(status_code=502, detail=f"Graph link resolution failed: {exc}") from exc

        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    p.id,
                    p.title,
                    COALESCE(ps.total_edits, 0) AS total_edits,
                    COALESCE(pra.edits_last_hour, 0) AS edits_last_hour,
                    ps.last_edit_time
                FROM pages p
                LEFT JOIN page_stats ps ON ps.page_id = p.id
                LEFT JOIN page_recent_activity pra ON pra.page_id = p.id
                WHERE p.id = %s
                LIMIT 1
                """,
                (center_page_id,),
            )
            center = cur.fetchone()

            cur.execute(
                """
                SELECT
                    t.id,
                    t.title,
                    COALESCE(ts.total_edits, 0) AS total_edits,
                    COALESCE(tra.edits_last_hour, 0) AS edits_last_hour,
                    ts.last_edit_time,
                    l.relation_type
                FROM page_links l
                JOIN pages t ON t.id = l.target_page_id
                LEFT JOIN page_stats ts ON ts.page_id = t.id
                LEFT JOIN page_recent_activity tra ON tra.page_id = t.id
                WHERE l.source_page_id = %s
                ORDER BY tra.edits_last_hour DESC, ts.total_edits DESC, t.title ASC
                LIMIT %s
                """,
                (center_page_id, limit),
            )
            neighbors = cur.fetchall()

    if center is None:
        raise HTTPException(status_code=404, detail="Center page not found")

    center_node = {
        "page_id": center[0],
        "title": center[1],
        "total_edits": center[2],
        "edits_last_hour": center[3],
        "has_recent_modifications": center[3] > 0,
        "color": "green" if center[3] > 0 else "red",
        "last_edit_time": center[4].isoformat() if center[4] else None,
    }

    neighbor_nodes = [
        {
            "page_id": r[0],
            "title": r[1],
            "total_edits": r[2],
            "edits_last_hour": r[3],
            "has_recent_modifications": r[3] > 0,
            "color": "green" if r[3] > 0 else "red",
            "last_edit_time": r[4].isoformat() if r[4] else None,
            "relation_type": r[5],
        }
        for r in neighbors
    ]

    edges = [
        {
            "source_page_id": center_node["page_id"],
            "target_page_id": n["page_id"],
            "relation_type": n["relation_type"],
        }
        for n in neighbor_nodes
    ]

    return {
        "center": center_node,
        "neighbors": neighbor_nodes,
        "edges": edges,
        "count": len(neighbor_nodes),
        "refreshed": refresh,
        "link_ttl_minutes": config.link_ttl_minutes,
    }
