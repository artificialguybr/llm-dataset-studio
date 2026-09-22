/* shared — vocabulary, helpers, icons, hooks, shell components for text dataset UI. */
import { useCallback, useEffect, useRef, useState } from 'react'

import { api, type Job, type ModelCatalog } from './api'

export type Page = 'dashboard' | 'import' | 'analyze' | 'clean' | 'validate' | 'curate' | 'compose' | 'queue' | 'dataset' | 'records' | 'issues' | 'annotation' | 'versions' | 'export' | 'models'
export const ISSUE_TYPES = ['language', 'repetition', 'too-short', 'too-long', 'spam', 'code', 'pii', 'secrets', 'toxicity', 'safety', 'schema', 'contamination', 'missing', 'empty']

export const ISSUE_LABELS: Record<string, string> = {
  language: 'language', repetition: 'repetition', 'too-short': 'too short', 'too-long': 'too long',
  'too_short': 'too short', 'too_long': 'too long',
  spam: 'spam', spam_score: 'spam', code: 'code', code_ratio: 'code',
  pii: 'possible PII', pii_score: 'possible PII', secrets: 'secrets',
  toxicity: 'toxicity', safety: 'safety', schema: 'schema', missing: 'missing', empty: 'empty',
  contamination: 'contamination', duplication: 'duplicate',
}
export const STATUS_LABELS: Record<string, string> = {
  keep: 'kept', review: 'review', quarantine: 'quarantine',
  reject: 'rejected', pending: 'pending', approved: 'approved',
  rejected: 'rejected', acknowledged: 'acknowledged', open: 'open',
  error: 'error', restore: 'restored',
}
export const t = (s: string) => STATUS_LABELS[s] ?? ISSUE_LABELS[s] ?? s

// ---------- legacy compat (being phased out) ----------
export const ADV_KEYS: [string, string][] = [
  ['status', 'status'], ['issue', 'issue'], ['license', 'license'],
  ['label', 'label'], ['tag', 'tag'],
]
export const EXPLORER_PAGE = 60

export function apiErrorMessage(error: unknown) {
  const raw = error instanceof Error ? error.message : String(error)
  const payload = raw.replace(/^\d+:\s*/, '')
  try {
    const detail = JSON.parse(payload).detail
    if (typeof detail === 'string') return detail
  } catch { /* ignore */ }
  return payload
}
export type Theme = 'light' | 'dark'

// inline SVG icons, consistent stroke
export const I = {
  keep: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5"/></svg>,
  reject: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M18 6 6 18M6 6l12 12"/></svg>,
  review: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 8v4l3 3"/></svg>,
  quarantine: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>,
  undo: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7v6h6"/><path d="M21 17a9 9 0 0 0-9-9 9 9 0 0 0-6 2.3L3 13"/><path d="M21 17a9 9 0 0 1-9 9 9 9 0 0 1-6-2.3L3 22"/></svg>,
  fullscreen: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M8 3H5a2 2 0 0 0-2 2v3"/><path d="M21 8V5a2 2 0 0 0-2-2h-3"/><path d="M3 16v3a2 2 0 0 0 2 2h3"/><path d="M16 21h3a2 2 0 0 0 2-2v-3"/></svg>,
  check: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round"><path d="M20 6 9 17l-5-5"/></svg>,
  warn: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>,
  license: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v18"/><path d="M6 7h12"/><path d="M6 17h12"/><path d="M8 3h8"/></svg>,
  export: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v12"/><path d="m7 10 5 5 5-5"/><path d="M5 21h14"/></svg>,
  import: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 15V3"/><path d="m7 8 5-5 5 5"/><path d="M5 21h14"/></svg>,
  plus: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14"/><path d="M5 12h14"/></svg>,
  chevL: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m15 18-6-6 6-6"/></svg>,
  chevR: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m9 18 6-6-6-6"/></svg>,
  chevD: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m6 9 6 6 6-6"/></svg>,
  funnel: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 5h16l-6 7v5l-4 2v-7L4 5Z"/></svg>,
  bookmark: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M6 4h12v17l-6-4-6 4Z"/></svg>,
  info: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4"/><path d="M12 8h.01"/></svg>,
  text: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h10"/></svg>,
  chat: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>,
  code: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="16 18 22 12 16 6"/><polyline points="8 6 2 12 8 18"/></svg>,
  search: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg>,
  folder: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/></svg>,
}

// ---------- shared shell ----------

export function Page({ bar, children, foot }: { bar: React.ReactNode; children: React.ReactNode; foot?: React.ReactNode }) {
  return <div className="page">
    {bar}
    <div className="page-body">{children}</div>
    {foot && <div className="footbar">{foot}</div>}
  </div>
}
export function PageBar({ kicker, title, sub, children }: { kicker?: string; title: React.ReactNode; sub?: React.ReactNode; children?: React.ReactNode }) {
  return <div className="vhead">
    <div className="vhead-row">
      <div className="vhead-ttl">
        {kicker && <div className="kicker">{kicker}</div>}
        <h1>{title}</h1>
        {sub && <p className="lede">{sub}</p>}
      </div>
      <div className="vhead-actions">{children}</div>
    </div>
    <div className="hrule" />
  </div>
}

export const distBar = (counts: Record<string, number> | undefined, total: number) => {
  const segs: [string, number][] = [['keep', counts?.keep ?? 0], ['review', counts?.review ?? 0], ['quarantine', counts?.quarantine ?? 0], ['reject', counts?.reject ?? 0]]
  const known = segs.reduce((s, [, n]) => s + n, 0)
  if (total > known) segs.push(['pending', total - known])
  return <div className="distbar" role="img" aria-label={`distribution: ${segs.map(([k, n]) => `${t(k)} ${n}`).join(', ')}`}>
    {segs.filter(([, n]) => n > 0).map(([k, n]) => <span key={k} className={k} style={{ width: `${(n / total) * 100}%` }} />)}
  </div>
}

// ---------- hooks ----------

export function useJobs() {
  const [jobs, setJobs] = useState<Job[]>([])
  const loops = useRef<Set<string>>(new Set())
  useEffect(() => () => { loops.current.clear() }, [])
  const track = useCallback(async (id: string): Promise<Job> => {
    const j: Job = await api.job(id)
    setJobs(prev => {
      const known = prev.find(x => x.id === id)
      return known ? prev.map(x => x.id === id ? j : x) : [...prev, j]
    })
    return j
  }, [])
  const start = useCallback(async (fn: () => Promise<{ job_id: string }>, onDone: () => void) => {
    const { job_id } = await fn()
    loops.current.add(job_id)
    let delay = 800
    for (;;) {
      await new Promise<void>(resolve => window.setTimeout(resolve, delay))
      if (!loops.current.has(job_id)) return
      const j = await track(job_id)
      const st = j.status
      if (st === 'completed' || st === 'failed' || st === 'cancelled') {
        loops.current.delete(job_id)
        if (st === 'failed') throw new Error(j.error_summary || `job ${st}`)
        onDone()
        return
      }
      delay = Math.min(delay * 1.6, 5000)
    }
  }, [track])
  return { jobs, start }
}
export function useModelCatalog() {
  const [catalog, setCatalog] = useState<ModelCatalog | null>(null)
  const [error, setError] = useState('')
  const load = useCallback(() => api.modelCatalog()
    .then(value => { setError(''); setCatalog(value); return value })
    .catch(e => { setError(apiErrorMessage(e)); throw e }), [])
  useEffect(() => { load().catch(() => {}) }, [load])
  return { catalog, error, reload: load }
}
export function ModelPicker({ capability, value, onChange }: { capability: string; value: string; onChange: (value: string) => void }) {
  const { catalog } = useModelCatalog()
  const choices = catalog?.models.filter(model => model.capability === capability) ?? []
  const activeModel = choices.find(model => model.active)
  const selected = value || activeModel?.id || ''
  return <label className="model-picker">model
    <select value={selected} onChange={e => onChange(e.target.value)} aria-label={`${capability} model`}>
      <option value="">{`automatic${activeModel ? ` (${activeModel.name})` : ' (none installed)'}`}</option>
      {choices.map(model => <option key={model.id} value={model.id} disabled={!model.installed}>{model.name}{model.installed ? '' : ' · install first'}</option>)}
    </select>
  </label>
}

// no lightbox for text datasets — just placeholder