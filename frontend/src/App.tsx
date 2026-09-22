// App shell: hash routing, workspace bar, import dialog; pages imported per route.
import { Fragment, useCallback, useEffect, useLayoutEffect, useState } from 'react'

import { api, type Dataset } from './api'

import { Page, PageBar, I, apiErrorMessage, distBar, useJobs } from './shared'
import type { Page as PageType, Theme } from './shared'
import { Dashboard } from './Dashboard'
import { QuickCleanPage } from './QuickClean'
import { Explorer } from './Explorer'
import { IssuesPage } from './Issues'
import { AnnotationPage } from './Annotate'
import { ModelCenter } from './Models'
import { VersionsPage } from './Versions'
import { ExportPage } from './Export'
import { RecordsPage } from './Records'
import { ImportPage } from './ImportPage'
import { AnalyzePage } from './AnalyzePage'
import { CleanPage } from './CleanPage'
import { ValidatePage } from './ValidatePage'
import { CuratePage } from './CuratePage'
import { ComposePage } from './ComposePage'

function ImportDialog({ datasets, initialDs, onClose, onDone }: { datasets: Dataset[]; initialDs: string; onClose: () => void; onDone: () => void }) {
  const [target, setTarget] = useState(initialDs || datasets[0]?.id || '')
  const [path, setPath] = useState('')
  const [zip, setZip] = useState('')
  const [jsonl, setJsonl] = useState('')
  const [err, setErr] = useState('')
  const { jobs, start } = useJobs()
  const submit = () => {
    if (!target || (!path.trim() && !zip.trim() && !jsonl.trim())) return
    setErr('')
    start(() => api.startImport(target, path.trim() ? [path.trim()] : [], zip.trim() ? [zip.trim()] : [], jsonl.trim() ? [jsonl.trim()] : []), onDone).catch(e => setErr(apiErrorMessage(e)))
  }
  return <div className="import-backdrop" onClick={e => { if (e.target === e.currentTarget) onClose() }}>
      <div className="import-sheet" role="dialog" aria-modal="true" aria-labelledby="import-title">
        <div className="dialog-head"><div><span className="eyebrow">IMPORT</span><h2 id="import-title">Import text</h2><p className="sub">Add a folder, ZIP, or JSONL/Parquet/TXT to the dataset without leaving curation.</p></div><button aria-label="Close import" onClick={onClose}>×</button></div>
        <label className="field-label">Target dataset<select value={target} onChange={e => setTarget(e.target.value)}><option value="">select…</option>{datasets.map(dataset => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}</select></label>
        <label className="field-label">Local folder<input placeholder="ex: data/fixture" value={path} onChange={e => setPath(e.target.value)} /></label>
        <div className="import-or">or</div>
        <label className="field-label">ZIP file<input placeholder="ex: data/texts.zip" value={zip} onChange={e => setZip(e.target.value)} /></label>
        <label className="field-label">JSONL / Parquet<input placeholder="ex: data/records.jsonl" value={jsonl} onChange={e => setJsonl(e.target.value)} /></label>
        {err && <div className="error">{err}</div>}
        {jobs.map(job => <div className="jobbar" key={job.id}><span className="jlabel">{job.type}</span><span>{job.processed}/{job.total}</span><div className="track"><div className="fill" style={{ width: `${job.progress}%` }} /></div></div>)}
        <div className="import-actions"><span className="muted">The import runs on the backend and continues while you navigate.</span><button onClick={onClose}>cancel</button><button className="primary" disabled={!target || (!path.trim() && !zip.trim() && !jsonl.trim()) || jobs.length > 0} onClick={submit}>{jobs.length ? 'importing…' : 'start import'}</button></div>
      </div>
    </div>
}

function WorkspaceBar({ datasets, ds, onDataset, onImport, page }: { datasets: Dataset[]; ds: string; onDataset: (id: string) => void; onImport: () => void; page: PageType }) {
  const label: Record<PageType, string> = { import: 'Import', dashboard: 'Catalog', analyze: 'Analyze', clean: 'Clean', validate: 'Validate', curate: 'Curate', compose: 'Compose', versions: 'Versions', export: 'Export', models: 'Settings', queue: 'Review', dataset: 'Explore', records: 'Records', issues: 'Issues', annotation: 'Labels' }
  return <header className="workspacebar">
    <select className="workspace-dataset" aria-label="Dataset ativo" value={ds} onChange={e => onDataset(e.target.value)}><option value="">Dataset…</option>{datasets.map(dataset => <option key={dataset.id} value={dataset.id}>{dataset.name}</option>)}</select>
    <span className="busy-dot" aria-label="processamento local" />
    <span className="workspace-crumb">/ <b>{label[page]}</b></span>
    <span className="spacer" />
    <button className="btn ghost workspace-run" onClick={() => { if (ds) location.hash = `#analyze/${ds}` }}>▷ Run</button>
    <button className="btn primary workspace-import" onClick={onImport} aria-label="novo import" title="novo import">{I.plus}<span>New</span></button>
  </header>
}


// ---------- App ----------

export default function App() {
  const [page, setPage] = useState<PageType>(() => (location.hash.slice(1).split('/')[0] as PageType) || 'dashboard')
  const [ds, setDs] = useState(() => location.hash.split('/')[1] ?? '')
  const [dsName, setDsName] = useState('')
  const [dsInfo, setDsInfo] = useState<Dataset | null>(null)
  const [workspaceDatasets, setWorkspaceDatasets] = useState<Dataset[]>([])
  const [importOpen, setImportOpen] = useState(false)
  const [topSearch, setTopSearch] = useState('')
  const [theme, setTheme] = useState<Theme>(() => localStorage.getItem('ids-theme') === 'dark' ? 'dark' : 'light')
  const [reducedMotion, setReducedMotion] = useState(() => localStorage.getItem('ids-reduced-motion') === 'true')
  const [filter, setFilter] = useState<Record<string, string>>({ q: '', status: '', issue: '', license: '' })
  const [reloadKey, bumpReload] = useState(0)
  useLayoutEffect(() => {
    document.documentElement.dataset.theme = theme
    document.documentElement.dataset.reducedMotion = String(reducedMotion)
    localStorage.setItem('ids-theme', theme)
    localStorage.setItem('ids-reduced-motion', String(reducedMotion))
  }, [theme, reducedMotion])
  const onMutation = useCallback(() => { bumpReload(k => k + 1) }, [])
  const go = (p: PageType, d?: string) => {
    setImportOpen(false)
    setPage(p); if (d) setDs(d)
    location.hash = d ? `#${p}/${d}` : `#${p}`
  }
  useEffect(() => {
    const apply = () => {
      const [p, d] = location.hash.slice(1).split('/')
      setImportOpen(false)
      if (p) { setPage(p as PageType); if (d) setDs(d) }
    }
    window.addEventListener('hashchange', apply)
    return () => window.removeEventListener('hashchange', apply)
  }, [])
  useEffect(() => {
    api.datasets().then(setWorkspaceDatasets).catch(() => {})
  }, [reloadKey])
  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect — reset síncrono ao trocar de dataset/aba; fetch vem em seguida
    if (!ds) { setDsName(''); setDsInfo(null); return } // limpar ao sair do dataset é síncrono e intencional
    api.dataset(ds).then((dataset: Dataset) => {
      setDsName(dataset.name)
      setDsInfo(dataset)
      // contagens vêm prontas do get_dataset (GROUP BY no servidor) — sem fetch de 1000 itens
    }).catch(() => setDsName(ds.slice(0, 13) + '…'))
  }, [ds, reloadKey])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) return
      if (ds && (e.key === 'l' || e.key === 'L')) go('queue', ds)
      else if (ds && (e.key === 'g' || e.key === 'G')) go('dataset', ds)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ds])
  const icons: Record<PageType, React.ReactNode> = {
    dashboard: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>,
    clean: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m3 20 4-4"/><path d="m8 15 7-7"/><path d="m14 9 2-2 3 3-2 2"/><path d="m4 18 2 2h11"/><path d="M17 16h4"/></svg>,
    dataset: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="3" width="18" height="18" rx="3"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="m21 15-5-5L5 21"/></svg>,
    issues: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>,
    annotation: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>,
    versions: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>,
    export: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>,
    records: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M8 10h8M8 14h8M8 18h8"/></svg>,
                models: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 7h16M4 12h16M4 17h16"/><circle cx="8" cy="7" r="2" fill="var(--bg)"/><circle cx="15" cy="12" r="2" fill="var(--bg)"/><circle cx="11" cy="17" r="2" fill="var(--bg)"/></svg>,
    import: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3v12m0 0l-4-4m4 4l4-4M4 17v2a2 2 0 002 2h12a2 2 0 002-2v-2"/></svg>,
    analyze: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M3 3v18h18M7 15l4-4 3 3 5-6"/></svg>,
    validate: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M9 12l2 2 4-4"/><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6l8-3z"/></svg>,
    curate: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>,
    compose: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M5 21h14M6 21V9a6 6 0 1112 0v12M9 3v4M15 3v4"/></svg>,
    queue: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M4 6h16M4 12h10M4 18h7"/></svg>,
  }
  const navGroups: [string | null, PageType[]][] = [
    [null, ['import', 'dashboard']],
    ['Analysis', ['analyze']],
    ['Prepare', ['clean', 'validate', 'curate']],
    ['Build', ['compose']],
    ['Ship', ['versions', 'export']],
  ]
  const NAV_LABEL: Record<PageType, string> = {
    import: 'Import', dashboard: 'Catalog', analyze: 'Analyze',
    clean: 'Clean', validate: 'Validate', curate: 'Curate', compose: 'Compose',
    versions: 'Versions', export: 'Export', models: 'Settings',
    queue: 'Review queue', dataset: 'Explore', records: 'Records', issues: 'Issues', annotation: 'Labels',
  }
  const navHelp: Record<PageType, string> = {
    import: 'Files, folders and Hugging Face', dashboard: 'Datasets, sources and provenance',
    analyze: 'Health and shape of the corpus', clean: 'Normalize, filter, redact and screen',
    validate: 'Schemas, duplicates and contamination', curate: 'Review, preferences, traces and synthetic',
    compose: 'Sampling, mixing and splitting', versions: 'Checkpoints and diffs',
    export: 'The final package', models: 'Models and system preferences',
    queue: 'One-by-one review queue', dataset: 'Side-by-side reading',
    records: 'Conversations, SFT, preferences and traces', issues: 'Detailed issues and duplicates',
    annotation: 'Categories, spans and labels',
  }
  // thin real-context footbar
  const foot = dsInfo ? <>
    <span><b>{dsName}</b> · <span className="mono">{dsInfo.item_counts?.total ?? 0} items</span></span>
    <span className="footer-dist">{distBar(dsInfo.item_counts, dsInfo.item_counts?.total ?? 0)}</span>
    <span>{dsInfo.open_issues ? <><b style={{ color: 'var(--warn)' }}>{dsInfo.open_issues}</b> open issues</> : 'no open issues'}</span>
    <span className="spacer" />
  </> : null
  const selectWorkspaceDataset = (id: string) => {
    setFilter(current => ({ ...current, q: '' }))
    if (id) go('dataset', id); else go('dashboard')
  }
  const updateWorkspaceSearch = (value: string) => {
    setTopSearch(value)
    setFilter(current => ({ ...current, q: value }))
  }
  const refreshWorkspace = () => {
    setImportOpen(false)
    bumpReload(k => k + 1)
  }
  const noDs = <Page bar={<PageBar title="No dataset selected" sub="choose a dataset from the top menu" />} foot={foot}>
    <div className="empty"><b>Select a dataset first</b><p>Use the active dataset selector to open a workspace.</p></div>
  </Page>
  const body = (() => {
    switch (page) {
      case 'dashboard': return <Dashboard ds={ds} go={go} foot={foot} />
      case 'import': return <ImportPage ds={ds} onDone={onMutation} foot={foot} />
      case 'analyze': return ds ? <AnalyzePage ds={ds} go={go} foot={foot} /> : noDs
      case 'clean': return ds ? <CleanPage ds={ds} onDone={onMutation} foot={foot} /> : noDs
      case 'validate': return ds ? <ValidatePage ds={ds} go={go} onDone={onMutation} foot={foot} /> : noDs
      case 'curate': return ds ? <CuratePage ds={ds} go={go} foot={foot} /> : noDs
      case 'compose': return ds ? <ComposePage ds={ds} onDone={onMutation} foot={foot} /> : noDs
      case 'queue': return ds ? <QuickCleanPage ds={ds} foot={foot} /> : noDs
      case 'dataset': return ds
        ? <Explorer ds={ds} filter={filter} setFilter={setFilter} reloadKey={reloadKey} foot={foot} onMutation={onMutation} />
        : noDs
      case 'issues': return ds ? <IssuesPage ds={ds} foot={foot} /> : noDs
      case 'annotation': return ds ? <AnnotationPage ds={ds} foot={foot} /> : noDs
      case 'versions': return ds ? <VersionsPage ds={ds} foot={foot} /> : noDs
      case 'export': return ds ? <ExportPage ds={ds} foot={foot} /> : noDs
      case 'records': return ds ? <RecordsPage ds={ds} foot={foot} /> : noDs
      case 'models': return <ModelCenter foot={foot} theme={theme} onThemeChange={setTheme} reducedMotion={reducedMotion} onReducedMotionChange={setReducedMotion} />
    }
  })()

  return <div className="app">
    <div className="sidebar">
      <div className="brand">
        <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 24 24" fill="none"><path d="M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z" stroke="currentColor" strokeWidth="1.8"/><path d="M10 10h4v4h-4z" fill="currentColor"/></svg></span>
        <span><b>Corpus</b><small>Dataset Studio</small></span>
      </div>
      <label className="sidebar-workspace" role="button" tabIndex={0} aria-label="Selecionar workspace" onClick={() => document.querySelector<HTMLSelectElement>('.workspace-dataset')?.focus()} onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') document.querySelector<HTMLSelectElement>('.workspace-dataset')?.focus() }}><span className="ws-avatar">PI</span><span>{dsName || 'portuguese-instruction'}</span><span className="ws-chev">⌄</span></label>
      <label className="sidebar-search"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg><input value={topSearch} onChange={e => updateWorkspaceSearch(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && ds) go('dataset', ds) }} placeholder="Search" aria-label="Search" /><kbd>⌘K</kbd></label>
      <nav className="primary-nav">
        {navGroups.map(([grp, items]) => <Fragment key={grp ?? 'top'}>
          {grp && <div className="grp-label">{grp}</div>}
          {items.map(p =>
            <button key={p} className={page === p ? 'active' : ''} title={navHelp[p]} aria-label={`${NAV_LABEL[p]}: ${navHelp[p]}`}
              onClick={() => go(p, ds)}>{icons[p]}{NAV_LABEL[p]}
              {p === 'dashboard' && workspaceDatasets.length ? <span className="nav-cnt">{workspaceDatasets.length}</span> : null}
              {p === 'clean' && dsInfo?.open_issues ? <span className="nav-dot" /> : null}
              {p === 'curate' && dsInfo?.open_issues ? <span className="nav-cnt">{dsInfo.open_issues}</span> : null}
            </button>)}
        </Fragment>)}
      </nav>

    </div>
    <div className="main">
      <WorkspaceBar datasets={workspaceDatasets} ds={ds} page={page} onDataset={selectWorkspaceDataset} onImport={() => setImportOpen(true)} />
      {body}
    </div>
    {importOpen && <ImportDialog datasets={workspaceDatasets} initialDs={ds} onClose={() => setImportOpen(false)} onDone={refreshWorkspace} />}
  </div>
}
