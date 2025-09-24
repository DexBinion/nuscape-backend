interface KPIProps { label: string; value: string; hint?: string }
export default function KPI({ label, value, hint }: KPIProps) {
  return (
    <div className="card p-4">
      <div className="hint">{label}</div>
      <div className="text-2xl font-semibold mt-1 tracking-tight">{value}</div>
      {hint && <div className="hint mt-1">{hint}</div>}
    </div>
  )
}
