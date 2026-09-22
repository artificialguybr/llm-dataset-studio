// Records — consolidated workspace for conversation/SFT/preference/trace records.
// One screen, four tabs; each record type gets a format-aware expanded preview:
// chat turns, chosen/rejected side-by-side, trace timeline. Read-only review:
// decisions happen in Clean/Explorer, this screen is for inspection and validation.
import { useCallback, useEffect, useState } from 'react'
import { api, type AgentTrace, type Conversation, type PreferencePair, type SFTRecord, type TextTurn } from './api'
import { I, Page, apiErrorMessage } from './shared'
import type React from 'react'

type Tab = 'conversations' | 'sft' | 'preferences' | 'traces'
const TABS: [Tab, string][] = [
  ['conversations', 'Conversations'], ['sft', 'SFT'], ['preferences', 'Preferences'], ['traces', 'Traces'],
]

const bubble = (turn: { role: string; content: string }, i: number) =>
  <div key={i} className={`bubble ${turn.role === 'assistant' ? 'right' : 'left'}`}>
    <span className="bubble-role">{turn.role}</span>
    <p>{turn.content}</p>
  </div>

export function RecordsPage({ ds, foot }: { ds: string; foot: React.ReactNode }) {
  const [tab, setTab] = useState<Tab>('conversations')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [sft, setSft] = useState<SFTRecord[]>([])
  const [pairs, setPairs] = useState<PreferencePair[]>([])
  const [traces, setTraces] = useState<AgentTrace[]>([])
  const [turns, setTurns] = useState<Record<string, TextTurn[]>>({})
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const load = useCallback(() => {
    if (!ds) return Promise.resolve()
    setLoading(true)
    return Promise.all([api.listConversations(ds), api.sftRecords(ds), api.preferencePairs(ds), api.traces(ds)])
      .then(([c, s, p, t]) => { setConversations(c); setSft(s); setPairs(p); setTraces(t) })
      .catch(e => setError(apiErrorMessage(e))).finally(() => setLoading(false))
  }, [ds])

  useEffect(() => { setExpanded(null); setTurns({}); void load() }, [load])

  useEffect(() => {
    if (tab !== 'conversations' || !expanded || turns[expanded]) return
    api.conversation(expanded).then(d => setTurns(prev => ({
      ...prev, [expanded]: ((d as Record<string, unknown>).turns as TextTurn[] | undefined) ?? [],
    }))).catch(() => setTurns(prev => ({ ...prev, [expanded]: [] })))
  }, [tab, expanded])

  const counts: Record<Tab, number> = {
    conversations: conversations.length, sft: sft.length,
    preferences: pairs.length, traces: traces.length,
  }

  const traceSteps = (tr: AgentTrace): { label: string; value: string }[] => {
    const tj = (tr.trace_json ?? {}) as Record<string, unknown>
    const steps: { label: string; value: string }[] = []
    for (const [k, v] of Object.entries(tj)) {
      const fmt = (o: unknown): string => {
        if (typeof o === 'string') return o.slice(0, 200)
        if (o && typeof o === 'object' && !Array.isArray(o)) {
          const r = (o as Record<string, unknown>).role
          const c = (o as Record<string, unknown>).content ?? (o as Record<string, unknown>).name ?? o
          return `${String(r ?? 'step')}: ${fmt(c)}`
        }
        if (Array.isArray(o)) return o.map(x => fmt(x)).join(' · ')
        return JSON.stringify(o).slice(0, 200)
      }
      if (k === 'steps' && Array.isArray(v)) {
        v.forEach((st, i) => steps.push({ label: `passo ${i + 1}`, value: fmt(st) }))
      } else if (k === 'tool_calls' && Array.isArray(v)) {
        v.forEach((tc, i) => steps.push({ label: `tool ${i + 1}`, value: fmt(tc) }))
      } else {
        steps.push({ label: k, value: JSON.stringify(v).slice(0, 160) })
      }
    }
    return steps
  }

  return <Page
    bar={<div className="dpage-head">
      <div className="ttl">
        <h1>Records</h1>
        <p>{ds ? `dataset ${ds.slice(0, 8)} · format validation` : 'select a dataset'}</p>
      </div>
      <div className="subtabs" role="tablist" style={{ marginBottom: 0 }}>
        {TABS.map(([value, label]) => <button key={value} role="tab" aria-selected={tab === value}
          className={`subtab${tab === value ? ' on' : ''}`} onClick={() => { setTab(value); setExpanded(null) }}>
          {label} <span className="cnt">{counts[value]}</span>
        </button>)}
      </div>
    </div>}
    foot={foot}>
    {error && <div className="error" role="alert">{error}</div>}
    {loading && <div className="empty">Loading…</div>}
    {!loading && <>
      {tab === 'conversations' && (conversations.length === 0
        ? <div className="empty"><b>No conversations</b><p>Import JSONL/ShareGPT/SFT data with message fields to populate.</p></div>
        : <div className="explorer-list">
          {conversations.map(c => {
            const open = expanded === c.id
            return <div key={c.id} className={`xl-row${open ? ' open' : ''}`}>
              <button className="xl-head" aria-expanded={open} onClick={() => setExpanded(open ? null : c.id)}>
                <span className="xl-name">{c.title || `conversa ${c.id.slice(0, 8)}`}</span>
                <span className="xl-preview">{c.conversation_type} · {c.turn_count} turnos · {c.total_tokens.toLocaleString()} tokens</span>
                <span className="xl-pills"><span className={`pill st-${c.decision_status}`}>{c.decision_status}</span></span>
                <span className="xl-chev">{I.chevR}</span>
              </button>
              {open && <div className="xl-body">
                <div className="chat">
                  {(turns[c.id] ?? []).length === 0 && <span className="muted">sem turnos registrados</span>}
                  {(turns[c.id] ?? []).map((tt, i) => bubble(tt, i))}
                </div>
              </div>}
            </div>
          })}
        </div>)}

      {tab === 'sft' && (sft.length === 0
        ? <div className="empty"><b>No SFT records</b><p>Import SFT/message-format data.</p></div>
        : <div className="explorer-list">
          {sft.map(r => {
            const open = expanded === r.id
            const messages = (r.messages ?? []) as { role: string; content: string }[]
            return <div key={r.id} className={`xl-row${open ? ' open' : ''}`}>
              <button className="xl-head" aria-expanded={open} onClick={() => setExpanded(open ? null : r.id)}>
                <span className="xl-name">{r.schema_type || 'sft'} · {messages.length} msgs</span>
                <span className="xl-preview">{(messages[0]?.content ?? '').slice(0, 120)}</span>
                <span className="xl-pills">
                  <span className="pill mono">{r.tokens.toLocaleString()} tokens</span>
                  <span className={`pill st-${r.status}`}>{r.status}</span>
                  {r.license && r.license !== 'unknown' && <span className="pill">{r.license}</span>}
                </span>
                <span className="xl-chev">{I.chevR}</span>
              </button>
              {open && <div className="xl-body">
                <div className="chat">{messages.map((m, i) => bubble(m, i))}</div>
                {r.system_prompt && <p className="muted">system: {r.system_prompt.slice(0, 200)}</p>}
              </div>}
            </div>
          })}
        </div>)}

      {tab === 'preferences' && (pairs.length === 0
        ? <div className="empty"><b>No preference pairs</b><p>Create chosen/rejected (DPO) pairs through import or the API.</p></div>
        : <div className="explorer-list">
          {pairs.map(p => {
            const open = expanded === p.id
            return <div key={p.id} className={`xl-row${open ? ' open' : ''}`}>
              <button className="xl-head" aria-expanded={open} onClick={() => setExpanded(open ? null : p.id)}>
                <span className="xl-name">{p.strategy || 'pair'} · {p.id.slice(0, 8)}</span>
                <span className="xl-preview">{p.prompt_text.slice(0, 120)}</span>
                <span className="xl-pills"><span className={`pill st-${p.status}`}>{p.status}</span></span>
                <span className="xl-chev">{I.chevR}</span>
              </button>
              {open && <div className="xl-body">
                <p className="xl-prompt"><b>prompt:</b> {p.prompt_text}</p>
                <div className="dpo-compare">
                  <div className="dpo-side chosen"><span className="eyebrow">CHOSEN ✓</span><p>{p.chosen_text}</p></div>
                  <div className="dpo-side rejected"><span className="eyebrow">REJECTED ✗</span><p>{p.rejected_text}</p></div>
                </div>
              </div>}
            </div>
          })}
        </div>)}

      {tab === 'traces' && (traces.length === 0
        ? <div className="empty"><b>No traces</b><p>Import agent traces, reasoning or tool-use logs.</p></div>
        : <div className="explorer-list">
          {traces.map(tr => {
            const open = expanded === tr.id
            return <div key={tr.id} className={`xl-row${open ? ' open' : ''}`}>
              <button className="xl-head" aria-expanded={open} onClick={() => setExpanded(open ? null : tr.id)}>
                <span className="xl-name">{tr.trace_type} · {tr.trace_id.slice(0, 12)}</span>
                <span className="xl-preview">{tr.model || '—'}{tr.error ? ` · erro: ${tr.error.slice(0, 60)}` : ''}</span>
                <span className="xl-pills">
                  {tr.tokens > 0 && <span className="pill mono">{tr.tokens.toLocaleString()}t</span>}
                  <span className={`pill ${tr.success === null ? '' : tr.success ? 'ok' : 'bad'}`}>
                    {tr.success === null ? '—' : tr.success ? 'sucesso' : 'falha'}
                  </span>
                </span>
                <span className="xl-chev">{I.chevR}</span>
              </button>
              {open && <div className="xl-body">
                <ol className="trace-steps">
                  {traceSteps(tr).map((st, i) => <li key={i}><b>{st.label}</b><span>{st.value}</span></li>)}
                  {traceSteps(tr).length === 0 && <span className="muted">trace sem detalhes</span>}
                </ol>
              </div>}
            </div>
          })}
        </div>)}
    </>}
    {foot && <div className="footbar" style={{ marginTop: 'auto' }}>{foot}</div>}
  </Page>
}
