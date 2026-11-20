import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { KeyRound, Waypoints } from 'lucide-react'
import { api, errorText } from './api'
import type { Session } from './api'

export function TeamLogin({ onLogin }: { onLogin: (value: Session) => void }) {
  const [invite, setInvite] = useState(() => new URLSearchParams(location.hash.slice(1)).get('invite') ?? '')
  const [activate, setActivate] = useState(Boolean(invite))
  const [pending, setPending] = useState(false)
  const [error, setError] = useState('')
  useEffect(() => {
    if (new URLSearchParams(location.hash.slice(1)).has('invite')) {
      window.history.replaceState(null, '', location.pathname + location.search)
    }
  }, [])

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError('')
    setPending(true)
    const form = new FormData(event.currentTarget)
    const input = { username: form.get('username'), password: form.get('password') }
    try {
      onLogin(await api<Session>(activate ? '/auth/activate' : '/auth/login',
        activate ? { ...input, name: form.get('name'), code: invite } : input))
    } catch (err) { setError(errorText(err)) } finally { setPending(false) }
  }

  return <main className="loading login-page">
    <form className="surface login-form team-login" onSubmit={submit} key={String(activate)}>
      <span className="brand-mark"><Waypoints size={21} /></span>
      <h1>{activate ? '激活团队账号' : '登录 ScopeBrief'}</h1>
      {activate && <>
        <label>邀请码<input autoComplete="one-time-code" maxLength={80} required
          value={invite} onChange={event => setInvite(event.target.value)} /></label>
        <label>显示名称<input name="name" autoComplete="name" minLength={2} maxLength={60} required /></label>
      </>}
      <label>用户名<input name="username" autoComplete="username" autoCapitalize="off" maxLength={40}
        pattern={activate ? '[a-z0-9][a-z0-9._\\-]{2,39}' : undefined} required /></label>
      <label>密码<input name="password" type="password" minLength={activate ? 12 : 1} maxLength={128}
        required autoComplete={activate ? 'new-password' : 'current-password'} /></label>
      {activate && <p className="muted form-hint">至少 12 个字符。邀请码仅可使用一次。</p>}
      {error && <div className="notice error" role="alert">{error}</div>}
      <button className="button primary" disabled={pending}>{activate ? '激活账号' : '登录'}</button>
      <button className="text-button login-toggle" type="button" disabled={pending}
        onClick={() => { setActivate(!activate); setError('') }}>
        <KeyRound size={14} /> {activate ? '返回账号登录' : '我有邀请码'}
      </button>
    </form>
  </main>
}
