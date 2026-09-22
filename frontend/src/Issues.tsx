// Issues — quality ledger + detector calibration + duplicate review (text datasets).
import { useCallback, useEffect, useMemo, useState } from 'react'

import { api, type DupGroup, type Issue, type Item } from './api'

import { I, ISSUE_LABELS, Page, t, } from './shared'
import type React from 'react'

export function IssuesPage({ ds, foot }: { ds: string; foot: React.ReactNode }) {
  const [issues, setIssues] = useState<Issue[]>([])
  const [duplicateGroups, setDuplicateGroups] = useState<DupGroup[]>([])
  const [reviewMode, setReviewMode] = useState<'issues' | 'duplicates'>('issues')
  const [duplicateView, setDuplicateView] = useState<'list' | 'fast'>('list')
  const [duplicatePage, setDuplicatePage] = useState(0)
  const [fastIndex, setFastIndex] = useState(0)
  const [fastDetails, setFastDetails] = useState<'left' | 'right' | null>(null)
  const [calib, setCalib] = useState('')
  const [thresholds, setThresholds] = useState<Record<string, number>>({})

  const load = useCallback(() => {
    api.issues(ds).then(setIssues)
    api.dataset(ds).then(d => setThresholds(d.thresholds_json ?? {})).catch(console.error)
  }, [ds])
  useEffect(() => { load() }, [load])

  const loadDuplicates = useCallback(() => {
    api.duplicates(ds).then(setDuplicateGroups).catch(console.error)
  }, [ds])
  useEffect(() => { loadDuplicates() }, [loadDuplicates])

  useEffect(() => {
    setDuplicatePage(0)
    setFastIndex(0)
    setFastDetails(null)
  }, [ds, reviewMode, duplicateView])

  const openIssues = issues.filter(i => i.status === 'open')

  const itemById = useMemo(() => new Map<string, Item>([
    ...issues.map(i => [i.item_id ?? i.text_id, i as unknown as Item] as [string, Item]),
    ...duplicateGroups.flatMap(g => g.members.map(m => [m.text_id, m as unknown as Item] as [string, Item])),
  ]), [issues, duplicateGroups])

  const byType = useMemo(() => {
    const m = new Map<string, Issue[]>()
    for (const i of openIssues) m.set(i.issue_type, [...(m.get(i.issue_type) ?? []), i])
    for (const v of m.values()) v.sort((a, b) => b.score - a.score)
    return m
  }, [openIssues])

  const repeatedItems = duplicateGroups.reduce((total, group) => total + group.members.length, 0)
  const canonicalItems = duplicateGroups.reduce((total, group) => total + group.members.filter(member => member.is_canonical).length, 0)
  const duplicatePageSize = 3
  const duplicatePageCount = Math.max(1, Math.ceil(duplicateGroups.length / duplicatePageSize))
  const visibleDuplicateGroups = duplicateGroups.slice(duplicatePage * duplicatePageSize, (duplicatePage + 1) * duplicatePageSize)

  const fastPairs = useMemo(() => duplicateGroups.flatMap(({ group, members }) => {
    const left = members.find(member => member.is_canonical) ?? members[0]
    if (!left) return []
    return members.filter(member => member.text_id !== left.text_id).map(right => ({ groupId: group.id, left, right }))
  }), [duplicateGroups])
  const fastPair = fastPairs[fastIndex]

  const THRESHOLD_KEYS: Record<string, string> = {
    language: 'language_threshold', repetition: 'repetition_threshold', 'too-short': 'min_length',
    'too-long': 'max_length', spam: 'spam_threshold', code: 'code_threshold',
    pii: 'pii_threshold', secrets: 'secrets_threshold', toxicity: 'toxicity_threshold',
    safety: 'safety_threshold', schema: 'schema_threshold', missing: 'missing_threshold', empty: 'empty_threshold',
  }

  const saveThreshold = (key: string, value: number) => {
    const next = { ...thresholds, [key]: value }
    setThresholds(next)
    fetch(`/api/datasets/${ds}`, { method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ thresholds_json: next }) }).then(load)
  }

  const quarantine = (itemId: string, reason: string) => api.setDecision(itemId, 'quarantine', reason).then(load)
  const quarantineDuplicates = (members: DupGroup['members']) => {
    const duplicates = members.filter(member => !member.is_canonical)
    return Promise.all(duplicates.map(member => api.setDecision(member.text_id, 'quarantine', 'duplicate')))
      .then(() => { load(); loadDuplicates() })
  }

  const chooseFast = useCallback((choice: 1 | 2) => {
    if (!fastPair) return
    const keep = choice === 1 ? fastPair.left : fastPair.right
    const discard = choice === 1 ? fastPair.right : fastPair.left
    Promise.all([
      api.setDecision(keep.text_id, 'keep', 'duplicate fast mode'),
      api.setDecision(discard.text_id, 'quarantine', 'duplicate fast mode'),
    ]).then(async () => {
      if (!keep.is_canonical) await api.swapCanonical(fastPair.groupId, keep.text_id)
      load()
      await loadDuplicates()
      setFastDetails(null)
      setFastIndex(index => Math.min(index, Math.max(0, fastPairs.length - 2)))
    }).catch(console.error)
  }, [fastPair, fastPairs.length, load, loadDuplicates])

  useEffect(() => {
    if (reviewMode !== 'duplicates' || duplicateView !== 'fast') return
    const onKey = (e: KeyboardEvent) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) return
      if (e.key === '1') chooseFast(1)
      else if (e.key === '2') chooseFast(2)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [reviewMode, duplicateView, fastPair, chooseFast])

  const fastCard = (member: DupGroup['members'][number], number: 1 | 2, side: 'left' | 'right') => {
    const item = itemById.get(member.text_id)
    const details = fastDetails === side
    return <article className="fast-card">
      <div className="fast-card-head"><span>ITEM {number}</span><b>{member.is_canonical ? 'current canonical' : 'duplicate candidate'}</b></div>
      <div className="fast-card-tabs" role="tablist" aria-label={`Item ${number} view`}>
        <button role="tab" aria-selected={!details} className={!details ? 'active' : ''} onClick={() => setFastDetails(null)}>content</button>
        <button role="tab" aria-selected={details} className={details ? 'active' : ''} onClick={() => setFastDetails(side)}>details</button>
      </div>
      {details
        ? <dl className="fast-details">
            <dt>filename</dt><dd>{item?.original_filename ?? 'unavailable'}</dd>
            <dt>location</dt><dd>{item?.relative_path || 'root'}</dd>
            <dt>tokens</dt><dd>{item?.tokens ?? '—'}</dd>
            <dt>language</dt><dd>{item?.language ?? '—'}</dd>
            <dt>size</dt><dd>{item ? `${(item.byte_size / 1024).toFixed(0)} kB` : '—'}</dd>
            <dt>similarity</dt><dd>{(member.similarity * 100).toFixed(0)}%</dd>
          </dl>
        : <pre className="fast-text" aria-label={`Keep item ${number}`}>
            {item?.text_content?.slice(0, 2000) ?? item?.preview?.slice(0, 2000) ?? 'Text unavailable'}
          </pre>}
      <button className="primary fast-keep" onClick={() => chooseFast(number)}>keep item {number} <kbd>{number}</kbd></button>
    </article>
  }

  const markReviewed = (issueId: string) => api.ackIssue(issueId, 'acknowledged').then(load)

  return <Page
    bar={<div className="dpage-head">
      <div className="ttl">
        <h1>Issues</h1>
        <p>{reviewMode === 'duplicates'
          ? `${duplicateGroups.length} duplicate groups · compare before deciding`
          : `${openIssues.length} open issues · review examples and decide`}</p>
      </div>
      <div className="dpage-actions"><span className="dbadge warn"><span className="b-dot" />{reviewMode === 'issues' ? openIssues.length : duplicateGroups.length}</span></div>
    </div>}
    foot={foot}>
    <div className="subtabs" role="tablist" aria-label="Review type">
      <button role="tab" aria-selected={reviewMode === 'issues'} className={`subtab${reviewMode === 'issues' ? ' on' : ''}`} onClick={() => setReviewMode('issues')}>Quality alerts <span className="cnt">{openIssues.length}</span></button>
      <button role="tab" aria-selected={reviewMode === 'duplicates'} className={`subtab${reviewMode === 'duplicates' ? ' on' : ''}`} onClick={() => setReviewMode('duplicates')}>Duplicates <span className="cnt">{duplicateGroups.length}</span></button>
    </div>
    {reviewMode === 'issues' && <>
      {openIssues.length === 0 && <div className="empty"><b>No quality alerts</b>run the "Quality" job on the Home page to analyze the dataset</div>}
      {calib && byType.get(calib) && <div className="review-examples-panel card">
        <div className="review-examples-head">
          <div><h3>Review examples — {ISSUE_LABELS[calib] ?? calib}</h3><p>Inspect each text, then choose the outcome. The original stays safe until you decide.</p></div>
          <button className="go" onClick={() => setCalib('')}>close examples</button>
        </div>
        {THRESHOLD_KEYS[calib] && <div className="review-sensitivity">
          <span>detector sensitivity</span>
          <input type="range" style={{ flex: 1, minWidth: 160 }} min={0}
                 max={THRESHOLD_KEYS[calib] === 'aspect_limit' ? 10 : 500}
                 step={THRESHOLD_KEYS[calib] === 'aspect_limit' || THRESHOLD_KEYS[calib] === 'min_resolution' ? 1 : 5}
                 value={thresholds[THRESHOLD_KEYS[calib]] ?? 0}
                 onChange={e => saveThreshold(THRESHOLD_KEYS[calib], Number(e.target.value))} />
          <b className="mono">{thresholds[THRESHOLD_KEYS[calib]] ?? '—'}</b>
          <span className="muted">rerun Quality to update the queue</span>
        </div>}
        <div className="review-example-list">
          {byType.get(calib)!.slice(0, 12).map((issue, index) => {
            const item = itemById.get(issue.item_id ?? issue.text_id)
            return <div key={issue.id} className="review-example-row">
              <div className="review-example-thumb" aria-label={`View text content`}>
                {item?.ingest_status === 'error' ? <span>×</span> : <span>{item?.text_content?.slice(0, 80) ?? item?.preview?.slice(0, 80) ?? '...'}</span>}
              </div>
              <span className="review-example-index">{String(index + 1).padStart(2, '0')}</span>
              <span className="review-example-copy"><b>{item?.original_filename ?? issue.text_id.slice(0, 8)}</b><span>{item?.relative_path || 'root'} · {item ? `${item.tokens ?? '?'} tokens · ${item?.language ?? '?'}` : 'details unavailable'}</span><span className="mono">{issue.detector_name} · score {issue.score.toFixed(2)} · threshold {issue.threshold.toFixed(2)}</span></span>
              <span className="review-example-status">{t(issue.status)}</span>
              <div className="review-example-actions">
                <button className="sm review-quarantine" onClick={() => quarantine(issue.item_id ?? issue.text_id, issue.issue_type)}>Quarantine</button>
                <button className="sm" onClick={() => markReviewed(issue.id)}>mark reviewed</button>
              </div>
            </div>
          })}
        </div>
      </div>}
      <div className="review-alerts">
        {[...byType.entries()].map(([k, list], groupIndex) => {
          const worst = list[0]
          const worstItem = itemById.get(worst.item_id ?? worst.text_id)
          return <div key={k} className="review-alert-row">
            <span className="review-alert-number">{String(groupIndex + 1).padStart(2, '0')}</span>
            <span className="review-alert-icon">{I.warn}</span>
            <button className="review-alert-preview" aria-label={`View text preview`} onClick={() => { /* preview */ }}>
              {worstItem?.ingest_status === 'error' ? <span>×</span> : <span>{worstItem?.text_content?.slice(0, 80) ?? worstItem?.preview?.slice(0, 80) ?? '...'}</span>}
            </button>
            <span className="review-alert-copy"><b>{ISSUE_LABELS[k] ?? k}</b><span>{worstItem?.original_filename ?? worst.text_id.slice(0, 8)} · {worst.detector_name}</span></span>
            <span className="review-alert-count"><b>{list.length}</b><span>open</span></span>
            <button className="go review-alert-action" onClick={() => quarantine(worst.item_id ?? worst.text_id, k)}>Quarantine worst</button>
            <button className="go review-alert-action" onClick={() => setCalib(calib === k ? '' : k)}>{calib === k ? 'Hide examples' : 'Review examples'}</button>
          </div>
        })}
      </div>
    </>}
    {reviewMode === 'duplicates' && <>
      <div className="dup-overview" aria-label="Duplicates overview">
        <span><b>{duplicateGroups.length}</b> groups detected</span>
        <span><b>{repeatedItems}</b> items involved</span>
        <span><b>{canonicalItems}</b> canonicals set</span>
      </div>
      <div className="duplicate-mode-switch" role="tablist" aria-label="Duplicate review mode">
        <button role="tab" aria-selected={duplicateView === 'list'} className={duplicateView === 'list' ? 'active' : ''} onClick={() => setDuplicateView('list')}>All groups</button>
        <button role="tab" aria-selected={duplicateView === 'fast'} className={duplicateView === 'fast' ? 'active' : ''} onClick={() => setDuplicateView('fast')}>Fast mode</button>
      </div>
      {duplicateView === 'fast'
        ? <div className="fast-review">
            {fastPair
              ? <>
                  <div className="fast-review-head">
                    <div><span className="eyebrow">FAST MODE</span><h3>Which item should stay?</h3><p>Choose one. The other is quarantined. Press <kbd>1</kbd> or <kbd>2</kbd>.</p></div>
                    <span className="fast-progress">{fastIndex + 1} of {fastPairs.length}</span>
                  </div>
                  <div className="fast-compare">
                    {fastCard(fastPair.left, 1, 'left')}
                    <span className="fast-vs">VS</span>
                    {fastCard(fastPair.right, 2, 'right')}
                  </div>
                  <div className="dup-pagination">
                    <button className="sm" disabled={fastIndex === 0} onClick={() => { setFastIndex(index => Math.max(0, index - 1)); setFastDetails(null) }}>previous</button>
                    <span>comparison {fastIndex + 1} / {fastPairs.length}</span>
                    <button className="sm" disabled={fastIndex >= fastPairs.length - 1} onClick={() => { setFastIndex(index => Math.min(fastPairs.length - 1, index + 1)); setFastDetails(null) }}>next</button>
                  </div>
                </>
              : <div className="empty"><b>No duplicate comparisons</b>all duplicate groups are resolved</div>}
          </div>
        : <>
            {duplicateGroups.length === 0 && <div className="empty"><b>No duplicates detected</b>run "exact dedup" or "semantic dedup" from Explore</div>}
            <div className="duplicates-review-list">
              {visibleDuplicateGroups.map(({ group, members }, groupIndex) => <div key={group.id} className="dupG">
                <div className="dh">
                  <span className="dup-number">{String(duplicatePage * duplicatePageSize + groupIndex + 1).padStart(2, '0')}</span>
                  <b>{group.method === 'sha256' ? 'Exact matches' : group.method === 'minhash' ? 'Near duplicates' : 'Semantic matches'}</b>
                  <span className="sim">{members.length} items</span>
                  <span className="spacer" style={{ flex: 1 }} />
                  {members.some(member => !member.is_canonical) && <button className="sm primary" onClick={() => quarantineDuplicates(members)}>Quarantine duplicates ({members.filter(member => !member.is_canonical).length})</button>}
                </div>
                <div className="row">
                  {members.map(m => <span key={m.text_id} className={`duptable${m.is_canonical ? ' canon' : ''}`} title={m.is_canonical ? 'canonical' : `similarity ${(m.similarity * 100).toFixed(0)}%`}>
                    <span className="dup-thumb">{itemById.get(m.text_id)?.text_content?.slice(0, 60) ?? itemById.get(m.text_id)?.preview?.slice(0, 60) ?? '...'}</span>
                    <span className="cap">{m.is_canonical ? '★ canonical' : `sim ${(m.similarity * 100).toFixed(0)}%`}</span>
                  </span>)}
                </div>
                <p className="dup-recommendation">Keep one canonical item and quarantine {members.filter(m => !m.is_canonical).length} duplicate{members.filter(m => !m.is_canonical).length === 1 ? '' : 's'}.</p>
              </div>)}
            </div>
            {duplicateGroups.length > duplicatePageSize && <div className="dup-pagination">
              <button className="sm" disabled={duplicatePage === 0} onClick={() => setDuplicatePage(page => Math.max(0, page - 1))}>previous</button>
              <span>groups {duplicatePage * duplicatePageSize + 1}–{Math.min((duplicatePage + 1) * duplicatePageSize, duplicateGroups.length)} of {duplicateGroups.length}</span>
              <button className="sm" disabled={duplicatePage >= duplicatePageCount - 1} onClick={() => setDuplicatePage(page => Math.min(duplicatePageCount - 1, page + 1))}>next</button>
            </div>}
          </>}
    </>}
  </Page>
}