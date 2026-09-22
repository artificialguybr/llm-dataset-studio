// Fila — um registro por vez, em painel de leitura grande com evidências
// destacadas no próprio texto. Decisões no teclado: K X Q P, desfazer Z.
import { useCallback, useEffect, useState, } from 'react'

import { api, type Issue, type Item, type Label } from './api'
import type React from 'react'
import { I, ISSUE_LABELS, t } from './shared'
import { highlightText } from './highlight'

export function QuickCleanPage({ ds, foot }: { ds: string; foot: React.ReactNode }) {
  const [items, setItems] = useState<Item[]>([])
  const [idx, setIdx] = useState(0)
  const [msg, setMsg] = useState('')
  const [comment, setComment] = useState('')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const [history, setHistory] = useState<{ id: string; prev: string; next: string }[]>([])
  const [queueTotal, setQueueTotal] = useState(0)
  const [itemInfo, setItemInfo] = useState<{ issues: Issue[]; labels: Label[]; text: string } | null>(null)
  useEffect(() => {
    setQueueTotal(0); setHistory([])
  }, [ds])
  const load = useCallback(() => {
    const drain = (offset: number): Promise<void> =>
      api.itemsPage(ds, { limit: '200', order: 'pending_first', queue: '1', offset: String(offset) })
        .then(({ items: page, total }) => {
          setItems(prev => (offset === 0 ? page : prev.concat(page)))
          setQueueTotal(total || page.length)
          if (offset + page.length < total) return drain(offset + page.length)
        }).catch(e => setErr(e.message))
    setIdx(0)
    return drain(0)
  }, [ds])
  useEffect(() => { load() }, [load])
  const item = items[idx]
  useEffect(() => {
    setItemInfo(null)
    if (item) api.item(item.id).then(d => setItemInfo({
      issues: d.issues, labels: d.labels,
      text: ((d as { item?: Item & { text_content?: string } }).item?.text_content) ?? '',
    })).catch(() => {})
  }, [item])
  const decide = useCallback((decision: string) => {
    if (!item || busy) return
    setBusy(true); setErr('')
    api.setDecision(item.id, decision, 'quick-clean').then(() => {
      setMsg(`${item.original_filename}: ${t(decision)}`)
      setHistory(h => [...h, { id: item.id, prev: item.decision_status, next: decision }])
      setItems(prev => prev.filter(x => x.id !== item.id))
      setIdx(i => Math.min(i, Math.max(0, items.length - 2)))
    }).catch(e => setErr(e.message)).finally(() => setBusy(false))
  }, [item, busy, items.length])
  const undo = useCallback(() => {
    const last = history[history.length - 1]
    if (!last || busy) return
    setBusy(true); setErr('')
    api.setDecision(last.id, last.prev, 'undo').then(() => {
      setHistory(h => h.slice(0, -1))
      setMsg(`desfeito: ${t(last.next)} → ${t(last.prev)}`)
      load()
    }).catch(e => setErr(e.message)).finally(() => setBusy(false))
  }, [history, busy, load])
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) return
      if (e.key === 'k' || e.key === 'K') decide('keep')
      else if (e.key === 'x' || e.key === 'X') decide('quarantine')
      else if (e.key === 'q' || e.key === 'Q') decide('review')
      else if (e.key === 'p' || e.key === 'P') decide('reject')
      else if (e.key === 'z' || e.key === 'Z') undo()
      else if (e.key === ' ' || e.key === 'ArrowRight') { e.preventDefault(); setIdx(i => Math.min(items.length - 1, i + 1)) }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); setIdx(i => Math.max(0, i - 1)) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [items.length, item, busy, history, decide, undo])
  const doneCount = Math.max(0, queueTotal - items.length)
  const pct = queueTotal ? Math.round((doneCount / queueTotal) * 100) : items.length ? 0 : 100
  const openIssues = itemInfo?.issues.filter(i => i.status === 'open') ?? []

  const meterTicks = (pct: number, n = 30) =>
    [...Array(n)].map((_, i) => <i key={i} className={i < Math.round(n * Math.min(100, Math.max(0, pct)) / 100) ? 'on' : ''} />)

  return <div className="review">
    <div className="dpage-head">
      <div className="ttl">
        <h1>Review queue</h1>
        <p>Originals never change — every decision is reversible. Shortcuts: K keep · X quarantine · Q review · P reject · Z undo.</p>
      </div>
      <div className="dpage-actions">
        <span className="dbadge" aria-live="polite">{items.length ? `${doneCount + 1} / ${queueTotal} · ${pct}%` : 'queue empty'}</span>
        <button className="btn icon" disabled={!history.length || busy} onClick={undo} title="desfazer (Z)" aria-label="desfazer">{I.undo}</button>
      </div>
    </div>
    <div className="meter" aria-label={`${pct}% decidido`}>{meterTicks(pct)}</div>
    {msg && <div className="ok clean-msg">{msg}</div>}
    {err && <div className="error clean-msg">{err}</div>}
    {!item && !err && <div className="empty clean-done"><b>queue empty</b>every text that needed a decision has been handled.</div>}
    {item && <div className="rq-stage">
      <div className="rq-meta">
        <b>{item.original_filename}</b>
        <span className="mono">{item.char_count ?? 0}c · {(item.tokens ?? 0).toLocaleString()}t · {item.language || '—'}</span>
        <span className="spacer" />
        <span className="muted">{idx + 1} / {items.length}</span>
        <button className="sm" disabled={idx === 0} onClick={() => setIdx(i => Math.max(0, i - 1))} aria-label="anterior">{I.chevL}</button>
        <button className="sm" disabled={idx >= items.length - 1} onClick={() => setIdx(i => Math.min(items.length - 1, i + 1))} aria-label="next">{I.chevR}</button>
      </div>
      <div className="mstrip">
        <span className="pill mono">#{(items[idx]?.id ?? '').slice(0, 8)}</span>
        {openIssues.map(i => <span key={i.id} className="pill warn">{ISSUE_LABELS[i.issue_type] ?? i.issue_type}</span>)}
        {openIssues.length === 0 && <span className="pill ok">sem achados</span>}
        <span className="spacer" />
        <span className={`pill ${item.decision_status === 'keep' ? 'ok' : item.decision_status === 'reject' ? 'bad' : item.decision_status === 'review' ? 'warn' : ''}`}>{t(item.decision_status)}</span>
      </div>
      {openIssues.length > 0 && <div className="rq-issues">
        {openIssues.map(i => <span key={i.id} className="pill warn">
          {ISSUE_LABELS[i.issue_type] ?? i.issue_type}{typeof i.score === 'number' ? ` · ${i.score.toFixed(2)}` : ''}</span>)}
      </div>}
      <div className="rq-read" aria-label="text under review">
        {item.ingest_status === 'error'
          ? <><b>Unable to open the file.</b>{'\n'}Quarantine keeps the original intact and removes the item from publication candidates.</>
          : itemInfo === null
            ? 'Loading text…'
            : highlightText(itemInfo.text || item.preview || '(sem texto)', openIssues)}
      </div>
      <label className="f">review comment</label>
      <textarea rows={2} value={comment} onChange={e => setComment(e.target.value)} placeholder="note attached to this decision…" />
      <div className="rq-actions" role="group" aria-label="Decision">
        <button className="dk keep" disabled={busy} onClick={() => decide('keep')}>Keep<kbd>K</kbd></button>
        <button className="dk quarantine" disabled={busy} onClick={() => decide('quarantine')}>Quarantine<kbd>X</kbd></button>
        <button className="dk review-decision" disabled={busy} onClick={() => decide('review')}>Review<kbd>Q</kbd></button>
        <button className="dk reject" disabled={busy} onClick={() => decide('reject')}>Reject<kbd>P</kbd></button>
      </div>
      <div className="rq-keys">shortcuts: <kbd>K</kbd> keep · <kbd>X</kbd> quarantine · <kbd>Q</kbd> review · <kbd>P</kbd> reject · <kbd>Z</kbd> undo · <kbd>←</kbd><kbd>→</kbd> navigate</div>
    </div>}
    {foot && <div className="footbar" style={{ marginTop: 'auto' }}>{foot}</div>}
  </div>
}
