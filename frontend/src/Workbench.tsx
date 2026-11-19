import { useState } from 'react'
import {
  Activity, ArrowRight, ArrowUpRight, BookOpenCheck, CircleAlert, ClipboardCheck,
  Code2, FileSearch, GitBranch, Layers3, LoaderCircle, ScanSearch,
} from 'lucide-react'
import { labels } from './api'
import type { Citation, FindingStatus, Project, Run } from './api'
import { Blank, ProjectIcon, WorkflowIllustration } from './ui'

const presets = [
  { label: '跨项目放行', question: '今晚北辰和潮汐各自能否上线？哪个还有阻塞？', icon: GitBranch },
  { label: '回退预案', question: '北辰和潮汐的回切阈值和负责人分别是谁？', icon: Layers3 },
  { label: '变更时段', question: '北辰和潮汐什么时候灰度？', icon: ClipboardCheck },
  { label: '缺证据情形', question: '北辰 2027 年的市场广告投放预算是多少？', icon: FileSearch },
]
const statuses: Record<FindingStatus, string> = {
  go: '可进入灰度',
  hold: '暂缓放行',
  grounded: '已找到证据',
  conflict: '需人工确认',
  insufficient: '资料不足',
}
const stages: Record<string, string> = {
  scope: '校验范围', plan: '拆解问题', retrieve: '检索正文', retry: '定向补查',
  budget: '限制上下文', generate: '提炼原文', fallback: '模型降级',
  verify: '验证结果', complete: '完成运行',
}

type WorkbenchProps = {
  run: Run | null
  busy: boolean
  draft: string
  setDraft: (value: string) => void
  scope: string[]
  projects: Project[]
  ask: (text: string) => void
  showCitation: (item: Citation) => void
}

export function Workbench({
  run, busy, draft, setDraft, scope, projects, ask, showCitation,
}: WorkbenchProps) {
  const result = run?.result
  const selected = projects.filter(project => scope.includes(project.id))
  const canAsk = !busy && selected.length > 0
  return <div className="view-content">
    {!run ? <section className="hero">
      <div className="hero-copy">
        <span className="hero-label"><ScanSearch size={15} /> 知识问答</span>
        <h1>跨项目上线评审</h1>
        <p>查放行、阻塞和回滚。每条结论都可以<br className="hero-break" />追到文档版本与原文。</p>
      </div>
      <WorkflowIllustration />
    </section> : <section className="run-heading">
      <div className="run-label"><BookOpenCheck size={16} /> 评审结果</div>
      <h1>{run.question}</h1>
      <div className="run-meta">
        {run.status === 'running' && <span className="chip violet"><LoaderCircle className="spin" size={14} /> 正在查证</span>}
        {result && <>
          <span className={'chip ' + (result.status === 'answered' ? 'teal' : 'amber')}>
            {result.status === 'answered' ? '证据齐全' : result.status === 'partial' ? '有未覆盖项' : '无法确认'}
          </span>
          <span>{result.generator === 'model' ? '模型摘录' : result.generator === 'fallback' ? '模型降级 · 原文摘录' : '原文摘录'}</span>
          <span>{result.duration_ms.toLocaleString()} ms</span>
        </>}
      </div>
    </section>}

    {run?.error && <div className="notice error" role="alert">{run.error}
      <button className="button" disabled={!canAsk} onClick={() => ask(run.question)}>重新运行</button>
    </div>}
    {run?.status === 'running' && <div className="surface progress-state" role="status">
      <LoaderCircle size={20} className="spin" />
      {run.events.at(-1)?.detail ?? '正在建立检索范围…'}
    </div>}
    {result && <div className="answer-area" aria-live="polite">
      {result.scope_limited && result.citations.length > 0 && <div className="surface abstention">
        <CircleAlert size={20} /> 部分提及项目超出此会话的权限或检索范围。
      </div>}
      {!result.citations.length && <div className="surface abstention">
        <CircleAlert size={22} />
        <div><strong>当前范围内缺少有效证据</strong><p>可以切换项目范围、补充资料或调整问题后再查证。</p></div>
      </div>}
      {!!result.findings.length && <div className={'finding-grid ' + (result.findings.length > 1 ? 'multiple' : '')}>
        {result.findings.map(finding => {
          const project = projects.find(item => item.id === finding.project_id)
          const citations = result.citations.filter(item => finding.citation_ids.includes(item.id))
          return <article className="surface finding" key={finding.project_id}>
            <header><div className="finding-name"><ProjectIcon name={finding.name} color={project?.color ?? 'violet'} />
              <h2>{finding.name}</h2></div>
              <span className={'chip decision-' + finding.status}>{statuses[finding.status]}</span>
            </header>
            {finding.status === 'conflict' && <p className="conflict-message">现行记录存在相反结论，请核对下方原文。</p>}
            {citations.map(item => <div className="finding-quote" key={item.id}>
              <div className="quote-heading">{item.heading}</div>
              <p>{item.quote} <button className="source-number" onClick={() => showCitation(item)}
                aria-label={'查看引用 ' + item.number}>{item.number}</button></p>
            </div>)}
            {!!finding.missing.length && <p className="missing-topics">
              待补资料 · {finding.missing.map(key => labels[key] ?? key).join('、')}
            </p>}
          </article>
        })}
      </div>}
    </div>}

    <form className="surface composer" onSubmit={event => { event.preventDefault(); if (canAsk) ask(draft) }}>
      <label htmlFor="question">{run ? '继续查证' : '问一个上线问题'}</label>
      <textarea id="question" placeholder="例如：北辰今晚能上线吗？" rows={2} value={draft}
        maxLength={600} onChange={event => setDraft(event.target.value)}
        onKeyDown={event => {
          if ((event.ctrlKey || event.metaKey) && event.key === 'Enter' && canAsk) {
            event.preventDefault()
            ask(draft)
          }
        }} />
      <div className="composer-actions">
        <span className="composer-scope"><Layers3 size={15} />
          {selected.length ? selected.map(project => project.name).join('、') : '请选择项目范围'}
        </span>
        <button className="button primary" disabled={!canAsk || draft.trim().length < 2} type="submit">
          查证 <ArrowRight size={17} />
        </button>
      </div>
    </form>
    <section className="presets" aria-label="示例问题">
      <h2>示例问题</h2>
      <div className="preset-grid">{presets.map(({ label, question, icon: Icon }) =>
        <button className="surface preset" key={label} disabled={!canAsk} onClick={() => ask(question)}>
          <span className="preset-icon"><Icon size={17} /></span>
          <span className="preset-copy"><strong>{label}</strong><small>{question}</small></span>
          <ArrowUpRight className="preset-arrow" size={16} />
        </button>,
      )}</div>
    </section>
  </div>
}

export function EvidencePanel({ run, showCitation }: {
  run: Run | null; showCitation: (item: Citation) => void
}) {
  const [choice, setChoice] = useState<'sources' | 'trace' | null>(null)
  const tab = choice ?? (run?.status === 'running' ? 'trace' : 'sources')
  const sources = run?.result?.citations ?? []
  return <aside className="evidence-panel" aria-label="证据与轨迹">
    <div className="evidence-heading"><span className="evidence-mark"><BookOpenCheck size={17} /></span>
      <h2>证据面板</h2></div>
    <div className="panel-tabs" aria-label="面板内容">
      <button className={tab === 'sources' ? 'active' : ''} aria-pressed={tab === 'sources'}
        onClick={() => setChoice('sources')}>引用 <span>{sources.length}</span></button>
      <button className={tab === 'trace' ? 'active' : ''} aria-pressed={tab === 'trace'}
        onClick={() => setChoice('trace')}>运行轨迹</button>
    </div>
    {tab === 'sources' ? (
      sources.length ? <div className="source-list">
        {sources.map(item => <button className="source-card" key={item.id} onClick={() => showCitation(item)}>
          <span className="source-number">{item.number}</span>
          <span><strong>{item.title}</strong><small>{item.heading}</small>
            <small className="code-label">v{item.revision} · 第 {item.start_line}
              {item.end_line !== item.start_line ? '–' + item.end_line : ''} 行</small></span>
          <ArrowUpRight size={14} />
        </button>)}
      </div> : <Blank icon={<FileSearch size={24} />} title={run?.result ? '没有引用' : '引用将在这里出现'}
        detail="打开一条引用，可以查看当时使用的文档版本和原文行号。" />
    ) : run?.events.length ? (
      <div className="trace-content">
        <ol className="trace-list">
          {run.events.map(event => <li key={event.id}>
            <i className={event.stage === 'fallback' || event.stage === 'budget' ? 'amber-dot' : ''} />
            <div><div className="trace-step"><strong>{stages[event.stage] ?? event.stage}</strong><small>+{event.elapsed_ms} ms</small></div>
              <p>{event.detail}</p></div>
          </li>)}
        </ol>
        {run.result?.usage && <div className="trace-usage">
          <Code2 size={15} /> {run.result.usage.total_tokens ?? '—'} tokens · {run.result.model}
        </div>}
      </div>
    ) : <Blank icon={<Activity size={24} />} title="等待运行" detail="这里会记录范围校验、检索、补查和验证步骤。" />}
  </aside>
}
