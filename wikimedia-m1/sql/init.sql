CREATE TABLE IF NOT EXISTS pages (
    id BIGSERIAL PRIMARY KEY,
    title TEXT NOT NULL UNIQUE,
    canonical_title TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS edit_events (
    id BIGSERIAL PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    page_id BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    event_time TIMESTAMPTZ NOT NULL,
    user_name TEXT,
    comment TEXT,
    raw_payload JSONB NOT NULL,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS page_stats (
    page_id BIGINT PRIMARY KEY REFERENCES pages(id) ON DELETE CASCADE,
    total_edits BIGINT NOT NULL DEFAULT 0,
    last_edit_time TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_edit_events_event_time ON edit_events(event_time);
CREATE INDEX IF NOT EXISTS idx_page_stats_last_edit_time ON page_stats(last_edit_time);