export type Role = 'member' | 'reviewer'
export type Project = { id: string; name: string; description: string; color: string }
export type Session = { role: Role | null; demo: boolean; projects: Project[]; model: string | null }
export type DocumentVersion = {
  id: string; project_id: string; key: string; title: string
  revision: number; published_at: string; current: boolean
}
export type FullDocument = DocumentVersion & { body: string }
export type Citation = {
  id: string; document_id: string; project_id: string; revision: number; number: number
  title: string; heading: string; quote: string; start_line: number; end_line: number
}
export type FindingStatus = 'go' | 'hold' | 'conflict' | 'grounded' | 'insufficient'
export type Result = {
  status: 'answered' | 'partial' | 'insufficient'
  scope_limited: boolean
  generator: 'extractive' | 'model' | 'fallback'
  model: string | null
  duration_ms: number
  usage: Record<string, number> | null
  findings: Array<{
    project_id: string; name: string; status: FindingStatus
    topics: string[]; missing: string[]; citation_ids: string[]
  }>
  citations: Citation[]
}
export type RunSummary = {
  id: string; question: string; status: 'running' | 'done' | 'failed'; created_at: string
}
export type Run = RunSummary & {
  result: Result | null; error: string | null; scope: string[]
  events: Array<{ id: number; stage: string; detail: string; elapsed_ms: number }>
}
export type Metrics = {
  passed: number; total: number; gold_hits: number; gold_total: number
  correct_decisions: number; decision_total: number; stale_citations: number; leak_cases: number
  correct_abstentions: number; abstention_total: number; p95_ms: number
}
type CaseOutcome = { pass: boolean; failures: string[]; duration_ms: number }
export type Report = {
  dataset: string
  mode: string
  metrics: { baseline: Metrics; harness: Metrics }
  cases: Array<{
    id: string; group: string; title: string; baseline: CaseOutcome; harness: CaseOutcome
  }>
}

export const labels: Record<string, string> = {
  decision: '放行结论',
  blocker: '阻塞事项',
  window: '变更时段',
  rollback: '回退方案',
  owner: '负责人',
  verification: '验收信息',
  dependency: '依赖关系',
  general: '相关资料',
}

export function formatDate(iso: string) {
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai', month: 'short', day: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
  }).format(new Date(iso))
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, body === undefined ? undefined : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? '服务暂时不可用，请重试。')
  }
  return response.json()
}

export const errorText = (error: unknown) => error instanceof Error
  ? error.message
  : '操作失败，请重试。'
