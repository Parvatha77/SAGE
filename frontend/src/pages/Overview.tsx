import { useEffect, useState } from "react"
import { getStats } from "../api/client"

export function Overview() {
  const [stats, setStats] = useState({ total_cases: 0, by_label: {}, by_state: {} })
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getStats()
      .then(setStats)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Research intelligence / Overview</div>
          <h1>Evidence Command Center</h1>
          <p className="subtitle">A consolidated view of research signals, content integrity and opportunities to translate evidence into practice.</p>
        </div>
        <button className="btn primary">▷ &nbsp; Run discovery</button>
      </div>

      <div className="grid kpis">
        <div className="card kpi">
          <div className="kpi-top"><span>Cases under review</span><span className="kpi-icon">⌕</span></div>
          <div className="kpi-value">{stats.by_state?.open ?? 0}</div>
          <div className="kpi-foot">Across all domains</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top"><span>Skeptic reviewed</span><span className="kpi-icon">✓</span></div>
          <div className="kpi-value">{stats.total_cases}</div>
          <div className="kpi-foot">Quality-checked</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top"><span>Evidence matches</span><span className="kpi-icon">◎</span></div>
          <div className="kpi-value">{Object.values(stats.by_label || {}).reduce((a: number, b: any) => a + b, 0)}</div>
          <div className="kpi-foot">Paired claims</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top"><span>Live pipeline ready</span><span className="kpi-icon">▷</span></div>
          <div className="kpi-value">7</div>
          <div className="kpi-foot">Stages online</div>
        </div>
      </div>

      <div className="workspace-status">
        <div className="workspace-status-copy">
          <div className="workspace-status-mark">i</div>
          <div>
            <strong>Demo workspace · Real evidence records</strong>
            <p>Cases include curated demo data across 5 domains (Health, Education, Psychology, Criminal Justice, Economics) plus real pipeline output from 1000+ papers.</p>
          </div>
        </div>
        <div className="workspace-status-actions">
          <button className="btn small">Inspect a case</button>
          <button className="btn small">View live demo</button>
        </div>
      </div>
    </>
  )
}
