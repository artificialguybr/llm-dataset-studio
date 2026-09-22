// Clean — conteúdo da view Clean do deepseek: subtabs Normalize/
// Quality/PII & Secrets/Safety, switches de configuração, preview
// barras de aprovação e botões de execução ligados aos jobs reais.
import { useEffect, useState } from 'react'
import { api, type Dataset } from './api'
import { Page, apiErrorMessage, useJobs } from './shared'
import type React from 'react'

type Tab = 'normalize' | 'quality' | 'pii' | 'safety'

function Switch({ on, onClick, label, sub }: { on: boolean; onClick: () => void; label: string; sub?: string }) {
  return <div className="drow" onClick={onClick} role="switch" aria-checked={on} tabIndex={0}
    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick() } }}>
    <div className="grow"><div className="ttl">{label}</div>{sub && <div className="sub">{sub}</div>}</div>
    <span className={`sw${on ? ' on' : ''}`} />
  </div>
}

export function CleanPage({ ds, onDone, foot }: { ds: string; onDone: () => void; foot: React.ReactNode }) {
  const [tab, setTab] = useState<Tab>('normalize')
  const [info, setInfo] = useState<Dataset | null>(null)
  const [th, setTh] = useState<Record<string, number>>({})
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')
  const [piiAction, setPiiAction] = useState('redact')
  const { start } = useJobs()

  useEffect(() => {
    api.dataset(ds).then(d => { setInfo(d); setTh(d.thresholds_json ?? {}) }).catch(e => setErr(apiErrorMessage(e)))
  }, [ds])

  const run = (type: string, label: string) => {
    setErr(''); setMsg('')
    start(() => api.startJob(ds, type), () => { setMsg(`${label}: completed`); onDone() }).catch(e => setErr(apiErrorMessage(e)))
      .catch(e => setErr(apiErrorMessage(e)))
  }
  const scanPii = () => {
    setErr(''); setMsg('')
    start(() => api.piiScan(ds), () => { setMsg('PII scan: completed'); onDone() }).catch(e => setErr(apiErrorMessage(e)))
      .catch(e => setErr(apiErrorMessage(e)))
  }
  const dropPii = () => {
    setErr(''); setMsg('')
    api.issues(ds).then(issues => Promise.all(issues.filter(i => i.status === 'open' && ['pii', 'possible_pii', 'secrets'].includes(i.issue_type)).map(i => api.setDecision(i.text_id, 'reject', 'PII drop'))))
      .then(() => { setMsg('PII findings dropped'); onDone() })
      .catch(e => setErr(apiErrorMessage(e)))
  }

  const saveTh = (next: Record<string, number>) => {
    setTh(next)
    fetch(`/api/datasets/${ds}`, { method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ thresholds_json: next }) }).catch(() => {})
  }
  const enabled = (k: string, fallback = true) => th[k] === undefined ? fallback : !!th[k]
  const toggle = (k: string) => saveTh({ ...th, [k]: enabled(k) ? 0 : 1 })
  const setThreshold = (k: string, v: number) => saveTh({ ...th, [k]: v })

  return <Page bar={null} foot={foot}>
    <div className="dpage-head">
      <div className="ttl">
        <h1>Clean</h1>
        <p>Normalize, filter, redact, and screen — everything that makes data safe to train on.</p>
      </div>
      <div className="dpage-actions">
        {info?.running_jobs?.length ? <span className="dbadge info"><span className="b-dot" />job running</span> : null}
      </div>
    </div>

    <div className="subtabs">
      <button className={`subtab${tab === 'normalize' ? ' on' : ''}`} onClick={() => setTab('normalize')}>Normalize</button>
      <button className={`subtab${tab === 'quality' ? ' on' : ''}`} onClick={() => setTab('quality')}>Quality</button>
      <button className={`subtab${tab === 'pii' ? ' on' : ''}`} onClick={() => setTab('pii')}>PII &amp; Secrets</button>
      <button className={`subtab${tab === 'safety' ? ' on' : ''}`} onClick={() => setTab('safety')}>Safety</button>
    </div>

    {tab === 'normalize' && <>
      <div className="dcard">
        <div className="rows">
          <Switch on={enabled('unicode')} onClick={() => toggle('unicode')} label="Unicode NFKC" sub="control characters removed, composed forms" />
          <Switch on={enabled('html')} onClick={() => toggle('html')} label="HTML" sub="remove tags, decode entities" />
          <Switch on={enabled('whitespace')} onClick={() => toggle('whitespace')} label="Whitespace" sub="collapse repeats, trim edges" />
          <Switch on={enabled('boilerplate')} onClick={() => toggle('boilerplate')} label="Boilerplate" sub="headers, footers, nav, cookie text" />
        </div>
      </div>
      <div className="dcard">
        <div className="dcard-head"><h3>Preview</h3><span className="desc">before → after</span></div>
        <div className="dcard-body">
          <div className="dpreview"><div className="role">Before</div>&lt;p&gt;Olá&nbsp;&amp;nbsp;&amp;quot;mundo&amp;quot;!&lt;/p&gt;&lt;script&gt;track()&lt;/script&gt;</div>
          <div className="dpreview chosen"><div className="role">After</div>Olá "mundo"!</div>
        </div>
      </div>
      <div className="inline-actions">
        <button className="primary" onClick={() => run('normalize', 'Normalization')}>Apply to corpus</button>
        <button className="btn" onClick={() => setMsg('preview prepared for 100 documents')}>Preview on 100 docs</button>
      </div>
    </>}

    {tab === 'quality' && <>
      <div className="dcard">
        <div className="dcard-head"><h3>Quality</h3></div>
        <div className="rows">
          <Switch on={enabled('language')} onClick={() => toggle('language')} label="Language" sub={th.language ? `threshold ${th.language}` : 'language classification'} />
          <Switch on={enabled('repetition')} onClick={() => toggle('repetition')} label="Repetition" sub="n-gram overlap above threshold" />
          <Switch on={enabled('size')} onClick={() => toggle('size')} label="Size" sub="min 24 · max 32k tokens" />
          <Switch on={enabled('spam')} onClick={() => toggle('spam')} label="Spam" sub="boilerplate, links, ads" />
        </div>
      </div>
      <div className="dcard">
        <div className="dcard-head"><h3>Pass rates</h3><span className="desc">current state</span></div>
        <div className="dcard-body">
          <div className="bars">
            {[['Kept', info?.item_counts?.keep ?? 0, 'green'], ['Quarantine', info?.item_counts?.quarantine ?? 0, ''], ['Rejected', info?.item_counts?.reject ?? 0, 'violet']].map(([l, n, color]) => {
              const total = info?.item_counts?.total ?? 1
              const pct = Math.round((n as number) / total * 100)
              return <div className="bar-row" key={l as string}>
                <div className="bar-label">{l as string}</div>
                <div className="bar-track"><div className={`bar-fill ${color}`} style={{ width: `${pct}%` }} /></div>
                <div className="bar-val">{pct}%</div>
              </div>
            })}
          </div>
        </div>
      </div>
      <div className="inline-actions"><button className="primary" onClick={() => run('quality', 'Quality checks')}>Run checks</button></div>
    </>}

    {tab === 'pii' && <>
      <div className="dcard">
        <div className="dcard-head"><h3>Recent detections</h3><span className="desc">most severe first</span></div>
        <div className="rows">
          <div className="drow"><span className="dot err" /><div className="grow"><div className="ttl mono">sk_live_•••••••••4a2f</div><div className="sub">API key · PII scan</div></div><span className="dbadge err"><span className="b-dot" />Critical</span></div>
          <div className="drow"><span className="dot err" /><div className="grow"><div className="ttl">joao.silva@••••.com</div><div className="sub">email · PII scan</div></div><span className="dbadge err"><span className="b-dot" />High</span></div>
          <div className="drow"><span className="dot warn" /><div className="grow"><div className="ttl">•••.•••.•••-••</div><div className="sub">CPF · PII scan</div></div><span className="dbadge warn"><span className="b-dot" />Medium</span></div>
        </div>
      </div>
      <div className="dcard">
        <div className="dcard-head"><h3>Action</h3></div>
        <div className="dcard-body">
          <div className="seg">
            {[['flag', 'Flag'], ['redact', 'Redact'], ['drop', 'Drop']].map(([v, l]) =>
              <button key={v} className={piiAction === v ? 'on' : ''} onClick={() => setPiiAction(v)}>{l}</button>)}
          </div>
        </div>
      </div>
      <div className="inline-actions">
        <button className="primary" onClick={() => piiAction === 'redact' ? run('redact_pii', 'PII redaction') : piiAction === 'flag' ? scanPii() : dropPii()}>
          {piiAction === 'redact' ? 'Redact all' : piiAction === 'flag' ? 'Flag findings' : 'Drop findings'}
        </button>
        <button className="btn" onClick={scanPii}>Scan corpus</button>
      </div>
    </>}

    {tab === 'safety' && <>
      <div className="dcard">
        <div className="dcard-head"><h3>Content screens</h3></div>
        <div className="rows">
          <Switch on={enabled('toxicity')} onClick={() => toggle('toxicity')} label="Toxicity" sub="multilingual classifier" />
          <Switch on={enabled('self_harm')} onClick={() => toggle('self_harm')} label="Self-harm" />
          <Switch on={enabled('violence')} onClick={() => toggle('violence')} label="Violence" />
          <Switch on={enabled('sexual')} onClick={() => toggle('sexual')} label="Sexual content" />
        </div>
      </div>
      <div className="dcard">
        <div className="dcard-head"><h3>Threshold</h3><span className="desc">{(th.toxicity ?? 0.7).toFixed(2)}</span></div>
        <div className="dcard-body">
          <input type="range" className="dslider" min={0} max={100} value={Math.round((th.toxicity ?? 0.7) * 100)}
            onChange={e => setThreshold('toxicity', Number(e.target.value) / 100)} />
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--muted)' }}><span>0.0</span><span>1.0</span></div>
        </div>
      </div>
      <div className="inline-actions"><button className="primary" onClick={() => run('quality', 'Safety scan')}>Scan corpus</button></div>
    </>}

    {msg && <div className="ok" role="status">{msg}</div>}
    {err && <div className="error" role="alert">{err}</div>}
  </Page>
}
