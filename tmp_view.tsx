import type { TopAppItem } from '@/types'
import { AppIcon } from '@/components/icons/app-icons'

export default function TopAppsCard({ items, title = 'Top Apps & Sites' }: { items: TopAppItem[]; title?: string }) {
  const sorted = [...items].sort((a, b) => b.minutes - a.minutes)
  const total = sorted.reduce((a, b) => a + b.minutes, 0) || 1
  const ICON_CENTER = 15 // nudge icons/text further left
  const ICON_HALF = 10 // AppIcon is h-5 w-5 (10px half)
  const LEFT_WIDTH = 260 // narrower left block so bars start earlier
  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-2">
        <div className="font-medium underline">{title}</div>
      </div>
      {sorted.length === 0 ? (
        <div className="hint">No activity yet.</div>
      ) : (
        <ul className="space-y-1">
          {sorted.map((it) => {
            const mins = Math.round(it.minutes)
            const pct = Math.max(0, Math.min(100, Math.round((it.minutes / total) * 100)))
            const barPct = Math.max(0, Math.min(100, Math.round(pct * 0.67)))
            return (
              <li key={it.name} className="py-2 flex items-center">
                {/* Left block: icon + labels */}
                <div className="flex items-center" style={{ width: LEFT_WIDTH, paddingLeft: ICON_CENTER }}>
                  <span style={{ marginLeft: -ICON_HALF }}>
                    <AppIcon
                      name={it.name}
                      kind={it.kind}
                      domain={(it as any).domain}
                      iconUrl={(it as any).iconUrl}
                      brandSlug={(it as any).brandSlug || it.icon}
                    />
                  </span>
                  <div className="ml-3 w-full">
                    <div className="font-medium truncate">{it.name}</div>
                    <div className="hint capitalize">{it.category}</div>
                  </div>
                </div>
                {/* Right block: time and bar on the same line */}
                <div className="ml-4 flex-1 flex items-center gap-3">
                  <span className="hint text-right" style={{ width: 56 }}>{mins}m</span>
                  <div className="h-2 flex-1">
                    <div className="h-2 bg-green-500 rounded-full" style={{ width: `${barPct}%` }} />
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
