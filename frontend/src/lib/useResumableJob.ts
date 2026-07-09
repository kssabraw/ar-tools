import { useCallback, useEffect, useRef, useState } from 'react'

// Drive a backgrounded async job (enqueue → poll) with reconnect-on-return.
//
// The Local SEO / Brand Voice / ICP long-running actions run server-side as
// async_jobs, so the work completes even if the user navigates away. This hook
// makes the *UI* survive the same navigation: it persists the in-flight job id
// in localStorage (keyed by `storageKey`) and, on remount, resumes polling and
// re-displays the result when it lands — instead of losing it.
//
// `poll` is module-specific (Local SEO polls .../jobs/status; Brand Voice / ICP
// poll .../scan/{job_id}); everything else is shared here.

export type JobPhase = 'idle' | 'running' | 'complete' | 'failed'

export interface JobPoll<T> {
  status: string // pending | running | complete | failed | cancelled
  result?: T | null
  error?: string | null
}

interface Persisted<M> {
  jobId: string
  meta: M
}

interface Options<T, M> {
  // Unique localStorage key for this operation (include the client id, and any
  // sub-scope like a page url, so concurrent operations don't collide).
  storageKey: string
  poll: (jobId: string) => Promise<JobPoll<T>>
  onComplete: (result: T | null, meta: M, resumed: boolean) => void
  onError?: (error: string, meta: M, resumed: boolean) => void
  intervalMs?: number
  // Re-poll a persisted job id on mount (reconnect after navigating away).
  autoResume?: boolean
}

function readStore<M>(key: string): Persisted<M> | null {
  try {
    const raw = localStorage.getItem(key)
    return raw ? (JSON.parse(raw) as Persisted<M>) : null
  } catch {
    return null
  }
}
function writeStore<M>(key: string, value: Persisted<M> | null) {
  try {
    if (value) localStorage.setItem(key, JSON.stringify(value))
    else localStorage.removeItem(key)
  } catch {
    /* storage unavailable (private mode / quota) — degrade to non-resumable */
  }
}

export function useResumableJob<T, M = undefined>(opts: Options<T, M>) {
  const { storageKey, intervalMs = 3000, autoResume = true } = opts
  // Start 'running' when a job is already persisted so the consumer renders the
  // busy state immediately on remount (and skips kicking off a duplicate).
  const [phase, setPhase] = useState<JobPhase>(() =>
    autoResume && readStore(storageKey) ? 'running' : 'idle',
  )
  const [elapsed, setElapsed] = useState(0)

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelledRef = useRef(false)
  // Keep the latest callbacks without re-subscribing the poll loop. Synced in an
  // effect (not during render) so the poll loop, which runs on timers after
  // commit, always reads the current callbacks.
  const cbRef = useRef(opts)
  useEffect(() => { cbRef.current = opts })

  const clearTimers = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    if (pollRef.current) { clearTimeout(pollRef.current); pollRef.current = null }
  }, [])

  // Start the once-a-second elapsed interval. The interval callback's setState is
  // deferred (safe to call from an effect); resetting `elapsed` to 0 is a separate
  // step only the event-handler path (start) needs — on a reconnect mount elapsed
  // is already its fresh 0, so we don't setState synchronously in the effect.
  const runInterval = useCallback(() => {
    if (timerRef.current) clearInterval(timerRef.current)
    timerRef.current = setInterval(() => setElapsed(s => s + 1), 1000)
  }, [])
  const startTicker = useCallback(() => {
    setElapsed(0)
    runInterval()
  }, [runInterval])

  const drive = useCallback((jobId: string, meta: M, resumed: boolean) => {
    cancelledRef.current = false
    if (pollRef.current) clearTimeout(pollRef.current)
    const tick = async () => {
      if (cancelledRef.current) return
      try {
        const st = await cbRef.current.poll(jobId)
        if (cancelledRef.current) return
        if (st.status === 'complete') {
          clearTimers()
          writeStore(cbRef.current.storageKey, null)
          setPhase('complete')
          cbRef.current.onComplete(st.result ?? null, meta, resumed)
          return
        }
        if (st.status === 'failed' || st.status === 'cancelled') {
          clearTimers()
          writeStore(cbRef.current.storageKey, null)
          setPhase('failed')
          cbRef.current.onError?.(st.error || 'job_failed', meta, resumed)
          return
        }
      } catch {
        // transient poll error — keep trying
      }
      pollRef.current = setTimeout(tick, intervalMs)
    }
    pollRef.current = setTimeout(tick, intervalMs)
  }, [clearTimers, intervalMs])

  // Enqueue a fresh job, persist it, then poll. `enqueue` returns the job id.
  const start = useCallback(async (enqueue: () => Promise<string>, meta: M) => {
    cancelledRef.current = false
    setPhase('running')
    startTicker()
    let jobId: string
    try {
      jobId = await enqueue()
    } catch (e) {
      clearTimers()
      setPhase('failed')
      cbRef.current.onError?.(e instanceof Error ? e.message : 'enqueue_failed', meta, false)
      return
    }
    if (cancelledRef.current) return
    writeStore(cbRef.current.storageKey, { jobId, meta })
    drive(jobId, meta, false)
  }, [clearTimers, drive, startTicker])

  // Stop polling without touching the job or its persisted id — the work keeps
  // running server-side and a later remount reconnects to it.
  const detach = useCallback(() => {
    cancelledRef.current = true
    clearTimers()
    setPhase('idle')
  }, [clearTimers])

  // Abandon the operation from the UI: stop polling and forget the job id (the
  // server job still finishes, but we won't reconnect to it).
  const reset = useCallback(() => {
    cancelledRef.current = true
    clearTimers()
    writeStore(storageKey, null)
    setPhase('idle')
  }, [clearTimers, storageKey])

  // On mount, reconnect to a persisted job (if any). On unmount, stop polling
  // but leave the persisted id so the next mount resumes.
  useEffect(() => {
    if (autoResume) {
      const p = readStore<M>(storageKey)
      if (p) {
        // elapsed is already its fresh 0 on this mount; just start the interval
        // (no synchronous setState in the effect) and resume polling.
        runInterval()
        drive(p.jobId, p.meta, true)
      }
    }
    return () => {
      cancelledRef.current = true
      clearTimers()
    }
    // storageKey identifies the operation; re-run if it changes (e.g. new page).
  }, [storageKey, autoResume, drive, runInterval, clearTimers])

  return { phase, elapsed, start, detach, reset, running: phase === 'running' }
}
