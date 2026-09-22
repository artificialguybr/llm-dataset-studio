// API client — all calls go through here; the frontend never touches the filesystem.
const j = async (url: string, opts?: RequestInit) => {
  const r = await fetch(url, { headers: { 'content-type': 'application/json' }, ...opts })
  if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`)
  const body = await r.text()
  return body ? JSON.parse(body) : null
}

export interface Dataset { id: string; name: string; description: string; license: string; license_policy?: string; current_version_id: string | null; thresholds_json: Record<string, number>; item_counts?: Record<string, number>; open_issues?: number; running_jobs?: string[]; unknown_license?: number }
export interface DatasetStats { documents: number; total_tokens: number; total_characters: number; total_words: number; average_tokens: number; average_characters: number; average_words: number; min_tokens: number; max_tokens: number; sources: number; languages: { value: string; count: number }[]; mime_types: { value: string; count: number }[] }
export interface Item { id: string; dataset_id: string; original_filename: string; relative_path: string; decision_status: string; ingest_status: string; char_count: number; word_count: number; tokens: number; language: string; has_html: boolean; text_content?: string; preview?: string; text_hash_sha256?: string; tags_json: string[]; license: string; created_at?: string; mime_type: string; byte_size: number }
export interface Issue { id: string; text_id: string; item_id?: string; item?: Item; issue_type: string; score: number; threshold: number; detector_name: string; detector_version: string; status: string; preview?: string; evidence_json?: Record<string, unknown> }
export interface Label { id: string; text_id: string; item_id?: string; item?: Item; label_type: string; category: string; value_json?: Record<string, unknown>; source_type: string; status: string; confidence: number | null; span_start?: number; span_end?: number }
export interface GeneratedText { id: string; text_id: string; item_id?: string; item?: Item; text: string; prompt: string; context: string; source_type: string; confidence: number | null; status: string }
export type Caption = GeneratedText
export interface Version { id: string; dataset_id: string; parent_version_id: string | null; item_count: number; checksum: string; description: string; created_at: string }
export interface Job { id: string; type: string; status: string; progress: number; total: number; processed: number; failed: number; error_summary: string; config_json?: Record<string, unknown>; created_at?: string }
export interface ProviderInfo { scope: string; name: string; version: string; active: boolean; available: boolean; setup: string }
export interface ProviderSettings { selection: Record<string, string>; providers: Record<string, { configured: boolean; model: string; models?: Record<string, string> }> }
export interface ModelSpec { id: string; name: string; capability: string; plugin_id: string; description: string; license: string; size_mb: number; source_url: string; revision: string; runtime: string; platforms: string[]; installable: boolean; memory_mb?: number; status: string; installed: boolean; active: boolean; installed_path?: string; sha256?: string; error?: string; sources?: { url: string; filename: string; sha256: string }[]; install_hint?: string; recommended?: boolean; quality_tier?: string; selection_reason?: string }
export interface PluginInfo { id: string; name?: string; version?: string; protocol?: string; capabilities?: string[]; permissions?: string[]; installed: boolean; path?: string }
export interface ModelCatalog { models: ModelSpec[]; plugins: PluginInfo[]; automation?: Record<string, { enabled: boolean; confidence: number; preview: boolean; auto_quarantine?: boolean }> }
export interface DupGroup { group: { id: string; method: string; threshold: number }; members: { text_id: string; similarity: number; is_canonical: boolean }[] }

export interface Conversation { id: string; dataset_id: string; title: string; conversation_type: string; turn_count: number; total_tokens: number; language: string; tags_json: string[]; license: string; decision_status: string; created_at: string }
export interface TextTurn { id: string; conversation_id: string; dataset_id: string; role: string; content: string; tokens: number; turn_index: number; tool_calls: unknown[]; tool_call_id?: string; agent_trace?: boolean; parent_turn_id?: string }
export interface PreferencePair { id: string; dataset_id: string; prompt_text: string; chosen_text: string; rejected_text: string; strategy: string; reviewer: string; status: string; created_at: string }
export interface SFTRecord { id: string; dataset_id: string; messages: unknown[]; system_prompt: string; tokens: number; schema_type: string; source_type: string; license: string; status: string; created_at: string }
export interface AgentTrace { id: string; dataset_id: string; trace_type: string; trace_id: string; trace_json: unknown; tokens: number; model: string; success?: boolean; error: string; created_at: string }
export interface ExplorerRecord { id: string; kind: 'text' | 'conversation' | 'sft' | 'preference' | 'trace'; title: string; preview: string; status: string; tokens: number; language: string; created_at: string; payload: Record<string, any> }

export const api = {
  datasets: () => j('/api/datasets'),
  dataset: (id: string) => j(`/api/datasets/${id}`),
  datasetStats: (id: string) => j(`/api/datasets/${id}/stats`) as Promise<DatasetStats>,
  createDataset: (name: string, description: string, folder?: string) =>
    j('/api/datasets', { method: 'POST', body: JSON.stringify({ name, description, ...(folder ? { folder } : {}) }) }),
  deleteDataset: (id: string) =>
    j(`/api/datasets/${id}`, { method: 'DELETE' }),
  seedDemo: () =>
    j('/api/seed-demo', { method: 'POST', body: JSON.stringify({}) }),
  startImport: (ds: string, paths: string[], zips: string[], jsonls: string[] = []) =>
    j(`/api/datasets/${ds}/imports`, { method: 'POST', body: JSON.stringify({ paths, zips, jsonls }) }),
  startJob: (ds: string, type: string, body: Record<string, unknown> = {}) =>
    j(`/api/datasets/${ds}/jobs/${type}`, { method: 'POST', body: JSON.stringify(body) }),
  startJobWithBody: (ds: string, type: string, body: Record<string, unknown>) =>
    j(`/api/datasets/${ds}/jobs/${type}`, { method: 'POST', body: JSON.stringify(body) }),
  job: (id: string) => j(`/api/jobs/${id}`),
  jobs: (ds: string) => j(`/api/datasets/${ds}/jobs`) as Promise<Job[]>,
  cancelJob: (id: string) => j(`/api/jobs/${id}/cancel`, { method: 'POST', body: '{}' }),
  items: async (ds: string, params: Record<string, string>) => {
    const qs = new URLSearchParams(params).toString()
    const r = await fetch(`/api/datasets/${ds}/items?${qs}`)
    if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`)
    return (await r.json()) as Item[]
  },
  itemsPage: async (ds: string, params: Record<string, string>) => {
    const qs = new URLSearchParams(params).toString()
    const r = await fetch(`/api/datasets/${ds}/items?${qs}`)
    if (!r.ok) throw new Error(`${r.status}: ${(await r.text()).slice(0, 200)}`)
    return { items: (await r.json()) as Item[], total: Number(r.headers.get('X-Total-Count') ?? 0) }
  },
  explorer: (ds: string, params: Record<string, string> = {}) => {
    const qs = new URLSearchParams(params).toString()
    return j(`/api/datasets/${ds}/explorer${qs ? `?${qs}` : ''}`) as Promise<{ records: ExplorerRecord[]; total: number }>
  },
  preferenceDecision: (id: string, decision: 'a' | 'b' | 'tie' | 'skip') =>
    j(`/api/preference-pairs/${id}/decision`, { method: 'PATCH', body: JSON.stringify({ decision }) }),
  explorerDecision: (id: string, decision: string) =>
    j(`/api/explorer/${id}/decision`, { method: 'PATCH', body: JSON.stringify({ decision }) }),
  item: (id: string) => j(`/api/items/${id}`),
  itemTextUrl: (id: string) => `/api/items/${id}/text`,
  itemStats: (id: string) => j(`/api/items/${id}/stats`),
  setDecision: (id: string, decision: string, reason: string = '') =>
    j(`/api/items/${id}/decision`, { method: 'PATCH', body: JSON.stringify({ decision, reason }) }),
  setTags: (id: string, tags: string[]) =>
    j(`/api/items/${id}/tags`, { method: 'PATCH', body: JSON.stringify({ tags }) }),
  setLicense: (id: string, license: string, evidence = '') =>
    j(`/api/items/${id}/license`, { method: 'PATCH', body: JSON.stringify({ license, license_evidence_uri: evidence }) }),
  issues: (ds: string, issue_type = ''): Promise<Issue[]> => {
    const qs = issue_type ? `?issue_type=${issue_type}` : ''
    return j(`/api/datasets/${ds}/issues${qs}`)
  },
  ackIssue: (id: string, status: string, reviewer = 'local') =>
    j(`/api/issues/${id}/ack`, { method: 'PATCH', body: JSON.stringify({ status, reviewer }) }),
  duplicates: (ds: string) => j(`/api/datasets/${ds}/duplicates`),
  addLabel: (item: string, body: Record<string, unknown>) =>
    j(`/api/items/${item}/labels`, { method: 'POST', body: JSON.stringify(body) }),
  updateLabel: (id: string, category: string) =>
    j(`/api/labels/${id}`, { method: 'PATCH', body: JSON.stringify({ category }) }),
  reviewLabel: (id: string, status: string) =>
    j(`/api/labels/${id}/review`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  versions: (ds: string) => j(`/api/datasets/${ds}/versions`),
  createVersion: (ds: string, description: string) =>
    j(`/api/datasets/${ds}/versions`, { method: 'POST', body: JSON.stringify({ description }) }),
  versionDiff: (ds: string, old: string, neu: string) =>
    j(`/api/datasets/${ds}/versions/diff?old=${old}&new=${neu}`),
  restoreVersion: (ds: string, v: string) =>
    j(`/api/datasets/${ds}/versions/${v}/restore`, { method: 'POST', body: '{}' }),
  search: (ds: string, q: string, text_id = '') => {
    const qs = new URLSearchParams({ ...(q ? { q } : {}), ...(text_id ? { text_id } : {}), limit: '50' }).toString()
    return j(`/api/datasets/${ds}/search?${qs}`)
  },
  clusters: (ds: string) => j(`/api/datasets/${ds}/clusters`),
  export: (ds: string, fmt: string, version_id = '') =>
    j(`/api/datasets/${ds}/export`, { method: 'POST', body: JSON.stringify({ fmt, ...(version_id ? { version_id } : {}) }) }),
  derive: (ds: string, name: string, filters: Record<string, string>) =>
    j(`/api/datasets/${ds}/derive`, { method: 'POST', body: JSON.stringify({ name, filters }) }),
  deriveFrom: (ds: string, name: string, body: Record<string, unknown>) =>
    j(`/api/datasets/${ds}/derive-from`, { method: 'POST', body: JSON.stringify({ name, ...body }) }),
  merge: (datasetIds: string[], name: string) =>
    j('/api/datasets/merge', { method: 'POST', body: JSON.stringify({ dataset_ids: datasetIds, name }) }),
  sample: (ds: string, size: number, method = 'random', seed = 0) =>
    j(`/api/datasets/${ds}/sample`, { method: 'POST', body: JSON.stringify({ size, method, seed }) }),
  mix: (sources: { dataset_id: string; weight: number }[], name: string, size = 0, seed = 0) =>
    j('/api/datasets/mix', { method: 'POST', body: JSON.stringify({ sources, name, size, seed }) }),
  split: (ds: string, ratios: number[]) =>
    j(`/api/datasets/${ds}/split`, { method: 'POST', body: JSON.stringify({ ratios }) }),
  swapCanonical: (group_id: string, item_id: string) =>
    j(`/api/duplicates/groups/${group_id}/canonical/${item_id}`, { method: 'PATCH', body: '{}' }),
  redactPii: (ds: string) => j(`/api/datasets/${ds}/redact-pii`, { method: 'POST', body: '{}' }),
  providerSettings: () => j('/api/provider-settings') as Promise<ProviderSettings>,
  saveProviderSettings: (body: Record<string, unknown>) => j('/api/provider-settings', { method: 'PATCH', body: JSON.stringify(body) }) as Promise<ProviderSettings>,
  providers: () => j('/api/providers'),
  modelCatalog: () => j('/api/model-catalog'),
  installModel: (id: string, source?: string, sha256?: string, licenseAck?: boolean) =>
    j(`/api/models/${id}/install`, { method: 'POST', body: JSON.stringify({ source: source ?? '', sha256: sha256 ?? '', license_ack: licenseAck ?? false }) }),
  uninstallModel: (id: string) =>
    j(`/api/models/${id}/uninstall`, { method: 'POST', body: '{}' }),
  activateModel: (id: string, capability: string) =>
    j(`/api/models/${id}/active`, { method: 'PATCH', body: JSON.stringify({ capability }) }),
  setModelAutomation: (capability: string, enabled: boolean, confidence = 0.95, preview = true, auto_quarantine = false) =>
    j(`/api/model-automation/${capability}`, { method: 'PATCH', body: JSON.stringify({ enabled, confidence, preview, auto_quarantine }) }),
  installPlugin: (path: string) =>
    j('/api/plugins/install', { method: 'POST', body: JSON.stringify({ path }) }),
  uninstallPlugin: (id: string) =>
    j(`/api/plugins/${id}/uninstall`, { method: 'POST', body: '{}' }),
  preannotate: (ds: string, body: Record<string, unknown> = {}) => j(`/api/datasets/${ds}/preannotate`, { method: 'POST', body: JSON.stringify(body) }),
  piiScan: (ds: string, body: Record<string, unknown> = {}) => j(`/api/datasets/${ds}/pii-scan`, { method: 'POST', body: JSON.stringify(body) }),
  // generated text (caption) for items
  caption: (id: string) => j(`/api/items/${id}/caption`),
  updateCaption: (id: string, text: string, status = 'approved') =>
    j(`/api/items/${id}/caption`, { method: 'PATCH', body: JSON.stringify({ text, status }) }),
  reviewCaption: (id: string, status: string) =>
    j(`/api/captions/${id}/review`, { method: 'PATCH', body: JSON.stringify({ status }) }),
  // items by label
  itemsByLabel: (ds: string, category = '', label_type = '') => {
    const qs = new URLSearchParams({ ...(category ? { category } : {}), ...(label_type ? { label_type } : {}) }).toString()
    return j(`/api/datasets/${ds}/items-by-label?${qs}`)
  },
  // conversations / chats
  listConversations: (ds: string) => j(`/api/conversations?dataset_id=${ds}`) as Promise<Conversation[]>,
  createConversation: (ds: string, body: Record<string, unknown>) =>
    j('/api/conversations', { method: 'POST', body: JSON.stringify({ dataset_id: ds, ...body }) }),
  conversation: (id: string) => j(`/api/conversations/${id}`),
  addTurn: (convId: string, body: Record<string, unknown>) =>
    j(`/api/conversations/${convId}/turns`, { method: 'POST', body: JSON.stringify(body) }),
  // sft / dpo / preference pairs
  createSftRecord: (ds: string, body: Record<string, unknown>) =>
    j(`/api/datasets/${ds}/sft-records`, { method: 'POST', body: JSON.stringify(body) }),
  sftRecords: (ds: string) => j(`/api/datasets/${ds}/sft-records`) as Promise<SFTRecord[]>,
  createPreferencePair: (ds: string, body: Record<string, unknown>) =>
    j(`/api/datasets/${ds}/preference-pairs`, { method: 'POST', body: JSON.stringify(body) }),
  preferencePairs: (ds: string, status = '') =>
    j(`/api/datasets/${ds}/preference-pairs${status ? `?status=${status}` : ''}`) as Promise<PreferencePair[]>,
  // agent traces
  createTrace: (ds: string, body: Record<string, unknown>) =>
    j(`/api/datasets/${ds}/traces`, { method: 'POST', body: JSON.stringify(body) }),
  traces: (ds: string) => j(`/api/datasets/${ds}/traces`) as Promise<AgentTrace[]>,
}
