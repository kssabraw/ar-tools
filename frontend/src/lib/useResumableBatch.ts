import { useCallback, useEffect, useRef, useState } from 'react'

// Drive a BATCH of async jobs (one per item) with reconnect-on-return.
//
// Bulk actions (Local SEO / Ecommerce bulk create + reoptimize, …) enqueue one
// async_jobs row per item server-side, so the work finishes whether or not this
// tab is open. This hook makes the *UI* survive the same navigation: it persists
// the batch's job ids in localStorage (keyed by `storageKey`) and, on remount,
// resumes polling and re-displays progress — the suite's "leave & finish in the
// background" affordance.
//
// It's the batch sibling of `useResumableJob` (single job). `poll` is
// module-specific (each module has its own `.../jobs/status` endpoint); the
// persistence, resume, and progress bookkeeping are shared here.

export interface BatchJobRow {
  id: string
  status: string // pending | running | complete | failed | cancelled
  error?: string | null
  result?: Record<string, unknown> | null
  // Live progress for a running generate/reoptimize job (0–100 + stage message);
  // absent for job types / modules that don't report it.
  progress?: number | null
  progress_message?: string | null
}

const TERMINAL = new Set(['complete', 'failed', 'cancelled'])

interface Persisted<M> {
  jobIds: string[]
  meta: M
}

interface Options<M> {
  // Unique localStorage key for this batch (include the client id + sub-scope so
  // concurrent batches don't collide).
  storageKey: string
  // Fetch the current status of the batch's jobs. Module-supplied.
  poll: (jobIds: string[]) => Promise<BatchJobRow[]>
  // Fired once when every job reaches a terminal state (the batch finished).
  onDone?: (rows: BatchJobRow[], meta: M, resumed: boolean) => void
  intervalMs?: number
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

export function useResumableBatch<M = undefined>(opts: Options<M>) {
  const { storageKey, intervalMs = 4000, autoResume = true } = opts
  const [batch, setBatch] = useState<Persisted<M> | null>(() =>
    autoResume ? readStore<M>(storageKey) : null,
  )
  const [rows, setRows] = useState<BatchJobRow[]>([])

  const cbRef = useRef(opts)
  useEffect(() => { cbRef.current = opts })
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const cancelledRef = useRef(false)
  const doneRef = useRef(false)

  // Begin a fresh batch: persist the ids and start polling.
  const start = useCallback((jobIds: string[], meta: M) => {
    const next = { jobIds, meta }
    writeStore(storageKey, next)
    doneRef.current = false
    setRows([])
    setBatch(next)
  }, [storageKey])

  // Forget the batch: stop polling and clear the persisted ids. The server jobs
  // still finish; we simply won't reconnect to them.
  const clear = useCallback(() => {
    writeStore(storageKey, null)
    setRows([])
    setBatch(null)
  }, [storageKey])

  // Stop polling but LEAVE the persisted ids so a later mount resumes ("leave &
  // finish in the background"). The completion notification still lands.
  const detach = useCallback(() => {
    if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    cancelledRef.current = true
    setBatch(null)
  }, [])

  useEffect(() => {
    if (!batch) return
    cancelledRef.current = false

    const tick = async () => {
      try {
        const fetched = await cbRef.current.poll(batch.jobIds)
        if (cancelledRef.current) return
        setRows(fetched)
        const finished =
          fetched.length > 0 && fetched.every((j) => TERMINAL.has(j.status))
        if (finished && !doneRef.current) {
          doneRef.current = true
          if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
          writeStore(cbRef.current.storageKey, null)
          cbRef.current.onDone?.(fetched, batch.meta, false)
        }
      } catch {
        /* transient poll failure — retry next tick rather than tearing down */
      }
    }

    void tick()
    timerRef.current = setInterval(tick, intervalMs)
    return () => {
      cancelledRef.current = true
      if (timerRef.current) { clearInterval(timerRef.current); timerRef.current = null }
    }
  }, [batch, intervalMs])

  const finished = rows.filter((r) => TERMINAL.has(r.status)).length
  const failed = rows.filter((r) => r.status === 'failed').length
  const total = batch?.jobIds.length ?? 0
  const running = Boolean(batch) && (rows.length === 0 || finished < rows.length)

  return { batch, rows, meta: batch?.meta, start, clear, detach, running, finished, failed, total }
}
