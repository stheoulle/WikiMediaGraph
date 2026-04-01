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
CREATE TABLE IF NOT EXISTS page_recent_activity (
    page_id BIGINT PRIMARY KEY REFERENCES pages(id) ON DELETE CASCADE,
    edits_last_hour INTEGER NOT NULL DEFAULT 0,
    window_start TIMESTAMPTZ NOT NULL,
    window_end TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE IF NOT EXISTS page_links (
    source_page_id BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    target_page_id BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'link',
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    freshness_expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (source_page_id, target_page_id)
);
CREATE TABLE IF NOT EXISTS page_activity_buckets (
    page_id BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    bucket_start TIMESTAMPTZ NOT NULL,
    bucket_minutes SMALLINT NOT NULL,
    edits_count INTEGER NOT NULL DEFAULT 0,
    unique_users_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (page_id, bucket_start, bucket_minutes)
);
CREATE INDEX IF NOT EXISTS idx_edit_events_event_time ON edit_events(event_time);
CREATE INDEX IF NOT EXISTS idx_page_stats_last_edit_time ON page_stats(last_edit_time);
CREATE INDEX IF NOT EXISTS idx_page_recent_activity_window_end ON page_recent_activity(window_end);
CREATE INDEX IF NOT EXISTS idx_page_recent_activity_edits_last_hour ON page_recent_activity(edits_last_hour);
CREATE INDEX IF NOT EXISTS idx_page_links_source_page_id ON page_links(source_page_id);
CREATE INDEX IF NOT EXISTS idx_page_links_freshness_expires_at ON page_links(freshness_expires_at);
CREATE INDEX IF NOT EXISTS idx_page_activity_buckets_bucket_start ON page_activity_buckets(bucket_start);
CREATE INDEX IF NOT EXISTS idx_page_activity_buckets_page_bucket ON page_activity_buckets(page_id, bucket_start DESC);