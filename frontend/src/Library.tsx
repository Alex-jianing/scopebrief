import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { ArrowUpRight, FilePlus2, FileText, FolderOpen, LoaderCircle, Search } from 'lucide-react'
import { api, errorText, formatDate, importPreview } from './api'
import type { Citation, DocumentVersion, FullDocument, Project } from './api'
import { Blank, Modal } from './ui'
import { BulkImport } from './BulkImport'

export type DocumentTarget = { id: string; citation?: Citation }

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
        <span className="chip accent">v{doc.revision}</span>
        <span className={'chip ' + (doc.current ? 'teal' : 'neutral')}>{doc.current ? '当前版本' : '历史版本'}</span>
        {doc.archived_at && <span className="chip amber">已归档</span>}
        <h3>{doc.title}</h3>
        <p>{formatDate(doc.published_at)}{citation && ' · ' + citation.heading}</p>
        {doc.source_name && <p>来源文件 · {doc.source_name}</p>}
        {doc.change_note && <p>版本说明 · {doc.change_note}</p>}
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

export function Library({ projects, open }: {
  projects: Project[]; open: (target: DocumentTarget) => void
}) {
  const [docs, setDocs] = useState<DocumentVersion[] | null>(null)
  const [filter, setFilter] = useState('')
  const [projectId, setProjectId] = useState('')
  const [includeHistory, setIncludeHistory] = useState(false)
  const [includeArchived, setIncludeArchived] = useState(false)
  const [bulk, setBulk] = useState(false)
  const [pageSize, setPageSize] = useState(35)
  const [archiveTarget, setArchiveTarget] = useState<DocumentVersion | null>(null)
  const [archiving, setArchiving] = useState(false)
  const [actionError, setActionError] = useState('')
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
  const writable = projects.filter(project => project.can_edit)
  const editable = new Set(writable.map(p => p.id))
  const visible = (docs ?? []).filter(doc =>
    (includeHistory || doc.current) && (includeArchived || !doc.archived_at) &&
    (!projectId || doc.project_id === projectId) &&
    (!query || (doc.title + ' ' + doc.key + ' ' + doc.source_name).toLowerCase().includes(query)),
  )
  async function archive() {
    if (!archiveTarget || archiving) return
    setArchiving(true)
    setActionError('')
    try {
      await api('/documents/' + archiveTarget.project_id + '/' + archiveTarget.key + '/archive',
        { archived: !archiveTarget.archived_at })
      setPublished((archiveTarget.archived_at ? '已恢复 ' : '已归档 ') + archiveTarget.title)
      setArchiveTarget(null)
      setAttempt(value => value + 1)
    } catch (err) { setActionError(errorText(err)) } finally { setArchiving(false) }
  }
  return <div className="wide-content">
    <div className="page-heading">
      <div><h1>项目资料</h1>
        <p>查看原文及历史版本。发布新版本后，下次问答会检索更新后的资料。</p></div>
      {!!writable.length && <div className="page-actions">
        <button className="button" onClick={() => setBulk(true)}>批量导入</button>
        <button className="button primary" onClick={() => setPublish('new')}><FilePlus2 size={17} /> 发布资料</button>
      </div>}
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
        <label className="checkbox-label"><input type="checkbox" checked={includeArchived}
          onChange={event => setIncludeArchived(event.target.checked)} /> 显示已归档</label>
        {docs && !error && <span className="table-count" role="status">{visible.length} 条资料</span>}
      </div>
      {error ? <div className="notice error" role="alert">{error}
        <button className="button" onClick={() => { setError(''); setAttempt(attempt + 1) }}>重试</button></div>
        : docs === null ? <div className="dialog-loading"><LoaderCircle className="spin" size={18} /> 加载资料…</div>
        : !visible.length ? <Blank icon={<FolderOpen size={24} />} title="没有匹配的资料" detail="试试其他关键词，或查看全部项目。" />
        : <div className="table-scroll"><table>
          <thead><tr><th>资料</th><th>项目</th><th>版本</th><th>发布时间</th><th>操作</th></tr></thead>
          <tbody>{visible.slice(0, pageSize).map(doc => <tr key={doc.id}>
            <td><button className="file-link" onClick={() => open({ id: doc.id })}><FileText size={16} /> {doc.title}</button>
              {doc.source_name && <small className="source-filename" title={doc.source_name}>{doc.source_name}</small>}</td>
            <td>{projects.find(project => project.id === doc.project_id)?.name}</td>
            <td><span className={'chip ' + (doc.archived_at ? 'amber' : doc.current ? 'teal' : 'neutral')}>
              v{doc.revision} · {doc.archived_at ? '归档' : doc.current ? '当前' : '历史'}</span></td>
            <td className="muted">{formatDate(doc.published_at)}</td>
            <td><div className="row-actions">
              <button className="icon-button" title="查看原文" aria-label={'查看 ' + doc.title + ' v' + doc.revision}
                onClick={() => open({ id: doc.id })}><ArrowUpRight size={15} /></button>
              {editable.has(doc.project_id) && doc.current && <>
                {!doc.archived_at && <button className="text-button" onClick={() => setPublish(doc)}>新版本</button>}
                <button className="text-button" onClick={() => { setArchiveTarget(doc); setActionError('') }}>
                  {doc.archived_at ? '恢复' : '归档'}
                </button>
              </>}
            </div></td>
          </tr>)}</tbody>
        </table></div>}
    </div>
    {visible.length > pageSize && <div className="pagination">
      <button className="button" onClick={() => setPageSize(count => count + 35)}>加载更多 · {visible.length - pageSize} 条</button>
    </div>}
    {archiveTarget && <Modal label={archiveTarget.archived_at ? '恢复资料' : '归档资料'}
      close={() => { if (!archiving) setArchiveTarget(null) }}>
      <div className="publish-form">
        <p>{archiveTarget.title}</p>
        <p className="muted form-hint">{archiveTarget.archived_at
          ? '恢复后，最新版本会重新进入检索范围。'
          : '归档后，这份资料会移出新问答的检索范围。已有引用仍可查看原文。'}</p>
        {actionError && <p className="notice error" role="alert">{actionError}</p>}
        <footer><button className="button" onClick={() => setArchiveTarget(null)} disabled={archiving}>取消</button>
          <button className="button primary" onClick={archive} disabled={archiving}>
            {archiveTarget.archived_at ? '确认恢复' : '确认归档'}</button></footer>
      </div>
    </Modal>}
    {publish && <PublishDialog projects={writable} seed={publish === 'new' ? null : publish} close={() => setPublish(null)}
      onPublish={doc => {
        setDocs(rows => [doc, ...(rows ?? []).map(item => item.key === doc.key && item.project_id === doc.project_id
          ? { ...item, current: false } : item)])
        setAttempt(attempt + 1)
        setPublished('已发布 ' + doc.title + ' · v' + doc.revision)
        setPublish(null)
      }} />}
    {bulk && <BulkImport projects={writable} close={() => setBulk(false)} onPublish={count => {
      setPublished('已批量发布 ' + count + ' 份资料')
      setAttempt(value => value + 1)
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
  const [source, setSource] = useState(seed?.source_name ?? '')
  const [changeNote, setChangeNote] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(Boolean(seed))
  const [pending, setPending] = useState(false)
  const [importing, setImporting] = useState(false)
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
      onPublish(await api<FullDocument>('/documents', {
        project_id: projectId, key, title, body, source_name: source, change_note: changeNote,
        expected_revision: seed?.revision,
      }))
    } catch (err) { setError(errorText(err)) } finally { setPending(false) }
  }
  return <Modal label={seed ? '发布新版本' : '发布 Markdown 资料'} close={() => { if (!pending) close() }}>
    <form className="publish-form" onSubmit={submit}>
      <div className="publish-fields">
        <label>项目<select disabled={Boolean(seed) || importing} value={projectId} onChange={event => setProjectId(event.target.value)}>
          {projects.map(p => <option value={p.id} key={p.id}>{p.name}</option>)}
        </select></label>
        <label>文档键<input readOnly={Boolean(seed)} placeholder="release-notes" value={key}
          pattern="[a-z0-9]+(?:-[a-z0-9]+)*" maxLength={40} required onChange={event => setKey(event.target.value)} /></label>
      </div>
      <label>标题<input value={title} maxLength={100} required onChange={event => setTitle(event.target.value)} /></label>
      <label className="import-label">导入文件 <input type="file" accept=".md,.markdown,.txt,.pdf,.docx" disabled={loading || importing || pending}
        onChange={async event => {
          const file = event.target.files?.[0]
          if (!file) return
          if (file.size > 8 * 1024 * 1024) { setError('单个文件上限为 8 MiB。'); return }
          setImporting(true)
          setError('')
          try {
            const content = await importPreview(projectId, file)
            setBody(content.body)
            setSource(content.source_name)
            if (!title.trim()) setTitle(content.title)
            const slug = content.title.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40).replace(/-$/, '')
            if (!key && slug) setKey(slug)
          } catch (err) { setError(errorText(err)) } finally { setImporting(false) }
        }} /></label>
      {importing ? <p className="form-hint" role="status">正在提取正文…</p>
        : <p className="muted form-hint">{source ? '来源文件 · ' + source : '支持 Markdown、TXT、PDF、DOCX。单文件 8 MiB 以内。'}</p>}
      <label>版本说明<input value={changeNote} maxLength={240} onChange={event => setChangeNote(event.target.value)} /></label>
      <label>Markdown 正文<textarea rows={9} disabled={loading || importing} required maxLength={180000}
        value={body} onChange={event => setBody(event.target.value)} placeholder={'## 放行结论 [decision=go]\n请填写评审记录。'} /></label>
      <details className="markdown-help"><summary>章节标签</summary>
        <p><code>[decision=go]</code> 放行，<code>[decision=hold]</code> 暂缓。其他可用标签为
          <code>[blocker]</code>、<code>[window]</code>、<code>[rollback]</code>、<code>[owner]</code>、
          <code>[verification]</code> 和 <code>[dependency]</code>。标签写在标题末尾。</p>
      </details>
      {error && <div className="notice error" role="alert">{error}</div>}
      <footer><button type="button" className="button" onClick={close} disabled={pending}>取消</button>
        <button type="submit" className="button primary" disabled={pending || loading || importing}>{pending ? '正在发布…' : '确认发布'}</button></footer>
    </form>
  </Modal>
}
