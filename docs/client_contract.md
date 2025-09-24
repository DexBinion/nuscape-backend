# NuScape Client Contract

## Overview

All client platforms (Windows, Android, iOS, Mac) must implement the same upload contract for consistency and reliability.

## Client Requirements

### 1. Local SQLite Queue

**Schema:**
```sql
CREATE TABLE events_queue (
  device_id TEXT NOT NULL,
  event_id TEXT PRIMARY KEY,
  ts INTEGER NOT NULL,
  kind TEXT NOT NULL,
  key TEXT NOT NULL,
  secs REAL NOT NULL,
  extras TEXT,
  uploaded INTEGER DEFAULT 0,
  seq INTEGER
);
```

### 2. Flush Triggers

Batch upload when ANY condition is met:
- **Count**: ≥50 events queued
- **Time**: Oldest unuploaded event ≥60 seconds
- **Background**: App goes to background

### 3. Payload Constraints

- **Max size**: 250KB per batch
- **Split strategy**: If batch >250KB, split into multiple requests
- **Event limit**: Reasonable batch sizes (typically 50-200 events)

## API Contract

### Endpoint

```
POST /api/v1/events/batch
Authorization: Bearer <device_jwt>
Content-Type: application/json
```

### Request Format

```json
{
  "device_id": "uuid",
  "sequence_start": 1201,
  "events": [
    {
      "event_id": "uuid-v4",
      "ts": 1736723456789,
      "kind": "app|url|screen",
      "key": "com.tiktok.app|youtube.com|LOCK_SCREEN",
      "secs": 37.5,
      "extras": {
        "title": "Video Title",
        "package": "com.google.android.youtube"
      }
    }
  ],
  "client_version": "android-1.0.0"
}
```

### Response Format

**Success (200):**
```json
{
  "acknowledged_ids": ["uuid-v4", "..."],
  "backoff_seconds": 0
}
```

### Event Schema

```json
{
  "event_id": "uuid-v4",           // Stable UUID for idempotency
  "ts": 1736723456789,             // Unix timestamp (milliseconds)
  "kind": "app|url|screen",        // Event type
  "key": "identifier",             // App package, domain, or screen state
  "secs": 0.0,                     // Duration in seconds
  "extras": {}                     // Platform-specific metadata
}
```

## Error Handling

### HTTP Status Codes

- **401 Unauthorized**: Client pauses uploads, re-authenticate
- **413 Payload Too Large**: Client halves batch size on next flush
- **429 Too Many Requests**: Client respects `backoff_seconds` (default 30s)
- **5xx Server Error**: Client exponential backoff + jitter (1s→60s)

### Retry Logic

```python
def backoff_strategy(attempt):
    if attempt <= 5:
        return min(60, (2 ** attempt) + random.uniform(0, 1))
    return 60 + random.uniform(0, 30)
```

### Idempotency

- **Event IDs**: Must be stable UUIDs
- **Upload tracking**: Only mark uploaded after receiving ACK
- **Replay safety**: Same batch uploaded twice = no data duplication

## Platform-Specific Notes

### Android
- **Data Source**: `UsageStatsManager` for foreground durations
- **Service**: `ForegroundService` with persistent notification
- **Permissions**: `PACKAGE_USAGE_STATS`, `RECEIVE_BOOT_COMPLETED`
- **Boot**: Auto-start via `BootReceiver`

### Windows/macOS
- **Data Source**: Active window tracking
- **Storage**: SQLite in user data directory
- **HTTP**: `reqwest` or platform HTTP client
- **Background**: System service/daemon

### iOS
- **Data Source**: Available app time APIs (without entitlements)
- **Storage**: SQLite in app sandbox
- **Background**: Background app refresh when permitted
- **Constraints**: Limited by iOS background execution

## Implementation Checklist

- [ ] SQLite queue with proper schema
- [ ] Batch flush logic (count/time/background triggers)
- [ ] HTTP client with retry/backoff
- [ ] JWT authentication handling
- [ ] Idempotency via stable event IDs
- [ ] Payload size validation and splitting
- [ ] Error handling for all HTTP status codes
- [ ] Background service for continuous tracking
- [ ] Boot/startup registration
- [ ] Local logging for debugging

## Testing

1. **Batch size**: Verify 50+ events trigger upload
2. **Timeout**: Verify 60s triggers upload
3. **Background**: Verify app backgrounding triggers upload
4. **Idempotency**: Upload same batch twice, verify no duplication
5. **Backoff**: Test 429 response handling
6. **Error recovery**: Test offline→online scenarios
7. **Large batches**: Test >250KB payload splitting