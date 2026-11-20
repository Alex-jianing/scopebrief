import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import {
  BookOpen, ChartNoAxesCombined, ChevronDown, ChevronRight,
  CircleHelp, Clock3, MessageSquareText, PanelsTopLeft, Plus,
  Shield, UsersRound,
} from 'lucide-react'
import { api, errorText, formatDate, isActive } from './api'
import type { Citation, Role, Run, RunSummary, Session } from './api'
import { Benchmark } from './Benchmark'
import { DocumentDialog, Library } from './Library'
import type { DocumentTarget } from './Library'
import { AuthLayout, BrandMark } from './ui'
import { Workbench } from './Workbench'
import { TeamWorkspace } from './Team'
import { WorkspaceQuality } from './WorkspaceQuality'
import { TeamLogin } from './TeamLogin'

const pages = [
  { id: 'ask', label: '评审问答', icon: PanelsTopLeft },
  { id: 'library', label: '项目资料', icon: BookOpen },
  { id: 'benchmark', label: '回归评测', icon: ChartNoAxesCombined },
  { id: 'team', label: '团队管理', icon: UsersRound },
] as const
type Page = typeof pages[number]['id']
const roles = { member: '项目成员', reviewer: '评审者' }

export function App() {
  const [page, setPage] = useState<Page>('ask')
  const [session, setSession] = useState<Session | null>(null)
  const [scope, setScope] = useState<string[]>([])
  const [history, setHistory] = useState<RunSummary[]>([])
  const [runId, setRunId] = useState<string | null>(null)
  const [run, setRun] = useState<Run | null>(null)
  const [error, setError] = useState('')
  const [starting, setStarting] = useState(false)
  const [draft, setDraft] = useState('')
  const [documentTarget, setDocument] = useState<DocumentTarget | null>(null)
  const questionInput = useRef<HTMLTextAreaElement>(null)

  function receiveSession(value: Session) {
    setSession(value)
    setScope(value.projects.slice(0, value.mode === 'team' ? 3 : 12).map(project => project.id))
    setHistory([])
    setRunId(null)
    setRun(null)
    setDraft('')
    setDocument(null)
  }

  useEffect(() => {
    api<Session>('/session').then(receiveSession).catch(err => setError(errorText(err)))
  }, [])

  useEffect(() => {
    if (!session?.role) return
    let cancelled = false
    api<RunSummary[]>('/runs').then(rows => {
      if (cancelled) return
      setHistory(rows)
      setRunId(current => current ?? rows[0]?.id ?? null)
    }).catch(err => { if (!cancelled) setError(errorText(err)) })
    return () => { cancelled = true }
  }, [session])

  useEffect(() => {
    if (!session?.role) return
    function focusComposer(event: KeyboardEvent) {
      if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey || event.isComposing ||
        event.defaultPrevented || document.querySelector('dialog[open], .scope-trigger[aria-expanded="true"]')) return
      if (event.target instanceof Element &&
        event.target.closest('input, textarea, select, [contenteditable], details[open]')) return
      event.preventDefault()
      setPage('ask')
      setError('')
      requestAnimationFrame(() => questionInput.current?.focus())
    }
    window.addEventListener('keydown', focusComposer)
    return () => window.removeEventListener('keydown', focusComposer)
  }, [session?.role])

  useEffect(() => {
    if (!runId || !session?.role) return
    const events = new EventSource('/api/runs/' + runId + '/events')
    let ignore = false
    let pollTimer: ReturnType<typeof setTimeout> | undefined
    function receive(snapshot: Run) {
      if (ignore) return
      setRun(snapshot)
      if (!isActive(snapshot.status)) {
        events.close()
        api<RunSummary[]>('/runs')
          .then(rows => { if (!ignore) setHistory(rows) })
          .catch(err => { if (!ignore) setError(errorText(err)) })
      }
    }
    function poll() {
      api<Run>('/runs/' + runId).then(snapshot => {
        if (ignore) return
        receive(snapshot)
        if (isActive(snapshot.status)) pollTimer = setTimeout(poll, 800)
      }).catch(err => {
        if (!ignore) {
          setError(errorText(err))
          setRunId(null)
        }
      })
    }
    events.addEventListener('snapshot', (msg: MessageEvent<string>) => receive(JSON.parse(msg.data)))
    events.onerror = () => {
      events.close()
      poll()
    }
    return () => {
      ignore = true
      events.close()
      clearTimeout(pollTimer)
    }
  }, [runId, session])

  const current = run?.id === runId ? run : null
  const busy = starting || isActive(current?.status) || Boolean(runId && !current)
  const opening = runId && !current ? history.find(item => item.id === runId) ?? null : null

  function navigate(next: Page, nextRunId?: string) {
    setPage(next)
    setError('')
    if (nextRunId !== undefined) setRunId(nextRunId)
    if (next !== page || (nextRunId !== undefined && nextRunId !== runId)) {
      window.scrollTo({ top: 0, behavior: 'instant' })
    }
  }

  function startQuestion() {
    setPage('ask')
    setError('')
    if (runId) {
      setRunId(null)
      setRun(null)
      setDraft('')
    }
    requestAnimationFrame(() => questionInput.current?.focus())
  }

  async function ask(question: string) {
    const text = question.trim()
    if (busy || text.length < 2 || !scope.length) return
    setStarting(true)
    setError('')
    try {
      const response = await api<{ id: string }>('/runs', { question: text, project_ids: scope })
      setPage('ask')
      setRunId(response.id)
      setRun({ id: response.id, question: text, status: 'queued', scope,
        created_at: new Date().toISOString(), result: null, error: null, feedback: null, events: [] })
      setDraft('')
      window.scrollTo({ top: 0, behavior: 'instant' })
    } catch (err) {
      setError(errorText(err))
    } finally {
      setStarting(false)
    }
  }

  async function login(role: Role, key = '') {
    setError('')
    receiveSession(await api<Session>('/session', { role, key }))
    setPage('ask')
  }

  async function syncProjects() {
    const next = await api<Session>('/session')
    const allowed = new Set(next.projects.map(project => project.id))
    setSession(next)
    setScope(items => {
      const valid = items.filter(id => allowed.has(id))
      return valid.length || !next.projects.length ? valid : [next.projects[0].id]
    })
    if (!next.account && next.mode === 'team') {
      receiveSession(next)
      setPage('ask')
    }
  }

  useEffect(() => {
    if (session?.mode !== 'team' || !session.account) return
    let ignore = false
    const refresh = async () => {
      try {
        const next = await api<Session>('/session')
        if (!ignore && JSON.stringify(next) !== JSON.stringify(session)) {
          receiveSession(next)
          setPage('ask')
        }
      } catch { /* An in-flight request or next focus can recover a short interruption. */ }
    }
    window.addEventListener('focus', refresh)
    const timer = setInterval(refresh, 30000)
    return () => { ignore = true; window.removeEventListener('focus', refresh); clearInterval(timer) }
  }, [session])

  async function stop() {
    if (!current || !isActive(current.status)) return
    try {
      const stopped = await api<Run>('/runs/' + current.id + '/cancel', {})
      setRun(existing => existing?.id === stopped.id ? stopped : existing)
      setHistory(await api<RunSummary[]>('/runs'))
    } catch (err) { setError(errorText(err)) }
  }

  async function logout() {
    try {
      await api('/auth/logout', {})
      receiveSession(await api<Session>('/session'))
      setPage('ask')
    } catch (err) { setError(errorText(err)) }
  }

  function showCitation(citation: Citation) {
    setDocument({ id: citation.document_id, citation })
  }

  if (!session) {
    return <main className="loading"><BrandMark /><p>{error || '正在打开问据…'}</p>
      {error && <button className="button" onClick={() => location.reload()}>重试</button>}
    </main>
  }
  if (session.role === null) return session.mode === 'team'
    ? <TeamLogin onLogin={value => { receiveSession(value); setPage('ask') }} />
    : <LoginPage onLogin={login} />

  const team = session.mode === 'team'
  const admin = Boolean(session.account?.admin)
  const visiblePages = pages.filter(item => item.id === 'team' ? admin : item.id !== 'benchmark' || !team || admin)
  const navigationLabel = (item: typeof pages[number]) => team && item.id === 'benchmark' ? '业务回归' : item.label
  const newQuestion = <button className="button new-question" type="button" disabled={busy} onClick={startQuestion}>
    <Plus size={17} /> 新建问答
  </button>

  return (
    <div className={'app-shell view-' + page}>
      <aside className="sidebar" aria-label="工作区">
        <button className="brand" type="button" onClick={() => navigate('ask')}>
          <BrandMark />
          <span><strong>问据</strong><small>团队知识工作台</small></span>
        </button>

        <div className="sidebar-action">{newQuestion}</div>

        <nav className="primary-nav" aria-label="主导航">
          {visiblePages.map(item =>
            <button key={item.id} aria-current={page === item.id ? 'page' : undefined}
              className={'nav-link ' + (page === item.id ? 'active' : '')}
              onClick={() => navigate(item.id)}>
              <item.icon size={17} /> <span>{navigationLabel(item)}</span>
            </button>,
          )}
        </nav>

        <section className={'history-section' + (history.length ? '' : ' is-empty')} aria-label="最近运行">
          <div className="sidebar-heading"><Clock3 size={14} /><span>最近问答</span></div>
          <div className="history-list">
            {history.length ? history.map(item => {
              const active = page === 'ask' && runId === item.id
              const timestamp = formatDate(item.created_at)
              return <button key={item.id} title={item.question + ' · ' + timestamp}
                aria-current={active ? 'true' : undefined} className={'history-item' + (active ? ' active' : '')}
                onClick={() => navigate('ask', item.id)}>
                <MessageSquareText size={15} />
                <span className="history-copy"><span>{item.question}</span><time dateTime={item.created_at}>{timestamp}</time></span>
                {isActive(item.status) && <i className="queue-dot" />}
              </button>
            }) : <p className="history-empty">还没有问答记录</p>}
          </div>
        </section>

        <div className="account">
          <details className="account-switch">
            <summary>
              <span className="account-avatar"><Shield size={17} /></span>
              <span className="account-label"><strong>{session.account?.name ?? roles[session.role]}</strong>
                <small>{team ? admin ? '团队管理员' : '团队成员' : session.demo ? '演示工作区' : '角色账号'}</small></span>
              <ChevronDown size={14} />
            </summary>
            <div className="account-menu">
              {session.demo ? (Object.keys(roles) as Role[]).map(role => (
                <button key={role} disabled={busy || role === session.role} onClick={event => {
                  event.currentTarget.closest('details')?.removeAttribute('open')
                  login(role).catch(err => setError(errorText(err)))
                }}>切换为{roles[role]}</button>
              )) : <button onClick={logout}>退出账号</button>}
            </div>
          </details>
        </div>
      </aside>

      <header className="topbar">
        <div className="breadcrumbs"><span>工作区</span><ChevronRight size={13} />
          <strong>{navigationLabel(pages.find(item => item.id === page) ?? pages[0])}</strong></div>
        <div className="top-actions">
          <span className="mode-indicator" title={session.model ?? undefined}><i />{session.model ? '模型已配置' : '本地摘录'}</span>
          <a className="icon-button api-link" href="/docs" target="_blank" rel="noreferrer" title="API 文档" aria-label="API 文档"><CircleHelp size={18} /></a>
          <div className="topbar-action">{newQuestion}</div>
        </div>
      </header>

      <main className="main-content">
        {error && <div className="notice error" role="alert">{error}</div>}
        <div className="view-stage" key={page}>
          {page === 'ask' && <Workbench run={current} opening={opening} busy={busy} starting={starting} questionInput={questionInput}
            draft={draft} setDraft={setDraft} scope={scope} setScope={setScope} projects={session.projects} ask={ask}
            showCitation={showCitation} team={team} stop={stop} setup={admin ? () => navigate('team') : undefined} />}
          {page === 'library' && <Library projects={session.projects} open={setDocument} />}
          {page === 'benchmark' && (team ? admin && <WorkspaceQuality projects={session.projects} /> : <Benchmark />)}
          {page === 'team' && admin && <TeamWorkspace onProjectChanged={syncProjects} />}
        </div>
      </main>
      {documentTarget && <DocumentDialog target={documentTarget} close={() => setDocument(null)} />}
    </div>
  )
}

function LoginPage({ onLogin }: { onLogin: (role: Role, key: string) => Promise<void> }) {
  const [role, setRole] = useState<Role>('member')
  const [key, setKey] = useState('')
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setPending(true)
    try { await onLogin(role, key) } catch (err) { setError(errorText(err)) } finally { setPending(false) }
  }
  return <AuthLayout>
    <form className="login-form" onSubmit={submit}>
      <BrandMark /><h1>登录问据</h1>
      <label>角色<select value={role} onChange={event => setRole(event.target.value as Role)}>
        <option value="member">项目成员</option><option value="reviewer">评审者</option>
      </select></label>
      <label>角色口令<input type="password" autoComplete="current-password" required
        value={key} onChange={event => setKey(event.target.value)} /></label>
      {error && <div className="notice error" role="alert">{error}</div>}
      <button className="button primary" disabled={pending}>登录</button>
    </form>
  </AuthLayout>
}
