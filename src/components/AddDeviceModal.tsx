import React from 'react'
import { FaAndroid, FaApple, FaWindows } from 'react-icons/fa'
import { SiIos } from 'react-icons/si'

type Platform = 'android' | 'ios' | 'macos' | 'windows'

export default function AddDeviceModal({ open, onClose, onSelect }: { open: boolean; onClose: () => void; onSelect: (p: Platform) => void }) {
  if (!open) return null

  const items: { id: Platform; label: string; desc: string; icon: React.ReactNode }[] = [
    { id: 'android', label: 'Android', desc: 'Install the NuScape Android app', icon: <FaAndroid className="text-[#3DDC84] text-2xl" aria-hidden /> },
    { id: 'windows', label: 'Windows', desc: 'Download the NuScape Windows app', icon: <FaWindows className="text-[#0078D6] text-2xl" aria-hidden /> },
    { id: 'ios', label: 'iOS', desc: 'Install via TestFlight or App Store', icon: <SiIos className="text-slate-900 text-2xl" aria-hidden /> },
    { id: 'macos', label: 'Mac', desc: 'Install the NuScape macOS app', icon: <FaApple className="text-slate-900 text-2xl" aria-hidden /> },
  ]

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center">
      <div className="absolute inset-0 bg-black/40" onClick={onClose} />

      <div className="relative max-w-3xl w-full px-6 py-8">
        <div className="bg-base p-6 rounded-2xl shadow-2xl transform-gpu" style={{ perspective: 900 }}>
          {/* title removed per request - only show option cards */}

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 items-stretch">
            {items.map((it) => (
              <button
                key={it.id}
                onClick={() => { onSelect(it.id); onClose() }}
                className="relative group p-0 rounded-xl hover:scale-105 transform transition overflow-hidden h-24 border border-base-stroke bg-base-bg"
                aria-label={`Add ${it.label}`}
              >
                <div className="flex items-center gap-4 p-4">
                  <div className="h-12 w-12 flex items-center justify-center rounded-md bg-white shadow-sm p-1.5">
                    {it.icon}
                  </div>
                  <div className="text-left text-base-text">
                    <div className="font-medium">{it.label}</div>
                    <div className="hint text-sm text-base-mute">{it.desc}</div>
                  </div>
                </div>
                <div className="pointer-events-none absolute inset-0 rounded-xl" style={{ transformStyle: 'preserve-3d', boxShadow: 'inset 0 1px 0 rgba(255,255,255,0.03)' }} />
              </button>
            ))}
          </div>

          <div className="mt-6 text-right">
            <button onClick={onClose} className="btn btn-ghost">Cancel</button>
          </div>
        </div>
      </div>
    </div>
  )
}
