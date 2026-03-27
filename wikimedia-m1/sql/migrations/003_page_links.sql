CREATE TABLE IF NOT EXISTS page_links (
    source_page_id BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    target_page_id BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    relation_type TEXT NOT NULL DEFAULT 'link',
    discovered_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    freshness_expires_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (source_page_id, target_page_id)
);
CREATE INDEX IF NOT EXISTS idx_page_links_source_page_id ON page_links(source_page_id);
CREATE INDEX IF NOT EXISTS idx_page_links_freshness_expires_at ON page_links(freshness_expires_at);