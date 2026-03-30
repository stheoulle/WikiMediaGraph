# WikiMedia Milestone 1

This folder implements Milestone 1 from the course README:

- SSE ingest from Wikimedia recent changes (Wikipedia pages only)
- Kafka topic edits.raw
- Consumer with idempotent processing
- PostgreSQL tables: pages, edit_events, page_stats

This folder now also implements Milestone 2:

- Last-hour activity read model (`page_recent_activity`)
- Periodic recomputation worker (every 60 seconds)
- API exposure for health, metrics, recent pages, and page activity

This folder now also implements Milestone 3:

- Link storage table with foreign keys (`page_links`)
- On-demand resolver against Wikipedia API with TTL cache refresh
- One-hop graph endpoint (`/api/graph`) for center page + neighbors

This folder now also implements Milestone 4:

- Browser graph explorer served by FastAPI at `/`
- Center node visualization with one-hop neighbors in an SVG graph
- Node color and size mapping from activity metrics
- Click-to-recenter behavior on adjacent nodes

This folder now also implements Milestone 5:

- Unified observability endpoint (`GET /api/observability`)
- Throughput, lag proxy, dedup consistency, link freshness, and API latency metrics

## Stack

- Python 3.11
- Redpanda (Kafka API)
- PostgreSQL 16
- Docker Compose

## Ingestion Scope

The producer consumes the Wikimedia `recentchange` stream but only keeps Wikipedia page changes.

- Included: Wikipedia page edit events.
- Excluded: non-Wikipedia projects and media/file-oriented changes (for example Wikimedia Commons image pages).

Default runtime mode in this repository:

- Docker for infrastructure only (`postgres` + `redpanda`)
- Host Python process for `producer` and `consumer`

## Project Layout

- docker-compose.yml: local runtime (infra by default, app containers optional)
- sql/init.sql: database schema for Milestone 1
- sql/migrations/002_page_recent_activity.sql: migration for Milestone 2 table
- sql/migrations/003_page_links.sql: migration for Milestone 3 links table
- app/producer/main.py: SSE -> Kafka producer
- app/consumer/main.py: Kafka -> PostgreSQL idempotent consumer
- app/recent_activity/main.py: rolling recomputation worker for last-hour activity
- app/api/main.py: FastAPI endpoints for milestone 2 exposure
- app/common/link_resolver.py: Wikipedia link resolver and DB link refresh logic
- app/api/static/: Milestone 4 frontend (`index.html`, `styles.css`, `app.js`)
- requirements.txt: Python dependencies
- .env.example: environment values for full Docker app mode
- .env.host.example: environment values for host app mode

## Quick Start

1. Start infrastructure containers:

```bash
docker compose up -d postgres redpanda
```

2. Create and activate a Python virtual environment on host:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

If your database volume already existed before Milestone 2, apply migration once:

```bash
docker exec -i wikimedia-postgres psql -U wikimedia -d wikimedia < sql/migrations/002_page_recent_activity.sql
docker exec -i wikimedia-postgres psql -U wikimedia -d wikimedia < sql/migrations/003_page_links.sql
```

3. Export environment for host mode:

```bash
set -a
source .env.host.example
export PYTHONPATH=$PWD
set +a
```

4. Run producer and consumer in separate terminals:

Terminal A:

```bash
source .venv/bin/activate
set -a; source .env.host.example; export PYTHONPATH=$PWD; set +a
python -m app.producer.main
```

Terminal B:

```bash
source .venv/bin/activate
set -a; source .env.host.example; export PYTHONPATH=$PWD; set +a
python -m app.consumer.main
```

5. Run Milestone 2 worker and API in separate terminals:

Terminal C:

```bash
source .venv/bin/activate
set -a; source .env.host.example; export PYTHONPATH=$PWD; set +a
python -m app.recent_activity.main
```

Terminal D:

```bash
source .venv/bin/activate
set -a; source .env.host.example; export PYTHONPATH=$PWD; set +a
python -m uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

6. Open Milestone 4 frontend:

```bash
xdg-open http://localhost:8000/
```

7. Verify data is flowing:

```bash
docker exec -it wikimedia-postgres psql -U wikimedia -d wikimedia -c "SELECT COUNT(*) FROM edit_events;"
docker exec -it wikimedia-postgres psql -U wikimedia -d wikimedia -c "SELECT p.title, s.total_edits, s.last_edit_time FROM page_stats s JOIN pages p ON p.id = s.page_id ORDER BY s.total_edits DESC LIMIT 10;"
docker exec -it wikimedia-postgres psql -U wikimedia -d wikimedia -c "SELECT COUNT(*) FROM page_recent_activity WHERE edits_last_hour > 0;"
```

8. Verify API exposure:

```bash
curl -s http://localhost:8000/api/health
curl -s http://localhost:8000/api/metrics
curl -s http://localhost:8000/api/observability
curl -s "http://localhost:8000/api/recent/pages?limit=10"
curl -s -X POST "http://localhost:8000/api/pages/France/links/refresh"
curl -s "http://localhost:8000/api/graph?page_title=France&refresh=true&limit=25"
```

The following shold both be zero whn checking for wrongly injested events

# Check for non-Wikipedia projects
```bash
docker exec -it wikimedia-postgres psql -U wikimedia -d wikimedia -c \
"SELECT raw_payload->>'wiki' AS wiki, COUNT(*) FROM edit_events 
 WHERE raw_payload->>'wiki' NOT LIKE '%wiki' 
 GROUP BY raw_payload->>'wiki';"
 ```

# Check for File/Image pages
```bash
docker exec -it wikimedia-postgres psql -U wikimedia -d wikimedia -c \
"SELECT COUNT(*) FROM pages WHERE title ILIKE 'File:%' OR title ILIKE 'Image:%';"
```

## Milestone 3 behavior

- `POST /api/pages/{title}/links/refresh`: fetches related links/redirects from Wikipedia API and stores rows in `page_links`.
- `GET /api/graph?page_title=...`: returns one-hop graph payload:
	- `center` node (with edit metrics and color hint)
	- `neighbors` list (linked pages with metrics)
	- `edges` list (`source_page_id`, `target_page_id`, `relation_type`)

Caching model:

- Each `page_links` row carries `freshness_expires_at`.
- Graph endpoint refreshes on demand with `refresh=true` or when cache is stale.

## Milestone 3 commands

Run these commands to use Milestone 3 directly.

1. Apply Milestone 3 migration (once for existing DB volume):

```bash
docker exec -i wikimedia-postgres psql -U wikimedia -d wikimedia < sql/migrations/003_page_links.sql
```

2. Force a link refresh for a Wikipedia page:

```bash
TITLE="Category:Taxa named by Harrison Gray Dyar Jr."
ENCODED_TITLE=$(python3 -c 'import urllib.parse,sys; print(urllib.parse.quote(sys.argv[1], safe=""))' "$TITLE")
curl -s -X POST "http://localhost:8000/api/pages/${ENCODED_TITLE}/links/refresh"
```

If this returns `{"detail":"Not Found"}`, restart the API process to load Milestone 3 routes:

```bash
pkill -f "uvicorn app.api.main:app" || true
source .venv/bin/activate
set -a; source .env.host.example; export PYTHONPATH=$PWD; set +a
python -m uvicorn app.api.main:app --host 0.0.0.0 --port 8000
```

3. Fetch one-hop graph (center + neighbors):

```bash
curl -s "http://localhost:8000/api/graph?page_title=${ENCODED_TITLE}&refresh=true&limit=25"
```

4. Recenter on an adjacent node (example):

```bash
curl -s "http://localhost:8000/api/graph?page_title=${ENCODED_TITLE}&refresh=false&limit=25"
```

5. Verify links are stored in database:

```bash
docker exec -it wikimedia-postgres psql -U wikimedia -d wikimedia -c "SELECT COUNT(*) FROM page_links;"
docker exec -it wikimedia-postgres psql -U wikimedia -d wikimedia -c "SELECT source_page_id, target_page_id, relation_type, freshness_expires_at FROM page_links ORDER BY discovered_at DESC LIMIT 10;"
```

## Milestone 4 behavior

- Visit `http://localhost:8000/` to open the graph explorer.
- Enter a page title and click **Load Graph** to render center + neighbors.
- Nodes are colored:
	- green: `has_recent_modifications = true`
	- red: `has_recent_modifications = false`
- Node size uses logarithmic scaling from `total_edits`.
- Click any neighbor node to re-center and fetch a new one-hop graph.

## Milestone 5 behavior

- `GET /api/observability` returns one aggregated payload for defense metrics.
- Includes stream activity:
	- total counts (`total_pages`, `total_edit_events`)
	- rates (`events_last_5m`, `events_per_second_last_5m`)
	- lag proxy (`latest_event_time`, `estimated_consumer_lag_seconds`, `lag_series_last_10m`)
- Includes dedup/consistency signal:
	- `total_counted_edits`
	- `dedup_consistency_gap` (expected `0`)
- Includes graph/link quality:
	- `total_links`, `stale_links`, `stale_link_ratio`
	- `adjacency_query_latency_ms`
- Includes API latency snapshots (`avg_ms`, `p50_ms`, `p95_ms`, `max_ms`) for key routes.

## Optional: full Docker app mode

If your Docker environment can access PyPI reliably:

```bash
cp .env.example .env
docker compose --profile app up --build
```

This starts optional app containers: `producer`, `consumer`, `recent-activity`, `api`.

## Idempotency and Correctness

The consumer enforces idempotent counting by:

1. Writing each incoming edit with unique event_id into edit_events.
2. If the insert conflicts, the message is treated as duplicate and does not increment counters.
3. If insert succeeds, page_stats.total_edits is incremented in the same transaction.

This makes at-least-once Kafka delivery effectively-once for counters.

## Notes

- The producer creates Kafka topic edits.raw if it does not exist.
- On restarts, consumer replay is safe due to unique event_id.
- Milestone 1 intentionally excludes recent-hour materialization, links, and graph API/frontend.

## Troubleshooting

### pip or DNS errors inside producer/consumer

Symptoms:

- `Temporary failure in name resolution`
- retries while downloading from `/simple/confluent-kafka/`

Preferred fix for this repository:

- Run app services on host (no Docker build needed for app code).
- Keep only Postgres and Redpanda inside Docker.

Recovery steps:

```bash
docker compose down
docker compose up -d postgres redpanda
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
set -a; source .env.host.example; export PYTHONPATH=$PWD; set +a
python -m app.consumer.main
```

If build still fails with DNS resolution during `pip install`, force host-network build:

```bash
docker compose down
docker build --network=host -t wikimedia-app:latest .
docker compose --profile app up -d --force-recreate
docker compose logs -f producer consumer
```

### SSE returns 403 Forbidden

Wikimedia SSE may reject clients that do not send a valid `User-Agent`.

This project now sends `SSE_USER_AGENT` by default. If you still see 403, set it explicitly:

```bash
export SSE_USER_AGENT="WikiMediaMilestone1/0.1 (course project)"
python -m app.producer.main
```
