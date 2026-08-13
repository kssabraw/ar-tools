import { useState } from 'react'
import type { CSSProperties } from 'react'
import { Gauge, Sparkles } from 'lucide-react'
import { useResumableJob } from '../../lib/useResumableJob'
import { Spinner } from '../localseo/Spinner'
import { scoreColor } from '../localseo/shared'
import type { ScoreResult } from '../localseo/types'
import { reoptApi } from './api'

// Score + reoptimize a completed BLOG run in place, against the 8 engines.
// Mirrors the Service page run view's score section but talks to the blog
// job endpoints (blog-score-async / blog-reoptimize-async → blog-score-jobs).
// Both run as resumable async jobs, so the work survives navigating away or a
// deploy mid-run and reconnects on remount. A reoptimize rewrites the run in
// place; `onReoptimized` lets the parent refetch the run to re-render the article.

type ScoreJobResult = { score?: ScoreResult | null; page?: unknown }

export function BlogScorePanel({ runId, onReoptimized }: { runId: string; onReoptimized?: () => void }) {
  const [score, setScore] = useState<ScoreResult | null>(null)
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [jobError, setJobError] = useState<string | null>(null)

  const jobKey = `blog:score:${runId}`
  // Seed the busy label from a persisted job so a resumed op keeps the right one.
  const [opKind, setOpKind] = useState<'score' | 'reopt' | null>(() => {
    try {
      const raw = localStorage.getItem(jobKey)
      const kind = raw ? (JSON.parse(raw) as { meta?: { kind?: string } }).meta?.kind : null
      return kind === 'score' || kind === 'reopt' ? kind : null
    } catch {
      return null
    }
  })

  const job = useResumableJob<ScoreJobResult, { kind: 'score' | 'reopt' }>({
    storageKey: jobKey,
    poll: async (jobId) => {
      const r = await reoptApi.blogScoreJob(runId, jobId)
      return { status: r.status, error: r.error, result: { score: r.score, page: r.page } }
    },
    onComplete: (result, meta) => {
      setOpKind(null)
      if (result?.score) setScore(result.score)
      setSelected(new Set())
      if (meta.kind === 'reopt') onReoptimized?.()
    },
    onError: (error, meta) => {
      setOpKind(null)
      setJobError(`${meta.kind === 'reopt' ? 'Could not reoptimize.' : 'Could not score the article.'} ${error}`)
    },
  })
  const scoring = job.running && opKind === 'score'
  const reoptimizing = job.running && opKind === 'reopt'

  const startScore = () => {
    setJobError(null)
    setOpKind('score')
    void job.start(async () => (await reoptApi.blogScoreAsync(runId)).job_id, { kind: 'score' })
  }
  const startReoptimize = () => {
    const defs = (score?.deficiencies ?? []).filter(d => selected.size === 0 || selected.has(d.engine_key))
    setJobError(null)
    setOpKind('reopt')
    void job.start(
      async () => (await reoptApi.blogReoptimizeAsync(runId, defs as unknown as Array<Record<string, unknown>>)).job_id,
      { kind: 'reopt' },
    )
  }

  return (
    <div style={cardStyle}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={{ fontSize: 15, fontWeight: 600, color: '#0f172a', margin: 0 }}>Article score</h2>
        <button type="button" onClick={startScore} disabled={job.running} style={btnStyle}>
          <Gauge size={14} /> {scoring ? 'Scoring…' : score ? 'Re-score' : 'Score'}
        </button>
        {score && (
          <button
            type="button"
            onClick={startReoptimize}
            disabled={job.running}
            style={{ ...btnStyle, color: '#fff', background: '#6366f1', borderColor: '#6366f1' }}
          >
            <Sparkles size={14} /> {reoptimizing ? 'Reoptimizing…' : selected.size ? `Reoptimize (${selected.size})` : 'Reoptimize'}
          </button>
        )}
        {job.running && <Spinner size={14} />}
      </div>

      {jobError && <div style={errStyle}>{jobError}</div>}
      {reoptimizing && (
        <div style={{ fontSize: 13, color: '#64748b', marginTop: 8 }}>
          Rewriting the article to fix the selected issues — this can take a couple of minutes, then it re-scores.
          It runs in the background, so navigating away (or a server update) won&apos;t lose it.
        </div>
      )}

      {score ? (
        <div style={{ marginTop: 12 }}>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: 10 }}>
            <span style={{ fontSize: 34, fontWeight: 800, color: scoreColor(score.composite_score) }}>
              {Math.round(score.composite_score)}
            </span>
            <span style={{ fontSize: 13, color: '#64748b' }}>/ 100 · {score.composite_status}</span>
          </div>
          {score.deficiencies?.length ? (
            <>
              <p style={{ fontSize: 13, color: '#475569', margin: '12px 0 6px' }}>
                Select issues to fix, then Reoptimize (none selected = fix all):
              </p>
              {score.deficiencies.map((d) => (
                <label key={d.engine_key} style={defRow}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <input
                      type="checkbox"
                      checked={selected.has(d.engine_key)}
                      onChange={(e) => setSelected((prev) => {
                        const n = new Set(prev)
                        if (e.target.checked) n.add(d.engine_key); else n.delete(d.engine_key)
                        return n
                      })}
                    />
                    <span style={{ fontWeight: 600, fontSize: 13, color: '#0f172a' }}>{d.engine}</span>
                    <span style={{ fontSize: 12, color: scoreColor(d.score ?? 0) }}>{d.score ?? 0}/100</span>
                  </div>
                  {!!d.issues?.length && <ul style={defListStyle}>{d.issues.map((i, k) => <li key={k}>{i}</li>)}</ul>}
                  {!!d.recommendations?.length && (
                    <ul style={{ ...defListStyle, color: '#16a34a' }}>{d.recommendations.map((r, k) => <li key={k}>{r}</li>)}</ul>
                  )}
                </label>
              ))}
            </>
          ) : (
            <p style={{ fontSize: 13, color: '#16a34a', marginTop: 10 }}>No deficiencies — this article scores well across all engines.</p>
          )}
        </div>
      ) : (
        !scoring && (
          <p style={{ fontSize: 13, color: '#64748b', marginTop: 10 }}>
            Score this article against the SEO/AEO engines to see per-engine deficiencies, then reoptimize it in place.
          </p>
        )
      )}
    </div>
  )
}

const cardStyle: CSSProperties = { background: '#fff', borderRadius: 12, border: '1px solid #e2e8f0', padding: 24, marginBottom: 20 }
const btnStyle: CSSProperties = { display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 13, padding: '6px 12px', border: '1px solid #e2e8f0', borderRadius: 8, background: '#fff', color: '#334155', cursor: 'pointer' }
const errStyle: CSSProperties = { color: '#dc2626', fontSize: 13, marginTop: 8 }
const defRow: CSSProperties = { display: 'block', border: '1px solid #e2e8f0', borderRadius: 8, padding: 10, marginBottom: 8, cursor: 'pointer' }
const defListStyle: CSSProperties = { margin: '6px 0 0 26px', padding: 0, fontSize: 12.5, color: '#64748b', lineHeight: 1.5 }
