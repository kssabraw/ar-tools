import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'

// Bulk publish for already-generated content. Unlike useBulkCreate (page
// generation, which takes minutes and runs as async jobs), publishing is a fast
// synchronous call per item — so this fans out client-side over the existing
// per-item publish endpoints with a small concurrency cap and tracks per-item
// outcomes. No new backend surface, no jobs.
//
// Each item can be published to the client's Google Drive (a new Google Doc),
// straight to their WordPress site, or both. The destination is chosen once for
// the whole batch.

export type PublishItemType = 'run' | 'local_seo_page' | 'ecommerce_page'
// Where a batch publishes to. 'both' fans out to Google Docs *and* WordPress
// per item (two calls). 'github' commits to the client's repo.
export type PublishDestination = 'google_docs' | 'wordpress' | 'github' | 'both'
// WordPress only: save as an unpublished draft or go live immediately.
export type WpStatus = 'draft' | 'publish'

export interface PublishItem {
  key: string // unique selection key, e.g. `run:<id>` / `lsp:<id>`
  type: PublishItemType
  id: string
  label: string
}

export type ItemStatus = 'queued' | 'publishing' | 'done' | 'failed'

export interface ItemResult {
  status: ItemStatus
  docUrl?: string | null // Google Doc link
  siteUrl?: string | null // WordPress link (edit link preferred, else live URL)
  repoUrl?: string | null // GitHub committed-file link
  error?: string
}

// How many publishes to run at once. The Apps Script webhook / WordPress REST
// API is the bottleneck; a small cap keeps things moving without hammering it.
const CONCURRENCY = 3

function endpointFor(item: PublishItem): string {
  return item.type === 'local_seo_page'
    ? `/local-seo/pages/${item.id}/publish`
    : item.type === 'ecommerce_page'
      ? `/ecommerce/pages/${item.id}/publish`
      : `/runs/${item.id}/publish`
}

// Publish a single item to one target, returning whichever URL that target
// produced. Throws on failure (caller records the error).
async function publishToTarget(
  item: PublishItem,
  target: 'google_docs' | 'wordpress' | 'github',
  wpStatus: WpStatus,
): Promise<{ docUrl?: string | null; siteUrl?: string | null; repoUrl?: string | null }> {
  const path = endpointFor(item)
  if (target === 'wordpress') {
    const res = await api.post<{ url?: string | null; edit_url?: string | null }>(
      path,
      { destination: 'wordpress', status: wpStatus },
    )
    return { siteUrl: res?.edit_url ?? res?.url ?? null }
  }
  if (target === 'github') {
    const res = await api.post<{ url?: string | null }>(path, { destination: 'github' })
    return { repoUrl: res?.url ?? null }
  }
  const res = await api.post<{ doc_url?: string | null }>(path, { destination: 'google_docs' })
  return { docUrl: res?.doc_url ?? null }
}

const TARGET_LABEL: Record<'google_docs' | 'wordpress' | 'github', string> = {
  google_docs: 'Google Docs',
  wordpress: 'Website',
  github: 'GitHub',
}

// Publish one item to the requested destination(s), aggregating the outcome into
// a single ItemResult. For 'both', a partial success (one target worked, the
// other failed) is reported as 'failed' but still surfaces the URL that did
// land, so the user can see what happened and decide whether to retry.
async function publishItem(
  item: PublishItem,
  destination: PublishDestination,
  wpStatus: WpStatus,
): Promise<ItemResult> {
  const targets: ('google_docs' | 'wordpress' | 'github')[] =
    destination === 'both' ? ['google_docs', 'wordpress'] : [destination]

  let docUrl: string | null | undefined
  let siteUrl: string | null | undefined
  let repoUrl: string | null | undefined
  const errors: string[] = []

  for (const target of targets) {
    try {
      const r = await publishToTarget(item, target, wpStatus)
      if ('docUrl' in r) docUrl = r.docUrl
      if ('siteUrl' in r) siteUrl = r.siteUrl
      if ('repoUrl' in r) repoUrl = r.repoUrl
    } catch (e) {
      const msg = e instanceof Error ? e.message : 'publish_failed'
      errors.push(targets.length > 1 ? `${TARGET_LABEL[target]}: ${msg}` : msg)
    }
  }

  // Every requested target failed → a clean failure.
  if (errors.length === targets.length) {
    return { status: 'failed', error: errors.join(' · ') }
  }
  // At least one target landed. A leftover error means a partial publish —
  // keep it visible (and retryable) while still showing the URL that worked.
  return {
    status: errors.length ? 'failed' : 'done',
    docUrl,
    siteUrl,
    repoUrl,
    error: errors.length ? errors.join(' · ') : undefined,
  }
}

export function useBulkPublish() {
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [publishing, setPublishing] = useState(false)
  const [results, setResults] = useState<Record<string, ItemResult>>({})
  const [destination, setDestination] = useState<PublishDestination>('google_docs')
  const [wpStatus, setWpStatus] = useState<WpStatus>('draft')
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
        const outcome = await publishItem(item, destination, wpStatus)
        if (cancelledRef.current) return
        setResults(r => ({ ...r, [item.key]: outcome }))
      }
    }

    await Promise.all(
      Array.from({ length: Math.min(CONCURRENCY, queue.length) }, worker),
    )
    if (cancelledRef.current) return
    setPublishing(false)
    // Drop everything that published cleanly from the selection so a re-publish
    // (which creates a fresh Doc / post) has to be a deliberate re-tick; leave
    // failures (incl. partials) selected so they can be retried with the button.
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
  }, [selected, publishing, destination, wpStatus])

  return {
    selected, toggle, setSelection, clear, reset, publishing, results, start,
    destination, setDestination, wpStatus, setWpStatus,
  }
}
