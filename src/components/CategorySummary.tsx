import type { UsagePoint } from '@/types'

export default function CategorySummary({ points, groupBy = 'hour' }: { points: UsagePoint[]; groupBy?: 'hour' | 'day' }) {
  const limit = groupBy === 'hour' ? 60 : 24 * 60

  const totals = points.reduce((acc, p) => {
    const sum = Object.values(p.breakdown).reduce((a, v) => a + (v ?? 0), 0)
    const scale = sum > limit ? limit / sum : 1
    for (const [k, v] of Object.entries(p.breakdown)) {
      acc[k] = (acc[k] ?? 0) + (v ?? 0) * scale
    }
    return acc
  }, {} as Record<string, number>)

  const rows = Object.entries(totals)
    .map(([k, v]) => ({ key: k, mins: v }))
    .sort((a, b) => b.mins - a.mins)

  const grand = rows.reduce((a, r) => a + r.mins, 0) || 1

  return (
    <div className="card p-4">
      <div className="font-medium mb-2">Where your time went ({groupBy === 'hour' ? 'today' : 'last 7d'})</div>
      <div className="space-y-2">
        {rows.map(({ key, mins }) => (
          <div key={key}>
            <div className="flex items-center justify-between hint">
              <span className="capitalize">{key}</span>
              <span>{Math.round(mins)}m • {Math.round((mins / grand) * 100)}%</span>
            </div>
            <div className="h-2 bg-base-stroke rounded-full overflow-hidden">
              <div className="h-2 bg-base-accent" style={{ width: `${(mins / grand) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
