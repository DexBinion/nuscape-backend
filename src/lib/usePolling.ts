import { useEffect, useRef } from 'react'

export function usePolling(fn: () => void | Promise<void>, ms: number) {
  const timer = useRef<number | null>(null)
  useEffect(() => {
    let mounted = true
    const tick = async () => {
      if (!mounted) return
      await fn()
      timer.current = window.setTimeout(tick, ms)
    }
    tick()
    return () => {
      mounted = false
      if (timer.current) clearTimeout(timer.current)
    }
  }, [fn, ms])
}

