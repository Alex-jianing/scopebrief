import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { ScanText, X } from 'lucide-react'

export function BrandMark() {
  return <span className="brand-mark" aria-hidden="true"><ScanText size={20} strokeWidth={1.8} /></span>
}

export function AuthLayout({ children }: { children: ReactNode }) {
  return <main className="login-page">
    <div className="login-content">{children}</div>
    <div className="login-art" aria-hidden="true" />
  </main>
}

export function Modal({ label, close, drawer, children }: {
  label: string; close: () => void; drawer?: boolean; children: ReactNode
}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => {
    const dialog = ref.current
    const trigger = document.activeElement
    dialog?.showModal()
    return () => {
      dialog?.close()
      if (trigger instanceof HTMLElement && trigger.isConnected) trigger.focus({ preventScroll: true })
    }
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

export function ProjectIcon({ name, color }: { name: string; color: string }) {
  return <span aria-hidden="true" className={'project-icon ' + color}>{name[0]}</span>
}

export function Blank({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return <div className="blank-state"><span className="blank-icon">{icon}</span>
    <strong>{title}</strong><p>{detail}</p></div>
}
