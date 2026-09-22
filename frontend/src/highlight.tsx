// highlight — marca trechos de evidência inline no texto lido.
// Cada issue pode carregar substrings em evidence_json; o que existir vira <mark>.
import type React from 'react'
import type { Issue } from './api'

type Mark = { start: number; end: number; kind: string }

/** Extrai spans [start,end) de evidências conhecidas no texto. */
export function evidenceSpans(text: string, issues: Issue[]): Mark[] {
  const marks: Mark[] = []
  const push = (needle: unknown, kind: string) => {
    if (typeof needle !== 'string' || !needle) return
    const frag = needle.slice(0, 120).replace(/\s+/g, ' ').trim()
    if (frag.length < 4) return
    let from = 0
    while (marks.length < 24) {
      const at = text.indexOf(frag, from)
      if (at < 0) break
      marks.push({ start: at, end: at + frag.length, kind })
      from = at + frag.length
    }
  }
  for (const iss of issues) {
    if (iss.status !== 'open') continue
    const ev = (iss.evidence_json ?? {}) as Record<string, unknown>
    if (iss.issue_type === 'contamination' && Array.isArray(ev.samples)) {
      for (const s of (ev.samples as unknown[]).slice(0, 6)) push(s, 'mk-cont')
    } else if (iss.issue_type === 'pii' || iss.issue_type === 'possible_pii') {
      push(ev.evidence, 'mk-pii')
    } else {
      push(ev.evidence, 'mk-' + iss.issue_type)
    }
  }
  marks.sort((a, b) => a.start - b.start)
  // remove sobreposições
  const out: Mark[] = []
  let last = -1
  for (const m of marks) {
    if (m.start >= last) { out.push(m); last = m.end }
  }
  return out
}

/** Renderiza o texto com <mark> nas evidências. */
export function highlightText(text: string, issues: Issue[]): React.ReactNode {
  const marks = evidenceSpans(text, issues)
  if (marks.length === 0) return text
  const parts: React.ReactNode[] = []
  let pos = 0
  marks.forEach((m, i) => {
    if (m.start > pos) parts.push(text.slice(pos, m.start))
    parts.push(<mark key={i} className={m.kind}>{text.slice(m.start, m.end)}</mark>)
    pos = m.end
  })
  if (pos < text.length) parts.push(text.slice(pos))
  return parts
}
