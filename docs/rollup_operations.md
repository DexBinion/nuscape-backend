# Rollup Operations Guide

## Environment setup
- Define `ROLLUP_CRON_KEY` in `.env` (already scaffolded) or via deployment secrets.
- Restart API after changing secrets so FastAPI picks up the key.

## Running rollups manually
1. Via CLI:
   ```bash
   uv run python tools/run_rollups.py --date 2025-09-27 --account default
   ```
   Omitting `--date` processes yesterday by default. Adjust `--gap` (seconds) as needed.
2. Via API:
   ```bash
   curl -X POST \
     -H "X-Cron-Key: $ROLLUP_CRON_KEY" \
     'https://your-host/api/v1/usage/rollups/run?date=2025-09-27&account_id=default'
   ```

## Scheduling (cron / workers)
- Configure your scheduler to run every 15 minutes or nightly, calling the endpoint above.
- Retry with exponential backoff if HTTP 503 is returned (Redis/DB maintenance).

## Backfilling historical data
- Loop over the desired day range and call the CLI or API for each date.
- For large windows, throttle requests (sleep ~2s) to limit DB load.

## Dashboards
- `usage_daily_totals` now powers attention summaries (`backend/routes_usage_summary.py`).
- Detailed per-device/app sessions live in `device_sessions_daily`; individual rows retain `fragment_count` for debugging.

## Validation checklist
- After a run, inspect the latest totals:
  ```sql
  SELECT session_date, total_attention_sec
    FROM usage_daily_totals
   WHERE account_id = 'default'
   ORDER BY session_date DESC
   LIMIT 7;
  ```
- For mismatch, re-run the affected day with a narrower `--gap` or inspect raw `usage_logs` slices.
