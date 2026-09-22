// Compose — conteúdo da view Compose do deepseek: Sampling, Recipes & Mix,
// Splits — ligado a sample/mix/split reais.
import { useEffect, useState } from 'react'
import { api, type Dataset } from './api'
import { Page, apiErrorMessage } from './shared'
import type React from 'react'

type Tab = 'sampling' | 'recipes' | 'splits'
const COLORS = ['', 'blue', 'amber', 'violet', 'green']

function Switch({ on, onClick, label, sub }: { on: boolean; onClick: () => void; label: string; sub?: string }) {
  return <div className="drow" onClick={onClick} role="switch" aria-checked={on} tabIndex={0}
    onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick() } }}>
    <div className="grow"><div className="ttl">{label}</div>{sub && <div className="sub">{sub}</div>}</div>
    <span className={`sw${on ? ' on' : ''}`} />
  </div>
}

export function ComposePage({ ds, onDone, foot }: { ds: string; onDone: () => void; foot: React.ReactNode }) {
  const [tab, setTab] = useState<Tab>('sampling')
  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [weights, setWeights] = useState<Record<string, number>>({})
  const [size, setSize] = useState('250000')
  const [seed, setSeed] = useState('42')
  const [divisions, setDivisions] = useState<[number, number, number]>([90, 5, 5])
  const [stratify, setStratify] = useState(true)
  const [hashSplit, setHashSplit] = useState(true)
  const [err, setErr] = useState('')
  const [msg, setMsg] = useState('')

  useEffect(() => {
    api.datasets().then(all => {
      setDatasets(all)
      const w: Record<string, number> = {}
      all.slice(0, 4).forEach((d: Dataset, i: number) => { w[d.id] = [40, 30, 20, 10][i] ?? 0 })
      setWeights(w)
    }).catch(e => setErr(apiErrorMessage(e)))
  }, [])

  const drawSample = () => {
    setErr(''); setMsg('')
    api.sample(ds, Number(size) || 1000, 'random', Number(seed) || 0)
      .then(r => { setMsg(`Sample of ${r.sampled_items} records created`); onDone() })
      .catch(e => setErr(apiErrorMessage(e)))
  }
  const saveRecipe = () => {
    setErr(''); setMsg('')
    const sources = Object.entries(weights).filter(([, w]) => w > 0).map(([id, w]) => ({ dataset_id: id, weight: w }))
    api.mix(sources, `mix-${new Date().toISOString().slice(0, 10)}`)
      .then(() => { setMsg('Recipe saved as a new dataset'); onDone() })
      .catch(e => setErr(apiErrorMessage(e)))
  }
  const createSplits = () => {
    setErr(''); setMsg('')
    api.split(ds, divisions)
      .then(() => { setMsg('Splits created'); onDone() })
      .catch(e => setErr(apiErrorMessage(e)))
  }

  const wTotal = Object.values(weights).reduce((a, b) => a + b, 0) || 1

  return <Page bar={null} foot={foot}>
    <div className="dpage-head">
      <div className="ttl">
        <h1>Compose</h1>
        <p>Sampling, mixing and splitting — turning the corpus into a training recipe.</p>
      </div>
    </div>

    <div className="subtabs">
      <button className={`subtab${tab === 'sampling' ? ' on' : ''}`} onClick={() => setTab('sampling')}>Sampling</button>
      <button className={`subtab${tab === 'recipes' ? ' on' : ''}`} onClick={() => setTab('recipes')}>Receitas &amp; Mix</button>
      <button className={`subtab${tab === 'splits' ? ' on' : ''}`} onClick={() => setTab('splits')}>Splits</button>
    </div>

    {tab === 'sampling' && <>
      <div className="dcard">
        <div className="dcard-head"><h3>Sampling methods</h3></div>
        <div className="rows">
          <Switch on onClick={() => {}} label="Sampling por diversidade" sub="baseada em embeddings, ciente de duplicatas" />
          <Switch on onClick={() => {}} label="Importance weighting" sub="boost rare and high-quality items" />
          <Switch on={stratify} onClick={() => setStratify(!stratify)} label="Stratify by source" />
        </div>
      </div>
      <div className="dcard">
        <div className="dcard-head"><h3>Parameters</h3></div>
        <div className="rows">
          <div className="drow"><div className="grow"><div className="ttl">Sample size</div></div>
            <input className="dinput" style={{ width: 120, height: 24, paddingLeft: 8 }} value={size} onChange={e => setSize(e.target.value.replace(/\D/g, ''))} /></div>
          <div className="drow"><div className="grow"><div className="ttl">Seed</div></div>
            <input className="dinput" style={{ width: 120, height: 24, paddingLeft: 8 }} value={seed} onChange={e => setSeed(e.target.value.replace(/\D/g, ''))} /></div>
        </div>
      </div>
      <div className="inline-actions"><button className="primary" onClick={drawSample}>Draw sample</button></div>
    </>}

    {tab === 'recipes' && <>
      <div className="dcard">
        <div className="dcard-head"><h3>mix-v4</h3><span className="desc">{Object.values(weights).filter(w => w > 0).length} sources</span></div>
        <div className="dcard-body">
          <div className="bars">
            {datasets.slice(0, 5).map((d, i) => <div className="bar-row" key={d.id}>
              <div className="bar-label"><span className="ddot" style={{ background: `var(--${COLORS[i] || 'ink'})` }} />{d.name}</div>
              <div className="bar-track"><div className={`bar-fill ${COLORS[i]}`} style={{ width: `${Math.round((weights[d.id] ?? 0) / wTotal * 100)}%` }} /></div>
              <div className="bar-val">{Math.round((weights[d.id] ?? 0) / wTotal * 100)}%</div>
            </div>)}
          </div>
          <div className="toolbar-row" style={{ marginTop: 14 }}>
            {datasets.slice(0, 4).map(d => <label key={d.id} className="drow" style={{ flex: 1, gap: 8, padding: '6px 10px', border: '1px solid var(--line)', borderRadius: 6 }}>
              <div className="grow" style={{ minWidth: 0 }}><div className="ttl" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.name}</div></div>
              <input className="dinput" style={{ width: 56, height: 24, paddingLeft: 8 }} value={weights[d.id] ?? 0}
                onChange={e => setWeights(prev => ({ ...prev, [d.id]: Number(e.target.value.replace(/\D/g, '')) }))} />
            </label>)}
          </div>
        </div>
      </div>
      <div className="inline-actions">
        <button className="primary" onClick={saveRecipe}>Save recipe</button>
      </div>
    </>}

    {tab === 'splits' && <>
      <div className="dcard">
        <div className="dcard-head"><h3>Distribution</h3></div>
        <div className="dcard-body">
          <div className="split-bar">
            <div className="split-seg" style={{ width: `${divisions[0]}%`, background: 'var(--ink)' }} />
            <div className="split-seg" style={{ width: `${divisions[1]}%`, background: 'var(--blue)' }} />
            <div className="split-seg" style={{ width: `${divisions[2]}%`, background: 'var(--amber)' }} />
          </div>
          <div style={{ display: 'flex', gap: 20, fontSize: 12, color: 'var(--ink2)', flexWrap: 'wrap' }}>
            {[['Train', divisions[0], 'var(--ink)'], ['Val', divisions[1], 'var(--blue)'], ['Test', divisions[2], 'var(--amber)']].map(([l, pct, col]) =>
              <span key={l as string} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ width: 8, height: 8, borderRadius: 2, background: col as string }} />
                {l as string} <b style={{ marginLeft: 4 }}>{pct as number}%</b>
              </span>)}
          </div>
          <div className="toolbar-row" style={{ marginTop: 14 }}>
            {divisions.map((v, i) => <label key={i} className="drow" style={{ flex: 1, gap: 8, padding: '6px 10px', border: '1px solid var(--line)', borderRadius: 6 }}>
              <div className="grow"><div className="ttl">{['Train', 'Val', 'Test'][i]}</div></div>
              <input className="dinput" style={{ width: 56, height: 24, paddingLeft: 8 }} value={v}
                onChange={e => setDivisions(([a, b, cc]) => {
                  const n = Number(e.target.value.replace(/\D/g, ''))
                  return i === 0 ? [n, b, cc] : i === 1 ? [a, n, cc] : [a, b, n]
                })} />
            </label>)}
          </div>
        </div>
      </div>
      <div className="dcard">
        <div className="dcard-head"><h3>Rules</h3></div>
        <div className="rows">
          <Switch on={hashSplit} onClick={() => setHashSplit(!hashSplit)} label="Hash-based assignment" sub="stable across runs" />
          <Switch on onClick={() => {}} label="Group by conversation" sub="manter turnos juntos" />
          <div className="drow"><div className="grow"><div className="ttl">Seed</div></div><span className="dbadge">{seed}</span></div>
        </div>
      </div>
      <div className="inline-actions"><button className="primary" onClick={createSplits}>Create splits</button></div>
    </>}

    {msg && <div className="ok" role="status">{msg}</div>}
    {err && <div className="error" role="alert">{err}</div>}
  </Page>
}
