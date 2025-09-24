# NuScape MVP Architecture

## Overview

NuScape is transformed from a direct-to-database usage tracker into a buffered, scalable system using Redis Streams for event queuing and PostgreSQL rollup tables for fast dashboard queries.

## Architecture

```
Clients (Windows/Android/iOS/Mac)
  └─ SQLite queue → batched uploads (idempotent, backoff)
      └─ HTTPS (JWT) → Ingest API (stateless, thin)
          └─ Queue = Redis Streams (Upstash/managed)
              └─ Processor (FastAPI worker / Python)
                  ├─ Validate + dedupe(event_id)
                  ├─ Write 1m/5m/60m rollups → Postgres
                  └─ DLQ (bad payloads)

Control Plane: Postgres (tenants/devices/policies)
Dashboards: read rollups only
Observability: metrics counters + structured logs
Retention: TTL on rollups; simple erasure job by device
```

## Key Components

### 1. Ingest API
- **Purpose**: Thin validation layer that enqueues events into Redis Streams
- **Endpoint**: `POST /api/v1/events/batch`
- **Response Time**: <100ms p95 under 50 RPS
- **Functionality**: JWT validation → Redis XADD → ACK response

### 2. Redis Streams Queue
- **Stream**: `nuscape:events` (main queue)
- **DLQ**: `nuscape:dlq` (dead letter queue)
- **Consumer Group**: `proc-1`
- **Retention**: 1M entries (approximate)

### 3. Event Processor
- **File**: `processor/worker.py`
- **Function**: Consumes stream, deduplicates, writes rollups
- **Deduplication**: Per-device LRU cache with 48h TTL
- **Error Handling**: Bad payloads → DLQ with reason

### 4. Rollup Tables
- **Tables**: `usage_1m`, `usage_5m`, `usage_60m`
- **Schema**: (account_id, device_id, bucket_start, kind, key) → aggregated metrics
- **Retention**: 13 months via TTL job
- **Performance**: Indexed for fast dashboard queries

### 5. Dashboard
- **Data Source**: Rollup tables only (no raw GROUP BY)
- **Queries**: Aggregated time-series data
- **Features**: Top apps, usage trends, device status

## Data Flow

1. **Client**: Local SQLite queue → batch when 50 events or 60s
2. **Ingest**: Validate JWT → XADD to Redis → return ACK
3. **Processor**: XREAD from Redis → dedupe → upsert rollups → ACK
4. **Dashboard**: Query rollups for fast aggregated views

## Scalability

- **Horizontal**: Multiple processor workers
- **Vertical**: Redis Streams handle high throughput
- **Storage**: Rollups keep dashboard queries fast
- **Future**: Upgrade to ClickHouse/Parquet for data lake

## Observability

- **Metrics**: `/metrics-lite` endpoint with counters
- **Logging**: Structured logs with context
- **Health**: `/healthz` endpoint
- **Monitoring**: Queue lag, error rates, throughput