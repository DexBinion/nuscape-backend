import { Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { UsagePoint } from '@/types'

function normalizePoint(p: UsagePoint, limit: number) {
  const sum = Object.values(p.breakdown).reduce((a, v) => a + (v ?? 0), 0)
  const scale = sum > limit ? limit / sum : 1
  const b = p.breakdown
  return {
    ts: p.ts,
    work: (b.work ?? 0) * scale,
    video: (b.video ?? 0) * scale,
    social: (b.social ?? 0) * scale,
    gaming: (b.gaming ?? 0) * scale,
    adult: (b.adult ?? 0) * scale,
  }
}

export default function UsageChart({ data, groupBy = 'hour' }: { data: UsagePoint[]; groupBy?: 'hour' | 'day' }) {
  const limit = groupBy === 'hour' ? 60 : 24 * 60 // cap to human time in bucket
  const fmt = (ts: string) => groupBy === 'hour'
    ? new Date(ts).toLocaleTimeString([], { hour: '2-digit' })
    : new Date(ts).toLocaleDateString([], { weekday: 'short' })

  const rows = data.map(p => {
    const n = normalizePoint(p, limit)
    return {
      ts: fmt(p.ts),
      work: n.work / 60,
      video: n.video / 60,
      social: n.social / 60,
      gaming: n.gaming / 60,
      adult: n.adult / 60,
    }
  })

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="font-medium">Screen Time (hrs)</div>
        <div className="hint">{groupBy === 'hour' ? 'Last 24h' : 'Last 7 days'}</div>
      </div>
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={rows}>
            <CartesianGrid strokeDasharray="3 3" opacity={0.1} />
            <XAxis dataKey="ts" />
            <YAxis domain={[0, groupBy === 'hour' ? 1 : 24]} />
            <Tooltip />
            <Legend />
            <Area type="monotone" dataKey="work" stackId="1" fill="#22c55e" stroke="#22c55e" />
            <Area type="monotone" dataKey="video" stackId="1" fill="#3b82f6" stroke="#3b82f6" />
            <Area type="monotone" dataKey="social" stackId="1" fill="#a855f7" stroke="#a855f7" />
            <Area type="monotone" dataKey="gaming" stackId="1" fill="#ef4444" stroke="#ef4444" />
            <Area type="monotone" dataKey="adult" stackId="1" fill="#f59e0b" stroke="#f59e0b" />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
