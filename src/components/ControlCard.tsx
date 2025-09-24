import type { Rule } from '@/types'

interface Props {
  rule: Rule
  onChange: (rule: Rule) => void
}

export default function ControlCard({ rule, onChange }: Props) {
  const set = (patch: Partial<Rule>) => onChange({ ...rule, ...patch })
  return (
    <div className="card p-4 space-y-3">
      <div className="flex items-center justify-between">
        <div className="font-medium capitalize">{rule.category}</div>
        <label className={`toggle ${rule.block ? 'toggle-active' : ''}`}
          onClick={() => set({ block: !rule.block })}>
          <span className="sr-only">Block</span>
          <span className="toggle-dot" />
        </label>
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <label className="hint">Daily limit (minutes)</label>
          <input type="number" min={0} className="mt-1 w-full rounded-lg bg-transparent border border-base-stroke px-3 py-2"
            value={rule.limitMinutesPerDay ?? 0}
            onChange={e => set({ limitMinutesPerDay: Number(e.target.value) })} />
        </div>
        <div>
          <label className="hint">Quiet hours (start–end)</label>
          <div className="mt-1 flex gap-2">
            <input type="time" className="w-full rounded-lg bg-transparent border border-base-stroke px-3 py-2"
              value={rule.schedule?.[0]?.start ?? '22:00'}
              onChange={e => set({ schedule: [{ start: e.target.value, end: rule.schedule?.[0]?.end ?? '07:00' }] })} />
            <input type="time" className="w-full rounded-lg bg-transparent border border-base-stroke px-3 py-2"
              value={rule.schedule?.[0]?.end ?? '07:00'}
              onChange={e => set({ schedule: [{ start: rule.schedule?.[0]?.start ?? '22:00', end: e.target.value }] })} />
          </div>
        </div>
      </div>
    </div>
  )
}

