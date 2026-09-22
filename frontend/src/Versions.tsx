// Versions — conteúdo da view Versions do deepseek: History + Diff, no design dele.
// Lógica real preservada: createVersion, versionDiff, restoreVersion.
import { useCallback, useEffect, useState, } from 'react'
import { api, type Version } from './api'
import { Page, apiErrorMessage } from './shared'
import type React from 'react'

type Tab = 'history' | 'diff'

export function VersionsPage({ ds, foot }: { ds: string; foot: React.ReactNode }) {
  const [tab, setTab] = useState<Tab>('history')
  const [versions, setVersions] = useState<Version[]>([])
  const [oldV, setOldV] = useState('')
  const [newV, setNewV] = useState('')
  const [diff, setDiff] = useState<{ added: string[]; removed: string[] } | null>(null)
  const [busy, setBusy] = useState(false)
  const [confirmRestore, setConfirmRestore] = useState(false)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  const load = useCallback(() => {
    api.versions(ds).then(v => {
      setVersions(v)
      setNewV(prev => prev || v.at(-1)?.id || '')
      setOldV(prev => prev || v.at(-2)?.id || v.at(-1)?.id || '')
    }).catch(e => setErr(apiErrorMessage(e)))
  }, [ds])
  useEffect(() => { void load() }, [load])

  const create = async () => {
    setBusy(true); setErr(''); setMsg('')
    try { await api.createVersion(ds, `checkpoint ${new Date().toLocaleString('pt-BR')}`); setMsg('checkpoint salvo'); await load() }
    catch (e) { setErr(apiErrorMessage(e)) } finally { setBusy(false) }
  }
  const compare = async () => {
    if (!oldV || !newV) return
    setBusy(true); setErr('')
    try { setDiff(await api.versionDiff(ds, oldV, newV)) } catch (e) { setErr(apiErrorMessage(e)) } finally { setBusy(false) }
  }
  const restore = async () => {
    if (!newV || !confirmRestore) return
    setBusy(true); setErr('')
    try { await api.restoreVersion(ds, newV); setMsg('checkpoint restored'); setConfirmRestore(false); await load() }
    catch (e) { setErr(apiErrorMessage(e)) } finally { setBusy(false) }
  }

  return <Page bar={null} foot={foot}>
    <div className="dpage-head">
      <div className="ttl">
        <h1>Versions</h1>
        <p>Every change kept. Diff, roll back, trace the lineage.</p>
      </div>
      <div className="dpage-actions">
        <button className="primary" disabled={busy} onClick={create}>+ Checkpoint</button>
      </div>
    </div>

    <div className="subtabs">
      <button className={`subtab${tab === 'history' ? ' on' : ''}`} onClick={() => setTab('history')}>History</button>
      <button className={`subtab${tab === 'diff' ? ' on' : ''}`} onClick={() => setTab('diff')}>Diff</button>
    </div>

    {tab === 'history' && <>
      <div className="dcard">
        <div className="rows">
          {versions.length === 0 && <div className="drow"><div className="grow"><div className="ttl">No checkpoints yet</div><div className="sub">save the state before a major change</div></div></div>}
          {[...versions].reverse().map((v, i) => <div className="drow hoverable" key={v.id} onClick={() => { setNewV(v.id); setDiff(null) }}>
            <span className={`dot ${i === 0 ? 'ok' : ''}`} />
            <div className="grow">
              <div className="ttl">v{versions.length - i}{i === 0 && <span className="dbadge ok" style={{ marginLeft: 6 }}><span className="b-dot" />Atual</span>}</div>
              <div className="sub">{v.description || 'checkpoint'} · {new Date(v.created_at).toLocaleDateString('pt-BR')} · {v.item_count} itens</div>
            </div>
            <span className="hash">{v.checksum.slice(0, 12)}</span>
          </div>)}
        </div>
      </div>
      <div className="inline-actions">
        <button className="btn" onClick={() => setTab('diff')}>Diff with current</button>
        <label className="drow" style={{ gap: 8, cursor: 'pointer', padding: '0 4px' }}>
          <input type="checkbox" checked={confirmRestore} onChange={e => setConfirmRestore(e.target.checked)} />
          <span className="sub">I understand that rolling back changes current decisions</span>
        </label>
        <button className="btn" disabled={busy || !confirmRestore || !newV} onClick={restore}>Roll back</button>
      </div>
    </>}

    {tab === 'diff' && <>
      <div className="dcard">
        <div className="dcard-head"><h3>{oldV.slice(0, 8)} → {newV.slice(0, 8)}</h3><span className="desc">{diff ? `${diff.added.length} added · ${diff.removed.length} removed` : 'select and compare'}</span></div>
        <div className="dcard-body">
          <div className="toolbar-row">
            <select className="dinput" style={{ paddingLeft: 10 }} value={oldV} onChange={e => setOldV(e.target.value)} aria-label="checkpoint antigo">
              {versions.map(v => <option key={v.id} value={v.id}>{v.description || v.id.slice(0, 8)}</option>)}
            </select>
            <select className="dinput" style={{ paddingLeft: 10 }} value={newV} onChange={e => setNewV(e.target.value)} aria-label="checkpoint novo">
              {versions.map(v => <option key={v.id} value={v.id}>{v.description || v.id.slice(0, 8)}</option>)}
            </select>
            <button className="primary" disabled={busy || !oldV || !newV} onClick={compare}>Comparar</button>
          </div>
          {diff && <div className="rows" style={{ marginTop: 14 }}>
            {diff.added.slice(0, 10).map(id => <div className="drow" key={id}>
              <span className="dot ok" />
              <div className="grow"><div className="ttl mono">+ {id.slice(0, 18)}</div><div className="sub">entered the corpus</div></div>
              <span className="mono" style={{ color: 'var(--green)' }}>+</span>
            </div>)}
            {diff.removed.slice(0, 10).map(id => <div className="drow" key={id}>
              <span className="dot err" />
              <div className="grow"><div className="ttl mono">− {id.slice(0, 18)}</div><div className="sub">left the corpus</div></div>
              <span className="mono" style={{ color: 'var(--red)' }}>−</span>
            </div>)}
          </div>}
        </div>
      </div>
    </>}

    {msg && <div className="ok" role="status">{msg}</div>}
    {err && <div className="error" role="alert">{err}</div>}
  </Page>
}
