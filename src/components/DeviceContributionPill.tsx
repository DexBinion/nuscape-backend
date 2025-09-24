import type { DeviceInfo } from '@/types'

const platformIcon = {
  windows: () => (
    <svg viewBox="0 0 24 24" className="h-6 w-6" aria-hidden>
      <rect x="2" y="3" width="9" height="8" fill="#3B82F6" />
      <rect x="13" y="3" width="9" height="8" fill="#60A5FA" />
      <rect x="2" y="13" width="9" height="8" fill="#60A5FA" />
      <rect x="13" y="13" width="9" height="8" fill="#3B82F6" />
    </svg>
  ),
  android: () => (
    <svg viewBox="0 0 24 24" className="h-6 w-6" aria-hidden>
      <rect x="7" y="3" width="10" height="18" rx="2" fill="#3B82F6" />
      <rect x="9" y="5" width="6" height="12" rx="1" fill="#0B0D12" />
      <circle cx="12" cy="18.5" r="0.8" fill="#E5E7EB" />
    </svg>
  ),
  macos: () => <span className="text-lg"></span>,
  ios: () => (
    <svg viewBox="0 0 24 24" className="h-6 w-6" aria-hidden>
      <rect x="5" y="4" width="14" height="16" rx="2" fill="#E6E7E8" />
      <rect x="8" y="7" width="8" height="10" rx="1" fill="#0B0D12" />
    </svg>
  ),
  linux: () => <span className="text-lg">🐧</span>,
} as const

function hm(mins: number) {
  const h = Math.floor(mins / 60)
  const m = Math.round(mins % 60)
  return `${h}h ${m}m`
}

export default function DeviceContributionPill({
  device,
  minutes,
  percent,
  selected,
  onClick,
  compact = false,
}: {
  device: Pick<DeviceInfo, 'id' | 'name' | 'platform' | 'status'>
  minutes: number
  percent: number
  selected?: boolean
  onClick?: () => void
  compact?: boolean
}) {
  const statusColor = device.status === 'active' ? 'bg-green-400' : device.status === 'idle' ? 'bg-yellow-400' : 'bg-gray-500'
  const Icon = platformIcon[device.platform]
  const pct = Math.max(0, Math.min(100, Math.round(percent)))

  return (
    <button
      onClick={onClick}
      aria-pressed={!!selected}
      data-selected={selected ? 'true' : 'false'}
      className={`card p-4 w-full text-left transition hover:bg-base-stroke/40 ${selected ? 'bg-base-stroke' : ''}`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="h-6 w-6 flex items-center justify-center">{Icon && <Icon />}</div>
          <div className="font-medium truncate">{device.name}</div>
        </div>
        {!compact && <div className="hint whitespace-nowrap">{hm(minutes)} • {pct}%</div>}
      </div>
      {!compact && (
        <div className="mt-2 h-2 bg-base-stroke rounded-full overflow-hidden">
          <div className="h-2 bg-base-accent" style={{ width: `${pct}%` }} />
        </div>
      )}
    </button>
  )
}
