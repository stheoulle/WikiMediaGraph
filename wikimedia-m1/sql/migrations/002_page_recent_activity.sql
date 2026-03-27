CREATE TABLE IF NOT EXISTS page_recent_activity (
    page_id BIGINT PRIMARY KEY REFERENCES pages(id) ON DELETE CASCADE,
    edits_last_hour INTEGER NOT NULL DEFAULT 0,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_page_recent_activity_window_end ON page_recent_activity(window_end);
CREATE INDEX IF NOT EXISTS idx_page_recent_activity_edits_last_hour ON page_recent_activity(edits_last_hour);