import type { DeviceInfo } from '@/types'

const platformBadge: Record<DeviceInfo['platform'], string> = {
  windows: 'Windows',
  android: 'Android',
  macos: 'macOS',
  ios: 'iOS',
  linux: 'Linux'
}

export default function DeviceCard({ d, onClick }: { d: DeviceInfo; onClick?: () => void }) {
  const date = new Date(d.lastSeen)
  const valid = !isNaN(date.getTime())
  const last = valid ? `${date.toLocaleTimeString()} • ${date.toLocaleDateString()}` : 'Never'
  const color = d.status === 'active' ? 'bg-green-400' : d.status === 'idle' ? 'bg-yellow-400' : 'bg-gray-400'

  return (
    <button onClick={onClick} className="card p-4 flex items-center justify-between text-left hover:bg-base-stroke/40 transition cursor-pointer w-full">
      <div className="flex items-center gap-3">
        <span className={`h-2.5 w-2.5 rounded-full ${color}`} />
        <div>
          <div className="font-medium">{d.name}</div>
          <div className="hint">{platformBadge[d.platform]} • Last seen {last}</div>
        </div>
      </div>
      <div className="hint capitalize">{d.status}</div>
    </button>
  )
}
