import { Outlet } from 'react-router-dom'
import Sidebar from './components/Sidebar'
import Header from './components/Header'

export default function App() {
  return (
    <div className="min-h-screen grid grid-cols-[260px_1fr]">
      <Sidebar />
      <main className="relative">
        <Header />
        <div className="p-6 lg:p-8 space-y-8 max-w-6xl mx-auto">
          <Outlet />
        </div>
      </main>
    </div>
  )
}

