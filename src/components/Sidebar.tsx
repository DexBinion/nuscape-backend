import { NavLink } from 'react-router-dom'
// using the new flat shield SVG in public/icons

export default function Sidebar() {
  return (
    <aside className="w-64 shrink-0 border-r border-base-stroke hidden md:block">
      <div className="p-4">
        <div className="flex items-center gap-2 mb-2">
          <img src="/icons/shield-grid.svg" alt="NuScape shield" className="h-12 w-12" />
          <div className="text-2xl font-semibold leading-none">NuScape</div>
        </div>
        {/* hint removed per request */}
      </div>
      <nav className="px-2 space-y-1">
  <Item to="/" label="Analyze" />
        <Item to="/controls" label="Control Center" />
        <Item to="/settings" label="Settings" />
      </nav>
      {/* footer removed per request */}
    </aside>
  )
}

function Item({ to, label }: { to: string; label: string }) {
  return (
    <NavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `flex items-center gap-2 px-3 py-2 rounded-xl transition ${
          isActive ? 'bg-base-stroke text-white' : 'hover:bg-base-stroke/40'
        }`
      }
    >
      <span className="text-sm">{label}</span>
    </NavLink>
  )
}
