export type TF = 'D' | 'W' | 'M' | 'A'

export default function TimeframeToggle({ value, onChange, highlightClass }: { value: TF; onChange: (v: TF) => void; highlightClass?: string }) {
  const order: TF[] = ['D', 'W', 'M', 'A']
  const lbl: Record<TF, string> = { D: 'Day', W: 'Week', M: 'Month', A: 'All' }
  const defaultHighlight = 'bg-[#A8AAAD] text-white'
  return (
    <div className="inline-flex border-2 border-base-stroke overflow-hidden">
      {order.map((t, idx) => (
        <button
          key={t}
          onClick={() => onChange(t)}
          className={`px-3 py-1.5 text-sm transition ${
            value === t ? (highlightClass ? highlightClass : defaultHighlight) : 'hover:bg-base-stroke/40'
          } ${idx === 0 ? 'rounded-l-xl' : ''} ${idx === order.length - 1 ? 'rounded-r-xl' : ''}`}
        >
          {lbl[t]}
        </button>
      ))}
    </div>
  )
}
