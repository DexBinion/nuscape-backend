import type { ControlsState, DeviceInfo, UsageSeries, TopAppItem } from '@/types'

const USE_PROXY = (import.meta.env.VITE_PROXY ?? '0') === '1'
const API_BASE = USE_PROXY ? '' : (import.meta.env.VITE_API_BASE || 'http://localhost:8000')
const API_TOKEN = import.meta.env.VITE_API_TOKEN
const DEMO = (import.meta.env.VITE_DEMO ?? '0') === '1'

let LAST_SOURCE: 'live' | 'mock' = DEMO ? 'mock' : 'live'
export const getApiSource = () => LAST_SOURCE

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  if (DEMO) return mock<T>(path)

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(init.headers as Record<string, string>),
  }
  if (API_TOKEN) headers['Authorization'] = `Bearer ${API_TOKEN}`

  try {
    const res = await fetch(`${API_BASE}${path}`, { ...init, headers })
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    LAST_SOURCE = 'live'
    return (await res.json()) as T
  } catch (e) {
    console.warn('API failed, using mock data for', path, e)
    LAST_SOURCE = 'mock'
    return mock<T>(path)
  }
}

export const Api = {
  getUsage: (
    from: string,
    to: string,
    groupBy: 'hour' | 'day' = 'hour',
    deviceId?: string
  ) => api<UsageSeries>(`/api/v1/dashboard/usage?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&group_by=${groupBy}${deviceId ? `&device_id=${encodeURIComponent(deviceId)}` : ''}`),

  getDevices: () => api<DeviceInfo[]>(`/api/v1/dashboard/devices`),

  getControls: () => api<ControlsState>(`/api/v1/controls`),

  saveControls: (payload: ControlsState) =>
    api<ControlsState>(`/api/v1/controls`, {
      method: 'POST',
      body: JSON.stringify(payload),
    }),

  focus: (minutes: number) =>
    api<ControlsState>(`/api/v1/controls/focus`, {
      method: 'POST',
      body: JSON.stringify({ minutes }),
    }),

  getTopApps: (from: string, to: string, limit = 5, deviceId?: string) =>
    api<{ items: TopAppItem[] }>(`/api/v1/dashboard/apps/top?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&limit=${limit}${deviceId ? `&device_id=${encodeURIComponent(deviceId)}` : ''}`),
}

// -----------------------------
// Mock / Demo layer (deterministic & realistic)
// -----------------------------
function seededRand(seed: number) {
  let s = seed >>> 0
  return () => (s = (s * 1664525 + 1013904223) >>> 0) / 2 ** 32
}

function mock<T>(path: string): T {
  // Support parsing query for group_by, limit, device context
  const url = new URL('http://x' + path)
  const group = url.searchParams.get('group_by') || 'hour'
  const limit = Number(url.searchParams.get('limit') || 5)
  const deviceId = url.searchParams.get('device_id') || undefined

  const now = Date.now()
  const hourSeed = Math.floor(now / 3_600_000)
  const daySeed = Math.floor(now / 86_400_000)
  const rand = seededRand((group === 'day' ? daySeed : hourSeed) + (deviceId ? deviceId.length * 7 : 0))

  if (path.startsWith('/api/v1/devices')) {
    const d: DeviceInfo[] = [
      { id: 'pc-1', name: 'Dexter Windows', platform: 'windows', lastSeen: new Date(now - 60_000).toISOString(), status: 'active' },
      { id: 'and-1', name: 'Dexter Android', platform: 'android', lastSeen: new Date(now - 2 * 60_000).toISOString(), status: 'idle' },
      { id: 'pc-2', name: 'Work Windows PC', platform: 'windows', lastSeen: new Date(now - 5 * 60_000).toISOString(), status: 'active' },
      { id: 'ipad-1', name: 'Dexter iPad', platform: 'ios', lastSeen: new Date(now - 10 * 60_000).toISOString(), status: 'idle' },
    ]
    return d as T
  }

  if (path.startsWith('/api/v1/apps/top')) {
    const catalog: Array<Omit<TopAppItem, 'total_seconds' | 'wifi_bytes' | 'cell_bytes' | 'breakdown'>> = [
      { app_id: 'youtube', display_name: 'YouTube', category: 'video', icon_url: null, icon_b64: null, primary_namespace: 'web', primary_identifier: 'youtube.com' },
      { app_id: 'google-chrome', display_name: 'Chrome', category: 'productivity', icon_url: '/brand/chrome.svg', icon_b64: null, primary_namespace: 'windows', primary_identifier: 'chrome.exe' },
      { app_id: 'instagram', display_name: 'Instagram', category: 'social', icon_url: null, icon_b64: null, primary_namespace: 'android', primary_identifier: 'com.instagram.android' },
      { app_id: 'steam', display_name: 'Steam', category: 'gaming', icon_url: '/brand/steam.svg', icon_b64: null, primary_namespace: 'windows', primary_identifier: 'steam.exe' },
      { app_id: 'paylocity', display_name: 'Paylocity', category: 'productivity', icon_url: null, icon_b64: null, primary_namespace: 'web', primary_identifier: 'paylocity.com' },
    ]
    let remaining = 120 + Math.round(rand() * 150)
    const items: TopAppItem[] = []
    for (const base of catalog) {
      const takeMinutes = Math.max(8, Math.round(rand() * Math.min(remaining, 70)))
      remaining -= takeMinutes
      const totalSeconds = takeMinutes * 60
      const webShare = base.primary_namespace === 'web' ? Math.round(totalSeconds * 0.5) : Math.round(totalSeconds * 0.05)
      const androidShare = base.primary_namespace === 'android' ? Math.round(totalSeconds * 0.5) : Math.round(totalSeconds * 0.25)
      const iosShare = base.primary_namespace === 'ios' ? Math.round(totalSeconds * 0.4) : Math.round(totalSeconds * 0.15)
      const windowsShare = Math.max(0, totalSeconds - webShare - androidShare - iosShare)
      items.push({
        ...base,
        total_seconds: totalSeconds,
        wifi_bytes: Math.round(rand() * 1_500_000),
        cell_bytes: Math.round(rand() * 300_000),
        breakdown: {
          web: Math.max(0, webShare),
          android: Math.max(0, androidShare),
          ios: Math.max(0, iosShare),
          windows: Math.max(0, windowsShare),
        },
      })
      if (items.length >= limit || remaining <= 0) break
    }
    return { items } as T
  }

  if (path.startsWith('/api/v1/usage')) {
    // device-level gets modest realistic totals; account-level higher
    const perHourTarget = deviceId ? 15 + rand() * 35 : 40 + rand() * 60

    if (group === 'day') {
      const points = Array.from({ length: 7 }).map((_, i) => {
        const ts = new Date(now - (6 - i) * 86_400_000).toISOString()
        const work = Math.round(120 + rand() * 180)
        const video = Math.round(100 + rand() * 140)
        const social = Math.round(80 + rand() * 110)
        const gaming = Math.round(40 + rand() * 80)
        const adult = Math.round(rand() < 0.25 ? 10 + rand() * 25 : 0)
        const minutes = work + video + social + gaming + adult
        return { ts, minutes, breakdown: { work, video, social, gaming, adult } }
      })
      return { from: points[0].ts, to: points.at(-1)!.ts, points } as T
    }

    const points = Array.from({ length: 24 }).map((_, i) => {
      const ts = new Date(now - (23 - i) * 3_600_000).toISOString()
      const base = perHourTarget
      const hour = new Date(ts).getHours()
      const mod = hour >= 9 && hour <= 17 ? 1.2 : hour >= 19 || hour <= 1 ? 1.0 : 0.6
      const total = Math.min(60, Math.round(base * mod * (0.6 + rand() * 0.8)))
      // split into categories
      const work = Math.round(total * (hour >= 9 && hour <= 17 ? 0.5 + rand() * 0.2 : 0.1 + rand() * 0.1))
      const video = Math.round(total * (hour >= 19 || hour <= 1 ? 0.35 + rand() * 0.2 : 0.1 + rand() * 0.2))
      const social = Math.round(total * (0.15 + rand() * 0.2))
      const gaming = Math.round(total * (hour >= 20 || hour <= 1 ? 0.2 + rand() * 0.2 : 0.05 + rand() * 0.1))
      const adult = Math.round(total * (hour >= 23 || hour <= 2 ? 0.02 + rand() * 0.06 : 0))
      const minutes = work + video + social + gaming + adult
      return { ts, minutes, breakdown: { work, video, social, gaming, adult } }
    })
    return { from: points[0].ts, to: points.at(-1)!.ts, points } as T
  }

  if (path.startsWith('/api/v1/controls')) {
    return {
      rules: [
        { id: 'r1', category: 'social', limitMinutesPerDay: 90 },
        { id: 'r2', category: 'video', limitMinutesPerDay: 120 },
        { id: 'r3', category: 'adult', block: true, schedule: [{ start: '22:00', end: '07:00' }] },
      ],
      focusMode: { active: false },
    } as T
  }

  if (path.startsWith('/api/v1/controls/focus')) {
    return { rules: [], focusMode: { active: true, until: new Date(Date.now() + 30 * 60_000).toISOString() } } as T
  }

  throw new Error('No mock for ' + path)
}
