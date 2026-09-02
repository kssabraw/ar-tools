import { useEffect, useRef, useState } from 'react'
import { matrixApi } from './api'
import type { MatrixAxis } from './MatrixAxesEditor'
import type { MatrixSuggestion } from './types'

// Suggest services / locations for a saved matrix: enqueue the axis job, poll
// until it settles, keep the suggestions per axis. One axis in flight at a time.
export function useSuggest(clientId: string, matrixId: string) {
  const [suggesting, setSuggesting] = useState<MatrixAxis | null>(null)
  const [services, setServices] = useState<MatrixSuggestion[]>([])
  const [locations, setLocations] = useState<MatrixSuggestion[]>([])
  const [notes, setNotes] = useState<string[]>([])
  const [error, setError] = useState('')
  const pollRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const cancelled = useRef(false)

  useEffect(() => () => {
    cancelled.current = true
    if (pollRef.current) clearTimeout(pollRef.current)
  }, [])

  const run = async (axis: MatrixAxis, seedService?: string | null) => {
    if (suggesting) return
    setSuggesting(axis)
    setError('')
    setNotes([])
    try {
      const { job_id } = await matrixApi.suggest(clientId, matrixId, { axis, seed_service: seedService ?? null })
      const poll = async () => {
        if (cancelled.current) return
        try {
          const res = await matrixApi.getSuggest(clientId, matrixId, job_id)
          if (res.status === 'complete') {
            if (axis === 'services') setServices(res.suggestions ?? [])
            else setLocations(res.suggestions ?? [])
            setNotes(res.degraded_notes ?? [])
            setSuggesting(null)
            return
          }
          if (res.status === 'failed') {
            setError(res.error || 'Suggestion failed')
            setSuggesting(null)
            return
          }
        } catch (e) {
          setError(e instanceof Error ? e.message : 'Suggestion failed')
          setSuggesting(null)
          return
        }
        pollRef.current = setTimeout(poll, 3000)
      }
      pollRef.current = setTimeout(poll, 2000)
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not start suggestions')
      setSuggesting(null)
    }
  }

  return { suggesting, services, locations, notes, error, run }
}
