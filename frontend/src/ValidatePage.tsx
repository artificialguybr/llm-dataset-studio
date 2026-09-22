// Validate — conteúdo da view Validate do deepseek: Schemas, Duplicates e
// Decontamination — checagens reais (counts por formato, grupos de duplicatas,
// issues de contaminação) + jobs dedup/decontaminate.
import { useCallback, useEffect, useState, } from 'react'
import { api, type DupGroup, type Issue } from './api'
import { Page, apiErrorMessage, useJobs } from './shared'
import type React from 'react'
import type { Page as PageType } from './shared'

type Tab = 'schemas' | 'duplicates' | 'decontam'

function Switch({ on, onClick, label, sub }: { on: boolean; onClick: () => void; label: string; sub?: string }) {
  return <div className="drow" onClick={onClick} role="switch" aria-checked={on} tabIndex={0}
    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick() } }}>
    <div className="grow"><div className="ttl">{label}</div>{sub && <div className="sub">{sub}</div>}</div>
    <span className={`sw${on ? ' on' : ''}`} />
  </div>
}

export function ValidatePage({ ds, go, onDone, foot }: { ds: string; go: (p: PageType, ds?: string) => void; onDone: () => void; foot: React.ReactNode }) {
  const [tab, setTab] = useState<Tab>('schemas')
  const [issues, setIssues] = useState<Issue[]>([])
  const [groups, setGroups] = useState<DupGroup[]>([])
  const [counts, setCounts] = useState<Record<string, number>>({})
  const [exactOn, setExactOn] = useState(true)
  const [nearOn, setNearOn] = useState(true)
  const [semOn, setSemOn] = useState(false)
  const [benches, setBenches] = useState<Record<string, boolean>>({ 'MMLU-PT': true, ENEM: true, GSM8K: true, HumanEval: true })
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const { start } = useJobs()

  const load = useCallback(() => {
    Promise.all([api.issues(ds), api.duplicates(ds),
      api.listConversations(ds), api.sftRecords(ds), api.preferencePairs(ds), api.traces(ds)])
      .then(([i, g, c, s, p, t]) => {
        setIssues(i); setGroups(g)
        setCounts({ conversas: c.length, sft: s.length, dpo: p.length, traces: t.length })
      }).catch(e => setErr(apiErrorMessage(e)))
  }, [ds])
  useEffect(() => { void load() }, [load])

  const run = (type: string, label = type) => {
    setErr(''); setMsg('')
    start(() => api.startJob(ds, type), () => { setMsg(`${label}: completed`); onDone(); load() }).catch(e => setErr(apiErrorMessage(e)))
  }
  const quarantineDups = (members: DupGroup['members']) =>
    Promise.all(members.filter(m => !m.is_canonical).map(m => api.setDecision(m.text_id, 'quarantine', 'duplicate')))
      .then(() => { onDone(); load() })

  const contam = issues.filter(i => i.issue_type === 'contamination' && i.status === 'open')
  const dupItems = groups.reduce((t, g) => t + g.members.length, 0)

  const SCHEMAS: [string, string, number, string][] = [
    ['corpus', 'id · text · source · license', counts.conversas ?? 0, 'ok'],
    ['sft', 'messages[] · role · content', counts.sft ?? 0, 'ok'],
    ['dpo', 'prompt · chosen · rejected', counts.dpo ?? 0, counts.dpo ? 'warn' : 'info'],
    ['traces', 'tools[] · steps[] · result', counts.traces ?? 0, 'ok'],
  ]

  return <Page bar={null} foot={foot}>
    <div className="dpage-head">
      <div className="ttl">
        <h1>Validate</h1>
        <p>Schemas, duplicates and benchmark contamination — the checks that keep the corpus honest.</p>
      </div>
    </div>

    <div className="subtabs">
      <button className={`subtab${tab === 'schemas' ? ' on' : ''}`} onClick={() => setTab('schemas')}>Schemas</button>
      <button className={`subtab${tab === 'duplicates' ? ' on' : ''}`} onClick={() => setTab('duplicates')}>Duplicates<span className="cnt">{groups.length}</span></button>
      <button className={`subtab${tab === 'decontam' ? ' on' : ''}`} onClick={() => setTab('decontam')}>Decontamination</button>
    </div>

    {tab === 'schemas' && <div className="dcard">
      <div className="dcard-head"><h3>Declared schemas</h3><button className="btn" onClick={() => setMsg('schema registration is managed by import format')}>+ New</button></div>
      <div className="rows">
        {SCHEMAS.map(([name, fields, n, st]) => <div className="drow hoverable" key={name} onClick={() => go('records', ds)}>
          <span className={`dot ${n ? st : ''}`} />
          <div className="grow"><div className="ttl">{name}</div><div className="sub mono">{fields}</div></div>
          <span className={`dbadge ${n ? st : ''}`}><span className="b-dot" />{n ? 'Passing' : 'Empty'}</span>
        </div>)}
      </div>
    </div>}

    {tab === 'duplicates' && <>
      <div className="dcard">
        <div className="dcard-head"><h3>Methods</h3></div>
        <div className="rows">
          <Switch on={exactOn} onClick={() => setExactOn(!exactOn)} label="Exact" sub="identical hash" />
          <Switch on={nearOn} onClick={() => setNearOn(!nearOn)} label="Near" sub="MinHash · Jaccard ≥ 0.85" />
          <Switch on={semOn} onClick={() => setSemOn(!semOn)} label="Semantic" sub="embedding cosine ≥ 0.94" />
        </div>
      </div>
      <div className="stats">
        <div className="stat"><div className="k">Grupos</div><div className="v">{groups.length}</div></div>
        <div className="stat"><div className="k">Items involved</div><div className="v">{dupItems}</div></div>
        <div className="stat"><div className="k">Canonicals</div><div className="v">{groups.reduce((t, g) => t + g.members.filter(m => m.is_canonical).length, 0)}</div></div>
        <div className="stat"><div className="k">Savings</div><div className="v">{dupItems ? Math.round((dupItems - groups.length) / dupItems * 100) : 0}<small>%</small></div></div>
      </div>
      <div className="dcard">
        <div className="dcard-head"><h3>Detected groups</h3><span className="desc">{groups.length}</span></div>
        <div className="rows">
          {groups.length === 0 && <div className="drow"><div className="grow"><div className="ttl">No groups detected</div><div className="sub">run deduplication above</div></div></div>}
          {groups.slice(0, 10).map(g => <div className="drow" key={g.group.id}>
            <span className={`dot ${g.group.method === 'sha256' ? 'err' : 'warn'}`} />
            <div className="grow">
              <div className="ttl">{g.group.method === 'sha256' ? 'Exact duplicates' : g.group.method === 'minhash' ? 'Near duplicates' : 'Semantic duplicates'}</div>
              <div className="sub">{g.members.length} items · threshold {g.group.threshold}</div>
            </div>
            <button className="btn sm" onClick={() => quarantineDups(g.members)}>Quarantine</button>
            <button className="btn sm" onClick={() => go('issues', ds)}>Compare</button>
          </div>)}
        </div>
      </div>
      <div className="inline-actions">
        {exactOn && <button className="primary" onClick={() => run('dedup_exact', 'Dedup exata')}>Run exact dedup</button>}
        {nearOn && <button className="primary" onClick={() => run('dedup_semantic', 'Near dedup')}>Run near dedup</button>}
        <button className="btn" onClick={() => go('issues', ds)}>Review clusters</button>
      </div>
    </>}

    {tab === 'decontam' && <>
      <div className="dcard">
        <div className="dcard-head"><h3>Benchmarks</h3></div>
        <div className="rows">
          {Object.entries(benches).map(([name, on]) => <Switch key={name} on={on}
            onClick={() => setBenches(prev => ({ ...prev, [name]: !on }))}
            label={name} sub="evaluation set" />)}
        </div>
      </div>
      <div className="dcard">
        <div className="dcard-head"><h3>Hits</h3><span className="desc">{contam.length} documentos</span></div>
        <div className="rows">
          {contam.length === 0 && <div className="drow"><div className="grow"><div className="ttl">No overlap</div><div className="sub">clean against benchmarks</div></div><span className="dbadge ok"><span className="b-dot" />Clean</span></div>}
          {contam.slice(0, 10).map(i => <div className="drow hoverable" key={i.id} onClick={() => go('queue', ds)}>
            <span className="dot warn" />
            <div className="grow"><div className="ttl">{i.item?.original_filename ?? i.text_id.slice(0, 8)}</div>
              <div className="sub">13-gram · recomendado: excluir</div></div>
            <span className="dbadge warn"><span className="b-dot" />Review</span>
          </div>)}
        </div>
      </div>
      <div className="inline-actions"><button className="primary" onClick={() => run('decontaminate', 'Decontamination')}>Run decontamination</button></div>
    {msg && <div className="ok" role="status">{msg}</div>}
    </>}

    {err && <div className="error" role="alert">{err}</div>}
  </Page>
}
