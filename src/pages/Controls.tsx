import { useEffect, useState } from 'react'
import { Api } from '@/lib/api'
import type { ControlsState, Rule } from '@/types'
import ControlCard from '@/components/ControlCard'

export default function Controls() {
  const [state, setState] = useState<ControlsState | null>(null)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    Api.getControls().then(setState)
  }, [])

  const updateRule = (r: Rule) => setState(s => s ? ({ ...s, rules: s.rules.map(x => x.id === r.id ? r : x) }) : s)

  const save = async () => {
    if (!state) return
    setSaving(true)
    const next = await Api.saveControls(state)
    setState(next)
    setSaving(false)
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {state?.rules.map(r => (
          <ControlCard key={r.id} rule={r} onChange={updateRule} />
        ))}
      </div>

      <div className="flex gap-2">
        <button className="btn btn-primary" onClick={save} disabled={saving}>
          {saving ? 'Saving…' : 'Save controls'}
        </button>
        <button className="btn" onClick={() => Api.focus(60)}>Start Focus 60m</button>
      </div>

      <div className="hint">Blocking and limits sync to all registered devices. On iOS/macOS, enforcement relies on Screen Time APIs.</div>
    </div>
  )
}

