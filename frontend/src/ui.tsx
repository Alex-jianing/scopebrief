import type { ReactNode } from 'react'
import { Activity, ClipboardList, GitBranch, Shield } from 'lucide-react'

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
