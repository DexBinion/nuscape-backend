import type { TopAppItem } from '@/types'
import { AppIcon } from '@/components/icons/app-icons'

const PLATFORM_LABELS: Record<string, string> = {
  android: 'Android',
  ios: 'iOS',
  windows: 'Windows',
  macos: 'macOS',
  linux: 'Linux',
  web: 'Web',
}

const BULLET = '•'

const formatLabel = (platform: string) => PLATFORM_LABELS[platform] ?? `${platform.charAt(0).toUpperCase()}${platform.slice(1)}`

const formatMinutes = (seconds: number) => {
  const mins = Math.round(seconds / 60)
  return mins > 0 ? `${mins}m` : `${Math.max(1, Math.round(seconds))}s`
}

export default function TopAppsCard({ items, title = 'Top Apps & Sites' }: { items: TopAppItem[]; title?: string }) {
  const sorted = [...items].sort((a, b) => b.total_seconds - a.total_seconds)
  const totalSeconds = sorted.reduce((a, b) => a + b.total_seconds, 0) || 1
  const ICON_CENTER = 15
  const ICON_HALF = 10
  const LEFT_WIDTH = 260

  return (
    <div className="card p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="font-medium underline">{title}</div>
      </div>
      {sorted.length === 0 ? (
        <div className="hint">No activity yet.</div>
      ) : (
        <ul className="space-y-2">
          {sorted.map((it) => {
              const minutes = Math.round(it.total_seconds / 60)
              const pct = Math.max(0, Math.min(100, Math.round((it.total_seconds / totalSeconds) * 100)))
              const kind: 'app' | 'site' = it.primary_namespace === 'web' ? 'site' : 'app'
              const domain = it.primary_namespace === 'web' ? it.primary_identifier ?? undefined : undefined
              // breakdown is per-platform seconds; normalize to ordered devices: android, windows, ios
              const breakdown = it.breakdown || {}
              const a = breakdown.android ?? 0
              const w = breakdown.windows ?? 0
              const i = breakdown.ios ?? 0
              const sum = Math.max(1, a + w + i)
              const aPct = Math.round((a / sum) * 100)
              const wPct = Math.round((w / sum) * 100)
              const iPct = Math.round((i / sum) * 100)

              return (
                <li key={it.app_id} className="pt-2 first:pt-2">
                  <div className="flex items-center">
                    <div className="flex items-center" style={{ width: LEFT_WIDTH, paddingLeft: ICON_CENTER }}>
                      <span style={{ marginLeft: -ICON_HALF }}>
                        <AppIcon
                          name={it.display_name}
                          kind={kind}
                          domain={domain}
                          iconUrl={it.icon_url ?? undefined}
                          iconB64={it.icon_b64 ?? undefined}
                          brandSlug={it.app_id}
                          appId={it.app_id}
                        />
                      </span>
                      <div className="ml-3 w-full">
                        <div className="font-medium truncate">{it.display_name}</div>
                        <div className="hint capitalize">{it.category}</div>
                      </div>
                    </div>
                    <div className="ml-4 flex-1 flex items-center gap-3">
                      <span className="hint text-right" style={{ width: 56 }}>{minutes}m</span>
                      <div className="h-2 flex-1 flex rounded-full overflow-hidden bg-base-stroke/30" style={{ height: 10 }}>
                        <div className="bg-green-500" style={{ width: `${aPct}%` }} />
                        <div className="bg-blue-500" style={{ width: `${wPct}%` }} />
                        <div className="bg-gray-200" style={{ width: `${iPct}%` }} />
                      </div>
                    </div>
                  </div>
                  {/* keep the platform breakdown badges but remove the 'web' pills per request; keep spacing consistent */}
                  {Object.entries(breakdown).filter(([k, v]) => k !== 'web' && v > 0).length > 0 && (
                    <div
                      className="mt-2 flex flex-wrap gap-2 text-[11px] text-muted-foreground"
                      style={{ marginLeft: ICON_CENTER + LEFT_WIDTH }}
                    >
                      {Object.entries(breakdown)
                        .filter(([k, v]) => k !== 'web' && v > 0)
                        .map(([platform, seconds]) => (
                          <span key={platform} className="rounded-full bg-base-stroke/70 px-2 py-0.5">
                            {formatLabel(platform)} {BULLET} {formatMinutes(seconds)}
                          </span>
                        ))}
                    </div>
                  )}
                </li>
              )
            })}
        </ul>
      )}
    </div>
  )
}
