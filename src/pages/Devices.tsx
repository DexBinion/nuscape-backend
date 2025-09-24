import { useEffect, useMemo, useState } from 'react'
import { Api } from '@/lib/api'
import type { DeviceInfo, UsageSeries } from '@/types'
import DeviceCard from '@/components/DeviceCard'
import DeviceDrawer from '@/components/DeviceDrawer'

export default function Devices() {
  const [devices, setDevices] = useState<DeviceInfo[]>([])
  const [open, setOpen] = useState<DeviceInfo | null>(null)
  const [usage, setUsage] = useState<UsageSeries | null>(null)

  useEffect(() => {
    Api.getDevices().then(setDevices)
  }, [])

  const list = useMemo(() => {
    const uniq = new Map<string, DeviceInfo>()
    for (const d of devices) {
      const key = d.id || `${d.name}-${d.platform}`
      if (!uniq.has(key)) uniq.set(key, d)
    }
    const arr = Array.from(uniq.values())
    const rank = { active: 0, idle: 1, offline: 2 } as const
    return arr.sort((a, b) => (rank[a.status] - rank[b.status]) || (new Date(b.lastSeen).getTime() - new Date(a.lastSeen).getTime()))
  }, [devices])

  useEffect(() => {
    if (!open) return
    const to = new Date(); const from = new Date(Date.now() - 24 * 60 * 60 * 1000)
    Api.getUsage(from.toISOString(), to.toISOString(), 'hour', open.id).then(setUsage)
  }, [open])

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {list.map(d => <DeviceCard key={d.id || d.name} d={d} onClick={() => setOpen(d)} />)}
      </div>
      <div className="hint">Click a device to see today’s breakdown and quick actions.</div>

      {open && (
        <DeviceDrawer device={open} usage={usage} onClose={() => setOpen(null)} onFocus={(m) => Api.focus(m)} />
      )}
    </div>
  )
}
