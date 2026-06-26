import { useEffect, useRef, useState } from 'react'
import { localSeoApi } from './api'

// Sequential bulk page creation — generate each selected keyword in turn via the
// normal generate flow (which saves server-side). One long generation at a time
// keeps progress honest and isolates per-page failures. Backs the "Plan Silo"
// and per-page "Related Pages" multi-select → bulk-create flows; both behave
// identically. No new backend: it's just the generate endpoint in a loop.
export function useBulkCreate(clientId: string, onCreated?: () => void) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [creating, setCreating] = useState(false)
  const [progress, setProgress] = useState<{ current: number; total: number; currentKw: string } | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [done, setDone] = useState(0)
  const [failed, setFailed] = useState(0)

  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const cancelledRef = useRef(false)
  const abortRef = useRef<AbortController | null>(null)

  // Stop the timer and abort any in-flight generate if the host unmounts mid-run.
  useEffect(() => () => {
    if (tickRef.current) clearInterval(tickRef.current)
    abortRef.current?.abort()
  }, [])

  const toggle = (kw: string, checked: boolean) => setSelected(prev => {
    const next = new Set(prev)
    if (checked) next.add(kw); else next.delete(kw)
    return next
  })
  const setSelection = (kws: string[]) => setSelected(new Set(kws))
  const clear = () => setSelected(new Set())
  // Clear selection + outcome counters (e.g. when a new plan is run).
  const reset = () => { clear(); setDone(0); setFailed(0) }

  // Generate each keyword in `queue` sequentially. location/locationCode are the
  // seed area; each keyword already carries its own sub-area / city.
  const start = async (queue: string[], location: string, locationCode: number | null) => {
    if (!queue.length || creating) return
    cancelledRef.current = false
    abortRef.current = new AbortController()
    setCreating(true)
    setDone(0)
    setFailed(0)
    setElapsed(0)
    if (tickRef.current) clearInterval(tickRef.current)
    tickRef.current = setInterval(() => setElapsed(s => s + 1), 1000)

    let nDone = 0
    let nFailed = 0
    for (let i = 0; i < queue.length; i++) {
      if (cancelledRef.current) break
      setProgress({ current: i + 1, total: queue.length, currentKw: queue[i] })
      try {
        await localSeoApi.generate(
          clientId,
          { keyword: queue[i], location: location.trim(), location_code: locationCode, force_refresh: false, page_template_url: null },
          abortRef.current?.signal,
        )
        if (cancelledRef.current) break
        nDone++; setDone(nDone)
      } catch {
        if (cancelledRef.current) break
        nFailed++; setFailed(nFailed)
      }
    }

    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null }
    abortRef.current = null
    setCreating(false)
    setProgress(null)
    // Drop the handled keywords (failed ones too — re-select to retry).
    clear()
    onCreated?.()
  }

  const cancel = () => {
    cancelledRef.current = true
    abortRef.current?.abort()
    abortRef.current = null
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null }
  }

  return { selected, toggle, setSelection, clear, reset, creating, progress, elapsed, done, failed, start, cancel }
}
