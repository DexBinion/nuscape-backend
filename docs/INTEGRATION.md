# NuScape – End‑to‑End Integration Guide

This document explains how the four pieces fit together and what each one must implement so “everything works properly”. It is written to be practical for day‑to‑day engineering across repos.

Components

1) NuScape UI (this repo)
   - Vite + React + TS + Tailwind at `http://localhost:5173` in dev
   - Reads env from `.env`
   - Calls the backend under `/api/v1/*`

2) NuScape Backend (currently on Replit)
   - REST API + persistence
   - Must expose the endpoints below and allow CORS or be used via the dev proxy

3) NuScape Agent (desktop)
   - Windows/macOS/Linux background service
   - Registers the device, periodically reports usage, enforces Controls

4) NuScape Mobile
   - Android/iOS app or service
   - Same registration + reporting contract as the Agent

-------------------------------------------------------------------------------

Quick Setup (Local UI + Replit backend)

- In `.env` (already set in this repo):
  - `VITE_DEMO=0`
  - `VITE_API_BASE=https://<your-replit-app>.replit.app`
  - `VITE_PROXY=1` (dev proxy avoids CORS tweaks on backend)
  - `VITE_API_TOKEN=` (if the backend requires Bearer auth)
- Run UI: `npm i && npm run dev` → http://localhost:5173
- Verify in DevTools → Network that UI calls `/api/...` and is proxied to the Replit URL.

-------------------------------------------------------------------------------

API Contract (v1)

Base path: `/api/v1`

Auth: Optional Bearer token

Headers (if token required):
```
Authorization: Bearer <token>
Content-Type: application/json
```

Endpoints used by UI

- `GET /api/v1/devices`
  - Returns `DeviceInfo[]`

- `GET /api/v1/usage?from=ISO&to=ISO&group_by=hour|day[&device_id=ID]`
  - Returns `UsageSeries`

- `GET /api/v1/apps/top?from=ISO&to=ISO&limit=5[&device_id=ID]`
  - Returns `{ items: TopAppItem[] }`

- `GET /api/v1/controls`
  - Returns `ControlsState`

- `POST /api/v1/controls`
  - Body: `ControlsState`
  - Returns updated `ControlsState`

- `POST /api/v1/controls/focus`
  - Body: `{ minutes: number }`
  - Returns updated `ControlsState`

Types (shared)

See `src/types.ts`. Key interfaces:

- `DeviceInfo { id, name, platform: 'windows'|'android'|'macos'|'ios'|'linux', lastSeen: ISO, status: 'active'|'idle'|'offline' }`
- `UsageSeries { from: ISO, to: ISO, points: UsagePoint[] }`
- `UsagePoint { ts: ISO, minutes: number, breakdown: Partial<Record<CategoryKey, number>> }`
- `TopAppItem { name, kind: 'app'|'site', category, minutes, icon?, brandSlug?, domain?, iconUrl? }`
- `ControlsState { rules: Rule[], focusMode?: { active: boolean; until?: ISO } }`
- `Rule { id, category, limitMinutesPerDay?, block?, schedule?: { start: 'HH:mm', end: 'HH:mm' }[] }`

-------------------------------------------------------------------------------

Desktop Agent + Mobile – Minimal Implementation

Registration

- POST on first run (or use a server‑side “upsert” behavior):
  - `POST /api/v1/devices/register`
  - Body: `{ id, name, platform, version, capabilities }`
  - Response: `{ ok: true }`
  - If you don’t want a register route, you can infer existence at first usage upload.

Heartbeat

- `PATCH /api/v1/devices/{id}/heartbeat` → 200
  - Body: `{ lastSeen: ISO, status: 'active'|'idle'|'offline' }`

Usage Reporting (batch)

- `POST /api/v1/usage/batch`
  - Body: `{ deviceId, from: ISO, to: ISO, points: UsagePoint[] }`
  - Server merges into per‑device series.

Top Apps Summary (optional push)

- `POST /api/v1/apps/top/batch`
  - Body: `{ deviceId, from: ISO, to: ISO, items: TopAppItem[] }`

Controls Fetch + Enforcement

- Agent/Mobile fetch every ~60s: `GET /api/v1/controls`
- Enforce `block` and `limitMinutesPerDay` on device.
- Honor temporary focus mode (`/api/v1/controls/focus`).

Notes

- Timezone: Send timestamps in UTC ISO; UI formats for local.
- Idempotency: Prefer “upsert” on server to avoid duplicate points.
- Security: Use device tokens or user token on the agents. Start simple: Bearer token.

-------------------------------------------------------------------------------

CORS & Proxy

- Option A (recommended in dev): enable the Vite dev proxy (`VITE_PROXY=1`). No backend CORS changes needed.
- Option B: Enable CORS on backend:
  - `Access-Control-Allow-Origin: http://localhost:5173`
  - `Access-Control-Allow-Headers: Content-Type, Authorization`
  - `Access-Control-Allow-Methods: GET, POST, PATCH, OPTIONS`

-------------------------------------------------------------------------------

Testing the API quickly (curl)

```
BASE="https://<your-replit-app>.replit.app"
HDR=(-H "Content-Type: application/json")
TOK="" # set if needed: -H "Authorization: Bearer $TOKEN"

curl -s $BASE/api/v1/devices
curl -s "$BASE/api/v1/usage?from=$(date -u -d '-24 hour' +%FT%TZ)&to=$(date -u +%FT%TZ)&group_by=hour"
curl -s "$BASE/api/v1/apps/top?from=$(date -u -d '-24 hour' +%FT%TZ)&to=$(date -u +%FT%TZ)&limit=5"
```

-------------------------------------------------------------------------------

Operational Checklist

- [ ] UI `.env` has `VITE_DEMO=0`, backend URL, and `VITE_PROXY=1`
- [ ] Backend endpoints above return expected shapes (`src/types.ts`)
- [ ] Agent/Mobile send usage batches and heartbeat
- [ ] Controls can be fetched + updated; focus POST works
- [ ] Icons: provide `iconUrl`/`brandSlug`/`domain` where possible

-------------------------------------------------------------------------------

Next Steps – If you want to move off Replit

1) Containerize backend (Dockerfile) or deploy to Render/Railway/Fly
2) Point `VITE_API_BASE` at the new URL (keep proxy on)
3) Optional staging env: `.env.staging` + separate DB

