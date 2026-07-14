import { useEffect, useRef, useState } from 'react'
import { ecommerceApi } from './api'
import type { EcommercePageType } from './types'

// Bulk page creation as background jobs: enqueue one generate job per keyword,
// then poll their status. The user can leave at any time (even switch clients)
// and the jobs keep running server-side — pages land in Saved Pages as they
// finish. Ecommerce analogue of the Local SEO useBulkCreate hook, but the
// generate signature is (keywords, page_type) with no location.
export function useBulkGenerate(clientId: string, onCreated?: () => void) {
  const [creating, setCreating] = useState(false)
  const [detached, setDetached] = useState(false) // left while jobs still run
  const [total, setTotal] = useState(0)
  const [done, setDone] = useState(0)
  const [failed, setFailed] = useState(0)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState('') // enqueue failed

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

  const reset = () => { setTotal(0); setDone(0); setFailed(0); setDetached(false); setError('') }

  // Enqueue one background generate job per keyword, then poll.
  const start = async (keywords: string[], pageType: EcommercePageType, notes?: string | null) => {
    const queue = keywords.map(k => k.trim()).filter(Boolean)
    if (!queue.length || creating) return
    cancelledRef.current = false
    setCreating(true)
    setDetached(false)
    setError('')
    setTotal(queue.length)
    setDone(0)
    setFailed(0)
    setElapsed(0)
    stopTimers()
    tickRef.current = setInterval(() => setElapsed(s => s + 1), 1000)

    let jobIds: string[] = []
    try {
      const res = await ecommerceApi.generateBulk(clientId, { keywords: queue, page_type: pageType, notes: notes?.trim() || null })
      jobIds = res.job_ids ?? []
    } catch (e) {
      stopTimers()
      setCreating(false)
      setTotal(0)
      setError(e instanceof Error ? e.message : 'Could not start generation')
      return
    }
    if (cancelledRef.current) return
    if (!jobIds.length) { stopTimers(); setCreating(false); return }
    setTotal(jobIds.length)

    const seen = new Set<string>()
    const poll = async () => {
      if (cancelledRef.current) return
      try {
        const statuses = await ecommerceApi.jobsStatus(clientId, jobIds)
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
    onCreated?.()
  }

  // Stop the batch: cancel the client's queued ecommerce jobs, then tear down the
  // poll/tick timers like leave() so the bar stops. Jobs already running finish.
  const stop = async () => {
    cancelledRef.current = true
    stopTimers()
    setCreating(false)
    try { await ecommerceApi.cancelJobs(clientId) } catch { /* best-effort — UI already stopped */ }
    onCreated?.()
  }

  return { creating, detached, total, done, failed, elapsed, error, start, leave, stop, reset }
}
