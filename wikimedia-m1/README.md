# WikiMedia Milestone 1

This folder implements Milestone 1 from the course README:

- SSE ingest from Wikimedia recent changes
- Kafka topic edits.raw
- Consumer with idempotent processing
- PostgreSQL tables: pages, edit_events, page_stats

This folder now also implements Milestone 2:

- Last-hour activity read model (`page_recent_activity`)
- Periodic recomputation worker (every 60 seconds)
- API exposure for health, metrics, recent pages, and page activity

## Stack

- Python 3.11
- Redpanda (Kafka API)
- PostgreSQL 16
- Docker Compose

Default runtime mode in this repository:

- Docker for infrastructure only (`postgres` + `redpanda`)
- Host Python process for `producer` and `consumer`

## Project Layout

- docker-compose.yml: local runtime (infra by default, app containers optional)
- sql/init.sql: database schema for Milestone 1
- sql/migrations/002_page_recent_activity.sql: migration for Milestone 2 table
- app/producer/main.py: SSE -> Kafka producer
- app/consumer/main.py: Kafka -> PostgreSQL idempotent consumer
- app/recent_activity/main.py: rolling recomputation worker for last-hour activity
- app/api/main.py: FastAPI endpoints for milestone 2 exposure
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

6. Verify data is flowing:

```bash
docker exec -it wikimedia-postgres psql -U wikimedia -d wikimedia -c "SELECT COUNT(*) FROM edit_events;"
docker exec -it wikimedia-postgres psql -U wikimedia -d wikimedia -c "SELECT p.title, s.total_edits, s.last_edit_time FROM page_stats s JOIN pages p ON p.id = s.page_id ORDER BY s.total_edits DESC LIMIT 10;"
docker exec -it wikimedia-postgres psql -U wikimedia -d wikimedia -c "SELECT COUNT(*) FROM page_recent_activity WHERE edits_last_hour > 0;"
```

7. Verify API exposure:

```bash
curl -s http://localhost:8000/api/health
curl -s http://localhost:8000/api/metrics
curl -s "http://localhost:8000/api/recent/pages?limit=10"
```

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
