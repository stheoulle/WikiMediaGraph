# WikiMedia Graph - Full Improvement Blueprint

This README is a detailed, execution-ready plan that explains all major improvement ideas for this project.

It is written to help you:
- justify design decisions during a defense/demo,
- prioritize implementation work,
- and build new features without losing correctness.

---

## 1. Current Project Snapshot

The current system already has a strong baseline:

- Streaming ingest from Wikimedia SSE
- Kafka/Redpanda decoupling
- Idempotent consumer writes to PostgreSQL
- Page counters and last-hour activity model
- Link resolver with TTL-based freshness
- One-hop graph API
- Interactive frontend graph with pan/zoom and recenter
- Aggregated observability endpoint

This is already a good architecture for a milestone project. The next stage is to evolve from "works for demo" to "robust + analytical + scalable".

---

## 2. Main Improvement Goals

The recommended roadmap focuses on 6 goals:

1. Add real historical analytics per page (time series)
2. Keep strong correctness while reducing compute cost
3. Prevent unbounded storage growth
4. Improve operational observability
5. Increase reliability for external API/network failures
6. Add tests so behavior is provable and regression-safe

---

## 3. Time Slider Feasibility (Important)

Your concern was: "a page is not modified more than 10 times an hour and only for a few hours/day, maybe not enough data for a slider."

Conclusion: a slider is still very feasible, but with aggregated buckets, not raw events.

### 3.1 Why raw-event slider looks sparse

If a page has around 10 edits/hour, raw event points are irregular:
- long flat periods,
- occasional small bursts,
- noisy visual shape.

This can feel empty and uninformative.

### 3.2 Why bucketed slider works

Use time buckets:
- 5-minute buckets for short windows
- 15-minute buckets for day view
- 1-hour buckets for week view

Expected edits in 15-minute buckets:

$$
\lambda_{15m} = \frac{10}{4} = 2.5
$$

Even for sparse pages, that produces meaningful trend bars/line shapes.

### 3.3 Recommended UX behavior

- Window presets: `1h`, `6h`, `24h`, `7d`
- Adaptive bucket size:
  - `1h` -> 1 or 5 minutes
  - `24h` -> 15 minutes
  - `7d` -> 1 hour
- Show two series:
  - bars = raw bucket count
  - line = smoothed trend (EMA)
- Optional toggle: `show empty buckets`

This makes low-frequency pages understandable without pretending there is high-resolution data.

---

## 4. Proposed Data Model Extensions

### 4.1 New table: page_activity_buckets

Add a materialized time-series table.

```sql
CREATE TABLE IF NOT EXISTS page_activity_buckets (
    page_id BIGINT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
    bucket_start TIMESTAMPTZ NOT NULL,
    bucket_minutes SMALLINT NOT NULL,
    edits_count INTEGER NOT NULL DEFAULT 0,
    unique_users_count INTEGER NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (page_id, bucket_start, bucket_minutes)
);

CREATE INDEX IF NOT EXISTS idx_pab_bucket_start
    ON page_activity_buckets(bucket_start);

CREATE INDEX IF NOT EXISTS idx_pab_page_bucket
    ON page_activity_buckets(page_id, bucket_start DESC);
```

### 4.2 Why this table matters

- avoids rescanning large raw event windows for each request,
- powers the slider quickly,
- creates a stable analytical layer that survives retention on raw events.

---

## 5. Stream Processing Improvements

### 5.1 Current behavior

- Consumer writes `edit_events` + increments `page_stats`
- Separate worker periodically recomputes `page_recent_activity` from raw events

This is simple and correct, but eventually expensive.

### 5.2 Proposed target behavior

On each accepted event in consumer transaction:

1. write deduplicated event record
2. update `page_stats`
3. upsert bucket row in `page_activity_buckets` for selected bucket size(s)

Then compute `edits_last_hour` from recent bucket sums (or keep current worker as reconciliation).

### 5.3 Migration strategy

- Phase 1: add buckets in parallel with current worker
- Phase 2: compare both methods for a period
- Phase 3: switch API reads to bucket-backed calculations

This keeps risk low while improving efficiency.

---

## 6. API Additions and Contract

### 6.1 New endpoint: page time series

`GET /api/pages/{title}/timeseries?window=24h&bucket=15m`

Response example:

```json
{
  "page_id": 42,
  "title": "France",
  "window_start": "2026-04-01T00:00:00Z",
  "window_end": "2026-04-02T00:00:00Z",
  "bucket_minutes": 15,
  "points": [
    {"t": "2026-04-01T10:00:00Z", "edits": 3, "users": 2},
    {"t": "2026-04-01T10:15:00Z", "edits": 1, "users": 1}
  ],
  "stats": {
    "sum_edits": 44,
    "max_bucket": 6,
    "non_empty_buckets": 18
  }
}
```

### 6.2 New endpoint: compare neighbors over time (optional)

`GET /api/graph/timeseries?page_title=France&neighbor_limit=5&window=24h`

Use this only after single-page time series works well.

---

## 7. Frontend Evolution Plan

### 7.1 New panel in graph UI

Add a "Page Evolution" panel beside center metrics:

- current selected page title
- window controls
- slider or scrubber timeline
- chart area (bars + trend line)
- summary stats (`total in window`, `peak bucket`, `active periods`)

### 7.2 Behavior details

- recenter graph -> auto-load time series for new center
- changing window/bucket -> only refresh chart endpoint
- hover bucket -> show timestamp + edits + users

### 7.3 Sparse data visualization rules

- if all buckets are zero: show explicit empty-state message
- if low counts: keep y-axis linear (no log for tiny values)
- smoothing line should be optional to avoid hiding true spikes

---

## 8. Storage and Retention Strategy

Raw events grow indefinitely if unchanged. Add retention policy.

### 8.1 Recommended policy

- keep raw `edit_events` for 7 to 30 days (choose based on disk)
- keep `page_stats`, `page_recent_activity`, `page_activity_buckets`, `page_links` long-term

### 8.2 Operational approach

- periodic cleanup job for old raw rows,
- or partition `edit_events` by day/month and drop old partitions quickly.

### 8.3 Why safe

Historical analytics are preserved in bucketed table, so dashboard features remain functional.

---

## 9. Link Resolver and External API Hardening

Current link refresh works, but can be more resilient.

### 9.1 Improvements

- retry policy with exponential backoff + jitter for Wikipedia API
- explicit timeout/retry metrics in observability
- optional cap on stored neighbors per page for interactive UX
- reuse persistent HTTP session to reduce connection overhead

### 9.2 Quality controls

- track refresh success/fail counters
- track average refresh duration
- expose stale ratio by age buckets

---

## 10. Observability Enhancements

You already expose an aggregated observability payload. Extend with:

- producer ingest rate (events/s at ingress)
- consumer processing rate (events/s applied)
- dedup ratio over rolling windows
- dead-letter or invalid-message count
- route-level error rates (`4xx`, `5xx`)
- cache hit/miss for link freshness decisions

This makes bottlenecks and regressions easy to explain.

---

## 11. Reliability and Error Handling

### 11.1 Add DLQ path for bad messages

Instead of only skipping invalid messages, write bad payload metadata to a dedicated table/topic:

- reason
- payload hash
- first seen timestamp
- sample payload snippet

### 11.2 Commit policy

Keep commit-after-success semantics to preserve correctness.

### 11.3 Replay confidence

Document replay behavior clearly:
- duplicates are dropped by `event_id` unique constraint
- stats remain correct under restart/reprocessing

---

## 12. Testing Plan (Missing Today, High Priority)

There are currently no project tests in the repository. Add a minimum test suite.

### 12.1 Unit tests

- normalization filters (Wikipedia-only + media exclusion)
- stable event id generation
- bucket timestamp rounding logic
- recent activity aggregation logic

### 12.2 Integration tests

- insert same event twice -> `page_stats.total_edits` increments once
- `/api/graph` returns stable schema and expected ordering
- `/api/pages/{title}/timeseries` returns contiguous buckets for requested window

### 12.3 Smoke tests

- service starts with host env
- critical endpoints respond with 200
- observability payload contains required keys

---

## 13. Performance Guardrails

Set measurable targets and check them periodically.

Suggested targets:

- P95 `GET /api/graph` under 300 ms for warm links
- P95 `GET /api/pages/{title}/timeseries` under 200 ms (24h/15m)
- dedup consistency gap remains 0
- stale link ratio below 20 percent under normal usage

---

## 14. Security and Data Hygiene

- avoid exposing raw payload directly through API
- cap page title length and sanitize input at API boundary
- enforce endpoint limits for graph and timeseries
- keep user metadata minimal in returned payloads

---

## 15. Phased Implementation Roadmap

### Phase A - Low risk, high value

1. Add `page_activity_buckets` migration
2. Add bucket upsert in consumer
3. Add `/api/pages/{title}/timeseries`
4. Add basic chart panel and window controls in frontend

### Phase B - Efficiency and reliability

1. Use bucket-backed recent activity calculations
2. Add retention job for old `edit_events`
3. Add DLQ table/topic and counters
4. Add retry strategy to link resolver

### Phase C - Defense-grade polish

1. Add integration tests and smoke checks
2. Extend observability payload with new metrics
3. Benchmark and tune indexes/queries
4. Improve README diagrams and runbooks

---

## 16. Suggested Demo Narrative

Use this sequence in presentation:

1. Show live ingestion and rising event count
2. Open graph, recenter through neighbors
3. Open observability endpoint and explain lag/dedup correctness
4. Show new time slider for selected center page
5. Explain sparse-data strategy (bucket + smoothing)
6. Highlight retention/testing/reliability roadmap

This tells a complete story: real-time system, interactive product, and production-minded engineering.

---

## 17. Immediate Next Build (Recommended)

If you only implement one feature next, choose this:

- add bucketed page time series + slider panel.

Why this one first:

- directly addresses your idea,
- creates visible product value,
- unlocks historical analytics while preserving current architecture.

---

## 18. Appendix - Practical Defaults

Use these defaults initially:

- default window: `24h`
- default bucket: `15m`
- smoothing: EMA with alpha `0.25`
- empty bucket policy: include zero buckets in response
- raw event retention: `14 days`

These values are easy to tune after real usage.

---

## 19. Summary

The current project is already a solid milestone implementation.

The improvement strategy is:
- preserve correctness-first design,
- add bucketed historical read model,
- power a meaningful slider even with sparse page edits,
- improve retention, testing, and observability to reach a more production-ready level.
