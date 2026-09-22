// Import — conteúdo da view Import do deepseek: subtabs File/Folder/
// Hugging Face, drop zones, regras de varredura e imports recentes (jobs reais).
import { useCallback, useEffect, useState } from 'react'
import { api, type Job } from './api'
import { Page, apiErrorMessage, useJobs } from './shared'
import type React from 'react'

type Tab = 'file' | 'folder' | 'hf'
const FMTS = ['JSONL', 'Parquet', 'TXT', 'CSV']

const IC = {
  upload: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 17V5m0 0l-4 4m4-4l4 4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>,
  folder: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/></svg>,
  hf: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="9"/><path d="M8 14s1.5 2 4 2 4-2 4-2M9 9h.01M15 9h.01"/></svg>,
  plus: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 5v14M5 12h14"/></svg>,
  search: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>,
}

function Switch({ on, onClick, label, sub }: { on: boolean; onClick: () => void; label: string; sub?: string }) {
  return <div className="drow" onClick={onClick} role="switch" aria-checked={on} tabIndex={0}
    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') onClick() }}>
    <div className="grow"><div className="ttl">{label}</div>{sub && <div className="sub">{sub}</div>}</div>
    <span className={`sw${on ? ' on' : ''}`} />
  </div>
}

export function ImportPage({ ds, onDone, foot }: { ds: string; onDone: () => void; foot: React.ReactNode }) {
  const [tab, setTab] = useState<Tab>('file')
  const [fmt, setFmt] = useState('JSONL')
  const [path, setPath] = useState('')
  const [showPath, setShowPath] = useState(false)
  const [folder, setFolder] = useState('')
  const [hfRepo, setHfRepo] = useState('')
  const [recurse, setRecurse] = useState(true)
  const [skipHidden, setSkipHidden] = useState(true)
  const [groupByExt, setGroupByExt] = useState(false)
  const [stream, setStream] = useState(true)
  const [err, setErr] = useState('')
  const [imports, setImports] = useState<Job[]>([])
  const { start } = useJobs()

  // imports recentes: jobs reais de ingest do backend (mais o otimista local em voo)
  useEffect(() => { setImports([]) }, [ds])

  const loadRecent = useCallback(() => {
    if (!ds) return
    api.jobs(ds).then(all => {
      const ingests = all
        .filter(j => j.type === 'ingest')
        .sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')))
        .slice(0, 6)
      setImports(prev => {
        const seen = new Set(prev.map(p => p.id))
        const real = ingests.map(j => {
          const cfg = j.config_json ?? {}
          const paths = Array.isArray(cfg.paths) ? cfg.paths as string[] : []
          const jsonls = Array.isArray(cfg.jsonls) ? cfg.jsonls as string[] : []
          const first = paths[0] ?? jsonls[0] ?? String(cfg.folder ?? '')
          const name = String(first).split('/').pop() || j.type
          return { ...j, error_summary: name }
        })
        return [...real.filter(r => !seen.has(r.id)),
                ...prev.filter(p => !p.id.startsWith('ing-') && !p.id.startsWith('dir-') && !p.id.startsWith('hf-')
                   || !real.some(r => r.error_summary === p.error_summary))].slice(0, 6)
      })
    }).catch(() => {})
  }, [ds])

  useEffect(() => { loadRecent() }, [loadRecent])

  const doImport = () => {
    if (!path.trim() || !ds) return
    setErr('')
    const entry: Job = { id: `ing-${Date.now()}`, type: 'ingest', status: 'running', progress: 0, total: 0, processed: 0, failed: 0, error_summary: path.trim().split(',')[0] }
    setImports(prev => [entry, ...prev])
    start(() => api.startImport(ds, path.trim().split(',').map(p => p.trim()).filter(Boolean), [], []),
      () => { onDone(); loadRecent() })
      .catch(e => setErr(apiErrorMessage(e)))
  }

  const doFolder = () => {
    if (!folder.trim() || !ds) return
    setErr('')
    const entry: Job = { id: `dir-${Date.now()}`, type: 'ingest', status: 'running', progress: 0, total: 0, processed: 0, failed: 0, error_summary: folder.trim() }
    setImports(prev => [entry, ...prev])
    start(() => api.startImport(ds, [folder.trim()], [], []), () => { onDone(); loadRecent() })
      .catch(e => setErr(apiErrorMessage(e)))
  }

  const doHf = () => {
    if (!hfRepo.trim() || !ds) return
    setErr('')
    const entry: Job = { id: `hf-${Date.now()}`, type: 'import_hf', status: 'running', progress: 0, total: 0, processed: 0, failed: 0, error_summary: hfRepo.trim() }
    setImports(prev => [entry, ...prev])
    start(() => api.startJobWithBody(ds, 'import_hf', { hf_dataset: hfRepo.trim() }),
      () => { onDone(); loadRecent() })
      .catch(e => setErr(apiErrorMessage(e)))
  }

  return <Page bar={null} foot={foot}>
    <div className="dpage-head">
      <div className="ttl">
        <h1>Import</h1>
        <p>Bring data in from files, folders or Hugging Face — one screen for all of it.</p>
      </div>
    </div>

    <div className="subtabs">
      <button className={`subtab${tab === 'file' ? ' on' : ''}`} onClick={() => setTab('file')}>File</button>
      <button className={`subtab${tab === 'folder' ? ' on' : ''}`} onClick={() => setTab('folder')}>Folder</button>
      <button className={`subtab${tab === 'hf' ? ' on' : ''}`} onClick={() => setTab('hf')}>Hugging Face</button>
    </div>

    {tab === 'file' && <>
      <div className="seg" style={{ marginBottom: 14 }}>
        {FMTS.map(f => <button key={f} className={fmt === f ? 'on' : ''} onClick={() => setFmt(f)}>{f}</button>)}
      </div>
      <div className="drop" onClick={() => setShowPath(true)}>
        <div className="drop-icon">{IC.upload}</div>
        <h4>Drop files here</h4>
        <p>or <u onClick={e => { e.stopPropagation(); setShowPath(true) }}>browse</u> — .jsonl, .parquet, .txt</p>
      </div>
      {showPath && <div className="toolbar-row">
        <div className="input-wrap">
          <span className="ico">{IC.search}</span>
          <input id="imp-file" className="dinput" placeholder="/server/path/data.jsonl"
            value={path} onChange={e => setPath(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') doImport() }} autoFocus />
        </div>
        <button className="primary" onClick={doImport}>Import</button>
      </div>}
      <div className="dcard">
        <div className="dcard-head"><h3>Recent imports</h3><span className="desc">last 24 hours</span></div>
        <div className="rows">
          {imports.length === 0 && <div className="drow"><div className="grow"><div className="ttl">No imports yet</div><div className="sub">drop a file above or paste a server path to start one</div></div></div>}
          {imports.map(imp => <div className="drow" key={imp.id}>
            <span className={`dot ${imp.status === 'completed' ? 'ok' : imp.status === 'failed' ? 'err' : 'run'}`} />
            <div className="grow"><div className="ttl">{imp.error_summary || imp.id.slice(0, 18)}</div>
              <div className="sub">{imp.type} · {imp.status === 'completed' ? `${imp.processed} items` : imp.status === 'failed' ? 'failed' : 'reading…'}</div></div>
            <span className={`dbadge ${imp.status === 'completed' ? 'ok' : imp.status === 'failed' ? 'err' : 'info'}`}><span className="b-dot" />{imp.status === 'completed' ? 'Complete' : imp.status === 'failed' ? 'Failed' : 'Reading'}</span>
          </div>)}
        </div>
      </div>
    </>}

    {tab === 'folder' && <>
      <div className="drop" onClick={() => document.getElementById('imp-folder')?.focus()}>
        <div className="drop-icon">{IC.folder}</div>
        <h4>Drop a folder</h4>
        <p>or <u>browse</u> — .txt, .jsonl, .parquet files will be scanned</p>
      </div>
      <div className="toolbar-row">
        <div className="input-wrap">
          <span className="ico">{IC.folder}</span>
          <input id="imp-folder" className="dinput" placeholder="/caminho/no/servidor/pasta/"
            value={folder} onChange={e => setFolder(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') doFolder() }} />
        </div>
        <button className="primary" onClick={doFolder}>Scan folder</button>
      </div>
      <div className="dcard">
        <div className="dcard-head"><h3>Scanning rules</h3></div>
        <div className="rows">
          <Switch on={recurse} onClick={() => setRecurse(!recurse)} label="Recurse subfolders" sub="follow every subdirectory" />
          <Switch on={skipHidden} onClick={() => setSkipHidden(!skipHidden)} label="Skip hidden files" sub=".DS_Store, .git, etc." />
          <Switch on={groupByExt} onClick={() => setGroupByExt(!groupByExt)} label="Group by extension" sub="manter .txt e .jsonl separados" />
        </div>
      </div>
    </>}

    {tab === 'hf' && <>
      <div className="dcard">
        <div className="dcard-head"><h3>Repository</h3></div>
        <div className="dcard-body">
          <div className="input-wrap">
            <span className="ico">{IC.hf}</span>
            <input className="dinput" placeholder="username/dataset-name" value={hfRepo}
              onChange={e => setHfRepo(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') doHf() }} />
          </div>
          <div className="inline-actions"><button className="primary" onClick={doHf}>Import</button></div>
        </div>
      </div>
      <div className="dcard">
        <div className="dcard-head"><h3>Configuration</h3></div>
        <div className="rows">
          <div className="drow"><div className="grow"><div className="ttl">Split</div></div><span className="dbadge">train</span></div>
          <div className="drow"><div className="grow"><div className="ttl">Revision</div></div><span className="dbadge">main</span></div>
          <Switch on={stream} onClick={() => setStream(!stream)} label="Stream mode" sub="don't download the full dataset" />
        </div>
      </div>
    </>}

    {err && <div className="error" role="alert">{err}</div>}
  </Page>
}
