import { useState } from 'react'
import {
  ChartNoAxesCombined, Check, Download, FlaskConical, LoaderCircle, Play, X,
} from 'lucide-react'
import { api, errorText } from './api'
import type { Metrics, Report } from './api'
import { Blank } from './ui'

const measures: Array<{ title: string; numerator: keyof Metrics; denominator: keyof Metrics }> = [
  { title: '用例通过率', numerator: 'passed', denominator: 'total' },
  { title: '目标证据召回', numerator: 'gold_hits', denominator: 'gold_total' },
  { title: '放行结论正确率', numerator: 'correct_decisions', denominator: 'decision_total' },
  { title: '正确拒答率', numerator: 'correct_abstentions', denominator: 'abstention_total' },
]

export function Benchmark() {
  const [report, setReport] = useState<Report | null>(null)
  const [running, setRunning] = useState(false)
  const [diffOnly, setDiffOnly] = useState(false)
  const [error, setError] = useState('')

  async function evaluate() {
    setRunning(true)
    setError('')
    try { setReport(await api<Report>('/benchmark', {})) }
    catch (err) { setError(errorText(err)) }
    finally { setRunning(false) }
  }

  function download() {
    if (!report) return
    const url = URL.createObjectURL(new Blob([JSON.stringify(report, null, 2) + '\n'],
      { type: 'application/json' }))
    const link = document.createElement('a')
    link.href = url
    link.download = 'scopebrief-evaluation.json'
    link.click()
    setTimeout(() => URL.revokeObjectURL(url), 1000)
  }

  return <div className="wide-content">
    <div className="page-heading">
      <div><div className="run-label"><FlaskConical size={16} /> 质量验证</div><h1>回归评测</h1>
        <p>在独立的合成语料上复跑 BM25 基线与 Harness，逐题核对结果。</p></div>
      <div className="page-actions">
        {report && <button className="button" onClick={download}><Download size={16} /> 导出 JSON</button>}
        <button className="button primary" disabled={running} onClick={evaluate}>
          {running ? <LoaderCircle size={16} className="spin" /> : <Play size={16} />}
          {running ? '正在评测…' : report ? '重新运行' : '运行评测'}
        </button>
      </div>
    </div>
    {error && <div className="notice error" role="alert">{error}</div>}
    {!report ? <div className="surface">
      <Blank icon={<ChartNoAxesCombined size={25} />} title={running ? '正在复跑固定评测集' : '运行一次可复现的对照评测'}
        detail="评测覆盖版本时效、跨项目问答、找不到证据时的拒答及项目权限。" />
    </div> : <>
      <div className="metrics-head">
        <span className="code-label">{report.dataset} · {report.cases.length} 条 · 原文摘录</span>
        <div className="chart-legend"><span><i /> BM25 基线</span><span><i /> Harness</span></div>
      </div>
      <div className="metrics-grid">
        {measures.map(({ title, numerator, denominator }) => <article className="surface metric" key={title}>
          <h2>{title}</h2>
          {(['baseline', 'harness'] as const).map(strategy => {
            const metrics = report.metrics[strategy]
            const value = metrics[numerator]
            const total = metrics[denominator]
            const ratio = total ? value / total : 0
            return <div className={'meter-row ' + strategy} key={strategy}>
              <progress aria-label={title + ' · ' + (strategy === 'baseline' ? 'BM25 基线' : 'Harness')} value={ratio} max={1} />
              <span title={Math.round(ratio * 100) + '%'}>{value}/{total}</span>
            </div>
          })}
        </article>)}
      </div>
      <div className="metric-foot surface">
        <span>历史版本引文 <strong>{report.metrics.baseline.stale_citations} → {report.metrics.harness.stale_citations}</strong></span>
        <span>越权用例 <strong>{report.metrics.baseline.leak_cases} → {report.metrics.harness.leak_cases}</strong></span>
        <span>Harness P95 <strong>{report.metrics.harness.p95_ms} ms</strong></span>
      </div>
      <section className="surface case-card">
        <header><h2>用例明细</h2>
          <label className="checkbox-label"><input type="checkbox" checked={diffOnly}
            onChange={event => setDiffOnly(event.target.checked)} /> 只看结果差异</label></header>
        <div className="table-scroll"><table>
          <thead><tr><th>用例</th><th>覆盖项</th><th>BM25 基线</th><th>Harness</th></tr></thead>
          <tbody>{report.cases.filter(row => !diffOnly || row.harness.pass !== row.baseline.pass)
            .map(row => <tr key={row.id}>
              <td><span className="case-id">{row.id}</span>{row.title}</td><td className="muted">{row.group}</td>
              {(['baseline', 'harness'] as const).map(strategy => <td key={strategy}>
                {row[strategy].pass ? <span className="result-pass"><Check size={15} /> 通过</span>
                  : <span className="result-fail"><X size={14} /> {row[strategy].failures.join(' · ')}</span>}
              </td>)}
            </tr>)}</tbody>
        </table></div>
      </section>
    </>}
  </div>
}
