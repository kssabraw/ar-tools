import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'

// Bulk "publish to Google Docs" for already-generated content. Unlike
// useBulkCreate (page generation, which takes minutes and runs as async jobs),
// publishing is a fast synchronous call per item — so this fans out client-side
// over the existing per-item publish endpoints with a small concurrency cap and
// tracks per-item outcomes. No new backend surface, no jobs.

export type PublishItemType = 'run' | 'local_seo_page'

export interface PublishItem {
  key: string // unique selection key, e.g. `run:<id>` / `lsp:<id>`
  type: PublishItemType
  id: string
  label: string
}

export type ItemStatus = 'queued' | 'publishing' | 'done' | 'failed'

export interface ItemResult {
  status: ItemStatus
  docUrl?: string | null
  error?: string
}

// How many publishes to run at once. The Apps Script webhook is the bottleneck;
// a small cap keeps things moving without hammering it.
const CONCURRENCY = 3

function publishOne(item: PublishItem): Promise<{ doc_url?: string | null }> {
  const path =
    item.type === 'local_seo_page'
      ? `/local-seo/pages/${item.id}/publish`
      : `/runs/${item.id}/publish`
  return api.post<{ doc_url?: string | null }>(path, { destination: 'google_docs' })
}

export function useBulkPublish() {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [publishing, setPublishing] = useState(false)
  const [results, setResults] = useState<Record<string, ItemResult>>({})
  const cancelledRef = useRef(false)

  // On unmount, stop applying results (the in-flight fetches resolve harmlessly).
  useEffect(() => () => { cancelledRef.current = true }, [])

  const toggle = (key: string, checked: boolean) => setSelected(prev => {
    const next = new Set(prev)
    if (checked) next.add(key); else next.delete(key)
    return next
  })
  const setSelection = (keys: string[]) => setSelected(new Set(keys))
  const clear = () => setSelected(new Set())
  // Clear selection + the previous run's outcome list.
  const reset = () => { clear(); setResults({}); setPublishing(false) }

  const start = useCallback(async (items: PublishItem[]) => {
    const queue = items.filter(i => selected.has(i.key))
    if (!queue.length || publishing) return
    cancelledRef.current = false
    setPublishing(true)
    setResults(Object.fromEntries(queue.map(i => [i.key, { status: 'queued' as ItemStatus }])))

    let next = 0
    const worker = async () => {
      for (;;) {
        if (cancelledRef.current) return
        const cur = next++
        if (cur >= queue.length) return
        const item = queue[cur]
        setResults(r => ({ ...r, [item.key]: { status: 'publishing' } }))
        try {
          const res = await publishOne(item)
          if (cancelledRef.current) return
          setResults(r => ({ ...r, [item.key]: { status: 'done', docUrl: res?.doc_url ?? null } }))
        } catch (e) {
          if (cancelledRef.current) return
          setResults(r => ({
            ...r,
            [item.key]: { status: 'failed', error: e instanceof Error ? e.message : 'publish_failed' },
          }))
        }
      }
    }

    await Promise.all(
      Array.from({ length: Math.min(CONCURRENCY, queue.length) }, worker),
    )
    if (cancelledRef.current) return
    setPublishing(false)
    // Drop everything that published cleanly from the selection so a re-publish
    // (which creates a fresh Doc) has to be a deliberate re-tick; leave failures
    // selected so they can be retried with the same button.
    setResults(current => {
      setSelected(prev => {
        const nextSel = new Set(prev)
        for (const item of queue) {
          if (current[item.key]?.status === 'done') nextSel.delete(item.key)
        }
        return nextSel
      })
      return current
    })
  }, [selected, publishing])

  return { selected, toggle, setSelection, clear, reset, publishing, results, start }
}
