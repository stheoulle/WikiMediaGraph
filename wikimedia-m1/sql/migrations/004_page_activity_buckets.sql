CREATE TABLE IF NOT EXISTS page_activity_buckets (
    page_id BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    bucket_start TIMESTAMPTZ NOT NULL,
    bucket_minutes SMALLINT NOT NULL,
    edits_count INTEGER NOT NULL DEFAULT 0,
    unique_users_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (page_id, bucket_start, bucket_minutes)
);

CREATE INDEX IF NOT EXISTS idx_page_activity_buckets_bucket_start
    ON page_activity_buckets(bucket_start);

CREATE INDEX IF NOT EXISTS idx_page_activity_buckets_page_bucket
    ON page_activity_buckets(page_id, bucket_start DESC);
