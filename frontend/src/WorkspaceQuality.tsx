import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Check, Download, Flag, FlaskConical, ListChecks, LoaderCircle, Play, Plus } from 'lucide-react'
import { api, errorText, formatDate } from './api'
import type {
  DocumentVersion, PendingFeedback, Project, ReviewCase, ReviewInfo, ReviewStatus, TeamReport,
} from './api'
import { Blank, Modal } from './ui'

const outcomes: Record<ReviewStatus, string> = { answered: '有答案', partial: '部分覆盖', insufficient: '证据不足' }
const sections = { feedback: '待复核反馈', cases: '业务用例', reports: '评测报告' }
type Tab = keyof typeof sections
type Editor = { feedback?: PendingFeedback; existing?: ReviewCase }

export function WorkspaceQuality({ projects }: { projects: Project[] }) {
  const [data, setData] = useState<ReviewInfo | null>(null)
  const [tab, setTab] = useState<Tab>('feedback')
  const [refresh, setRefresh] = useState(0)
  const [editor, setEditor] = useState<Editor | null>(null)
  const [report, setReport] = useState<TeamReport | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let ignore = false
    api<ReviewInfo>('/review').then(value => { if (!ignore) setData(value) })
      .catch(err => { if (!ignore) setError(errorText(err)) })
    return () => { ignore = true }
  }, [refresh])

  async function change(path: string, body: unknown) {
    try {
      setError('')
      await api(path, body)
      setRefresh(value => value + 1)
    } catch (err) { setError(errorText(err)) }
  }

  async function run() {
    setBusy(true)
    setError('')
    try {
      setReport(await api<TeamReport>('/review/evaluate', {}))
      setTab('reports')
      setRefresh(value => value + 1)
    } catch (err) { setError(errorText(err)) } finally { setBusy(false) }
  }

  function exportReport() {
    if (!report) return
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2) + '\n'], { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'scopebrief-review-' + report.id + '.json'
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return <div className="wide-content">
    <div className="page-heading">
      <div><h1>业务回归</h1>
        <p>用团队资料验证常见问题，并把错误回答转成可复跑的用例。</p></div>
      <div className="page-actions">
        <button className="button" disabled={!projects.length} onClick={() => setEditor({})}><Plus size={16} /> 新建用例</button>
        <button className="button primary" disabled={busy || !data?.cases.some(test => test.active)} onClick={run}>
          {busy ? <LoaderCircle size={16} className="spin" /> : <Play size={16} />}
          {busy ? '评测中…' : '运行团队评测'}</button>
      </div>
    </div>
    {data && <div className="metrics-grid workspace-stats">
      {[['累计问答', data.stats.runs], ['排队或执行中', data.stats.pending],
        ['失败运行', data.stats.failed], ['累计模型 Tokens', data.stats.tokens]].map(([name, count]) =>
        <article className="surface metric" key={name}><h2>{name}</h2><strong>{count.toLocaleString()}</strong></article>)}
    </div>}
    <nav className="section-nav" aria-label="业务回归视图">
      {(Object.keys(sections) as Tab[]).map(id => <button className={tab === id ? 'active' : ''} aria-pressed={tab === id}
        type="button" key={id} onClick={() => { setTab(id); setError('') }}>{sections[id]}</button>)}
    </nav>
    {error && <p className="notice error" role="alert">{error}</p>}
    {data && tab === 'feedback' && <section className="surface case-card">
      {data.feedback.length ? <div className="table-scroll"><table><thead>
        <tr><th>问题与说明</th><th>提交人</th><th>操作</th></tr></thead><tbody>
        {data.feedback.map(item => <tr key={item.run_id}><td>
          <strong>{item.question}</strong><div className="muted feedback-note">{item.note || '请求人工复核'}</div>
          <div className="code-label">{item.scope.map(id => projects.find(p => p.id === id)?.name ?? id).join('、')}</div>
        </td><td>{item.author}<div className="code-label">{formatDate(item.updated_at)}</div></td>
          <td><div className="row-actions"><button className="button" onClick={() => setEditor({ feedback: item })}>转为用例</button>
            <button className="text-button" onClick={() => change('/review/feedback/' + item.run_id + '/resolve', {})}>标记已处理</button>
          </div></td></tr>)}</tbody></table></div>
        : <Blank icon={<Flag size={24} />} title="没有待复核反馈" detail="成员点击回答下方的「需复核」后，会在这里出现。" />}
    </section>}
    {data && tab === 'cases' && <section className="surface case-card">
      {data.cases.length ? <div className="table-scroll"><table><thead><tr>
        <th>用例</th><th>预期状态</th><th>目标证据</th><th>操作</th>
      </tr></thead><tbody>{data.cases.map(item => <tr key={item.id}>
        <td><strong>{item.title}</strong><div className="muted">{item.question}</div></td>
        <td>{outcomes[item.expected_status]}{!item.active && <span className="chip neutral">已停用</span>}</td>
        <td>{item.required_sources.map(id => <div className="code-label" key={id}>{id}</div>)}
          {item.phrase && <div>{item.phrase}</div>}</td>
        <td><div className="row-actions"><button className="text-button" onClick={() => setEditor({ existing: item })}>编辑</button>
          <button className="text-button" onClick={() => change('/review/cases/' + item.id + '/availability', { archived: item.active })}>
            {item.active ? '停用' : '启用'}</button></div></td>
      </tr>)}</tbody></table></div> : <Blank icon={<ListChecks size={24} />} title="还没有业务用例"
        detail="添加一个问题，并标记期望状态、证据资料或必须出现的原文。" />}
    </section>}
    {data && tab === 'reports' && <section className="surface case-card">
      <header><h2>{report ? '通过 ' + report.passed + ' / ' + report.total : '评测报告'}</h2><div className="page-actions">
        {report && <button className="button" onClick={exportReport}><Download size={14} /> 导出 JSON</button>}
        {!!data.reports.length && <select aria-label="选择历史报告" value={report?.id ?? ''}
          onChange={event => {
            if (!event.target.value) return
            api<TeamReport>('/review/reports/' + event.target.value).then(setReport).catch(err => setError(errorText(err)))
          }}><option value="">选择历史报告</option>
          {data.reports.map(item => <option key={item.id} value={item.id}>
            {formatDate(item.created_at)} · {item.passed}/{item.total}</option>)}</select>}
      </div></header>
      {report ? <>
        <p className="panel-note">评测基于运行开始时的资料快照。下面列出实际使用的文档版本。</p>
        <div className="table-scroll"><table><thead><tr>
          <th>用例</th><th>预期 / 实际状态</th><th>实际引用版本</th><th>结果</th>
        </tr></thead><tbody>{report.cases.map(item => <tr key={item.id}>
          <td>{item.title}</td><td>{outcomes[item.expected_status]} / {outcomes[item.status]}</td>
          <td>{item.versions.map(id => <div className="code-label" key={id}>{id}</div>)}</td>
          <td>{item.pass ? <span className="result-pass"><Check size={15} /> 通过</span>
            : <div className="result-fail">
              {[item.expected_status !== item.status && '回答状态不符',
                item.missing.length > 0 && '缺少 ' + item.missing.join('、'),
                !item.phrase_match && '引文缺少预期文本'].filter(Boolean).join(' · ')}
            </div>}</td>
        </tr>)}</tbody></table></div>
      </> : <Blank icon={<FlaskConical size={24} />} title="选择报告或运行评测"
        detail="每次运行保存用例结果、引用版本和未通过原因。" />}
    </section>}
    {editor && <CaseEditor editor={editor} projects={projects} close={() => setEditor(null)}
      done={() => { setEditor(null); setTab('cases'); setRefresh(value => value + 1) }} />}
  </div>
}

function CaseEditor({ editor, projects, close, done }: {
  editor: Editor; projects: Project[]; close: () => void; done: () => void
}) {
  const existing = editor.existing
  const [docs, setDocs] = useState<DocumentVersion[]>([])
  const [scope, setScope] = useState(existing?.scope ?? editor.feedback?.scope ?? projects.slice(0, 1).map(p => p.id))
  const [sources, setSources] = useState(existing?.required_sources ?? [])
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    let ignore = false
    api<DocumentVersion[]>('/documents').then(rows => { if (!ignore) setDocs(rows.filter(doc => doc.current && !doc.archived_at)) })
      .catch(err => { if (!ignore) setError(errorText(err)) })
    return () => { ignore = true }
  }, [])

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setPending(true)
    setError('')
    try {
      await api('/review/cases' + (existing ? '/' + existing.id : ''), {
        title: form.get('title'), question: form.get('question'), expected_status: form.get('status'),
        project_ids: scope, required_sources: sources, phrase: form.get('phrase'),
        feedback_run_id: editor.feedback?.run_id,
      })
      done()
    } catch (err) { setError(errorText(err)) } finally { setPending(false) }
  }
  return <Modal label={existing ? '编辑回归用例' : '新建回归用例'} close={() => { if (!pending) close() }}>
    <form className="publish-form" onSubmit={save}>
      <label>用例标题<input name="title" minLength={2} maxLength={100} required
        defaultValue={existing?.title ?? editor.feedback?.question.slice(0, 96)} /></label>
      <label>问题<textarea name="question" minLength={2} maxLength={600} rows={2} required
        defaultValue={existing?.question ?? editor.feedback?.question} /></label>
      <fieldset className="choice-list"><legend>项目范围</legend>
        {projects.map(p => <label className="checkbox-label" key={p.id}><input type="checkbox" checked={scope.includes(p.id)}
          disabled={scope.length >= 12 && !scope.includes(p.id)} onChange={() => {
            if (scope.includes(p.id)) {
              setScope(ids => ids.filter(id => id !== p.id))
              setSources(values => values.filter(id => !id.startsWith(p.id + '/')))
            } else setScope(ids => [...ids, p.id])
          }} />{p.name}</label>)}
      </fieldset>
      <label>预期状态<select name="status" defaultValue={existing?.expected_status ?? 'answered'}>
        {(Object.entries(outcomes) as Array<[ReviewStatus, string]>).map(([id, label]) =>
          <option key={id} value={id}>{label}</option>)}
      </select></label>
      <fieldset className="choice-list source-choices"><legend>目标证据资料</legend>
        {docs.filter(doc => scope.includes(doc.project_id)).map(doc => {
          const key = doc.project_id + '/' + doc.key
          return <label className="checkbox-label" key={doc.id}><input type="checkbox" checked={sources.includes(key)}
            disabled={sources.length >= 12 && !sources.includes(key)} onChange={() =>
              setSources(values => values.includes(key) ? values.filter(value => value !== key) : [...values, key])} />
            {doc.title}</label>
        })}
        {!docs.some(doc => scope.includes(doc.project_id)) && <span className="muted form-hint">所选项目暂时没有可检索的资料。</span>}
      </fieldset>
      <label>引文应包含的文本<input name="phrase" maxLength={240} defaultValue={existing?.phrase}
        placeholder="可选，例如 SLA 为 48 小时" /></label>
      {editor.feedback && <p className="muted form-hint">保存后，这条反馈会从待复核列表移入业务用例。</p>}
      {error && <p className="notice error" role="alert">{error}</p>}
      <footer><button className="button" type="button" disabled={pending} onClick={close}>取消</button>
        <button className="button primary" disabled={pending || !scope.length}>保存用例</button></footer>
    </form>
  </Modal>
}
