export default function Header() {
  // Minimal, calm header (no date/time, no API pill)
  const title = (() => {
    const p = window.location.pathname
    if (p === '/' || p === '') return null
    return p.slice(1).replace(/^[a-z]/, m => m.toUpperCase())
  })()

  return (
    <header className="sticky top-0 z-10 backdrop-blur supports-[backdrop-filter]:bg-base-bg/70">
      <div className="max-w-6xl mx-auto px-6 lg:px-8 py-4 flex items-center justify-between">
        {title ? (
          <h1 className="text-xl font-semibold">{title}</h1>
        ) : (
          <div className="text-xl font-semibold" aria-hidden="true" />
        )}
        <div />
      </div>
    </header>
  )
}
