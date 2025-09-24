#!/usr/bin/env python3
"""
NuScape Event Processor Worker
Consumes events from Redis Streams, deduplicates, and writes to rollup tables
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from collections import defaultdict
import redis
import asyncpg
from backend.settings import settings
from backend.metrics import metrics

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class EventProcessor:
    def __init__(self):
        self.redis_client = None
        self.postgres_pool = None
        self.consumer_name = f"processor-{int(time.time())}"
        self.dedupe_cache = {}  # Simple in-memory cache for MVP
        self.running = True
        # Track last time we ran session-to-rollup aggregation (epoch ms)
        self._last_session_agg_run = 0
    async def connect(self):
        """Connect to Redis and PostgreSQL"""
        try:
            # Redis connection
            self.redis_client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                retry_on_timeout=True
            )
            self.redis_client.ping()
            logger.info("Connected to Redis successfully")
            
            # Create consumer group if it doesn't exist
            try:
                self.redis_client.xgroup_create(
                    settings.queue_stream_name,
                    settings.queue_consumer_group,
                    id='0',
                    mkstream=True
                )
                logger.info(f"Created consumer group: {settings.queue_consumer_group}")
            except redis.RedisError as e:
                if "BUSYGROUP" not in str(e):
                    logger.error(f"Failed to create consumer group: {e}")
                
            # PostgreSQL connection pool
            # asyncpg expects a scheme of "postgresql" or "postgres" — strip SQLAlchemy-style
            # "postgresql+asyncpg" if present and respect sslmode query param.
            from urllib.parse import urlparse, urlunparse, parse_qs

            _raw = settings.database_url
            _parsed = urlparse(_raw)
            _query = parse_qs(_parsed.query or "")
            _use_ssl = False
            if "sslmode" in _query:
                sslmode_val = _query.get("sslmode", [""])[0].lower()
                if sslmode_val and sslmode_val != "disable":
                    _use_ssl = True

            _scheme = _parsed.scheme
            # Convert SQLAlchemy-style scheme to plain postgres scheme accepted by asyncpg
            if "+asyncpg" in _scheme:
                _scheme = _scheme.replace("+asyncpg", "")

            _clean_parsed = _parsed._replace(scheme=_scheme, query="")
            dsn = urlunparse(_clean_parsed)

            # Pass ssl=True when required (asyncpg accepts ssl argument)
            ssl_arg = True if _use_ssl else None

            self.postgres_pool = await asyncpg.create_pool(
                dsn,
                min_size=2,
                max_size=10,
                command_timeout=60,
                ssl=ssl_arg
            )
            logger.info("Connected to PostgreSQL successfully")
            
        except Exception as e:
            logger.error(f"Failed to connect: {e}")
            raise
    
    async def ensure_rollup_tables(self):
        """Create rollup tables if they don't exist"""
        rollup_ddl = """
        CREATE TABLE IF NOT EXISTS usage_1m (
            account_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            bucket_start TIMESTAMPTZ NOT NULL,
            kind TEXT NOT NULL,
            key TEXT NOT NULL,
            secs_sum DOUBLE PRECISION DEFAULT 0,
            events_count INTEGER DEFAULT 0,
            last_ts TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (account_id, device_id, bucket_start, kind, key)
        );
        
        CREATE INDEX IF NOT EXISTS idx_usage_1m_lookup
        ON usage_1m (account_id, device_id, bucket_start DESC);
        
        CREATE TABLE IF NOT EXISTS usage_5m (
            account_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            bucket_start TIMESTAMPTZ NOT NULL,
            kind TEXT NOT NULL,
            key TEXT NOT NULL,
            secs_sum DOUBLE PRECISION DEFAULT 0,
            events_count INTEGER DEFAULT 0,
            last_ts TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (account_id, device_id, bucket_start, kind, key)
        );
        
        CREATE INDEX IF NOT EXISTS idx_usage_5m_lookup
        ON usage_5m (account_id, device_id, bucket_start DESC);
        
        CREATE TABLE IF NOT EXISTS usage_60m (
            account_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            bucket_start TIMESTAMPTZ NOT NULL,
            kind TEXT NOT NULL,
            key TEXT NOT NULL,
            secs_sum DOUBLE PRECISION DEFAULT 0,
            events_count INTEGER DEFAULT 0,
            last_ts TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT NOW(),
            PRIMARY KEY (account_id, device_id, bucket_start, kind, key)
        );
        
        CREATE INDEX IF NOT EXISTS idx_usage_60m_lookup
        ON usage_60m (account_id, device_id, bucket_start DESC);
        """
        
        async with self.postgres_pool.acquire() as conn:
            await conn.execute(rollup_ddl)
        logger.info("Rollup tables ensured")
    
    def is_duplicate(self, device_id: str, event_id: str) -> bool:
        """Check if event is a duplicate using durable Redis SET with TTL"""
        dedupe_key = f"dedupe:{device_id}"
        
        try:
            # Try to add event_id to Redis SET
            # Returns 1 if new, 0 if already exists
            added = self.redis_client.sadd(dedupe_key, event_id)
            
            if added == 1:
                # New event - set/refresh TTL to 48 hours
                self.redis_client.expire(dedupe_key, 48 * 3600)
                return False  # Not a duplicate
            else:
                # Event already exists in set
                return True  # Is a duplicate
                
        except redis.RedisError as e:
            logger.warning(f"Redis dedup check failed for {device_id}:{event_id}: {e}")
            # Fallback to in-memory cache if Redis fails
            cache_key = f"{device_id}:{event_id}"
            
            if cache_key in self.dedupe_cache:
                return True
            
            # Mark as seen in fallback cache
            self.dedupe_cache[cache_key] = time.time()
            return False
    
    def bucket_timestamp(self, ts_ms: int, bucket_minutes: int) -> datetime:
        """Round timestamp down to bucket boundary"""
        dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        # Round down to bucket boundary
        minute = (dt.minute // bucket_minutes) * bucket_minutes
        return dt.replace(minute=minute, second=0, microsecond=0)
    
    async def write_to_rollups(self, account_id: str, device_id: str, events: List[Dict[str, Any]]):
        """Write events to rollup tables"""
        if not events:
            return
        
        # Group events by bucket and key for efficiency
        rollup_data = {
            1: defaultdict(lambda: {"secs": 0, "count": 0, "last_ts": None}),
            5: defaultdict(lambda: {"secs": 0, "count": 0, "last_ts": None}),
            60: defaultdict(lambda: {"secs": 0, "count": 0, "last_ts": None})
        }
        
        for event in events:
            ts_ms = event.get("ts", int(time.time() * 1000))
            event_dt = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
            kind = event.get("kind", "unknown")
            key = event.get("key", "unknown")
            secs = float(event.get("secs", 0))
            
            # Process for each bucket size
            for bucket_minutes in [1, 5, 60]:
                bucket_start = self.bucket_timestamp(ts_ms, bucket_minutes)
                rollup_key = (bucket_start, kind, key)
                
                rollup_data[bucket_minutes][rollup_key]["secs"] += secs
                rollup_data[bucket_minutes][rollup_key]["count"] += 1
                rollup_data[bucket_minutes][rollup_key]["last_ts"] = max(
                    rollup_data[bucket_minutes][rollup_key]["last_ts"] or event_dt,
                    event_dt
                )
        
        # Write to database
        async with self.postgres_pool.acquire() as conn:
            async with conn.transaction():
                # Write to each rollup table
                for bucket_minutes, table_suffix in [(1, "1m"), (5, "5m"), (60, "60m")]:
                    if not rollup_data[bucket_minutes]:
                        continue
                    
                    upsert_query = f"""
                    INSERT INTO usage_{table_suffix}
                    (account_id, device_id, bucket_start, kind, key, secs_sum, events_count, last_ts)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                    ON CONFLICT (account_id, device_id, bucket_start, kind, key)
                    DO UPDATE SET
                        secs_sum = usage_{table_suffix}.secs_sum + EXCLUDED.secs_sum,
                        events_count = usage_{table_suffix}.events_count + EXCLUDED.events_count,
                        last_ts = GREATEST(usage_{table_suffix}.last_ts, EXCLUDED.last_ts)
                    """
                    
                    for (bucket_start, kind, key), data in rollup_data[bucket_minutes].items():
                        await conn.execute(
                            upsert_query,
                            account_id, device_id, bucket_start, kind, key,
                            data["secs"], data["count"], data["last_ts"]
                        )
        
        logger.info(f"Wrote {len(events)} events to rollups for device {device_id}")
        metrics.increment("processor_events_total", len(events))

    async def aggregate_sessions_once(self):
        """Aggregate recent app_sessions rows into minute/5m/60m rollup tables.

        This method queries app_sessions created since the last run and upserts
        aggregated seconds into usage_1m/5m/60m using kind='app_session' and key=package.
        """
        if not self.postgres_pool or not self.redis_client:
            logger.warning("Cannot aggregate sessions: missing postgres pool or redis client")
            return

        # Get last run (epoch ms) from Redis; default to 0 to process all rows once
        last_key = "processor:last_session_agg"
        try:
            last_ms_raw = self.redis_client.get(last_key)
            last_ms = int(last_ms_raw) if last_ms_raw else 0
        except Exception:
            last_ms = 0

        now_ms = int(time.time() * 1000)
        if last_ms >= now_ms:
            return  # nothing to do

        # Query app_sessions created in (last_ms, now_ms]
        sql = """
        SELECT id, device_id, package, start_ts, end_ts, duration_ms, engaged_ms, interaction_count, created_at
        FROM app_sessions
        WHERE created_at > to_timestamp($1) AND created_at <= to_timestamp($2)
        """
        # convert ms to seconds
        last_s = last_ms / 1000.0
        now_s = now_ms / 1000.0

        async with self.postgres_pool.acquire() as conn:
            rows = await conn.fetch(sql, last_s, now_s)

            if not rows:
                # Update last run even if empty to avoid repeated scans
                try:
                    self.redis_client.set(last_key, str(now_ms), ex=60 * 60 * 24 * 7)
                except Exception:
                    pass
                logger.debug("No new app_sessions to aggregate")
                return

            # Build synthetic 'events' for rollup writer: kind='app_session', key=package
            synthetic_events = []
            for r in rows:
                # Prefer start_ts for bucketing; fallback to created_at
                ts_dt = r["start_ts"] or r["created_at"]
                if not ts_dt:
                    continue
                ts_ms = int(ts_dt.timestamp() * 1000)
                secs = float((r["duration_ms"] or 0) / 1000.0)
                synthetic_events.append({
                    "ts": ts_ms,
                    "kind": "app_session",
                    "key": r["package"] or "unknown",
                    "secs": secs
                })

            # Use write_to_rollups to upsert aggregated seconds into usage_* tables
            # Group by device_id; write_to_rollups expects a device_id and events list
            by_device = defaultdict(list)
            for r, se in zip(rows, synthetic_events):
                by_device[r["device_id"]].append(se)

            for device_id, events_list in by_device.items():
                try:
                    await self.write_to_rollups("default", device_id, events_list)
                except Exception as e:
                    logger.error(f"Failed to upsert rollups for device {device_id}: {e}")

        # Persist last run timestamp in Redis
        try:
            self.redis_client.set(last_key, str(now_ms), ex=60 * 60 * 24 * 7)
        except Exception:
            pass

        logger.info(f"Aggregated {len(rows)} app_sessions into rollups (window {last_ms} -> {now_ms})")
    
    async def process_message(self, message_id: str, fields: Dict[str, Any]):
        """Process a single message from the stream"""
        try:
            account_id = fields.get("account_id", "default")
            device_id = fields.get("device_id")
            events_json = fields.get("events_json")
            client_version = fields.get("client_version", "unknown")
            
            if not device_id or not events_json:
                logger.warning(f"Invalid message {message_id}: missing device_id or events_json")
                metrics.increment("processor_dlq_total", labels={"reason": "invalid_format"})
                return False
            
            # Parse events
            try:
                events = json.loads(events_json)
            except json.JSONDecodeError as e:
                logger.warning(f"Invalid JSON in message {message_id}: {e}")
                metrics.increment("processor_dlq_total", labels={"reason": "invalid_json"})
                return False
            
            # Deduplicate events
            valid_events = []
            dupes_dropped = 0
            
            for event in events:
                event_id = event.get("event_id")
                if not event_id:
                    continue  # Skip events without IDs
                
                if self.is_duplicate(device_id, event_id):
                    dupes_dropped += 1
                    continue
                
                valid_events.append(event)
            
            metrics.increment("processor_dupes_dropped_total", dupes_dropped)
            
            # Write to rollups
            if valid_events:
                await self.write_to_rollups(account_id, device_id, valid_events)
            
            logger.info(f"Processed message {message_id}: {len(valid_events)} events, {dupes_dropped} dupes dropped")
            return True
            
        except Exception as e:
            logger.error(f"Error processing message {message_id}: {e}")
            metrics.increment("processor_dlq_total", labels={"reason": "processing_error"})
            return False
    
    async def run(self):
        """Main processing loop"""
        await self.connect()
        await self.ensure_rollup_tables()
        
        logger.info(f"Starting processor with consumer: {self.consumer_name}")
        
        while self.running:
            try:
                # Read messages from stream
                messages = self.redis_client.xreadgroup(
                    settings.queue_consumer_group,
                    self.consumer_name,
                    {settings.queue_stream_name: '>'},
                    count=10,
                    block=1000  # 1 second timeout
                )
                
                if not messages:
                    # Periodically aggregate app_sessions even when no stream messages
                    now = time.time()
                    if now - (self._last_session_agg_run / 1000.0 if self._last_session_agg_run else 0) > 15:
                        try:
                            await self.aggregate_sessions_once()
                        except Exception as e:
                            logger.warning(f"Session aggregation failed in idle loop: {e}")
                        self._last_session_agg_run = int(now * 1000)
                    continue
                
                # Process messages
                for stream_name, stream_messages in messages:
                    for message_id, fields in stream_messages:
                        start_time = time.time()
                        
                        try:
                            success = await self.process_message(message_id, fields)
                            
                            if success:
                                # ACK the message
                                self.redis_client.xack(
                                    settings.queue_stream_name,
                                    settings.queue_consumer_group,
                                    message_id
                                )
                                
                                # Record processing latency
                                latency_ms = (time.time() - start_time) * 1000
                                metrics.record_histogram("rollup_latency_ms", latency_ms)
                            else:
                                # Message failed processing, will be retried
                                logger.warning(f"Failed to process message {message_id}")
                                
                        except Exception as e:
                            logger.error(f"Error processing message {message_id}: {e}")
                            metrics.increment("processor_dlq_total", labels={"reason": "exception"})
                
                # After processing a batch of stream messages, periodically run session aggregation
                now = time.time()
                if now - (self._last_session_agg_run / 1000.0 if self._last_session_agg_run else 0) > 15:
                    try:
                        await self.aggregate_sessions_once()
                    except Exception as e:
                        logger.warning(f"Session aggregation failed after processing messages: {e}")
                    self._last_session_agg_run = int(now * 1000)
                
            except Exception as e:
                logger.error(f"Error in processing loop: {e}")
                await asyncio.sleep(5)  # Brief pause on error
    
    async def shutdown(self):
        """Graceful shutdown"""
        logger.info("Shutting down processor...")
        self.running = False
        if self.postgres_pool:
            await self.postgres_pool.close()
        if self.redis_client:
            self.redis_client.close()

async def main():
    """Main entry point"""
    processor = EventProcessor()
    
    try:
        await processor.run()
    except KeyboardInterrupt:
        logger.info("Received shutdown signal")
    finally:
        await processor.shutdown()

if __name__ == "__main__":
    asyncio.run(main())