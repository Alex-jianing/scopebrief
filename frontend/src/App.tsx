import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import {
  BookOpen, ChartNoAxesCombined, Check, ChevronDown, ChevronRight,
  CircleHelp, Clock3, MessageSquareText, PanelsTopLeft,
  Shield, Waypoints,
} from 'lucide-react'
import { api, errorText } from './api'
import type { Citation, Role, Run, RunSummary, Session } from './api'
import { Benchmark } from './Benchmark'
import { DocumentDialog, Library } from './Library'
import type { DocumentTarget } from './Library'
import { ProjectIcon } from './ui'
import { EvidencePanel, Workbench } from './Workbench'

const pages = [
  { id: 'ask', label: '评审问答', icon: PanelsTopLeft },
  { id: 'library', label: '项目资料', icon: BookOpen },
  { id: 'benchmark', label: '回归评测', icon: ChartNoAxesCombined },
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
  const [document, setDocument] = useState<DocumentTarget | null>(null)

  function receiveSession(value: Session) {
    setSession(value)
    setScope(value.projects.map(project => project.id))
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
    if (!runId || !session?.role) return
    const events = new EventSource('/api/runs/' + runId + '/events')
    let ignore = false
    let pollTimer: ReturnType<typeof setTimeout> | undefined
    function receive(snapshot: Run) {
      if (ignore) return
      setRun(snapshot)
      if (snapshot.status !== 'running') {
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
        if (snapshot.status === 'running') pollTimer = setTimeout(poll, 800)
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
  const busy = starting || current?.status === 'running' || Boolean(runId && !current)

  async function ask(question: string) {
    const text = question.trim()
    if (busy || text.length < 2 || !scope.length) return
    setStarting(true)
    setError('')
    try {
      const response = await api<{ id: string }>('/runs', { question: text, project_ids: scope })
      setPage('ask')
      setRunId(response.id)
      setRun({ id: response.id, question: text, status: 'running', scope,
        created_at: new Date().toISOString(), result: null, error: null, events: [] })
      setDraft('')
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

  function showCitation(citation: Citation) {
    setDocument({ id: citation.document_id, citation })
  }

  if (!session) {
    return <main className="loading"><Waypoints size={34} /><p>{error || '正在打开工作台…'}</p>
      {error && <button className="button" onClick={() => location.reload()}>重试</button>}
    </main>
  }
  if (session.role === null) return <LoginPage onLogin={login} />

  return (
    <div className={'app-shell view-' + page}>
      <aside className="sidebar" aria-label="工作区">
        <button className="brand" onClick={() => setPage('ask')}>
          <span className="brand-mark"><Waypoints size={21} strokeWidth={2.3} /></span>
          <span><strong>ScopeBrief</strong><small>项目证据台</small></span>
        </button>

        <nav className="primary-nav" aria-label="主导航">
          {pages.map(({ id, label, icon: Icon }) =>
            <button key={id} aria-current={page === id ? 'page' : undefined}
              className={'nav-link ' + (page === id ? 'active' : '')}
              onClick={() => { setPage(id); setError('') }}>
              <Icon size={17} /> <span>{label}</span>
            </button>,
          )}
        </nav>

        <section className="workspace-projects" aria-label="项目范围">
          <div className="sidebar-heading">
            <span>项目范围</span><small>{scope.length}/{session.projects.length}</small>
          </div>
          <div className="project-list">
            {session.projects.map(project => (
              <label className="project-check" key={project.id}>
                <input type="checkbox" checked={scope.includes(project.id)} onChange={() => {
                  setScope(existing => existing.includes(project.id)
                    ? existing.filter(id => id !== project.id)
                    : [...existing, project.id])
                }} />
                <ProjectIcon name={project.name} color={project.color} />
                <span className="project-label"><strong>{project.name}</strong><small>{project.description}</small></span>
                <span className="checkmark" aria-hidden="true"><Check size={12} strokeWidth={3} /></span>
              </label>
            ))}
          </div>
        </section>

        <section className="history-section" aria-label="最近运行">
          <div className="sidebar-heading"><span>最近运行</span><Clock3 size={13} /></div>
          {history.length ? history.slice(0, 8).map(item => (
            <button key={item.id} title={item.question}
              className={'history-item ' + (page === 'ask' && runId === item.id ? 'active' : '')}
              onClick={() => { setError(''); setPage('ask'); setRunId(item.id) }}>
              <MessageSquareText size={14} /><span>{item.question}</span>
            </button>
          )) : <p className="history-empty">完成一次提问后显示</p>}
        </section>

        <div className="account">
          <details className="account-switch">
            <summary>
              <span className="account-avatar"><Shield size={17} /></span>
              <span className="account-label"><strong>{roles[session.role]}</strong>
                <small>{session.demo ? '合成演示工作区' : '角色账号'}</small></span>
              <ChevronDown size={14} />
            </summary>
            <div className="account-menu">
              {session.demo ? (Object.keys(roles) as Role[]).map(role => (
                <button key={role} disabled={busy || role === session.role} onClick={event => {
                  event.currentTarget.closest('details')?.removeAttribute('open')
                  login(role).catch(err => setError(errorText(err)))
                }}>切换为{roles[role]}</button>
              )) : <span>角色会话有效期为 12 小时</span>}
            </div>
          </details>
        </div>
      </aside>

      <header className="topbar">
        <div className="breadcrumbs"><span>团队知识</span><ChevronRight size={13} />
          <strong>{pages.find(item => item.id === page)?.label}</strong></div>
        <div className="top-actions">
          <span className="mode-indicator" title={session.model ?? undefined}><i />{session.model ? '模型已配置' : '本地摘录'}</span>
          <a className="icon-button api-link" href="/docs" target="_blank" rel="noreferrer" title="API 文档" aria-label="API 文档"><CircleHelp size={18} /></a>
        </div>
      </header>

      <main className="main-content">
        {error && <div className="notice error" role="alert">{error}</div>}
        {page === 'ask' && <Workbench run={current} busy={busy} draft={draft} setDraft={setDraft}
          scope={scope} projects={session.projects} ask={ask} showCitation={showCitation} />}
        {page === 'library' && <Library projects={session.projects} canPublish={session.role === 'reviewer'} open={setDocument} />}
        {page === 'benchmark' && <Benchmark />}
      </main>
      {page === 'ask' && <EvidencePanel key={runId ?? 'initial'} run={current} showCitation={showCitation} />}
      {document && <DocumentDialog target={document} close={() => setDocument(null)} />}
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
  return <main className="loading login-page">
    <form className="surface login-form" onSubmit={submit}>
      <Waypoints size={30} /><h1>登录 ScopeBrief</h1>
      <label>角色<select value={role} onChange={event => setRole(event.target.value as Role)}>
        <option value="member">项目成员</option><option value="reviewer">评审者</option>
      </select></label>
      <label>角色口令<input type="password" autoComplete="current-password" required
        value={key} onChange={event => setKey(event.target.value)} /></label>
      {error && <div className="notice error" role="alert">{error}</div>}
      <button className="button primary" disabled={pending}>登录</button>
    </form>
  </main>
}
