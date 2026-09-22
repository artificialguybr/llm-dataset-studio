// Export — conteúdo da view Export do deepseek: seletor de formato,
// card "Include" com switches e botão de exportação. Lógica real preservada.
import { useCallback, useEffect, useState, } from 'react'
import { api, type Dataset, type Issue, type Version } from './api'
import { Page, apiErrorMessage } from './shared'
import type React from 'react'

const FMTS: [string, string][] = [['jsonl', 'JSONL'], ['parquet', 'Parquet'], ['hf', 'Hugging Face'], ['manifest', 'Manifest']]

export function ExportPage({ ds, foot }: { ds: string; foot: React.ReactNode }) {
  const [info, setInfo] = useState<Dataset | null>(null)
  const [issues, setIssues] = useState<Issue[]>([])
  const [versions, setVersions] = useState<Version[]>([])
  const [fmt, setFmt] = useState('jsonl')
  const [versionId, setVersionId] = useState('')
  const [result, setResult] = useState<Record<string, unknown> | null>(null)
  const [includeReport, setIncludeReport] = useState(false)
  const [includeProvenance, setIncludeProvenance] = useState(true)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const load = useCallback(() => {
    Promise.all([api.dataset(ds), api.issues(ds), api.versions(ds)])
      .then(([d, i, v]) => {
        setInfo(d); setIssues(i); setVersions(v)
        setVersionId(prev => prev || (d.current_version_id ?? v.at(-1)?.id ?? ''))
      }).catch(e => setErr(apiErrorMessage(e)))
  }, [ds])
  useEffect(() => { void load() }, [load])

  const open = issues.filter(i => i.status === 'open').length
  const ic = info?.item_counts
  const included = (ic?.keep ?? 0) + (ic?.restore ?? 0)
  const unknownLicense = info?.unknown_license ?? 0
  const licenseBlocked = info?.license_policy === 'strict' && unknownLicense > 0
  const blocked = open > 0 || licenseBlocked

  const doExport = async () => {
    setBusy(true); setErr(''); setMsg('')
    try { setResult(await api.export(ds, fmt, versionId)); setMsg('Export package created') }
    catch (e) { setErr(apiErrorMessage(e)) } finally { setBusy(false) }
  }

  return <Page bar={null} foot={foot}>
    <div className="dpage-head">
      <div className="ttl">
        <h1>Export</h1>
        <p>Ship the dataset in whatever shape the next step needs.</p>
      </div>
      <div className="dpage-actions">
        {blocked
          ? <span className="dbadge err"><span className="b-dot" />{open ? `${open} flags` : `${unknownLicense} licenses`} blocking</span>
          : <span className="dbadge ok"><span className="b-dot" />Ready</span>}
      </div>
    </div>

    <div className="dcard">
      <div className="dcard-head"><h3>Format</h3></div>
      <div className="dcard-body">
        <div className="seg">
          {FMTS.map(([v, label]) => <button key={v} className={fmt === v ? 'on' : ''} onClick={() => setFmt(v)}>{label}</button>)}
        </div>
        <div className="toolbar-row" style={{ marginTop: 14 }}>
          <select className="dinput" style={{ paddingLeft: 10, maxWidth: 260 }} value={versionId} onChange={e => setVersionId(e.target.value)} aria-label="checkpoint">
            <option value="">current working state</option>
            {versions.map(v => <option key={v.id} value={v.id}>{v.description || v.id.slice(0, 8)}</option>)}
          </select>
          <span className="dbadge">{included.toLocaleString('pt-BR')} items included</span>
        </div>
      </div>
    </div>

    <div className="dcard">
      <div className="dcard-head"><h3>Include</h3></div>
      <div className="rows">
        <div className="drow"><div className="grow"><div className="ttl">Train split</div><div className="sub">{(ic?.keep ?? 0).toLocaleString('en-US')} approved for training</div></div><span className="sw on" /></div>
        <div className="drow"><div className="grow"><div className="ttl">Training records</div><div className="sub">sft.jsonl · dpo.jsonl · traces.jsonl (TRL/OpenAI contracts)</div></div><span className="sw on" /></div>
        <div className="drow"><div className="grow"><div className="ttl">Provenance manifest</div><div className="sub">decisions, labels, sources and checksum</div></div><span className={`sw${includeProvenance ? ' on' : ''}`} onClick={() => setIncludeProvenance(!includeProvenance)} /></div>
        <div className="drow"><div className="grow"><div className="ttl">Quality report</div><div className="sub">detector and threshold summary</div></div><span className={`sw${includeReport ? ' on' : ''}`} onClick={() => setIncludeReport(!includeReport)} /></div>
      </div>
    </div>

    {result && <div className="dcard">
      <div className="dcard-head"><h3>Result</h3></div>
      <div className="dcard-body"><pre className="mono" style={{ whiteSpace: 'pre-wrap' }}>{JSON.stringify(result, null, 2)}</pre></div>
    </div>}

    <div className="inline-actions">
      <button className="primary" disabled={busy || blocked} onClick={doExport}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>
        Export {versionId ? versionId.slice(0, 8) : 'current state'}
      </button>
    </div>

    {msg && <div className="ok" role="status">{msg}</div>}
    {err && <div className="error" role="alert">{err}</div>}
  </Page>
}
