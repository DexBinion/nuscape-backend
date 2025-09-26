const segments = [
  { start: -24, color: '#F54784' },
  { start: 36, color: '#FF8A3C' },
  { start: 96, color: '#FFD24D' },
  { start: 156, color: '#34D399' },
  { start: 216, color: '#0FB5A3' },
  { start: 276, color: '#0EA5E9' },
]

const SWEEP = 48
const OUTER_RADIUS = 56
const INNER_RADIUS = 28

function degToRad(deg: number) {
  return ((deg - 90) * Math.PI) / 180
}

function polar(radius: number, angleDeg: number) {
  const rad = degToRad(angleDeg)
  return {
    x: 60 + radius * Math.cos(rad),
    y: 60 + radius * Math.sin(rad),
  }
}

function segmentPath(startDeg: number) {
  const endDeg = startDeg + SWEEP
  const outerStart = polar(OUTER_RADIUS, startDeg)
  const outerEnd = polar(OUTER_RADIUS, endDeg)
  const innerEnd = polar(INNER_RADIUS, endDeg)
  const innerStart = polar(INNER_RADIUS, startDeg)
  const largeArc = SWEEP > 180 ? 1 : 0

  return [
    `M ${innerStart.x.toFixed(2)} ${innerStart.y.toFixed(2)}`,
    `L ${outerStart.x.toFixed(2)} ${outerStart.y.toFixed(2)}`,
    `A ${OUTER_RADIUS} ${OUTER_RADIUS} 0 ${largeArc} 1 ${outerEnd.x.toFixed(2)} ${outerEnd.y.toFixed(2)}`,
    `L ${innerEnd.x.toFixed(2)} ${innerEnd.y.toFixed(2)}`,
    `A ${INNER_RADIUS} ${INNER_RADIUS} 0 ${largeArc} 0 ${innerStart.x.toFixed(2)} ${innerStart.y.toFixed(2)}`,
    'Z',
  ].join(' ')
}

export default function ShieldIcon({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 120 120" className={className} aria-hidden>
      <circle cx="60" cy="60" r="58" fill="#ffffff" />
      {segments.map((segment) => (
        <path key={segment.start} d={segmentPath(segment.start)} fill={segment.color} />
      ))}
      <circle cx="60" cy="60" r="18" fill="#ffffff" />
    </svg>
  )
}
