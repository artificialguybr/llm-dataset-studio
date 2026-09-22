import { useCallback, useEffect, useMemo, useState } from 'react'
import { api, type ExplorerRecord, type Issue, type Item } from './api'
import { apiErrorMessage, t } from './shared'
import type React from 'react'

type Mode = 'read' | 'rapid'
type TextDetail = { item: Item & { text_content?: string }; issues: Issue[] }

const statusOptions = [['', 'All statuses'], ['review', 'Needs review'], ['pending', 'Pending'], ['keep', 'Kept'], ['quarantine', 'Quarantine'], ['reject', 'Rejected']]
const orderOptions = [['recent', 'Recent'], ['name', 'Name'], ['tokens', 'Tokens'], ['pending_first', 'Priority']]

function RecordKind({ record }: { record: ExplorerRecord }) {
  const label = record.kind === 'conversation' ? 'chat' : record.kind === 'preference' ? 'DPO' : record.kind
  return <span className="ux-pill">{label}</span>
}

function Bubble({ role, children }: { role: string; children: React.ReactNode }) {
  return <div className={`ux-bubble ${role === 'user' ? 'user' : role === 'assistant' ? 'assistant' : role === 'tool' ? 'tool' : ''}`}>
    <div className="ux-role">{role}</div>{children}
  </div>
}

function PreferenceContent({ record, onDecision }: { record: ExplorerRecord; onDecision: (decision: 'a' | 'b' | 'tie' | 'skip') => void }) {
  const p = record.payload
  return <div className="ux-preference">
    <div className="ux-question">Which answer is better for this prompt?</div>
    <Bubble role="prompt">{String(p.prompt ?? '')}</Bubble>
    <div className="ux-answers">
      <div className="ux-answer"><span className="ux-letter">A</span><div className="ux-answer-label">Response A</div>{String(p.chosen ?? '')}</div>
      <div className="ux-answer"><span className="ux-letter">B</span><div className="ux-answer-label">Response B</div>{String(p.rejected ?? '')}</div>
    </div>
    <div className="ux-preference-actions">
      <button className="ux-button primary" onClick={() => onDecision('a')}>A is better</button>
      <button className="ux-button" onClick={() => onDecision('b')}>B is better</button>
      <button className="ux-button" onClick={() => onDecision('tie')}>Tie / neither</button>
    </div>
  </div>
}

function ConversationContent({ record }: { record: ExplorerRecord }) {
  const turns = Array.isArray(record.payload.turns) ? record.payload.turns as { role: string; content: string }[] : []
  return <div className="ux-chat">{turns.map((turn, index) => <Bubble key={`${turn.role}-${index}`} role={turn.role}>{turn.content}</Bubble>)}</div>
}

function TraceContent({ record }: { record: ExplorerRecord }) {
  const trace = record.payload.trace
  return <div className="ux-trace"><pre>{typeof trace === 'string' ? trace : JSON.stringify(trace, null, 2)}</pre></div>
}

function SftContent({ record }: { record: ExplorerRecord }) {
  const messages = Array.isArray(record.payload.messages) ? record.payload.messages as { role: string; content: string }[] : []
  return <div className="ux-chat">{messages.map((message, index) => <Bubble key={`${message.role}-${index}`} role={message.role}>{message.content}</Bubble>)}</div>
}

function StandardContent({ record, text }: { record: ExplorerRecord; text?: string }) {
  if (record.kind === 'text') return <div className="ux-text">{text === undefined ? 'Loading…' : text || 'Text unavailable'}</div>
  if (record.kind === 'conversation') return <ConversationContent record={record} />
  if (record.kind === 'sft') return <SftContent record={record} />
  if (record.kind === 'trace') return <TraceContent record={record} />
  return <div className="ux-text">{record.preview}</div>
}

export function Explorer({ ds, filter, setFilter, reloadKey, foot, onMutation }: {
  ds: string; filter: Record<string, string>; setFilter: (f: Record<string, string>) => void;
  reloadKey: number; foot: React.ReactNode; onMutation: () => void
}) {
  const [records, setRecords] = useState<ExplorerRecord[]>([])
  const [total, setTotal] = useState(0)
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [textDetails, setTextDetails] = useState<Record<string, TextDetail>>({})
  const [mode, setMode] = useState<Mode>('read')
  const [detailsOpen, setDetailsOpen] = useState(false)
  const [query, setQuery] = useState(filter.q ?? '')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)

  const load = useCallback(async () => {
    setLoading(true); setError('')
    try {
      const result = await api.explorer(ds, {
        q: filter.q ?? '', status: filter.status ?? '', issue: filter.issue ?? '',
        record_filter: filter.record_filter ?? '', order: filter.order ?? 'recent', limit: '100', offset: '0',
      })
      setRecords(result.records); setTotal(result.total)
      setSelectedId(current => current && result.records.some(r => r.id === current) ? current : result.records[0]?.id ?? null)
    } catch (e) { setError(apiErrorMessage(e)) } finally { setLoading(false) }
  }, [ds, filter.q, filter.status, filter.issue, filter.record_filter, filter.order])

  useEffect(() => { void load() }, [load, reloadKey])
  useEffect(() => { setQuery(filter.q ?? '') }, [filter.q])

  const selected = records.find(record => record.id === selectedId) ?? null
  const selectedDetail = selected?.kind === 'text' ? textDetails[selected.id] : undefined

  useEffect(() => {
    if (!selected || selected.kind !== 'text' || textDetails[selected.id]) return
    api.item(selected.id).then(data => setTextDetails(current => ({ ...current, [selected.id]: data as TextDetail })))
      .catch(() => setTextDetails(current => ({ ...current, [selected.id]: { item: { text_content: '' } as TextDetail['item'], issues: [] } })))
  }, [selected, textDetails])

  const loadMore = async () => {
    if (loadingMore || records.length >= total) return
    setLoadingMore(true)
    try {
      const result = await api.explorer(ds, {
        q: filter.q ?? '', status: filter.status ?? '', issue: filter.issue ?? '',
        record_filter: filter.record_filter ?? '', order: filter.order ?? 'recent', limit: '100', offset: String(records.length),
      })
      setRecords(current => current.concat(result.records))
    } catch (e) { setError(apiErrorMessage(e)) } finally { setLoadingMore(false) }
  }

  const updateFilter = (name: string, value: string) => setFilter({ ...filter, [name]: value })
  const submitSearch = () => updateFilter('q', query.trim())

  const decide = async (record: ExplorerRecord, decision: string) => {
    try {
      if (record.kind === 'preference' && (decision === 'a' || decision === 'b' || decision === 'tie')) {
        await api.preferenceDecision(record.id, decision)
      } else if (record.kind === 'text') {
        await api.setDecision(record.id, decision, 'explorer')
      } else if (record.kind === 'conversation') {
        await api.explorerDecision(record.id, decision)
      } else {
        setMessage('This record type is read-only for now'); return
      }
      setMessage(record.kind === 'preference' ? 'Preference saved' : `${t(decision)} applied`)
      onMutation()
      const currentIndex = records.findIndex(item => item.id === record.id)
      const next = records[currentIndex + 1] ?? records[currentIndex - 1]
      setSelectedId(next?.id ?? null)
      await load()
    } catch (e) { setError(apiErrorMessage(e)) }
  }

  const moveSelection = (delta: number) => {
    if (!records.length) return
    const index = Math.max(0, records.findIndex(record => record.id === selectedId))
    setSelectedId(records[(index + delta + records.length) % records.length].id)
  }

  useEffect(() => {
    if (mode !== 'rapid') return
    const onKey = (event: KeyboardEvent) => {
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement || event.target instanceof HTMLTextAreaElement) return
      if (event.key.toLowerCase() === 'j') moveSelection(1)
      if (event.key.toLowerCase() === 'k') moveSelection(-1)
      if (event.key.toLowerCase() === 'u') setMessage('Undo is available from the record history')
      if (!selected) return
      if (selected.kind === 'preference') {
        if (event.key.toLowerCase() === 'a') void decide(selected, 'a')
        if (event.key.toLowerCase() === 'b') void decide(selected, 'b')
        if (event.key.toLowerCase() === 's') void decide(selected, 'skip')
      } else {
        const decisions = ['keep', 'review', 'quarantine', 'reject']
        const decision = decisions[Number(event.key) - 1]
        if (decision) void decide(selected, decision)
      }
    }
    window.addEventListener('keydown', onKey); return () => window.removeEventListener('keydown', onKey)
  })

  const filterChips = useMemo(() => [
    ['', 'All records'], ['review', 'Needs review'], ['conversation', 'Conversations'],
    ['preference', 'Preference pairs'], ['has_tool_calls', 'Has tool calls'], ['missing_final', 'Missing final response'],
  ], [])

  const renderMain = () => {
    if (!selected) return <div className="ux-empty">No records match these filters.</div>
    if (selected.kind === 'preference') return <PreferenceContent record={selected} onDecision={decision => void decide(selected, decision)} />
    return <StandardContent record={selected} text={selectedDetail?.item?.text_content} />
  }

  const reviewActions = selected?.kind === 'preference'
    ? null
    : <div className="ux-reviewbar">
        <button className="ux-button keep" onClick={() => selected && void decide(selected, 'keep')}>Keep</button>
        <button className="ux-button" onClick={() => selected && void decide(selected, 'review')}>Review</button>
        <button className="ux-button" onClick={() => selected && void decide(selected, 'quarantine')}>Quarantine</button>
        <button className="ux-button reject" onClick={() => selected && void decide(selected, 'reject')}>Reject</button>
        <span className="ux-next">J / K next · 1–4 decide · U undo</span>
      </div>

  return <div className="page explorer-page">
    <div className="dpage-head"><div className="ttl"><h1>Explore</h1><p>Search, understand, decide, and continue later — with one consistent record workspace.</p></div><div className="dpage-actions"><span className="dbadge">{total.toLocaleString()} records</span></div></div>
    <div className="ux-app">
      <div className="ux-top"><b>Explore</b><span className="ux-dataset">{ds}</span><span className="spacer" /><span className="ux-pill">{total.toLocaleString()} records</span><button className="ux-button" onClick={() => setDetailsOpen(open => !open)}>Details</button><button className="ux-button primary" onClick={() => { localStorage.setItem(`lds-explorer-view:${ds}`, JSON.stringify(filter)); setMessage('View saved locally') }}>Save view</button></div>
      <div className="ux-command"><div className="ux-search">⌕<input aria-label="Search records" placeholder="Search records, prompts, roles, or trace steps" value={query} onChange={event => setQuery(event.target.value)} onKeyDown={event => { if (event.key === 'Enter') submitSearch() }} /></div><select value={filter.status ?? ''} onChange={event => updateFilter('status', event.target.value)}>{statusOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><select value={filter.order ?? 'recent'} onChange={event => updateFilter('order', event.target.value)}>{orderOptions.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select><div className="ux-mode"><button className={mode === 'read' ? 'on' : ''} onClick={() => setMode('read')}>Read</button><button className={mode === 'rapid' ? 'on' : ''} onClick={() => setMode('rapid')}>Rapid review</button></div></div>
      <div className="ux-filters"><span>Filters:</span>{filterChips.map(([value, label]) => <button key={value} className={`ux-pill${(filter.record_filter ?? '') === value ? ' active' : ''}`} onClick={() => updateFilter('record_filter', value)}>{label}</button>)}<select value={filter.issue ?? ''} onChange={event => updateFilter('issue', event.target.value)}><option value="">Issue type</option>{['pii', 'toxicity', 'repetition', 'spam', 'code', 'too-short', 'too-long', 'contamination'].map(issue => <option key={issue} value={issue}>{t(issue)}</option>)}</select></div>
      {message && <div className="ok" role="status" onClick={() => setMessage('')}>{message}</div>}{error && <div className="error" role="alert" onClick={() => setError('')}>{error}</div>}
      {mode === 'read' ? <div className="ux-workspace"><aside className="ux-queue"><div className="ux-queue-head"><b>Records</b><span>{loading ? 'Loading…' : `${total.toLocaleString()} total`}</span></div>{records.map(record => <button key={record.id} className={`ux-row${record.id === selectedId ? ' selected' : ''}`} onClick={() => setSelectedId(record.id)}><span className={`ux-dot ${record.status === 'review' || record.status === 'pending' ? 'warn' : record.status === 'reject' ? 'red' : ''}`} /><span className="ux-rowbody"><span className="ux-name">{record.title}</span><span className="ux-preview">{record.preview || 'No preview'}</span></span><span className="ux-rowmeta"><RecordKind record={record} /></span></button>)}{records.length === 0 && <div className="ux-empty small">No records match these filters.</div>}{records.length < total && <button className="ux-load-more" onClick={() => void loadMore()} disabled={loadingMore}>{loadingMore ? 'Loading…' : `Load more · ${total - records.length} remaining`}</button>}</aside><section className="ux-reader"><div className="ux-reader-head"><div><div className="ux-label">{selected?.kind === 'preference' ? 'Preference review' : selected?.kind === 'conversation' ? 'Conversation review' : selected?.kind === 'trace' ? 'Trace review' : selected?.kind === 'sft' ? 'Instruction review' : 'Text review'}</div><h2>{selected?.title ?? 'No record selected'}</h2><p>{selected ? `${selected.kind} · ${selected.tokens.toLocaleString()} tokens${selected.language ? ` · ${selected.language}` : ''}` : 'Choose a record from the queue'}</p></div><span className="spacer" />{selected && <span className="ux-pill">{t(selected.status)}</span>}</div><div className="ux-content">{renderMain()}</div>{reviewActions}</section></div> : <div className="ux-rapid"><div className="ux-rapid-card"><div className="ux-label">Rapid review · {selected ? `${records.findIndex(record => record.id === selected.id) + 1} / ${records.length}` : '0 / 0'}</div><div className="ux-rapid-head"><div><h2>{selected?.kind === 'preference' ? 'Which answer is better?' : selected?.title ?? 'No record selected'}</h2><p>{selected ? `${selected.kind} · ${selected.tokens.toLocaleString()} tokens` : 'No records match these filters'}</p></div><span className="spacer" /><span className="ux-pill">{total ? `${Math.round(((records.findIndex(record => record.id === selected?.id) + 1) / total) * 100)}% position` : '0%'}</span></div><div className="ux-progress"><i style={{ width: `${total ? Math.max(3, ((records.findIndex(record => record.id === selected?.id) + 1) / total) * 100) : 0}%` }} /></div>{renderMain()}{selected?.kind === 'preference' ? <div className="ux-shortcuts">A / ← response A · B / → response B · S skip · J next · U undo</div> : <div className="ux-rapid-actions"><button className="ux-button keep" onClick={() => selected && void decide(selected, 'keep')}>Keep</button><button className="ux-button" onClick={() => selected && void decide(selected, 'review')}>Review</button><button className="ux-button" onClick={() => selected && void decide(selected, 'quarantine')}>Quarantine</button><button className="ux-button reject" onClick={() => selected && void decide(selected, 'reject')}>Reject</button><span className="ux-shortcuts">1–4 decide · J next · U undo</span></div>}</div></div>}
      {detailsOpen && <div className="ux-drawer"><div><b>Dataset</b><span>{ds}</span></div><div><b>Current filters</b><span>{filter.status || 'all statuses'} · {filter.order || 'recent'}</span></div><div><b>Session</b><span>Selection remains while you review</span></div></div>}
    </div>{foot && <div className="footbar" style={{ marginTop: 'auto' }}>{foot}</div>}
  </div>
}
