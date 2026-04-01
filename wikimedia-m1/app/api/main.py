from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque
import math
from pathlib import Path
from threading import Lock
import time
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.common.config import load_settings
from app.common.db import db_connection
from app.common.link_resolver import (
    LinkResolverConfig,
    ensure_page_exists,
    links_are_fresh,
    refresh_links_for_page,
)

app = FastAPI(title="WikiMedia Milestone 5 API", version="0.4.0")
settings = load_settings()
_STATIC_DIR = Path(__file__).resolve().parent / "static"
_LATENCY_MAX_SAMPLES = 4000
_REQUEST_LATENCIES_MS: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=_LATENCY_MAX_SAMPLES))
_LATENCY_LOCK = Lock()
_ALLOWED_WINDOWS: dict[str, timedelta] = {
    "1h": timedelta(hours=1),
    "6h": timedelta(hours=6),
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
}
_ALLOWED_BUCKET_MINUTES = {1, 5, 15, 60}

app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


def _percentile(values: list[float], p: float) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    rank = max(1, math.ceil((p / 100.0) * len(sorted_values)))
    return sorted_values[rank - 1]


def _latency_snapshot(path: str) -> dict[str, Any]:
    with _LATENCY_LOCK:
        values = list(_REQUEST_LATENCIES_MS[path])

    if not values:
        return {
            "count": 0,
            "avg_ms": None,
            "p50_ms": None,
            "p95_ms": None,
            "max_ms": None,
        }

    return {
        "count": len(values),
        "avg_ms": round(sum(values) / len(values), 2),
        "p50_ms": round(_percentile(values, 50) or 0.0, 2),
        "p95_ms": round(_percentile(values, 95) or 0.0, 2),
        "max_ms": round(max(values), 2),
    }


def _floor_to_bucket(ts: datetime, bucket_minutes: int) -> datetime:
    ts_utc = ts.astimezone(timezone.utc)
    floored_minute = (ts_utc.minute // bucket_minutes) * bucket_minutes
    return ts_utc.replace(minute=floored_minute, second=0, microsecond=0)


def _parse_window_param(window: str) -> timedelta:
    parsed = _ALLOWED_WINDOWS.get(window)
    if parsed is None:
        allowed = ", ".join(_ALLOWED_WINDOWS.keys())
        raise HTTPException(status_code=400, detail=f"Invalid window '{window}'. Allowed values: {allowed}.")
    return parsed


@app.middleware("http")
async def collect_api_latency(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000.0

    path = request.url.path
    if path.startswith("/api/"):
        with _LATENCY_LOCK:
            _REQUEST_LATENCIES_MS[path].append(elapsed_ms)

    return response


def _link_config() -> LinkResolverConfig:
    return LinkResolverConfig(
        wiki_api_url=settings.wiki_api_url,
        link_ttl_minutes=settings.link_ttl_minutes,
        request_timeout_seconds=settings.wiki_http_timeout_seconds,
    )


@app.get("/")
def graph_ui() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


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


@app.get("/api/observability")
def observability() -> dict[str, Any]:
    now_utc = datetime.now(timezone.utc)
    window_1h = now_utc - timedelta(hours=1)
    window_5m = now_utc - timedelta(minutes=5)
    window_10m = now_utc - timedelta(minutes=10)

    graph_query_latency_ms: float | None = None

    with db_connection(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM pages")
            total_pages = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM edit_events")
            total_edit_events = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM edit_events WHERE event_time >= %s", (window_1h,))
            events_last_hour = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM edit_events WHERE event_time >= %s", (window_5m,))
            events_last_5m = cur.fetchone()[0]

            cur.execute("SELECT COALESCE(SUM(total_edits), 0) FROM page_stats")
            total_counted_edits = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM page_recent_activity WHERE edits_last_hour > 0")
            active_pages_last_hour = cur.fetchone()[0]

            cur.execute("SELECT COALESCE(SUM(edits_last_hour), 0) FROM page_recent_activity")
            edits_last_hour_materialized = cur.fetchone()[0]

            cur.execute("SELECT MAX(event_time) FROM edit_events")
            newest_event_time = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM page_links")
            total_links = cur.fetchone()[0]

            cur.execute("SELECT COUNT(*) FROM page_links WHERE freshness_expires_at <= NOW()")
            stale_links = cur.fetchone()[0]

            cur.execute(
                """
                SELECT date_trunc('minute', event_time) AS minute_bucket, COUNT(*)
                FROM edit_events
                WHERE event_time >= %s
                GROUP BY minute_bucket
                ORDER BY minute_bucket ASC
                """,
                (window_10m,),
            )
            lag_series_rows = cur.fetchall()

            # Lightweight adjacency query timing as a proxy for graph-read database cost.
            cur.execute(
                """
                SELECT source_page_id
                FROM page_links
                GROUP BY source_page_id
                ORDER BY COUNT(*) DESC
                LIMIT 1
                """
            )
            top_source = cur.fetchone()

            if top_source is not None:
                start_query = time.perf_counter()
                cur.execute(
                    """
                    SELECT l.target_page_id
                    FROM page_links l
                    JOIN pages t ON t.id = l.target_page_id
                    LEFT JOIN page_stats ts ON ts.page_id = t.id
                    LEFT JOIN page_recent_activity tra ON tra.page_id = t.id
                    WHERE l.source_page_id = %s
                    ORDER BY tra.edits_last_hour DESC, ts.total_edits DESC, t.title ASC
                    LIMIT 25
                    """,
                    (top_source[0],),
                )
                cur.fetchall()
                graph_query_latency_ms = (time.perf_counter() - start_query) * 1000.0

    dedup_consistency_gap = total_edit_events - total_counted_edits
    lag_seconds = None
    if newest_event_time is not None:
        lag_seconds = max(0.0, (now_utc - newest_event_time).total_seconds())

    return {
        "timestamp_utc": now_utc.isoformat(),
        "windows": {
            "one_hour_start": window_1h.isoformat(),
            "five_min_start": window_5m.isoformat(),
            "ten_min_start": window_10m.isoformat(),
            "window_end": now_utc.isoformat(),
        },
        "stream_activity": {
            "total_pages": total_pages,
            "total_edit_events": total_edit_events,
            "events_last_hour": events_last_hour,
            "events_last_5m": events_last_5m,
            "events_per_second_last_5m": round(events_last_5m / 300.0, 3),
            "active_pages_last_hour": active_pages_last_hour,
            "materialized_edits_last_hour": edits_last_hour_materialized,
            "latest_event_time": newest_event_time.isoformat() if newest_event_time else None,
            "estimated_consumer_lag_seconds": round(lag_seconds, 3) if lag_seconds is not None else None,
            "lag_series_last_10m": [
                {
                    "minute": r[0].isoformat(),
                    "events": r[1],
                }
                for r in lag_series_rows
            ],
        },
        "dedup_and_consistency": {
            "total_counted_edits": total_counted_edits,
            "dedup_consistency_gap": dedup_consistency_gap,
            "dedup_consistency_ok": dedup_consistency_gap == 0,
            "note": "Gap should remain zero under idempotent processing.",
        },
        "graph_and_links": {
            "total_links": total_links,
            "stale_links": stale_links,
            "fresh_links": max(0, total_links - stale_links),
            "stale_link_ratio": round((stale_links / total_links), 4) if total_links > 0 else 0.0,
            "adjacency_query_latency_ms": round(graph_query_latency_ms, 3) if graph_query_latency_ms is not None else None,
        },
        "api_latency_ms": {
            "graph": _latency_snapshot("/api/graph"),
            "metrics": _latency_snapshot("/api/metrics"),
            "observability": _latency_snapshot("/api/observability"),
        },
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


@app.get("/api/pages/{title}/timeseries")
def page_timeseries(
    title: str,
    window: str = Query(default="24h"),
    bucket: int = Query(default=15, ge=1, le=60),
) -> dict[str, Any]:
    if bucket not in _ALLOWED_BUCKET_MINUTES:
        allowed = ", ".join(str(v) for v in sorted(_ALLOWED_BUCKET_MINUTES))
        raise HTTPException(status_code=400, detail=f"Invalid bucket '{bucket}'. Allowed minutes: {allowed}.")

    window_delta = _parse_window_param(window)
    now_utc = datetime.now(timezone.utc)
    window_start_raw = now_utc - window_delta
    window_start = _floor_to_bucket(window_start_raw, bucket)
    window_end = _floor_to_bucket(now_utc, bucket)

    with db_connection(settings.database_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT id, title FROM pages WHERE title = %s LIMIT 1", (title,))
            page_row = cur.fetchone()

            if page_row is None:
                raise HTTPException(status_code=404, detail="Page not found")

            page_id = page_row[0]

            cur.execute(
                """
                SELECT bucket_start, edits_count
                FROM page_activity_buckets
                WHERE page_id = %s
                  AND bucket_minutes = %s
                  AND bucket_start >= %s
                  AND bucket_start <= %s
                ORDER BY bucket_start ASC
                """,
                (page_id, bucket, window_start, window_end),
            )
            rows = cur.fetchall()

    edits_by_bucket = {row[0]: row[1] for row in rows}
    points: list[dict[str, Any]] = []
    total_buckets = 0
    non_empty_buckets = 0
    max_bucket = 0
    sum_edits = 0

    current = window_start
    while current <= window_end:
        edits = int(edits_by_bucket.get(current, 0))
        points.append({"t": current.isoformat(), "edits": edits})
        total_buckets += 1
        sum_edits += edits
        if edits > 0:
            non_empty_buckets += 1
        if edits > max_bucket:
            max_bucket = edits
        current += timedelta(minutes=bucket)

    return {
        "page_id": page_id,
        "title": title,
        "window": window,
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "bucket_minutes": bucket,
        "points": points,
        "stats": {
            "sum_edits": sum_edits,
            "max_bucket": max_bucket,
            "non_empty_buckets": non_empty_buckets,
            "total_buckets": total_buckets,
        },
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
