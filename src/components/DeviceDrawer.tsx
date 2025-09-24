import UsageChart from '@/components/UsageChart'
import type { DeviceInfo, UsageSeries } from '@/types'

export default function DeviceDrawer({ device, usage, onClose, onFocus }: {
  device: DeviceInfo
  usage: UsageSeries | null
  onClose: () => void
  onFocus: (mins: number) => void
}) {
  const totals = usage?.points.reduce((acc, p) => {
    for (const [k, v] of Object.entries(p.breakdown)) acc[k] = (acc[k] ?? 0) + (v ?? 0)
    return acc
  }, {} as Record<string, number>) || {}

  return (
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/50" onClick={onClose} />
      <aside className="absolute right-0 top-0 h-full w-full sm:w-[480px] bg-base-card border-l border-base-stroke p-6 overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <div>
            <div className="text-lg font-semibold">{device.name}</div>
            <div className="hint capitalize">{device.platform} • {device.status}</div>
          </div>
          <button className="btn" onClick={onClose}>Close</button>
        </div>

        <div className="space-y-4">
          {usage ? <UsageChart data={usage.points} groupBy="hour" /> : <div className="card p-4 hint">Loading usage…</div>}

          <div className="card p-4">
            <div className="font-medium mb-2">Today on this device</div>
            <ul className="hint space-y-1">
              {Object.entries(totals).map(([k, v]) => (
                <li key={k} className="flex justify-between"><span className="capitalize">{k}</span><span>{Math.round(v)}m</span></li>
              ))}
              {Object.keys(totals).length === 0 && <li>No data yet.</li>}
            </ul>
          </div>

          <div className="flex gap-2">
            {[30, 60, 120].map(m => (
              <button key={m} className="btn btn-primary" onClick={() => onFocus(m)}>Focus {m}m</button>
            ))}
          </div>
        </div>
      </aside>
    </div>
  )
}

