export default function ShieldIcon({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 24 24" className={className} aria-hidden>
      <defs>
        <linearGradient id="ns-shield" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#60A5FA" />
          <stop offset="100%" stopColor="#3B82F6" />
        </linearGradient>
      </defs>
      <path fill="url(#ns-shield)" d="M12 2l7 3v6c0 5-3.4 9.7-7 11-3.6-1.3-7-6-7-11V5l7-3z"/>
      <path fill="#fff" opacity="0.2" d="M12 4l5 2v4c0 4-2.5 7.8-5 8.9C9.5 17.8 7 14 7 10V6l5-2z"/>
    </svg>
  )
}

