// Rótulos — rotule trechos do texto com o mouse.
// Selecione um trecho na leitura → escolha a categoria → cria o rótulo do span.
// Whole-document labels and comments; no image-style layers.
import { useCallback, useEffect, useState } from 'react'

import { api, type Item, type Label } from './api'

import { I, apiErrorMessage } from './shared'
import type React from 'react'

export function AnnotationPage({ ds, foot }: { ds: string; foot: React.ReactNode }) {
  const [idx, setIdx] = useState(0)
  const [items, setItems] = useState<Item[]>([])
  const [labels, setLabels] = useState<Label[]>([])
  const [fullText, setFullText] = useState('')
  const [category, setCategory] = useState('')
  const [note, setNote] = useState('')
  const [sel, setSel] = useState<{ start: number; end: number; quote: string } | null>(null)
  const [msg, setMsg] = useState('')
  const [err, setErr] = useState('')

  const load = useCallback(() => {
    api.itemsPage(ds, { limit: '200', order: 'recent' }).then(({ items: page }) => setItems(page)).catch(e => setErr(e.message))
  }, [ds])
  useEffect(() => { load() }, [load])

  const item = items[idx]
  useEffect(() => {
    setLabels([]); setFullText(''); setSel(null)
    if (!item) return
    api.item(item.id).then((d: { item?: Item & { text_content?: string }; labels: Label[] }) => {
      setLabels(d.labels)
      setFullText(d.item?.text_content ?? '')
    }).catch(() => { setLabels([]); setFullText('') })
  }, [item])

  const categories = [...new Set(labels.map(l => l.category).filter(Boolean))]
  const onSelect = (e: React.SyntheticEvent<HTMLTextAreaElement>) => {
    const el = e.currentTarget
    const start = el.selectionStart; const end = el.selectionEnd
    if (end > start) setSel({ start, end, quote: fullText.slice(start, end) })
    else setSel(null)
  }
  const addSpanLabel = () => {
    if (!item || !sel || !category.trim()) { setErr('Select a span and enter a category'); return }
    api.addLabel(item.id, { label_type: 'span', category: category.trim(),
      span_start: sel.start, span_end: sel.end, value: { text: sel.quote }, source_type: 'human' })
      .then(() => { setMsg(`Label "${category.trim()}" created`); setSel(null); setCategory('')
        api.item(item.id).then(d => setLabels(d.labels)).catch(() => {}) })
      .catch(e => setErr(apiErrorMessage(e)))
  }
  const addDocLabel = () => {
    if (!item || !category.trim()) { setErr('Enter a label category'); return }
    api.addLabel(item.id, { label_type: 'doc', category: category.trim(), source_type: 'human' })
      .then(() => { setMsg(`documento rotulado como "${category.trim()}"`); setCategory('')
        api.item(item.id).then(d => setLabels(d.labels)).catch(() => {}) })
      .catch(e => setErr(apiErrorMessage(e)))
  }
  const addNote = () => {
    if (!item || !note.trim()) return
    api.addLabel(item.id, { label_type: 'note', category: 'comment', value: { text: note.trim() }, source_type: 'human' })
      .then(() => { setMsg('Comment saved'); setNote('')
        api.item(item.id).then(d => setLabels(d.labels)).catch(() => {}) })
      .catch(e => setErr(apiErrorMessage(e)))
  }
  const review = (id: string, status: string) =>
    api.reviewLabel(id, status).then(() => {
      setMsg(status === 'approved' ? 'Label approved' : 'Label rejected')
      api.item(item.id).then(d => setLabels(d.labels)).catch(() => {})
    }).catch(e => setErr(apiErrorMessage(e)))

  return <div className="page" style={{ overflow: 'hidden' }}>
    <div className="dpage-head">
      <div className="ttl">
        <h1>Labels</h1>
        <p>{item ? item.original_filename : 'no items'}</p>
      </div>
      <div className="dpage-actions">
        <span className="dbadge">{item ? `${idx + 1} / ${items.length}` : ''}</span>
        <button className="btn icon" disabled={idx === 0} onClick={() => setIdx(i => Math.max(0, i - 1))} aria-label="previous">{I.chevL}</button>
        <button className="btn icon" disabled={idx >= items.length - 1} onClick={() => setIdx(i => Math.min(items.length - 1, i + 1))} aria-label="next">{I.chevR}</button>
      </div>
    </div>
    {msg && <div className="ok clean-msg">{msg}</div>}
    {err && <div className="error clean-msg" onClick={() => setErr('')}>{err}</div>}
    {item && <div className="rq-stage">
      <div className="rq-read ann-read" aria-label="text to label">
        <textarea className="ann-textarea" readOnly value={fullText || item.preview || ''} aria-label="text"
          onSelect={onSelect}
          placeholder="no text" />
      </div>
      {sel && <div className="ann-selbar" role="status">
        <span className="muted">selected span: <b>“{sel.quote.slice(0, 80)}{sel.quote.length > 80 ? '…' : ''}”</b> ({sel.end - sel.start} characters)</span>
      </div>}
      <div className="ann-form">
        <label className="field-label">category
          <input list={`cats-${ds}`} value={category} onChange={e => setCategory(e.target.value)} placeholder="e.g. pii, quality, style…" />
          <datalist id={`cats-${ds}`}>{categories.map(c => <option key={c} value={c} />)}</datalist>
        </label>
        <button className="primary" disabled={!sel || !category.trim()} onClick={addSpanLabel}>label selected span</button>
        <button className="sm" disabled={!category.trim()} onClick={addDocLabel}>label entire document</button>
      </div>
      <div className="ann-form">
        <label className="field-label">comment
          <input value={note} onChange={e => setNote(e.target.value)} placeholder="note about this text…" />
        </label>
        <button className="sm" disabled={!note.trim()} onClick={addNote}>save comment</button>
      </div>
      {labels.length > 0 && <div className="xpane-issues">
        {labels.map(l => <span key={l.id} className={`pill ${l.status === 'rejected' ? 'bad' : l.status === 'pending' ? 'warn' : 'ok'}`}>
          {l.category}{l.span_start != null ? ' · “' + fullText.slice(l.span_start ?? 0, l.span_end ?? 0).slice(0, 40) + '…”' : l.label_type === 'note' ? ' · comment' : ''}
          {l.status === 'pending' && <> <button className="sm" onClick={() => review(l.id, 'approved')}>approve</button>
            <button className="sm" onClick={() => review(l.id, 'rejected')}>reject</button></>}
        </span>)}
      </div>}
      {labels.length === 0 && <p className="muted" style={{ margin: '14px 2px' }}>no labels yet — select a span in the text above to begin.</p>}
    </div>}
    {!item && <div className="empty"><b>no items</b>import text through Explore to label it here.</div>}
    {foot && <div className="footbar" style={{ marginTop: 'auto' }}>{foot}</div>}
  </div>
}
