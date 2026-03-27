# WikiMedia - Real-Time Page Edit Graph

## 1. Project Summary

WikiMedia is a real-time data system that ingests Wikipedia page edit events, maintains edit activity metrics, stores linked-page relationships, and serves an interactive graph visualization.

The system is designed for:

- Streaming ingestion at approximately 1,000 events/second
- Correctness-first counter updates with idempotent processing
- Fast retrieval of one-hop page neighborhoods for graph navigation
- Last-hour activity visibility for recency-aware visualization

This project aligns with course themes:

- Distributed ingestion and decoupling (Kafka)
- Stream semantics and time windows (recent activity)
- Relational modeling and precomputation to reduce repeated work
- Architectural trade-offs and measurable design decisions

---

## 2. Problem Statement

Given a live stream of page modification events:

1. Count how many times each page has been modified
2. Track whether pages have modifications in the last hour
3. Build and cache page-link relationships to avoid recomputation
4. Serve graph-ready data for an interface where users can re-center on adjacent pages

The central user interaction is:

1. User selects a page
2. Backend returns the selected page metrics and its linked pages
3. Frontend renders the selected page in the center and neighbors around it
4. User clicks a neighbor to make it the new center

---

## 3. Scope

## Included in MVP

- Kafka ingestion from Wikimedia SSE
- Total edit counters per page
- Last-hour edit activity per page
- Linked-page extraction and relational storage with foreign keys
- Interactive graph with click-to-recenter on adjacent pages

## Explicitly out of MVP

- Fully persistent, pan/zoom graph that keeps all explored nodes in memory forever
- Multi-hop exploration as default query behavior
- Complex ranking/recommendation algorithms

These are reserved as post-MVP improvements.

---

## 4. High-Level Architecture

## Components

1. SSE Ingestor

- Connects to Wikimedia SSE endpoint
- Parses events and publishes normalized messages to Kafka topic edits.raw

1. Kafka

- Buffers bursty traffic
- Decouples external source ingestion from internal processing
- Supports replay from offsets for recovery

1. Stream Consumer / Processor

- Consumes edits.raw
- Performs idempotency checks (event_id)
- Updates page counters and recent activity window tables
- Triggers link extraction on demand or by policy

1. Link Resolver

- Fetches linked pages or redirects for selected page
- Writes relationships to relational tables with foreign keys
- Avoids repeated fetch/compute by cache-validity policy

1. PostgreSQL

- Primary transactional store
- Source of truth for pages, counters, recent events, and link relationships

1. API Service (FastAPI)

- Serves graph payloads for selected page
- Returns center node + adjacent nodes + styling metrics (size, color inputs)

1. Frontend Graph UI

- Displays center node and neighbors
- Node color from recency
- Node size from total edits
- Click neighbor -> re-center and re-query

---

## 5. Data Flow

## Ingestion flow

1. SSE event arrives
2. Event normalized with stable event_id
3. Message sent to Kafka topic edits.raw
4. Consumer reads message
5. Dedup check by event_id
6. If new event:

- Insert raw event record
- Upsert page total counter
- Upsert/refresh page last-hour state

## User-driven link flow

1. User requests page P graph
2. API checks if links for P are fresh enough
3. If stale/missing: resolver fetches links and stores edges
4. API returns center page metrics + one-hop neighbor metrics

## Visualization flow

1. Frontend receives graph payload
2. Center node shown in middle
3. Nodes colored:

- Green if recently modified (within 1 hour)
- Red otherwise

4. Node size scaled by total edit count
2. Clicking any neighbor repeats flow with new center

---

## 6. Consistency and Correctness Model

Project choice: correctness-first under at-least-once delivery.

## Guarantees

- No double-counting when duplicate events are reprocessed
- Counter updates are idempotent by unique event_id
- Counter update and dedup registration are transactional

## Delivery semantics

- Kafka consumer uses at-least-once processing
- Idempotency layer converts at-least-once into effectively-once counters

## Why this choice

- Counter drift is difficult to explain in a graded data project
- Correctness is easier to defend than "eventual fix-up later"
- PostgreSQL transactions and unique constraints make this practical

---

## 7. Database Design (PostgreSQL)

## 7.1 Core entities

### pages

- id (bigserial, primary key)
- title (text, unique, not null)
- canonical_title (text, indexed)
- created_at (timestamp)
- updated_at (timestamp)

### edit_events

- id (bigserial, primary key)
- event_id (text, unique, not null)
- page_id (bigint, foreign key -> pages.id, not null)
- event_time (timestamp, indexed, not null)
- user_name (text)
- comment (text)
- raw_payload (jsonb)
- ingested_at (timestamp)

Purpose: append-only auditable log of accepted unique events.

### page_stats

- page_id (bigint, primary key, foreign key -> pages.id)
- total_edits (bigint, not null, default 0)
- last_edit_time (timestamp, indexed)
- updated_at (timestamp)

Purpose: hot read model for node size and center metric display.

### page_recent_activity

- page_id (bigint, primary key, foreign key -> pages.id)
- edits_last_hour (integer, not null, default 0)
- window_start (timestamp, not null)
- window_end (timestamp, not null)
- updated_at (timestamp)

Purpose: hot read model for node color and recent metrics.

### page_links

- source_page_id (bigint, foreign key -> pages.id, not null)
- target_page_id (bigint, foreign key -> pages.id, not null)
- relation_type (text, default 'link')
- discovered_at (timestamp)
- freshness_expires_at (timestamp, indexed)
- primary key (source_page_id, target_page_id)

Purpose: cached adjacency graph with FK integrity.

## 7.2 Critical constraints and indexes

- unique index on edit_events.event_id for idempotency
- index on edit_events.event_time for time-window maintenance
- index on page_stats.last_edit_time
- composite index for fast adjacency reads on page_links(source_page_id, target_page_id)
- index on page_links.freshness_expires_at for cache refresh decisions

---

## 8. API Design

## 8.1 Get graph for center page

GET /api/graph?page_title={title}&depth=1

Response shape:

- center:
- page_id
- title
- total_edits
- edits_last_hour
- has_recent_modifications
- neighbors: list of node summaries with same metrics
- edges: list of source-target pairs
- generated_at

## 8.2 Recenter behavior

- Frontend sends same endpoint with clicked neighbor title
- Backend returns new center + its one-hop neighborhood

## 8.3 Required observability endpoints

- GET /api/health
- GET /api/metrics (consumer lag, processing rate, dedup hit rate)

---

## 9. Visualization Rules

## Node color

- Green: has_recent_modifications = true
- Red: has_recent_modifications = false

## Node size

- Proportional to total_edits
- Recommended scaling: logarithmic to avoid giant outliers

Example idea:

- visual_radius = base + alpha * ln(total_edits + 1)

## Center metric panel

Show for selected page:

- Total edits
- Edits in last hour
- Last edit timestamp
- Neighbor count

---

## 10. Last-Hour Activity Strategy

Two valid implementations are acceptable. Choose one and document it during implementation.

## Option A: rolling recomputation job

- Keep raw events in edit_events
- Every minute, recompute edits_last_hour from [now-1h, now]
- Simpler correctness model, slightly heavier read workload

## Option B: incremental window maintenance

- Increment recent counter on new event
- Schedule decrement when event exits the 1-hour window
- Lower query cost, higher state complexity

Recommended for MVP: Option A, because it is easier to defend and test.

---

## 11. Failure Handling

## Duplicate events

- Handled by unique event_id constraint
- Duplicate insert ignored, counter not incremented

## Consumer restart

- Resume from Kafka committed offsets
- Safe replay due to idempotent storage logic

## Temporary DB outage

- Consumer retries with backoff
- Lag increases temporarily, then catches up

## Link resolver failures

- Return center page with known neighbors only
- Mark link refresh as pending and retry asynchronously

---

## 12. Performance Targets

Given the selected assumptions:

- Sustained ingest target: around 1,000 events/s
- P95 graph query latency (one-hop): under 300 ms (warm cache)
- Recenter interaction latency goal: under 500 ms end-to-end perceived

These are project targets, not strict guarantees.

---

## 13. Security and Data Hygiene

- Validate and sanitize all external fields from SSE payload
- Enforce API request limits to prevent abusive graph crawling
- Store only necessary user metadata from events
- Keep raw payload in JSONB for audit/debug, but avoid exposing directly in API

---

## 14. Deployment

## Local/dev setup

- Docker Compose services:
- zookeeper (if needed by Kafka distribution)
- kafka
- postgres
- api
- consumer
- frontend

## Runtime separation

- API and consumer as separate deployable services
- Independent scaling based on read vs ingest load

---

## 15. Testing Strategy

## Unit tests

- Event normalization
- Idempotent update logic
- Node color/size mapping functions

## Integration tests

- SSE -> Kafka -> consumer -> PostgreSQL pipeline
- Duplicate event replay does not change counts
- Graph endpoint returns consistent center + neighbors

## End-to-end tests

- User clicks center page, then neighbor recenter flow
- Recent activity color changes after synthetic events

---

## 16. Observability and Project Defense Metrics

Track and present:

- Kafka consumer lag over time
- Events processed/s
- Dedup hit rate (duplicates dropped)
- Counter update latency
- Graph API p50/p95 latency
- DB query plans for adjacency endpoint

These metrics provide concrete support for architecture choices.

---

## 17. Architectural Trade-Off Defense (Presentation Ready)

## Why Kafka

- Handles bursty unbounded stream
- Decouples source volatility from DB writes
- Supports replay for reliability and recovery

## Why PostgreSQL

- Strong relational modeling for page-links with foreign keys
- Transactional idempotent counter updates
- Simpler correctness story for grading and demos

## Why precompute and cache links

- Avoid expensive repeated link extraction per click
- Improves interactivity and reduces backend variance

## Why one-hop graph for MVP

- Predictable payload size and latency
- Easier to debug and defend
- Extensible to multi-hop after baseline validation

---

## 18. Known Risks and Mitigations

1. Hot pages become write hotspots

- Mitigation: batched counter updates or partitioning strategy later

1. Link graph growth may increase query cost

- Mitigation: one-hop limits, pagination, cache freshness policy

1. Event schema drift from source

- Mitigation: schema validation + fallback parsing path

1. Late/out-of-order events affecting recency

- Mitigation: event-time handling policy clearly documented

---

## 19. Future Improvements

1. Keep entire explored graph client-side with pan/zoom and smooth focus transitions
2. Add websocket push updates for live node color/size refresh
3. Introduce graph ranking (most active or most connected pages)
4. Add ClickHouse sink for historical analytics dashboards
5. Add multi-hop expansion with adaptive pruning

---

## 20. Milestone Plan

1. Milestone 1 - Ingestion and idempotent counters (implemented)

- SSE ingest, Kafka topic, consumer, pages/page_stats/edit_events tables
- Implementation path: cours/wikimedia-m1
- Includes: Docker Compose stack, PostgreSQL schema, SSE producer, idempotent Kafka consumer

1. Milestone 2 - Recent activity (implemented)

- last-hour read model and API exposure
- Implementation path: cours/wikimedia-m1
- Includes: `page_recent_activity` table, 60-second recomputation worker, and FastAPI endpoints (`/api/health`, `/api/metrics`, `/api/recent/pages`, `/api/pages/{title}/activity`)

1. Milestone 3 - Link storage and graph endpoint

- page_links table, resolver logic, one-hop API

1. Milestone 4 - Frontend interaction

- center node render, color/size rules, recenter-on-click

1. Milestone 5 - Hardening and defense

- tests, observability metrics, architecture trade-off evidence

---

## 21. Definition of Done (MVP)

- Stream events are ingested and persisted
- Duplicate events do not inflate counters
- Last-hour activity is visible and correct
- Linked pages are stored with foreign keys
- Graph UI supports center + neighbors and recenter interaction
- README, tests, and metrics are sufficient to defend architectural choices
