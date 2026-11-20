import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Copy, FolderPlus, History, KeyRound, LoaderCircle, Pencil, Plus, UsersRound } from 'lucide-react'
import { api, errorText, formatDate } from './api'
import type { Grants, Invitation, TeamInfo, TeamMember, TeamProject } from './api'
import { Blank, Modal, ProjectIcon } from './ui'

const auditLabels: Record<string, string> = {
  'account.activated': '激活账号', 'account.password_reset': '重设密码',
  'project.saved': '保存项目', 'invite.issued': '生成邀请', 'invite.revoked': '撤销邀请',
  'member.updated': '更新成员权限', 'document.published': '发布资料',
  'document.archived': '归档资料', 'document.restored': '恢复资料',
  'case.saved': '保存用例', 'case.enabled': '启用用例', 'case.disabled': '停用用例',
  'quality.evaluated': '运行回归', 'feedback.resolved': '处理反馈',
}

function invitationState(invite: Invitation) {
  if (invite.used_by) return '已使用'
  return invite.expires_at * 1000 > Date.now() ? '待激活' : '已失效'
}

export function TeamWorkspace({ onProjectChanged }: { onProjectChanged: () => Promise<void> }) {
  const [data, setData] = useState<TeamInfo | null>(null)
  const [tab, setTab] = useState<'projects' | 'members' | 'activity'>('projects')
  const [generation, refresh] = useState(0)
  const [project, setProject] = useState<TeamProject | 'new' | null>(null)
  const [member, setMember] = useState<TeamMember | 'invite' | null>(null)
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  useEffect(() => {
    let ignore = false
    api<TeamInfo>('/team').then(value => { if (!ignore) setData(value) })
      .catch(err => { if (!ignore) setError(errorText(err)) })
    return () => { ignore = true }
  }, [generation])

  async function revoke(invite: Invitation) {
    try {
      setError('')
      await api('/team/invitations/' + invite.id + '/revoke', {})
      setMessage('邀请码已撤销。')
      refresh(value => value + 1)
    } catch (err) { setError(errorText(err)) }
  }

  return <div className="wide-content">
    <div className="page-heading"><div>
      <div className="run-label"><UsersRound size={16} /> 工作区</div>
      <h1>团队管理</h1><p>管理项目、成员和资料权限。</p>
    </div><div className="page-actions">
      {tab === 'projects' && <button className="button primary" onClick={() => setProject('new')}>
        <FolderPlus size={17} /> 创建项目</button>}
      {tab === 'members' && <button className="button primary" onClick={() => setMember('invite')}>
        <KeyRound size={17} /> 邀请成员</button>}
    </div></div>
    <nav className="section-nav" aria-label="团队管理视图">
      {(['projects', 'members', 'activity'] as const).map(id =>
        <button type="button" key={id} className={tab === id ? 'active' : ''} aria-pressed={tab === id}
          onClick={() => { setTab(id); setError(''); setMessage('') }}>
          {{ projects: '项目', members: '成员与邀请', activity: '操作记录' }[id]}
        </button>,
      )}
    </nav>
    {error && <p className="notice error" role="alert">{error}</p>}
    {message && <p className="notice success" role="status">{message}</p>}
    {!data && !error && <div className="dialog-loading"><LoaderCircle className="spin" size={18} /> 加载团队…</div>}
    {data && tab === 'projects' && <div className="team-grid">
      {data.projects.map(p => <article className="surface project-card" key={p.id}>
        <header><ProjectIcon name={p.name} color={p.color} /><div><h2>{p.name}</h2><span className="code-label">{p.id}</span></div>
          <button className="icon-button" type="button" aria-label={'编辑 ' + p.name} onClick={() => setProject(p)}><Pencil size={16} /></button>
        </header>
        {p.description && <p>{p.description}</p>}
        <div className="project-card-meta">
          <span>{data.members.filter(m => m.enabled && m.grants[p.id]).length} 位授权成员</span>
          {p.aliases.filter(alias => alias !== p.id && alias !== p.name).map(alias => <span className="chip neutral" key={alias}>{alias}</span>)}
        </div>
      </article>)}
      {!data.projects.length && <div className="surface full-width">
        <Blank icon={<FolderPlus size={23} />} title="创建第一个项目" detail="项目决定成员能读到哪些资料，以及谁可以发布版本。" />
      </div>}
    </div>}
    {data && tab === 'members' && <>
      <section className="surface case-card">
        <header><h2>成员账号</h2></header>
        <div className="table-scroll"><table><thead><tr><th>成员</th><th>状态</th><th>项目权限</th><th>操作</th></tr></thead>
          <tbody>{data.members.map(person => <tr key={person.id}>
            <td><strong>{person.name}</strong><div className="code-label">{person.username}</div></td>
            <td><span className={'chip ' + (person.enabled ? 'teal' : 'neutral')}>{person.enabled ? '可用' : '已停用'}</span></td>
            <td>{person.admin ? '团队管理员' : Object.keys(person.grants).length ? <div className="inline-grants">
              {Object.entries(person.grants).map(([key, level]) => <span className="chip neutral" key={key}>
                {data.projects.find(p => p.id === key)?.name ?? key} · {level === 'editor' ? '编辑' : '只读'}</span>)}
            </div> : <span className="muted">待分配项目</span>}</td>
            <td>{!person.admin && <button className="text-button" onClick={() => setMember(person)}>设置权限</button>}</td>
          </tr>)}</tbody></table></div>
      </section>
      <section className="surface case-card section-gap">
        <header><h2>最近邀请</h2></header>
        {data.invitations.length ? <div className="table-scroll"><table><thead>
          <tr><th>邀请备注</th><th>项目数</th><th>状态</th><th>有效期</th><th>操作</th></tr>
        </thead><tbody>{data.invitations.map(invite => <tr key={invite.id}>
          <td>{invite.label}</td><td>{Object.keys(invite.grants).length}</td><td>{invitationState(invite)}</td>
          <td>{invite.expires_at ? formatDate(new Date(invite.expires_at * 1000).toISOString()) : '—'}</td>
          <td>{invitationState(invite) === '待激活' && <button className="text-button" onClick={() => revoke(invite)}>撤销邀请</button>}</td>
        </tr>)}</tbody></table></div> : <p className="panel-note">生成邀请码后，这里会显示邀请状态。</p>}
      </section>
    </>}
    {data && tab === 'activity' && <section className="surface case-card">
      <header><h2><History size={16} /> 最近变更</h2></header>
      {data.activity.length ? <div className="table-scroll"><table><thead><tr><th>时间</th><th>操作人</th><th>动作</th><th>对象</th></tr></thead>
        <tbody>{data.activity.map(record => <tr key={record.id}>
          <td>{formatDate(record.at)}</td><td>{record.actor ?? '系统'}</td>
          <td>{auditLabels[record.action] ?? record.action}</td><td className="code-label">{record.target}</td>
        </tr>)}</tbody></table></div> : <p className="panel-note">项目、权限和资料变更会记录在这里。</p>}
    </section>}
    {project && <ProjectEditor project={project === 'new' ? null : project} close={() => setProject(null)}
      done={async name => {
        setProject(null)
        setMessage('已保存项目 ' + name)
        refresh(value => value + 1)
        await onProjectChanged().catch(err => setError(errorText(err)))
      }} />}
    {member && data && <MemberEditor member={member === 'invite' ? null : member} projects={data.projects}
      close={() => setMember(null)}
      done={() => {
        refresh(value => value + 1)
        if (member !== 'invite') { setMember(null); setMessage('成员权限已保存。') }
      }} />}
  </div>
}

function ProjectEditor({ project, close, done }: {
  project: TeamProject | null; close: () => void; done: (name: string) => Promise<void>
}) {
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const name = String(form.get('name'))
    setPending(true)
    setError('')
    try {
      await api('/team/projects', {
        id: form.get('id'), name, description: form.get('description'),
        aliases: String(form.get('aliases')).split(/[,，]/).map(value => value.trim()).filter(Boolean),
        color: form.get('color'),
      })
      await done(name)
    } catch (err) { setError(errorText(err)) } finally { setPending(false) }
  }
  return <Modal label={project ? '编辑项目' : '创建项目'} close={() => { if (!pending) close() }}>
    <form className="publish-form" onSubmit={save}>
      <div className="publish-fields">
        <label>项目名称<input name="name" defaultValue={project?.name} minLength={2} maxLength={100} required /></label>
        <label>项目标识<input name="id" defaultValue={project?.id} maxLength={40} pattern="[a-z0-9]+(?:-[a-z0-9]+)*"
          placeholder="payments" readOnly={Boolean(project)} required /></label>
      </div>
      <label>描述<input name="description" defaultValue={project?.description} maxLength={240} /></label>
      <label>问答别名<input name="aliases" maxLength={320} placeholder="多个常用叫法用逗号分开"
        defaultValue={project?.aliases.filter(alias => alias !== project.id && alias !== project.name).join('，')} /></label>
      <label>项目颜色<select name="color" defaultValue={project?.color ?? 'violet'}>
        <option value="violet">紫色</option><option value="teal">青色</option><option value="amber">琥珀色</option>
      </select></label>
      {error && <p className="notice error" role="alert">{error}</p>}
      <footer><button type="button" className="button" disabled={pending} onClick={close}>取消</button>
        <button className="button primary" disabled={pending}><Plus size={15} /> 保存项目</button></footer>
    </form>
  </Modal>
}

function MemberEditor({ member, projects, close, done }: {
  member: TeamMember | null; projects: TeamProject[]; close: () => void; done: () => void
}) {
  const [grants, setGrants] = useState<Grants>(member?.grants ?? {})
  const [enabled, setEnabled] = useState(member?.enabled ?? true)
  const [invite, setInvite] = useState<{ code: string; expires_at: number } | null>(null)
  const [copied, setCopied] = useState(false)
  const [error, setError] = useState('')
  const [pending, setPending] = useState(false)
  const inviteUrl = invite ? location.origin + location.pathname + '#invite=' + encodeURIComponent(invite.code) : ''
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    setPending(true)
    setError('')
    try {
      if (member) {
        await api('/team/members/' + member.id, { enabled, grants })
      } else {
        setInvite(await api('/team/invitations', { label: form.get('label'), grants }))
      }
      done()
    } catch (err) { setError(errorText(err)) } finally { setPending(false) }
  }
  return <Modal label={member ? '设置成员权限' : invite ? '邀请码已生成' : '邀请成员'} close={() => { if (!pending) close() }}>
    {invite ? <div className="publish-form">
      <p className="form-hint">链接仅可激活一次，有效期至 {formatDate(new Date(invite.expires_at * 1000).toISOString())}。</p>
      <label>邀请码<input readOnly value={invite.code} onFocus={event => event.target.select()} /></label>
      <label>激活链接<input readOnly value={inviteUrl} onFocus={event => event.target.select()} /></label>
      <footer><button className="button" onClick={async () => {
        try { await navigator.clipboard.writeText(inviteUrl); setCopied(true) }
        catch { setError('请选中激活链接后手动复制。') }
      }}><Copy size={15} /> {copied ? '已复制' : '复制激活链接'}</button>
        <button className="button primary" onClick={close}>完成</button></footer>
      {error && <p className="notice error" role="alert">{error}</p>}
    </div> : <form className="publish-form" onSubmit={submit}>
      {member ? <><strong>{member.name}</strong><label className="checkbox-label">
        <input type="checkbox" checked={enabled} onChange={event => setEnabled(event.target.checked)} /> 允许账号登录</label></>
        : <label>邀请备注<input name="label" minLength={2} maxLength={100} placeholder="方便管理员识别这条邀请" required /></label>}
      <div className="grant-editor"><strong>项目权限</strong>
        {projects.map(project => <label key={project.id}>
          <span><ProjectIcon name={project.name} color={project.color} /> {project.name}</span>
          <select aria-label={project.name + '权限'} value={grants[project.id] ?? ''}
            onChange={event => {
              const value = event.target.value as '' | 'reader' | 'editor'
              const next = { ...grants }
              if (value) next[project.id] = value
              else delete next[project.id]
              setGrants(next)
            }}>
            <option value="">无权限</option><option value="reader">只读与提问</option><option value="editor">编辑与发布</option>
          </select>
        </label>)}
        {!projects.length && <p className="muted form-hint">先邀请账号也可以。项目创建后可补授权。</p>}
      </div>
      {error && <p className="notice error" role="alert">{error}</p>}
      <footer><button type="button" className="button" disabled={pending} onClick={close}>取消</button>
        <button className="button primary" disabled={pending}>{member ? '保存权限' : '生成邀请'}</button></footer>
    </form>}
  </Modal>
}
