import { useEffect, useRef, useState } from 'react'
import { localSeoApi } from './api'
import type { RelatedPageItem } from './types'

// Drives the Fanout-powered silo plan: kick off the async job and poll until it
// completes/fails. Shared by the "Plan Silo" tab and the per-page "Related
// Pages" tab so both behave identically. A monotonic run token invalidates an
// in-flight poll loop when a new run starts, the caller resets, or it unmounts —
// so stale results can never land.
export function useSiloPlan(clientId: string) {
  const [items, setItems] = useState<RelatedPageItem[] | null>(null)
  const [notes, setNotes] = useState<string[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const runRef = useRef(0)
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => {
    runRef.current++
    if (pollRef.current) clearTimeout(pollRef.current)
  }, [])

  const reset = () => {
    runRef.current++
    if (pollRef.current) clearTimeout(pollRef.current)
    setItems(null)
    setNotes([])
    setError('')
    setLoading(false)
  }

  const run = async (keyword: string, location: string, locationCode?: number | null) => {
    if (!keyword.trim() || !location.trim()) return
    setError('')
    setLoading(true)
    setItems(null)
    setNotes([])
    const myRun = ++runRef.current // invalidates any prior in-flight poll loop
    try {
      const { job_id } = await localSeoApi.startSiloPlan(clientId, {
        keyword: keyword.trim(), location: location.trim(), location_code: locationCode ?? null,
      })
      while (runRef.current === myRun) {
        await new Promise<void>(resolve => { pollRef.current = setTimeout(resolve, 3000) })
        if (runRef.current !== myRun) return
        const res = await localSeoApi.getSiloPlan(clientId, job_id)
        if (res.status === 'complete') {
          setItems(res.items ?? [])
          setNotes(res.degraded_notes ?? [])
          break
        }
        if (res.status === 'failed') {
          setError(res.error || 'Silo planning failed')
          break
        }
      }
    } catch (e) {
      if (runRef.current === myRun) setError(e instanceof Error ? e.message : 'Silo planning failed')
    } finally {
      if (runRef.current === myRun) setLoading(false)
    }
  }

  return { items, notes, loading, error, run, reset }
}
