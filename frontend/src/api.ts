export type Role = 'member' | 'reviewer'
export type Project = { id: string; name: string; description: string; color: string; can_edit: boolean }
export type Account = { id: string; username: string; name: string; admin: boolean }
export type Session = {
  role: Role | null; demo: boolean; mode: 'demo' | 'shared' | 'team'
  projects: Project[]; model: string | null; account: Account | null
}
export type DocumentVersion = {
  id: string; project_id: string; key: string; title: string
  revision: number; published_at: string; current: boolean
  archived_at: string | null; source_name: string; change_note: string
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
  id: string; question: string; status: 'queued' | 'running' | 'done' | 'failed' | 'cancelled'
  created_at: string
}
export type Feedback = { rating: 'helpful' | 'review'; note: string; resolved_at: string | null }
export type Run = RunSummary & {
  result: Result | null; error: string | null; scope: string[]
  feedback: Feedback | null
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
export type Grants = Record<string, 'reader' | 'editor'>
export type TeamMember = Account & { enabled: boolean; grants: Grants }
export type TeamProject = Omit<Project, 'can_edit'> & { aliases: string[] }
export type Invitation = {
  id: string; label: string; grants: Grants; expires_at: number; used_by: string | null
}
export type TeamInfo = {
  projects: TeamProject[]; members: TeamMember[]; invitations: Invitation[]
  activity: Array<{ id: number; at: string; actor: string | null; action: string; target: string }>
}
export type ReviewStatus = Result['status']
export type ReviewCase = {
  id: string; title: string; question: string; scope: string[]; expected_status: ReviewStatus
  required_sources: string[]; phrase: string; active: boolean
}
export type PendingFeedback = {
  run_id: string; note: string; updated_at: string; question: string; scope: string[]; author: string
}
export type TeamReport = {
  id: string; created_at: string; total: number; passed: number
  cases: Array<{
    id: string; title: string; expected_status: ReviewStatus; status: ReviewStatus
    pass: boolean; missing: string[]; phrase_match: boolean; versions: string[]
  }>
}
export type ReviewInfo = {
  stats: { runs: number; pending: number; failed: number; tokens: number }
  feedback: PendingFeedback[]; cases: ReviewCase[]
  reports: Array<Omit<TeamReport, 'cases'>>
}
export type IntakeResult = { title: string; source_name: string; body: string }

export const isActive = (status?: RunSummary['status']) => status === 'queued' || status === 'running'

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

const workspaceDateFormat = new Intl.DateTimeFormat('zh-CN', {
  timeZone: 'Asia/Shanghai', month: 'short', day: 'numeric',
  hour: '2-digit', minute: '2-digit', hour12: false,
})

export function formatDate(iso: string) {
  return workspaceDateFormat.format(new Date(iso))
}

export async function api<T>(path: string, body?: unknown): Promise<T> {
  return readResponse(await fetch('/api' + path, body === undefined ? undefined : {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }))
}

export async function importPreview(projectId: string, file: File): Promise<IntakeResult> {
  const query = new URLSearchParams({ project_id: projectId, filename: file.name })
  return readResponse(await fetch('/api/intake/preview?' + query, {
    method: 'POST', headers: { 'Content-Type': 'application/octet-stream' }, body: file,
  }))
}

async function readResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    const error = await response.json().catch(() => null)
    throw new Error(error?.detail ?? '服务暂时不可用，请重试。')
  }
  return response.json()
}

export const errorText = (error: unknown) => error instanceof Error
  ? error.message
  : '操作失败，请重试。'
