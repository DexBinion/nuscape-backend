export default function Settings() {
  return (
    <div className="space-y-4">
      <div className="card p-6">
        <div className="font-medium mb-2">Appearance</div>
        <div className="hint">Dark by default. Light mode later if we get bored.</div>
      </div>
      <div className="card p-6">
        <div className="font-medium mb-2">API</div>
        <div className="hint">Set VITE_API_BASE in your .env to your Replit backend. Optional token: VITE_API_TOKEN.</div>
      </div>
    </div>
  )
}

