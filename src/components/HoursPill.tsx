// TimeframeToggle removed per request

type Slot = { label: string; value: string }

export default function HoursPill({ value, slots = [], goal = '—', highlightOs }: { value: string; slots?: Slot[]; goal?: string; highlightOs?: 'android'|'ios'|'macos'|'windows'|null }) {
  const items: Slot[] = [
    { label: 'Total Time', value },
    ...slots,
    { label: 'Goal', value: goal },
  ].slice(0, 4)

  return (
    <div className="card p-3">
      <div className="grid grid-cols-1 md:grid-cols-4 gap-2 items-stretch">
        {items.map((s) => (
          <Metric key={s.label} label={s.label} value={s.value} />
        ))}
      </div>
    </div>
  )
}

function Metric({ label, value }: { label: string; value: string }) {
  const isTimeMetric = /time|daily average/i.test(label)

  function formatTimeString(v: string) {
    if (!v) return '—'
    // match "1h 20m", "1h20m", "1 h 20 m"
    const hmMatch = v.match(/(\d+)\s*h(?:ours?)?\s*(\d+)\s*m(?:in(?:utes?)?)?/i)
    if (hmMatch) {
      const h = String(Number(hmMatch[1])).padStart(2, '0')
      const m = String(Number(hmMatch[2] ?? 0)).padStart(2, '0')
      return `${h}:${m}`
    }

    const compactHm = v.match(/(\d+)h\s*(\d+)m/i)
    if (compactHm) {
      const h = String(Number(compactHm[1])).padStart(2, '0')
      const m = String(Number(compactHm[2] ?? 0)).padStart(2, '0')
      return `${h}:${m}`
    }

    const colonMatch = v.match(/(\d{1,2}):(\d{2})/)
    if (colonMatch) {
      const h = String(Number(colonMatch[1])).padStart(2, '0')
      const m = String(Number(colonMatch[2])).padStart(2, '0')
      return `${h}:${m}`
    }

    const cleaned = v.replace(/[hmHM]/g, '').trim()
    const parts = cleaned.split(/[:\s]+/).filter(Boolean)
    if (parts.length === 2) {
      const h = String(Number(parts[0]) || 0).padStart(2, '0')
      const m = String(Number(parts[1]) || 0).padStart(2, '0')
      return `${h}:${m}`
    }
    return v
  }

  function ClockSVG({ time }: { time: string }) {
    const ticks = Array.from({ length: 12 })
    return (
      <svg viewBox="0 0 100 100" className="w-20 h-20">
        <g transform="translate(50,50)">
          <circle r="40" cx="0" cy="0" stroke="#A8AAAD" strokeWidth="2" fill="transparent" />
          {ticks.map((_, i) => {
            const angle = (i / 12) * 360
            const inner = 36
            const outer = 40
            const x1 = inner * Math.cos((angle * Math.PI) / 180)
            const y1 = inner * Math.sin((angle * Math.PI) / 180)
            const x2 = outer * Math.cos((angle * Math.PI) / 180)
            const y2 = outer * Math.sin((angle * Math.PI) / 180)
            return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#A8AAAD" strokeWidth={i % 3 === 0 ? 2 : 1} strokeLinecap="round" />
          })}
          <text x="0" y="6" textAnchor="middle" fontFamily="monospace" fontSize="16" fill="#E6E7E8" fontWeight={600}>{time}</text>
        </g>
      </svg>
    )
  }

  const display = isTimeMetric ? formatTimeString(value) : value

  return (
    <div className="rounded-xl p-2 flex flex-col items-center justify-center text-center">
      <div className="hint mb-1 text-sm">{label}</div>
      {isTimeMetric ? (
        <div className="flex items-center justify-center -mt-1">
          <ClockSVG time={display} />
        </div>
      ) : (
        <div className="mt-0 text-lg font-medium tracking-tight">{display}</div>
      )}
    </div>
  )
}
