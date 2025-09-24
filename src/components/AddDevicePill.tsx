import React from 'react'

export default function AddDevicePill({ onClick }: { onClick?: () => void }) {
  return (
    <button
      onClick={onClick}
      className="card inline-flex px-4 py-3 text-center transition hover:bg-base-stroke/40 items-center justify-center gap-3 z-20"
      aria-label="Add device"
      style={{ width: 'auto' }}
    >
      <div className="flex items-center gap-3">
        <div className="font-medium">Add Device</div>
        <div className="text-2xl">+</div>
      </div>
    </button>
  )
}
