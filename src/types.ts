export type CategoryKey =
  | 'social'
  | 'video'
  | 'work'
  | 'gaming'
  | 'other'
  | 'adult'
  | 'productivity'
  | 'education'
  | 'communication'

export interface UsagePoint {
  ts: string // ISO
  minutes: number
  breakdown: Partial<Record<CategoryKey, number>>
}

export interface UsageSeries {
  from: string
  to: string
  points: UsagePoint[]
}

export interface DeviceInfo {
  id: string
  name: string
  platform: 'windows' | 'android' | 'macos' | 'ios' | 'linux'
  lastSeen: string
  status: 'active' | 'idle' | 'offline'
}

export interface Rule {
  id: string
  category: CategoryKey
  limitMinutesPerDay?: number
  block?: boolean
  schedule?: { start: string; end: string }[] // e.g. 22:00-07:00
}

export interface ControlsState {
  rules: Rule[]
  focusMode?: {
    active: boolean
    until?: string // ISO
  }
  blockedAppIds?: string[]
}

export interface TopAppItem {
  app_id: string
  display_name: string
  category: CategoryKey
  icon_url?: string | null
  icon_b64?: string | null
  total_seconds: number
  wifi_bytes: number
  cell_bytes: number
  breakdown: Record<string, number>
  primary_namespace?: string | null
  primary_identifier?: string | null
}
