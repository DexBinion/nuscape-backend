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
  ios: () => <span className="text-lg"></span>,
  linux: () => <span className="text-lg">🐧</span>,
} as const

export default function DevicePill({ device, minutesToday, onClick }: { device: DeviceInfo; minutesToday: number; onClick?: () => void }) {
  const hrs = Math.floor(minutesToday / 60)
  const mins = Math.round(minutesToday % 60)
  const statusColor = device.status === 'active' ? 'bg-green-400' : device.status === 'idle' ? 'bg-yellow-400' : 'bg-gray-500'
  const Icon = platformIcon[device.platform]

  return (
    <button onClick={onClick} className="card p-4 flex items-center justify-between w-full text-left hover:bg-base-stroke/40 transition">
      <div className="flex items-center gap-3">
        <span className={`h-2.5 w-2.5 rounded-full ${statusColor}`} />
        <div className="h-6 w-6 flex items-center justify-center">{Icon && <Icon />}</div>
        <div>
          <div className="font-medium">{device.name}</div>
          <div className="hint">Today: {hrs}h {mins}m</div>
        </div>
      </div>
      <div className="hint capitalize">{device.platform}</div>
    </button>
  )
}
