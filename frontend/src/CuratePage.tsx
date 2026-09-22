// Curate — conteúdo da view Curate do deepseek: fila de revisão, pares
// de preferência DPO, traces & ferramentas, geração sintética.
import { useCallback, useEffect, useState, } from 'react'
import { api, type AgentTrace, type Issue, type PreferencePair } from './api'
import { Page, apiErrorMessage } from './shared'
import type React from 'react'
import type { Page as PageType } from './shared'

type Tab = 'review' | 'pref' | 'traces' | 'synth'
const ISSUE_LABEL: Record<string, string> = {
  contamination: 'Contamination', pii_score: 'PII', pii: 'PII', duplication: 'Duplicate',
  quality_language: 'Language', quality_repetition: 'Repetition', quality_size: 'Size', quality_spam: 'Spam',
  too_short: 'Too short', too_long: 'Too long', repetition: 'Repetition',
  spam_score: 'Spam', code_ratio: 'Code', toxicity: 'Toxicity',
}

export function CuratePage({ ds, go, foot }: { ds: string; go: (p: PageType, ds?: string) => void; foot: React.ReactNode }) {
  const [tab, setTab] = useState<Tab>('review')
  const [issues, setIssues] = useState<Issue[]>([])
  const [pairs, setPairs] = useState<PreferencePair[]>([])
  const [traces, setTraces] = useState<AgentTrace[]>([])
  const [filter, setFilter] = useState('all')
  const [err, setErr] = useState('')
  const [synth, setSynth] = useState<Record<string, boolean>>({})
  const toggleSynth = (k: string) => setSynth(prev => ({ ...prev, [k]: !(prev[k] ?? false) }))

  const load = useCallback(() => {
    Promise.all([api.issues(ds), api.preferencePairs(ds), api.traces(ds)])
      .then(([i, p, t]) => { setIssues(i); setPairs(p); setTraces(t) })
      .catch(e => setErr(apiErrorMessage(e)))
  }, [ds])
  useEffect(() => { void load() }, [load])

  const open = issues.filter(i => i.status === 'open')
  const shown = filter === 'all' ? open : open.filter(i => i.issue_type === filter)
  const filterGroups = Object.entries(open.reduce<Record<string, number>>((acc, i) => { acc[i.issue_type] = (acc[i.issue_type] ?? 0) + 1; return acc }, {}))
  const pair = pairs[0]
  const reviewCount = open.length
  const filterButtons = filterGroups.slice(0, 3).map(([type, n]) => [type, `${ISSUE_LABEL[type] ?? type} · ${n}`])

  return <Page bar={null} foot={foot}>
    <div className="dpage-head">
      <div className="ttl">
        <h1>Curate</h1>
        <p>Human judgement and derived data — review, preference pairs, traces and synthetic generation.</p>
      </div>
    </div>

    <div className="subtabs">
      <button className={`subtab${tab === 'review' ? ' on' : ''}`} onClick={() => setTab('review')}>Review<span className="cnt">{reviewCount}</span></button>
      <button className={`subtab${tab === 'pref' ? ' on' : ''}`} onClick={() => setTab('pref')}>Preference / DPO</button>
      <button className={`subtab${tab === 'traces' ? ' on' : ''}`} onClick={() => setTab('traces')}>Traces &amp; Tools</button>
      <button className={`subtab${tab === 'synth' ? ' on' : ''}`} onClick={() => setTab('synth')}>Synthetic</button>
    </div>

    {tab === 'review' && <>
      <div className="seg" style={{ marginBottom: 14 }}>
        <button className={filter === 'all' ? 'on' : ''} onClick={() => setFilter('all')}>All · {reviewCount}</button>
        {filterButtons.map(([type, label]) =>
          <button key={type} className={filter === type ? 'on' : ''} onClick={() => setFilter(type)}>{label}</button>)}
      </div>
      <div className="dcard">
        <div className="rows">
          {open.length === 0 && <div className="drow"><div className="grow"><div className="ttl">queue empty</div><div className="sub">Run Quality, PII or dedup jobs from Analyze to open review alerts</div></div></div>}
          {shown.slice(0, 20).map(i => <div className="drow hoverable" key={i.id} onClick={() => go('queue', ds)}>
            <span className={`dot ${i.issue_type === 'pii' ? 'err' : 'warn'}`} />
            <div className="grow">
              <div className="ttl">{ISSUE_LABEL[i.issue_type] ?? i.issue_type}{i.item ? ` · ${i.item.original_filename}` : ''}</div>
              <div className="sub">{(i.preview ?? '').replace(/\s+/g, ' ').slice(0, 90) || (`score ${i.score.toFixed(2)} · threshold ${i.threshold}`)}</div>
            </div>
            <span className={`dbadge ${i.issue_type === 'pii' ? 'err' : 'warn'}`}><span className="b-dot" />Review</span>
          </div>)}
        </div>
      </div>
    </>}

    {tab === 'pref' && (pairs.length === 0
      ? <div className="dcard"><div className="dcard-body"><p className="muted">No preference pairs yet. Import DPO data (prompt · chosen · rejected) to populate.</p></div></div>
      : <>
        <div className="dcard">
          <div className="dcard-head"><h3>Par #{pair!.id.slice(0, 8)}</h3><span className="desc">{pair!.strategy || 'dpo'} · {pairs.length} pairs in dataset</span></div>
          <div className="dcard-body">
            <div className="dpreview"><div className="role">Prompt</div>{pair!.prompt_text}</div>
            <div className="dpreview chosen"><div className="role">✓ Chosen</div>{pair!.chosen_text}</div>
            <div className="dpreview rejected"><div className="role">✕ Rejected</div>{pair!.rejected_text}</div>
          </div>
        </div>
        <div className="dcard">
          <div className="dcard-head"><h3>All os pares</h3><span className="desc">{pairs.length}</span></div>
          <div className="rows">
            {pairs.slice(0, 10).map(p => <div className="drow hoverable" key={p.id} onClick={() => setPairs(prev => [p, ...prev.filter(x => x.id !== p.id)])}>
              <span className={`dot ${p.status === 'approved' ? 'ok' : p.status === 'rejected' ? 'err' : 'warn'}`} />
              <div className="grow"><div className="ttl">{p.strategy || 'pair'} · {p.id.slice(0, 8)}</div><div className="sub">{p.prompt_text.slice(0, 90)}</div></div>
              <span className="dbadge">{p.status}</span>
            </div>)}
          </div>
        </div>
      </>)}

    {tab === 'traces' && (traces.length === 0
      ? <div className="dcard"><div className="dcard-body"><p className="muted">No traces yet. Import agent/tool logs to populate.</p></div></div>
      : <div className="dcard">
        <div className="dcard-head"><h3>Agent runs</h3><span className="desc">{traces.length} traces</span></div>
        <div className="dcard-body">
          <div className="tl">
            {traces.slice(0, 8).map(tr => <div className={`tl-item ${tr.success === null ? 'run' : tr.success ? 'ok' : 'warn'}`} key={tr.id}>
              <div className="tl-ttl mono">{tr.trace_type} · {tr.model || '—'}</div>
              <div className="tl-sub">{tr.tokens.toLocaleString()} tokens{tr.error ? ` · erro: ${tr.error.slice(0, 60)}` : ''}</div>
            </div>)}
          </div>
        </div>
      </div>)}

    {tab === 'synth' && <>
      <div className="dcard">
        <div className="dcard-head"><h3>Synthetic generation</h3><span className="desc">requires an active generation model</span></div>
        <div className="rows">
          {([['rewrites', 'Rewrites', 'paraphrase and simplify', true],
             ['hard_neg', 'Hard negatives', 'plausible but incorrect answers', true],
             ['multi_turn', 'Multi-turn expansion', 'turn a prompt into a dialogue', false],
             ['reasoning', 'Reasoning traces', 'chain-of-thought style steps', false]] as [string, string, string, boolean][]).map(([k, l, sub, on]: [string, string, string, boolean]) =>
            <div className="drow" key={k} onClick={() => toggleSynth(k)} role="switch" aria-checked={synth[k] ?? on} tabIndex={0}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); toggleSynth(k) } }}>
              <div className="grow"><div className="ttl">{l}</div><div className="sub">{sub}</div></div>
              <span className={`sw${(synth[k] ?? on) ? ' on' : ''}`} />
            </div>)}
        </div>
      </div>
      <div className="inline-actions">
        <button className="primary" onClick={() => go('models')}>Configure generation model</button>
        <button className="btn" onClick={() => go('queue', ds)}>Send to review</button>
      </div>
    </>}

    {err && <div className="error" role="alert">{err}</div>}
  </Page>
}
