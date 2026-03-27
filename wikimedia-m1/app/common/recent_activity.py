from datetime import datetime, timedelta, timezone

import psycopg



def recompute_recent_activity(conn: psycopg.Connection, now_utc: datetime | None = None) -> int:
    now_utc = now_utc or datetime.now(timezone.utc)
    window_start = now_utc - timedelta(hours=1)

    with conn.transaction():
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO page_recent_activity (page_id, edits_last_hour, window_start, window_end, updated_at)
                SELECT
                    e.page_id,
                    COUNT(*)::int AS edits_last_hour,
                    %s AS window_start,
                    %s AS window_end,
                    NOW() AS updated_at
                FROM edit_events e
                WHERE e.event_time >= %s
                  AND e.event_time <= %s
                GROUP BY e.page_id
                ON CONFLICT (page_id)
                DO UPDATE SET
                    edits_last_hour = EXCLUDED.edits_last_hour,
                    window_start = EXCLUDED.window_start,
                    window_end = EXCLUDED.window_end,
                    updated_at = NOW()
                """,
                (window_start, now_utc, window_start, now_utc),
            )

            # Clear pages no longer active in the current 1-hour window.
            cur.execute(
                """
                UPDATE page_recent_activity
                SET edits_last_hour = 0,
                    window_start = %s,
                    window_end = %s,
                    updated_at = NOW()
                WHERE page_id NOT IN (
                    SELECT DISTINCT page_id
                    FROM edit_events
                    WHERE event_time >= %s AND event_time <= %s
                )
                """,
                (window_start, now_utc, window_start, now_utc),
            )

            return cur.rowcount
