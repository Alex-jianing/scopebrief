import { useEffect, useRef, useState } from 'react'
import type { FormEvent, ReactNode } from 'react'
import { ArrowUpRight, BookOpen, FilePlus2, FileText, FolderOpen, LoaderCircle, Search, X } from 'lucide-react'
import { api, errorText, formatDate } from './api'
import type { Citation, DocumentVersion, FullDocument, Project } from './api'
import { Blank } from './ui'

export type DocumentTarget = { id: string; citation?: Citation }

function Modal({ label, close, drawer, children }: {
  label: string; close: () => void; drawer?: boolean; children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current
    dialog?.showModal()
    return () => dialog?.close()
  }, [])
  return <dialog ref={ref} aria-label={label} className={drawer ? 'dialog drawer' : 'dialog'}
    onCancel={event => { event.preventDefault(); close() }}
    onClick={event => { if (event.target === event.currentTarget) close() }}>
    <div className="dialog-inner">
      <header className="dialog-heading"><h2>{label}</h2>
        <button className="icon-button" type="button" onClick={close} aria-label="关闭"><X size={20} /></button>
      </header>
      {children}
    </div>
  </dialog>
}

export function DocumentDialog({ target, close }: { target: DocumentTarget; close: () => void }) {
  const [doc, setDoc] = useState<FullDocument | null>(null)
  const [error, setError] = useState('')
  const highlighted = useRef<HTMLDivElement>(null)
  useEffect(() => {
    let ignore = false
    api<FullDocument>('/documents/' + encodeURIComponent(target.id))
      .then(value => { if (!ignore) setDoc(value) })
      .catch(err => { if (!ignore) setError(errorText(err)) })
    return () => { ignore = true }
  }, [target.id])
  useEffect(() => {
    highlighted.current?.scrollIntoView({ block: 'nearest' })
  }, [doc])
  const citation = target.citation
  return <Modal label={citation ? '引用原文' : '资料原文'} close={close} drawer>
    {error && <div className="notice error" role="alert">{error}</div>}
    {!error && !doc && <div className="dialog-loading"><LoaderCircle className="spin" size={19} /> 加载资料…</div>}
    {doc && <>
      <div className="document-title">
        <span className="chip violet">v{doc.revision}</span>
        <span className={'chip ' + (doc.current ? 'teal' : 'neutral')}>{doc.current ? '当前版本' : '历史版本'}</span>
        <h3>{doc.title}</h3>
        <p>{formatDate(doc.published_at)}{citation && ' · ' + citation.heading}</p>
      </div>
      <div className="source-text" aria-label="带行号的 Markdown 原文">
        {doc.body.split(/\r\n|\r|\n/).map((line, i) => {
          const active = citation && citation.start_line <= i + 1 && i + 1 <= citation.end_line
          return <div className={'source-line ' + (active ? 'highlighted' : '')} key={i}
            ref={citation?.start_line === i + 1 ? highlighted : undefined}>
            <span aria-hidden="true">{i + 1}</span><code>{line || '\u00a0'}</code>
          </div>
        })}
      </div>
    </>}
  </Modal>
}

export function Library({ projects, canPublish, open }: {
  projects: Project[]; canPublish: boolean; open: (target: DocumentTarget) => void
}) {
  const [docs, setDocs] = useState<DocumentVersion[] | null>(null)
  const [filter, setFilter] = useState('')
  const [projectId, setProjectId] = useState('')
  const [includeHistory, setIncludeHistory] = useState(false)
  const [publish, setPublish] = useState<DocumentVersion | 'new' | null>(null)
  const [published, setPublished] = useState('')
  const [error, setError] = useState('')
  const [attempt, setAttempt] = useState(0)
  useEffect(() => {
    let ignore = false
    api<DocumentVersion[]>('/documents')
      .then(value => { if (!ignore) setDocs(value) })
      .catch(err => { if (!ignore) setError(errorText(err)) })
    return () => { ignore = true }
  }, [attempt])
  const query = filter.trim().toLowerCase()
  const visible = (docs ?? []).filter(doc =>
    (includeHistory || doc.current) && (!projectId || doc.project_id === projectId) &&
    (!query || (doc.title + ' ' + doc.key).toLowerCase().includes(query)),
  )
  return <div className="wide-content">
    <div className="page-heading">
      <div><div className="run-label"><BookOpen size={16} /> 知识库</div><h1>项目资料</h1>
        <p>查看原文及历史版本。发布新版本后，下次问答会检索更新后的资料。</p></div>
      {canPublish && <button className="button primary" onClick={() => setPublish('new')}><FilePlus2 size={17} /> 发布资料</button>}
    </div>
    {published && <div className="notice success" role="status">{published}</div>}
    <div className="surface library-card">
      <div className="table-tools">
        <label className="search-input"><Search size={16} /><input aria-label="搜索资料" placeholder="搜索资料名称"
          value={filter} onChange={event => setFilter(event.target.value)} /></label>
        <select aria-label="过滤项目" value={projectId} onChange={event => setProjectId(event.target.value)}>
          <option value="">全部项目</option>
          {projects.map(project => <option key={project.id} value={project.id}>{project.name}</option>)}
        </select>
        <label className="checkbox-label"><input type="checkbox" checked={includeHistory}
          onChange={event => setIncludeHistory(event.target.checked)} /> 包含历史版本</label>
      </div>
      {error ? <div className="notice error" role="alert">{error}
        <button className="button" onClick={() => { setError(''); setAttempt(attempt + 1) }}>重试</button></div>
        : docs === null ? <div className="dialog-loading"><LoaderCircle className="spin" size={18} /> 加载资料…</div>
        : !visible.length ? <Blank icon={<FolderOpen size={24} />} title="没有匹配的资料" detail="试试其他关键词，或查看全部项目。" />
        : <div className="table-scroll"><table>
          <thead><tr><th>资料</th><th>项目</th><th>版本</th><th>发布时间</th><th>操作</th></tr></thead>
          <tbody>{visible.map(doc => <tr key={doc.id}>
            <td><button className="file-link" onClick={() => open({ id: doc.id })}><FileText size={16} /> {doc.title}</button></td>
            <td>{projects.find(project => project.id === doc.project_id)?.name}</td>
            <td><span className={'chip ' + (doc.current ? 'teal' : 'neutral')}>v{doc.revision} · {doc.current ? '当前' : '历史'}</span></td>
            <td className="muted">{formatDate(doc.published_at)}</td>
            <td><div className="row-actions">
              <button className="icon-button" title="查看原文" aria-label={'查看 ' + doc.title + ' v' + doc.revision}
                onClick={() => open({ id: doc.id })}><ArrowUpRight size={15} /></button>
              {canPublish && doc.current && <button className="text-button" onClick={() => setPublish(doc)}>新版本</button>}
            </div></td>
          </tr>)}</tbody>
        </table></div>}
    </div>
    {publish && <PublishDialog projects={projects} seed={publish === 'new' ? null : publish} close={() => setPublish(null)}
      onPublish={doc => {
        setDocs(rows => [doc, ...(rows ?? []).map(item => item.key === doc.key && item.project_id === doc.project_id
          ? { ...item, current: false } : item)])
        setAttempt(attempt + 1)
        setPublished('已发布 ' + doc.title + ' · v' + doc.revision)
        setPublish(null)
      }} />}
  </div>
}

function PublishDialog({ projects, seed, close, onPublish }: {
  projects: Project[]; seed: DocumentVersion | null; close: () => void
  onPublish: (doc: FullDocument) => void
}) {
  const [projectId, setProjectId] = useState(seed?.project_id ?? projects[0]?.id ?? '')
  const [key, setKey] = useState(seed?.key ?? '')
  const [title, setTitle] = useState(seed?.title ?? '')
  const [body, setBody] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(Boolean(seed))
  const [pending, setPending] = useState(false)
  useEffect(() => {
    if (!seed) return
    let ignore = false
    api<FullDocument>('/documents/' + encodeURIComponent(seed.id))
      .then(doc => { if (!ignore) setBody(doc.body) })
      .catch(err => { if (!ignore) setError(errorText(err)) })
      .finally(() => { if (!ignore) setLoading(false) })
    return () => { ignore = true }
  }, [seed])
  async function submit(event: FormEvent) {
    event.preventDefault()
    setError('')
    setPending(true)
    try {
      onPublish(await api<FullDocument>('/documents', { project_id: projectId, key, title, body }))
    } catch (err) { setError(errorText(err)) } finally { setPending(false) }
  }
  return <Modal label={seed ? '发布新版本' : '发布 Markdown 资料'} close={() => { if (!pending) close() }}>
    <form className="publish-form" onSubmit={submit}>
      <div className="publish-fields">
        <label>项目<select disabled={Boolean(seed)} value={projectId} onChange={event => setProjectId(event.target.value)}>
          {projects.map(p => <option value={p.id} key={p.id}>{p.name}</option>)}
        </select></label>
        <label>文档键<input readOnly={Boolean(seed)} placeholder="release-notes" value={key}
          pattern="[a-z0-9]+(?:-[a-z0-9]+)*" maxLength={40} required onChange={event => setKey(event.target.value)} /></label>
      </div>
      <label>标题<input value={title} maxLength={100} required onChange={event => setTitle(event.target.value)} /></label>
      <label className="import-label">从文件载入 <input type="file" accept=".md,.txt,text/markdown,text/plain" disabled={loading}
        onChange={async event => {
          const file = event.target.files?.[0]
          if (!file) return
          if (file.size > 64000) { setError('请选择 16,000 字以内的 Markdown 文档。'); return }
          try {
            const content = await file.text()
            if (content.length > 16000) { setError('正文最多 16,000 字。'); return }
            setBody(content)
            setError('')
          } catch (err) { setError(errorText(err)) }
        }} /></label>
      <label>Markdown 正文<textarea rows={9} disabled={loading} required maxLength={16000}
        value={body} onChange={event => setBody(event.target.value)} placeholder={'## 放行结论 [decision=go]\n请填写评审记录。'} /></label>
      <details className="markdown-help"><summary>章节标签</summary>
        <p><code>[decision=go]</code> 放行，<code>[decision=hold]</code> 暂缓。其他可用标签为
          <code>[blocker]</code>、<code>[window]</code>、<code>[rollback]</code>、<code>[owner]</code>、
          <code>[verification]</code> 和 <code>[dependency]</code>。标签写在标题末尾。</p>
      </details>
      {error && <div className="notice error" role="alert">{error}</div>}
      <footer><button type="button" className="button" onClick={close} disabled={pending}>取消</button>
        <button type="submit" className="button primary" disabled={pending || loading}>{pending ? '正在发布…' : '确认发布'}</button></footer>
    </form>
  </Modal>
}
