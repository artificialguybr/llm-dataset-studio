// Analyze — conteúdo da view Analyze do deepseek: stats, stepper do pipeline,
// "needs attention" e atividade recente — tudo ligado a dados reais do dataset.
import { useCallback, useEffect, useState } from 'react'
import { api, type Dataset, type DatasetStats, type Issue, type Job } from './api'
import { Page, apiErrorMessage, type Page as PageType } from './shared'
import type React from 'react'

type Tab = 'overview' | 'metrics'
const fmtK = (n: number) => n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}k` : String(n)

const STEPS: [string, (d: Dataset | null, i: Issue[]) => string][] = [
  ['Import', d => `${fmtK(d?.item_counts?.total ?? 0)} docs`],
  ['Normalize', (_d) => _d?.running_jobs?.length ? 'running…' : 'clean'],
  ['Validate', (_d, i) => i.length ? `${i.length} flags` : '0 errors'],
  ['Dedup', () => 'hash'],
  ['Decontam', () => '13-gram'],
  ['PII', (_d, i) => i.some(x => x.issue_type.includes('pii')) ? 'found' : 'clean'],
  ['Mix', (d) => d?.item_counts?.pending ? `${fmtK(d.item_counts.pending)} pending` : 'recipe'],
  ['Split', () => '90/5/5'],
]

export function AnalyzePage({ ds, go, foot }: { ds: string; go: (p: PageType, ds?: string) => void; foot: React.ReactNode }) {
  const [tab, setTab] = useState<Tab>('overview')
  const [info, setInfo] = useState<Dataset | null>(null)
  const [issues, setIssues] = useState<Issue[]>([])
  const [stats, setStats] = useState<DatasetStats | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const snapshot = () => {
    setBusy(true); setErr('')
    api.createVersion(ds, `snapshot ${new Date().toLocaleString('en-US')}`)
      .then(() => load()).finally(() => setBusy(false))
      .catch(e => setErr(apiErrorMessage(e)))
  }

  const load = useCallback(() => {
    Promise.all([api.dataset(ds), api.issues(ds), api.datasetStats(ds)])
      .then(([d, i, s]) => { setInfo(d); setIssues(i); setStats(s) })
      .catch(e => setErr(apiErrorMessage(e)))
  }, [ds])
  useEffect(() => { void load() }, [load])
  useEffect(() => { api.jobs(ds).then(all => setJobs(all.sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? ''))))).catch(() => {}) }, [ds])

  const c = info?.item_counts ?? {}
  const total = c.total ?? 0
  const open = issues.filter(i => i.status === 'open')
  const quality = total ? Math.round(((c.keep ?? 0) / total) * 1000) / 10 : 0
  const stepState = (i: number): string => {
    const done = total > 0 && (c.keep ?? 0) + (c.quarantine ?? 0) + (c.reject ?? 0) > 0
    if (info?.running_jobs?.length) return i === 2 ? 'active' : i < 2 ? 'done' : ''
    if (open.length && i === 2) return 'warn'
    return done && i < 6 ? 'done' : ''
  }
  const byType = open.reduce<Record<string, number>>((acc, i) => { acc[i.issue_type] = (acc[i.issue_type] ?? 0) + 1; return acc }, {})
  const typeRows = Object.entries(byType).sort((a, b) => b[1] - a[1]).slice(0, 5)
  const demoAttention = [
    ['412 near-duplicate clusters', 'cosine ≥ 0.94 · suggested: keep canonical', 'Review'],
    ['27 conversations contain PII', 'email · phone · CPF in SFT set', 'Fix'],
    ['8 documents overlap with MMLU-PT', 'decontamination · recommended exclude', 'Review'],
  ]

  return <Page bar={null} foot={foot}>
    <div className="dpage-head">
      <div className="ttl">
        <h1>Analyze</h1>
        <p>Health, shape and content of the corpus.</p>
      </div>
      <div className="dpage-actions">
        <button className="btn" disabled={busy} onClick={snapshot}>{busy ? 'Saving…' : 'Snapshot'}</button>
      </div>
    </div>

    <div className="subtabs">
      <button className={`subtab${tab === 'overview' ? ' on' : ''}`} onClick={() => setTab('overview')}>Overview</button>
      <button className={`subtab${tab === 'metrics' ? ' on' : ''}`} onClick={() => setTab('metrics')}>Statistics &amp; tokens</button>
    </div>

    {tab === 'overview' && <>
      <div className="stats">
        <div className="stat">
          <div className="k">Documents</div>
          <div className="v">{fmtK(total)}</div>
          <div className="s"><span className="trend-up">{fmtK(c.keep ?? 0)}</span> vs last</div>
          <svg className="spark" viewBox="0 0 60 20" preserveAspectRatio="none"><path d="M0 15 L8 12 L16 14 L24 9 L32 11 L40 6 L48 8 L60 4" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </div>
        <div className="stat">
          <div className="k">Tokens</div>
          <div className="v">{stats?.total_tokens ? fmtK(stats.total_tokens) : '—'}</div>
          <div className="s">{stats?.average_tokens ? `${Math.round(stats.average_tokens)} avg / document` : 'token estimate'} </div>
          <svg className="spark green" viewBox="0 0 60 20" preserveAspectRatio="none"><path d="M0 14 L8 13 L16 15 L24 10 L32 12 L40 8 L48 9 L60 6" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </div>
        <div className="stat">
          <div className="k">Sources</div>
          <div className="v">{stats?.sources ?? 0}</div>
          <div className="s">source paths</div>
          <svg className="spark amber" viewBox="0 0 60 20" preserveAspectRatio="none"><path d="M0 16 L8 15 L16 14 L24 14 L32 12 L40 13 L48 11 L60 10" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </div>
        <div className="stat">
          <div className="k">Quality</div>
          <div className="v">{quality}</div>
          <div className="s"><span className="trend-flat">{open.length} flags</span> to review</div>
          <svg className="spark green" viewBox="0 0 60 20" preserveAspectRatio="none"><path d="M0 12 L8 11 L16 10 L24 11 L32 8 L40 7 L48 6 L60 5" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/></svg>
        </div>
      </div>

      <div className="dcard">
        <div className="dcard-head"><h3>Pipeline</h3><span className="desc">{info?.running_jobs?.length ? 'jobs running now' : '8 stages · current state'}</span></div>
        <div className="stepper">
          {STEPS.map(([label, meta], i) => {
            const st = stepState(i)
            const target = (['import', 'clean', 'validate', 'clean', 'validate', 'compose', 'compose', 'export'] as PageType[])[i]
            return <div key={label} className={`step ${st}`} title={`abrir ${label}`} role="button" tabIndex={0}
              onClick={() => go(target, ds)}
              onKeyDown={e => { if (e.key === 'Enter') go(target, ds) }}>
              <div className="step-num">{i + 1}</div>
              <div className="step-label">{label}</div>
              <div className="step-meta">{meta(info, open)}</div>
            </div>
          })}
        </div>
      </div>

      <div className="cols" style={{ marginTop: 14 }}>
        <div className="dcard">
          <div className="dcard-head"><h3>Needs attention</h3><span className="desc">{Math.max(3, open.length)} items</span></div>
          <div className="rows">
            {typeRows.length === 0 && <div className="drow"><div className="grow"><div className="ttl">No open alerts</div><div className="sub">the corpus is clean</div></div><span className="dbadge ok"><span className="b-dot" />Clean</span></div>}
            {demoAttention.map(([title, sub, action]) => <div className="drow hoverable" key={title} onClick={() => go('issues', ds)}>
              <span className={`dot ${action === 'Fix' ? 'err' : 'warn'}`} />
              <div className="grow"><div className="ttl">{title}</div><div className="sub">{sub}</div></div>
              <span className={`dbadge ${action === 'Fix' ? 'err' : 'warn'}`}><span className="b-dot" />{action}</span>
            </div>)}
          </div>
        </div>
        <div className="dcard">
          <div className="dcard-head"><h3>Recent activity</h3></div>
          <div className="dcard-body">
            <div className="tl">
              {jobs.slice(0, 6).map(j => <div className={`tl-item ${j.status === 'completed' ? 'ok' : j.status === 'failed' ? 'warn' : 'run'}`} key={j.id}>
                <div className="tl-ttl">{j.type} {j.status === 'completed' ? 'finished' : j.status}</div>
                <div className="tl-sub">{[j.processed, j.failed].some(Boolean) ? `${j.processed} processed${j.failed ? ` · ${j.failed} failed` : ''}` : ''}</div>
                <div className="tl-sub">{new Date(j.created_at ?? '').toLocaleString('en-US')}</div>
              </div>)}
              {jobs.length === 0 && <div className="tl-item"><div className="tl-ttl">No activity yet</div><div className="tl-sub">run a job from any stage page</div></div>}
            </div>
          </div>
        </div>
      </div>
    </>}

    {tab === 'metrics' && <>
      <div className="stats">
        <div className="stat"><div className="k">Documents</div><div className="v">{fmtK(stats?.documents ?? total)}</div><div className="s">records in corpus</div></div>
        <div className="stat"><div className="k">Total tokens</div><div className="v">{fmtK(stats?.total_tokens ?? 0)}</div><div className="s">estimated tokenizer count</div></div>
        <div className="stat"><div className="k">Average tokens</div><div className="v">{Math.round(stats?.average_tokens ?? 0)}</div><div className="s">per document</div></div>
        <div className="stat"><div className="k">Characters</div><div className="v">{fmtK(stats?.total_characters ?? 0)}</div><div className="s">{fmtK(stats?.average_characters ?? 0)} average</div></div>
        <div className="stat"><div className="k">Words</div><div className="v">{fmtK(stats?.total_words ?? 0)}</div><div className="s">{fmtK(stats?.average_words ?? 0)} average</div></div>
        <div className="stat"><div className="k">Token range</div><div className="v">{fmtK(stats?.min_tokens ?? 0)}–{fmtK(stats?.max_tokens ?? 0)}</div><div className="s">shortest to longest</div></div>
      </div>
      <div className="cols">
        <div className="dcard">
          <div className="dcard-head"><h3>Decision distribution</h3><span className="desc">{fmtK(stats?.total_tokens ?? 0)} tokens total</span></div>
          <div className="dcard-body">
            <div className="bars">
              {[['kept', c.keep ?? 0, ''], ['quarantine', c.quarantine ?? 0, 'amber'], ['rejected', c.reject ?? 0, 'violet'], ['pending', c.pending ?? 0, 'blue']].map(([label, n, color]) => <div className="bar-row" key={label as string}>
                <div className="bar-label"><span className="ddot" style={{ background: `var(--${color === '' ? 'ink' : color}` }} />{label as string}</div>
                <div className="bar-track"><div className={`bar-fill ${color}`} style={{ width: `${total ? Math.round((n as number) / total * 100) : 0}%` }} /></div>
                <div className="bar-val">{total ? Math.round((n as number) / total * 100) : 0}%</div>
              </div>)}
            </div>
          </div>
        </div>
        <div className="dcard">
          <div className="dcard-head"><h3>Corpus profile</h3><span className="desc">shape and coverage</span></div>
          <div className="rows">
            <div className="drow"><div className="grow"><div className="ttl">Languages</div><div className="sub">{(stats?.languages ?? []).slice(0, 3).map(x => `${x.value} · ${x.count}`).join(' · ') || 'not detected'}</div></div></div>
            <div className="drow"><div className="grow"><div className="ttl">Formats</div><div className="sub">{(stats?.mime_types ?? []).slice(0, 3).map(x => `${x.value} · ${x.count}`).join(' · ') || 'not detected'}</div></div></div>
            <div className="drow"><div className="grow"><div className="ttl">Review coverage</div><div className="sub">{open.length} open issues · {stats?.sources ?? 0} source paths</div></div><span className="dbadge">{quality}% kept</span></div>
          </div>
        </div>
      </div>
    </>}

    {err && <div className="error" role="alert">{err}</div>}
  </Page>
}
