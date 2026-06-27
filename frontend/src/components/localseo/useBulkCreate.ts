import { useEffect, useRef, useState } from 'react'
import { localSeoApi } from './api'

// Bulk page creation as background jobs: enqueue one generate job per selected
// keyword, then poll their status. The user can leave at any time (even switch
// clients) and the jobs keep running server-side — pages land in Saved Pages as
// they finish. Backs the "Plan Silo" and per-page "Related Pages" multi-select
// → bulk-create flows; both behave identically.
export function useBulkCreate(clientId: string, onCreated?: () => void) {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [creating, setCreating] = useState(false)
  const [detached, setDetached] = useState(false) // left while jobs still run
  const [total, setTotal] = useState(0)
  const [done, setDone] = useState(0)
  const [failed, setFailed] = useState(0)
  const [elapsed, setElapsed] = useState(0)

  const tickRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelledRef = useRef(false)

  // On unmount, stop the timer + poll. The jobs themselves keep running.
  useEffect(() => () => {
    cancelledRef.current = true
    if (tickRef.current) clearInterval(tickRef.current)
    if (pollRef.current) clearTimeout(pollRef.current)
  }, [])

  const stopTimers = () => {
    if (tickRef.current) { clearInterval(tickRef.current); tickRef.current = null }
    if (pollRef.current) { clearTimeout(pollRef.current); pollRef.current = null }
  }

  const toggle = (kw: string, checked: boolean) => setSelected(prev => {
    const next = new Set(prev)
    if (checked) next.add(kw); else next.delete(kw)
    return next
  })
  const setSelection = (kws: string[]) => setSelected(new Set(kws))
  const clear = () => setSelected(new Set())
  // Clear selection + outcome counters (e.g. when a new plan is run).
  const reset = () => { clear(); setTotal(0); setDone(0); setFailed(0); setDetached(false) }

  // Enqueue one background generate job per keyword, then poll. location/
  // locationCode are the seed area; each keyword already carries its own
  // sub-area / city.
  const start = async (queue: string[], location: string, locationCode: number | null) => {
    if (!queue.length || creating) return
    cancelledRef.current = false
    setCreating(true)
    setDetached(false)
    setTotal(queue.length)
    setDone(0)
    setFailed(0)
    setElapsed(0)
    stopTimers()
    tickRef.current = setInterval(() => setElapsed(s => s + 1), 1000)

    let jobIds: string[] = []
    try {
      const res = await localSeoApi.generateBulk(clientId, {
        keywords: queue, location: location.trim(), location_code: locationCode,
        force_refresh: false, page_template_url: null,
      })
      jobIds = res.job_ids ?? []
    } catch {
      stopTimers()
      setCreating(false)
      setFailed(queue.length)
      return
    }
    if (cancelledRef.current) return
    if (!jobIds.length) { stopTimers(); setCreating(false); return }
    setTotal(jobIds.length)

    const seen = new Set<string>()
    const poll = async () => {
      if (cancelledRef.current) return
      try {
        const statuses = await localSeoApi.jobsStatus(clientId, jobIds)
        if (cancelledRef.current) return
        let d = 0
        let f = 0
        let progressed = false
        for (const st of statuses) {
          if (st.status === 'complete') { d++; if (!seen.has(st.job_id)) { seen.add(st.job_id); progressed = true } }
          else if (st.status === 'failed') { f++; if (!seen.has(st.job_id)) { seen.add(st.job_id); progressed = true } }
        }
        setDone(d)
        setFailed(f)
        if (progressed) onCreated?.() // pages appear in Saved Pages as they finish
        if (d + f >= jobIds.length) {
          stopTimers()
          setCreating(false)
          clear()
          onCreated?.()
          return
        }
      } catch {
        // transient poll error — keep trying
      }
      pollRef.current = setTimeout(poll, 4000)
    }
    pollRef.current = setTimeout(poll, 4000)
  }

  // Leave the progress view without stopping the jobs — they finish server-side
  // and the pages keep dropping into Saved Pages.
  const leave = () => {
    cancelledRef.current = true
    stopTimers()
    setCreating(false)
    setDetached(true)
    clear()
    onCreated?.()
  }

  return { selected, toggle, setSelection, clear, reset, creating, detached, total, done, failed, elapsed, start, leave }
}
