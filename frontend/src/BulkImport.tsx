import { useState } from 'react'
import { LoaderCircle } from 'lucide-react'
import { api, errorText, importPreview } from './api'
import type { IntakeResult, Project } from './api'
import { Modal } from './ui'

type ImportRow = {
  name: string; source: IntakeResult | null; key: string
  status: 'ready' | 'published' | 'error'; detail: string
}
const keyPattern = /^[a-z0-9]+(?:-[a-z0-9]+)*$/
const countLimit = 15

export function BulkImport({ projects, close, onPublish }: {
  projects: Project[]; close: () => void; onPublish: (count: number) => void
}) {
  const [project, setProject] = useState(projects[0]?.id ?? '')
  const [rows, setRows] = useState<ImportRow[]>([])
  const [stage, setStage] = useState<'reading' | 'publishing' | null>(null)
  const [message, setMessage] = useState('')

  function update(index: number, fields: Partial<ImportRow>) {
    setRows(list => list.map((row, i) => i === index ? { ...row, ...fields } : row))
  }

  async function load(files: File[]) {
    if (!files.length) return
    setMessage('')
    if (files.length > countLimit) { setMessage('每批最多选择 15 份文件。'); return }
    setStage('reading')
    const next: ImportRow[] = []
    for (const [i, file] of files.entries()) {
      try {
        const source = await importPreview(project, file)
        const slug = source.title.toLowerCase().replace(/[^a-z0-9]+/g, '-')
          .slice(0, 40).replace(/^-+|-+$/g, '')
        const key = slug || 'doc-' + Date.now().toString(36) + '-' + (i + 1)
        next.push({ name: file.name, source, key, status: 'ready', detail: '待发布' })
      } catch (err) {
        next.push({ name: file.name, source: null, key: '', status: 'error', detail: errorText(err) })
      }
      setRows([...next])
    }
    setStage(null)
  }

  async function publish() {
    const pending = rows.flatMap((row, index) => row.source && row.status !== 'published'
      ? [{ index, row, source: row.source }] : [])
    const valid = pending.map(entry => entry.row.key)
    setMessage('')
    if (new Set(valid).size !== valid.length || valid.some(key => !keyPattern.test(key) || key.length > 40)) {
      setMessage('每份待发布资料都需要一个不重复的文档键。使用小写字母、数字和连字符。')
      return
    }
    setStage('publishing')
    let passed = 0
    for (const { index, row, source } of pending) {
      try {
        await api('/documents', { project_id: project, key: row.key,
          title: source.title.length > 1 ? source.title : source.source_name, body: source.body,
          source_name: source.source_name, change_note: '批量导入', create_only: true })
        update(index, { status: 'published', detail: '已发布 v1' })
        passed += 1
      } catch (err) { update(index, { status: 'error', detail: errorText(err) }) }
    }
    setStage(null)
    if (passed) onPublish(passed)
  }

  return <Modal label="批量导入资料" close={() => { if (!stage) close() }}>
    <div className="publish-form">
      <label>目标项目<select disabled={Boolean(stage) || rows.length > 0} value={project}
        onChange={event => setProject(event.target.value)}>
        {projects.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
      </select></label>
      <label className="import-label">选择多个文件<input type="file" multiple
        accept=".md,.markdown,.txt,.pdf,.docx" disabled={Boolean(stage) || rows.some(row => row.status === 'published')}
        onChange={event => load(Array.from(event.target.files ?? []))} /></label>
      <p className="muted form-hint">每批最多 15 份，每份不超过 8 MiB。要更新已有资料，请从该资料的「新版本」发布。</p>
      {stage && <p className="dialog-loading" role="status"><LoaderCircle size={17} className="spin" />
        {stage === 'reading' ? '正在提取文件…' : '正在逐份发布…'}</p>}
      {!!rows.length && <div className="table-scroll batch-scroll"><table>
        <thead><tr><th>文件</th><th>文档键</th><th>状态</th></tr></thead>
        <tbody>{rows.map((row, index) => <tr key={index}>
          <td>{row.name}</td><td>{row.source ? <input aria-label={row.name + ' 文档键'} value={row.key} maxLength={40}
            disabled={Boolean(stage) || row.status === 'published'} onChange={event => update(index, { key: event.target.value })} /> : '—'}</td>
          <td className={row.status === 'error' ? 'result-fail' : row.status === 'published' ? 'result-pass' : ''}>{row.detail}</td>
        </tr>)}</tbody>
      </table></div>}
      {message && <p className="notice error" role="alert">{message}</p>}
      <footer><button className="button" disabled={Boolean(stage)} onClick={close}>关闭</button>
        <button className="button primary" disabled={Boolean(stage) || !rows.some(row => row.source && row.status !== 'published')}
          onClick={publish}>发布可用资料</button></footer>
    </div>
  </Modal>
}
