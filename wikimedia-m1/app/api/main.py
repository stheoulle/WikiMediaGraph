from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Query

from app.common.config import load_settings
from app.common.db import db_connection

app = FastAPI(title="WikiMedia Milestone 2 API", version="0.1.0")
settings = load_settings()


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
