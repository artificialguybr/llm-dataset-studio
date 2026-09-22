// Catalog — conteúdo da view Catalog do deepseek: subtabs Datasets/Sources/
// Provenança, filtro + seg, rows com dot/val/badge. Clique abre o Explorer.
import { useCallback, useEffect, useState, } from 'react'
import { api, type Dataset, type Version } from './api'
import { Page, apiErrorMessage } from './shared'
import type { Page as PageType } from './shared'
import type React from 'react'

type Tab = 'datasets' | 'sources' | 'provenance'
const fmtK = (n: number) => n >= 1_000_000 ? `${(n / 1_000_000).toFixed(1)}M` : n >= 1000 ? `${Math.round(n / 1000)}k` : String(n)

export function Dashboard({ ds, go, foot }: { ds: string; go: (p: PageType, dsId?: string) => void; foot: React.ReactNode }) {
  const [tab, setTab] = useState<Tab>('datasets')
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [versions, setVersions] = useState<Version[]>([])
  const [q, setQ] = useState('')
  const [seg, setSeg] = useState('all')
  const [newName, setNewName] = useState('')
  const [createOpen, setCreateOpen] = useState(false)
  const [creating, setCreating] = useState(false)
  const [seeding, setSeeding] = useState(false)
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    api.datasets().then(setDatasets).catch(e => setErr(e.message))
    if (ds) api.versions(ds).then(setVersions).catch(() => {})
  }, [ds])
  useEffect(() => { void load() }, [load])

  const statusOf = (d: Dataset): [string, string] => {
    const open = d.open_issues ?? 0
    if (open > 3) return ['err', `${open} flags`]
    if (open > 0) return ['warn', 'Review']
    if ((d.item_counts?.pending ?? 0) > 0 && (d.item_counts?.total ?? 0) > 0) return ['info', 'New']
    return ['ok', 'Clean']
  }
  const shown = datasets.filter(d => {
    if (q && !d.name.toLowerCase().includes(q.toLowerCase())) return false
    const [st] = statusOf(d)
    return seg === 'all' || (seg === 'clean' && st === 'ok') || (seg === 'review' && st === 'warn') || (seg === 'flagged' && st === 'err')
  })
  const current = datasets.find(d => d.id === ds) ?? null

  const create = () => {
    if (!newName.trim()) return
    setCreating(true); setErr('')
    api.createDataset(newName.trim(), 'text dataset').then(() => { setNewName(''); setCreateOpen(false); load() })
      .catch(e => setErr(e.message)).finally(() => setCreating(false))
  }

  return <Page bar={null} foot={foot}>
    <div className="dpage-head">
      <div className="ttl">
        <h1>Catalog</h1>
        <p>Everything you have — datasets, sources and their provenance.</p>
      </div>
      <div className="dpage-actions">
        <button className="btn" onClick={() => setCreateOpen(true)}>+ Add</button>
      </div>
    </div>

    <div className="subtabs">
      <button className={`subtab${tab === 'datasets' ? ' on' : ''}`} onClick={() => setTab('datasets')}>Datasets<span className="cnt">{datasets.length}</span></button>
      <button className={`subtab${tab === 'sources' ? ' on' : ''}`} onClick={() => setTab('sources')}>Sources</button>
      <button className={`subtab${tab === 'provenance' ? ' on' : ''}`} onClick={() => setTab('provenance')}>Provenance</button>
    </div>

    {tab === 'datasets' && <>
      <div className="toolbar-row">
        <div className="input-wrap">
          <span className="ico"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg></span>
          <input className="dinput" placeholder="Filter datasets…" value={q} onChange={e => setQ(e.target.value)} />
        </div>
        <div className="seg">
          {[['all', 'All'], ['clean', 'Clean'], ['review', 'Review'], ['flagged', 'Flagged']].map(([v, l]) =>
            <button key={v} className={seg === v ? 'on' : ''} onClick={() => setSeg(v)}>{l}</button>)}
        </div>
      </div>
      <div className="dcard">
        <div className="rows catalog-rows">
          {shown.length === 0 && <div className="drow"><div className="grow"><div className="ttl">No datasets yet</div><div className="sub">load the built-in sample corpus, or import your own texts</div></div><button className="primary sm" disabled={seeding} onClick={() => { setSeeding(true); setErr(''); api.seedDemo().then(r => { load(); go('dataset', r.dataset_id) }).catch(e => setErr(apiErrorMessage(e))).finally(() => setSeeding(false)) }}>{seeding ? 'Loading…' : 'Load sample dataset'}</button></div>}
          {shown.map(d => {
            const [st, label] = statusOf(d)
            const total = d.item_counts?.total ?? 0
            return <div className="drow hoverable" key={d.id} onClick={() => go('dataset', d.id)}>
              <span className={`dot ${st}`} />
              <div className="grow">
                <div className="ttl">{d.name}</div>
                <div className="sub">{d.description || 'no description'} · {(d.item_counts?.keep ?? 0).toLocaleString('en-US')} kept</div>
              </div>
              <span className="val">{fmtK(total)}</span>
              <span className={`dbadge ${st}`}><span className="b-dot" />{label}</span>
              <button className="btn icon" title="Delete dataset" aria-label={`Delete ${d.name}`}
                onClick={e => { e.stopPropagation(); if (window.confirm(`Delete "${d.name}"? Items and checkpoints are removed; source files stay on disk.`)) { setErr(''); api.deleteDataset(d.id).then(load).catch(e2 => setErr(apiErrorMessage(e2))) } }}>
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M3 6h18M8 6V4a2 2 0 012-2h4a2 2 0 012 2v2m3 0v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6"/></svg>
              </button>
            </div>
          })}
        </div>
      </div>
      {createOpen && <div className="dcard catalog-create">
        <div className="dcard-head"><h3>New dataset</h3><button className="btn" onClick={() => setCreateOpen(false)}>Cancel</button></div>
        <div className="dcard-body">
          <div className="toolbar-row" style={{ marginBottom: 0 }}>
            <div className="input-wrap">
              <input className="dinput" placeholder="dataset name…" value={newName}
                onChange={e => setNewName(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') create() }} autoFocus />
            </div>
            <button className="primary" disabled={creating || !newName.trim()} onClick={create}>{creating ? 'Adding…' : 'Add'}</button>
          </div>
        </div>
      </div>}
    </>}

    {tab === 'sources' && <>
      <div className="dcard">
        <div className="dcard-head"><h3>Local</h3><span className="desc">{datasets.length} sources</span></div>
        <div className="rows">
          {datasets.map(d => <div className="drow hoverable" key={d.id} onClick={() => go('dataset', d.id)}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" style={{ color: 'var(--muted)' }}><path d="M14 3H6a2 2 0 00-2 2v14a2 2 0 002 2h12a2 2 0 002-2V9l-6-6z"/><path d="M14 3v6h6"/></svg>
            <div className="grow"><div className="ttl">{d.name}</div><div className="sub mono">local dataset · {d.license || 'no license'}</div></div>
            <span className={`dbadge ${statusOf(d)[0]}`}><span className="b-dot" />{statusOf(d)[1]}</span>
          </div>)}
        </div>
      </div>
    </>}

    {tab === 'provenance' && (current
      ? <>
        <div className="dcard">
          <div className="meta-grid" style={{ border: 'none' }}>
            <div className="meta-cell"><div className="meta-k">License</div><div className="meta-v">{current.license || '—'}</div></div>
            <div className="meta-cell"><div className="meta-k">Origin</div><div className="meta-v">local dataset</div></div>
            <div className="meta-cell"><div className="meta-k">Manifest</div><div className="meta-v hash">{(current.current_version_id ?? '—').slice(0, 8)}</div></div>
            <div className="meta-cell"><div className="meta-k">Checkpoints</div><div className="meta-v">{versions.length}</div></div>
          </div>
          <div className="meta-grid" style={{ borderBottom: 'none' }}>
            <div className="meta-cell"><div className="meta-k">Items</div><div className="meta-v">{(current.item_counts?.total ?? 0).toLocaleString('pt-BR')}</div></div>
            <div className="meta-cell"><div className="meta-k">Kept</div><div className="meta-v">{(current.item_counts?.keep ?? 0).toLocaleString('pt-BR')}</div></div>
            <div className="meta-cell"><div className="meta-k">Flags</div><div className="meta-v">{current.open_issues ?? 0}</div></div>
            <div className="meta-cell"><div className="meta-k">Pending</div><div className="meta-v">{(current.item_counts?.pending ?? 0).toLocaleString('pt-BR')}</div></div>
          </div>
        </div>
        <div className="dcard">
          <div className="dcard-head"><h3>Lineage</h3></div>
          <div className="dcard-body">
            <div className="tl">
              {[...versions].reverse().slice(0, 6).map((v, i) => <div className={`tl-item ${i === 0 ? 'ok' : ''}`} key={v.id}>
                <div className="tl-ttl">{v.description || `v${versions.length - i}`}</div>
                <div className="tl-sub">{v.item_count} items · {new Date(v.created_at).toLocaleDateString('en-US')}</div>
              </div>)}
              {versions.length === 0 && <div className="tl-item"><div className="tl-ttl">No checkpoints yet</div><div className="tl-sub">create one in Versions</div></div>}
            </div>
          </div>
        </div>
      </>
      : <div className="dcard"><div className="dcard-body"><p className="muted">Select a dataset from the workspace to view provenance.</p></div></div>)}

    {err && <div className="error" role="alert">{err}</div>}
  </Page>
}
