export default function RangeToggle({ value, onChange }: { value: '24h' | '7d'; onChange: (v: '24h' | '7d') => void }) {
  const btn = (v: '24h' | '7d', label: string) => (
    <button
      onClick={() => onChange(v)}
      className={`px-3 py-1.5 rounded-xl border transition ${
        value === v ? 'bg-base-accent text-white border-transparent' : 'border-base-stroke hover:bg-base-stroke/40'
      }`}
    >
      {label}
    </button>
  )
  return (
    <div className="flex items-center gap-2">{btn('24h', 'Last 24h')}{btn('7d', 'Last 7 days')}</div>
  )
}

