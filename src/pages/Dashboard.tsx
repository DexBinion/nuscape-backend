import { useCallback, useEffect, useMemo, useState } from 'react'
import { Api } from '@/lib/api'
import type { DeviceInfo, UsageSeries, TopAppItem } from '@/types'
import HoursPill from '@/components/HoursPill'
import TopAppsCard from '@/components/TopAppsCard'
import TimeframeToggle, { TF } from '@/components/TimeframeToggle'
import DeviceContributionPill from '@/components/DeviceContributionPill'
import AddDevicePill from '@/components/AddDevicePill'
import AddDeviceModal from '@/components/AddDeviceModal'
import ShieldIcon from '@/components/icons/ShieldIcon'

function cappedSum(series: UsageSeries, perBucketCapMin: number) {
  return series.points.reduce((a, p) => a + Math.min(perBucketCapMin, p.minutes), 0)
}

function rangeFor(tf: TF) {
  const now = new Date()
  const to = now
  const from = new Date(now)
  let group: 'hour' | 'day' = 'hour'
  if (tf === 'D') from.setTime(now.getTime() - 24 * 60 * 60 * 1000)
  else if (tf === 'W') { from.setTime(now.getTime() - 7 * 24 * 60 * 60 * 1000); group = 'day' }
  else if (tf === 'M') { from.setTime(now.getTime() - 30 * 24 * 60 * 60 * 1000); group = 'day' }
  else { from.setTime(now.getTime() - 90 * 24 * 60 * 60 * 1000); group = 'day' }
  return { from, to, group }
}

export default function Dashboard() {
  const [devices, setDevices] = useState<DeviceInfo[]>([])
  const [series, setSeries] = useState<UsageSeries | null>(null)
  const [topApps, setTopApps] = useState<TopAppItem[]>([])
  const [perDeviceRaw, setPerDeviceRaw] = useState<Record<string, number>>({})
  const [perDeviceNorm, setPerDeviceNorm] = useState<Record<string, number>>({})
  const [tf, setTf] = useState<TF>('W')
  const [selected, setSelected] = useState<string | null>(null)

  const load = useCallback(async () => {
    const { from, to, group } = rangeFor(tf)
    const [d, u] = await Promise.all([
      Api.getDevices(),
      Api.getUsage(from.toISOString(), to.toISOString(), group),
    ])

    setDevices(d)
    setSeries(u)

    const byPlat: Record<string, DeviceInfo> = {}
    for (const x of d) { if (!byPlat[x.platform]) byPlat[x.platform] = x }
    const chosen = [byPlat['windows'], byPlat['android']].filter(Boolean) as DeviceInfo[]

    const per: Record<string, number> = {}
    await Promise.all(chosen.map(async (dev) => {
      const s = await Api.getUsage(from.toISOString(), to.toISOString(), group, dev.id)
      per[dev.id] = cappedSum(s, group === 'hour' ? 60 : 24 * 60)
    }))
    setPerDeviceRaw(per)
  }, [tf])

  useEffect(() => { load() }, [load])

  // If API returned no devices (mock or edge), seed two extra devices for UI preview
  useEffect(() => {
    if (devices.length === 0) {
      setDevices([
        { id: 'pc-1', name: 'Dexter Windows', platform: 'windows', lastSeen: new Date().toISOString(), status: 'active' },
        { id: 'and-1', name: 'Dexter Android', platform: 'android', lastSeen: new Date().toISOString(), status: 'idle' },
        { id: 'ipad-1', name: 'Dexter iPad', platform: 'ios', lastSeen: new Date().toISOString(), status: 'idle' },
      ])
    }
  }, [devices])

  const totalMins = useMemo(() => series ? cappedSum(series, tf === 'D' ? 60 : 24 * 60) : 0, [series, tf])
  const hm = (mins: number) => {
    const h = Math.floor(mins / 60)
    const m = Math.round(mins % 60)
    return `${h}h ${m}m`
  }
  const totalHM = useMemo(() => hm(totalMins), [totalMins])
  const avgHM = useMemo(() => {
    const { from, to } = rangeFor(tf)
    const denomDays = Math.max(1, Math.round((to.getTime() - from.getTime()) / 86_400_000))
    return hm(Math.round(totalMins / denomDays))
  }, [tf, totalMins])

  useEffect(() => {
    const sumDevices = Object.values(perDeviceRaw).reduce((a, v) => a + v, 0)
    if (sumDevices === 0 || totalMins === 0) { setPerDeviceNorm(perDeviceRaw); return }
    const factor = Math.min(1, totalMins / sumDevices)
    const norm: Record<string, number> = {}
    for (const [k, v] of Object.entries(perDeviceRaw)) norm[k] = Math.round(v * factor)
    setPerDeviceNorm(norm)
  }, [perDeviceRaw, totalMins])

  useEffect(() => {
    const { from, to } = rangeFor(tf)
    const seed = () => {
      const data = [
        { app_id: 'youtube', display_name: 'YouTube', total_seconds: 60 * 45, primary_namespace: 'web', primary_identifier: 'youtube.com', breakdown: { web: 60 * 45 }, icon_url: undefined, icon_b64: undefined, category: 'Video', wifi_bytes: 0, cell_bytes: 0 },
        { app_id: 'facebook', display_name: 'Facebook', total_seconds: 60 * 30, primary_namespace: 'web', primary_identifier: 'facebook.com', breakdown: { web: 60 * 30 }, icon_url: undefined, icon_b64: undefined, category: 'Social', wifi_bytes: 0, cell_bytes: 0 },
        { app_id: 'tiktok', display_name: 'TikTok', total_seconds: 60 * 25, primary_namespace: 'web', primary_identifier: 'tiktok.com', breakdown: { web: 60 * 25 }, icon_url: undefined, icon_b64: undefined, category: 'Social', wifi_bytes: 0, cell_bytes: 0 },
        { app_id: 'x', display_name: 'X', total_seconds: 60 * 20, primary_namespace: 'web', primary_identifier: 'x.com', breakdown: { web: 60 * 20 }, icon_url: undefined, icon_b64: undefined, category: 'Social', wifi_bytes: 0, cell_bytes: 0 },
        { app_id: 'instagram', display_name: 'Instagram', total_seconds: 60 * 15, primary_namespace: 'web', primary_identifier: 'instagram.com', breakdown: { web: 60 * 15 }, icon_url: undefined, icon_b64: undefined, category: 'Social', wifi_bytes: 0, cell_bytes: 0 },
      ]
      return data as unknown as TopAppItem[]
    }

    Api.getTopApps(from.toISOString(), to.toISOString(), 5, selected ?? undefined).then(r => {
      if (r && Array.isArray(r.items) && r.items.length > 0) setTopApps(r.items)
      else setTopApps(seed())
    }).catch(() => setTopApps(seed()))
  }, [tf, selected])

  const devicesToShow = useMemo(() => {
    // Filter out dev devices and prioritize real user devices
    const realDevices = devices.filter(d => !d.name.includes('dev-') && d.name !== 'dev-react-ui')
    const byPlat: Record<string, DeviceInfo> = {}
    
    // For each platform, pick the real device (not dev device)
    for (const d of realDevices) { 
      if (!byPlat[d.platform]) byPlat[d.platform] = d 
    }
    
  const picks: DeviceInfo[] = []
  if (byPlat['windows']) picks.push(byPlat['windows'])
  if (byPlat['android']) picks.push(byPlat['android'])
  if (byPlat['ios']) picks.push(byPlat['ios'])
    
    // Fallback to real devices if no windows/android found
    return picks.length ? picks : realDevices.slice(0, 2)
  }, [devices])

  const [showAddDevice, setShowAddDevice] = useState(false)
  const [selectedOs, setSelectedOs] = useState<'android'|'ios'|'macos'|'windows'|null>(null)

  const handleAddDevice = (platform: 'android' | 'ios' | 'macos' | 'windows') => {
    // TODO: wire to onboarding / specific instructions. For now just open a new tab or log
    // We'll use a simple alert to indicate selection in the UI for now.
    // eslint-disable-next-line no-alert
    alert(`Add device: ${platform}`)
    setSelectedOs(platform)
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <AddDevicePill onClick={() => setShowAddDevice(true)} />

        {devicesToShow.map((d) => {
          const mins = perDeviceNorm[d.id] ?? 0
          const pct = totalMins > 0 ? (mins / totalMins) * 100 : 0
          return (
            <DeviceContributionPill
              key={d.id}
              device={d}
              minutes={mins}
              percent={pct}
              selected={selected === d.id}
              onClick={() => setSelected(d.id)}
              compact
            />
          )
        })}
      </div>

      {/* Total time card now sits between device row and top apps - timeframe toggle moved inside HoursPill */}
      <div className="mt-8">
        <HoursPill
        value={totalHM}
        slots={[
          { label: 'Daily Average', value: avgHM },
          { label: 'Devices', value: String(new Set(devices.map(d => d.id)).size) },
        ]}
        goal={'Open'}
        tf={tf}
        onChangeTf={(t) => { setTf(t); setSelected(null) }}
        highlightOs={selectedOs}
      />
      </div>

      <TopAppsCard
        items={topApps}
        title="Top Apps & Sites"
      />

  <AddDeviceModal open={showAddDevice} onClose={() => setShowAddDevice(false)} onSelect={(p) => { handleAddDevice(p); setShowAddDevice(false) }} />
    </div>
  )
}
