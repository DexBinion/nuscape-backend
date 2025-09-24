import redis
import json
import logging
import time
from typing import Dict, Any, Optional
from backend.settings import settings
from backend.metrics import metrics

logger = logging.getLogger(__name__)

class RedisClient:
    def __init__(self):
        self.client = None
        self.is_redis_available = False
        self.connect()
    
    def connect(self):
        """Connect to Redis with retry logic"""
        try:
            self.client = redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
                retry_on_timeout=True
            )
            # Test connection
            self.client.ping()
            self.is_redis_available = True
            logger.info("Connected to Redis successfully")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {e}")
            self.is_redis_available = False
            
            if settings.require_redis:
                # In production mode, don't use MockRedis - fail hard
                logger.error("REQUIRE_REDIS is enabled - refusing to use MockRedis fallback")
                self.client = None
            else:
                # For development, use a mock Redis if connection fails
                self.client = MockRedis()
                logger.warning("Using MockRedis fallback for development")
            
            metrics.increment("redis_connection_errors")
    
    def enqueue_events(
        self, 
        account_id: str, 
        device_id: str, 
        events_data: Dict[str, Any]
    ) -> bool:
        """Enqueue events batch into Redis Streams"""
        # Critical: Don't enqueue if Redis is not available and required
        if not self.is_redis_available:
            if settings.require_redis:
                logger.error("Redis unavailable and REQUIRE_REDIS=true - rejecting events")
                metrics.increment("queue_enqueue_errors")
                return False
            else:
                logger.warning("Redis unavailable but REQUIRE_REDIS=false - using MockRedis")
        
        # Don't attempt to enqueue if client is None (hard Redis failure)
        if self.client is None:
            logger.error("Redis client is None - cannot enqueue events")
            metrics.increment("queue_enqueue_errors")
            return False
            
        try:
            payload = {
                "account_id": account_id,
                "device_id": device_id,
                "events_json": json.dumps(events_data["events"]),
                "sequence_start": events_data.get("sequence_start", 0),
                "client_version": events_data.get("client_version", "unknown"),
                "ts": int(time.time() * 1000)
            }
            
            # Add to stream with maxlen to prevent unbounded growth
            message_id = self.client.xadd(
                settings.queue_stream_name,
                payload,
                maxlen=settings.queue_maxlen,
                approximate=True
            )
            
            # Only increment success metrics for real Redis, not MockRedis
            if self.is_redis_available:
                metrics.increment("queue_enqueue_total")
                logger.info(f"Enqueued batch for device {device_id}: {message_id}")
            else:
                logger.warning(f"MockRedis received batch for device {device_id}: {message_id} (NOT PERSISTENT)")
                
            return True
            
        except Exception as e:
            logger.error(f"Failed to enqueue events: {e}")
            metrics.increment("queue_enqueue_errors")
            return False
    
    def is_available(self) -> bool:
        """Check if Redis is truly available for durable storage"""
        return self.is_redis_available and self.client is not None and not isinstance(self.client, MockRedis)
    
    def get_connection_status(self) -> Dict[str, Any]:
        """Get detailed connection status for health checks"""
        return {
            "connected": self.is_redis_available,
            "client_type": "redis" if self.is_redis_available else ("mock" if self.client else "none"),
            "require_redis": settings.require_redis,
            "available_for_storage": self.is_available()
        }
    
    def get_queue_info(self) -> Dict[str, Any]:
        """Get queue status information"""
        if self.client is None:
            return {"length": 0, "groups": 0, "last_generated_id": "0-0", "error": "redis_unavailable"}
            
        try:
            info = self.client.xinfo_stream(settings.queue_stream_name)
            result = {
                "length": info.get("length", 0),
                "groups": info.get("groups", 0),
                "last_generated_id": info.get("last-generated-id", "0-0")
            }
            
            # Add warning if using MockRedis
            if not self.is_redis_available:
                result["warning"] = "using_mock_redis"
                
            return result
        except Exception as e:
            logger.error(f"Failed to get queue info: {e}")
            return {"length": 0, "groups": 0, "last_generated_id": "0-0", "error": str(e)}

class MockRedis:
    """Mock Redis for development when Redis is unavailable"""
    
    def __init__(self):
        self.data = []
        logger.warning("Using MockRedis - events will not be processed!")
    
    def ping(self):
        return True
    
    def xadd(self, stream, fields, maxlen=None, approximate=None):
        self.data.append({"stream": stream, "fields": fields})
        return f"mock-{len(self.data)}-0"
    
    def xinfo_stream(self, stream):
        return {"length": len(self.data), "groups": 0, "last-generated-id": "mock-0-0"}

# Global Redis client
redis_client = RedisClient()