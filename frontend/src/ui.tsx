import { useEffect, useRef } from 'react'
import type { ReactNode } from 'react'
import { Activity, ClipboardList, GitBranch, Shield, X } from 'lucide-react'

export function Modal({ label, close, drawer, children }: {
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

export function ProjectIcon({ name, color }: { name: string; color: string }) {
  return <span aria-hidden="true" className={'project-icon ' + color}>{name[0]}</span>
}

export function Blank({ icon, title, detail }: { icon: ReactNode; title: string; detail: string }) {
  return <div className="blank-state"><span className="blank-icon">{icon}</span>
    <strong>{title}</strong><p>{detail}</p></div>
}

export function WorkflowIllustration() {
  return <div className="workflow-art" aria-hidden="true">
    <span className="orbit orbit-one" /><span className="orbit orbit-two" />
    <div className="workflow-node node-in"><ClipboardList size={26} /></div>
    <div className="workflow-node node-core"><GitBranch size={36} /></div>
    <div className="workflow-node node-out"><Shield size={22} /></div>
    <div className="workflow-node node-audit"><Activity size={17} /></div>
  </div>
}
