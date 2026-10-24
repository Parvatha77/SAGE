import { useEffect, useState } from "react"
import { getNeeds } from "../api/client"

interface ImpactProps {
  onCopilot: (context: string) => void
}

interface Need {
  id: string
  title: string
  state: string
  is_example: boolean
}

export function Impact({ onCopilot }: ImpactProps) {
  const [needs, setNeeds] = useState<Need[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    getNeeds()
      .then(setNeeds)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Use case 02 / Research translation</div>
          <h1>Real-World Impact Studio</h1>
          <p className="subtitle">Connect current, relevant evidence to policy and practice needs. Build a defensible brief, then track approval and engagement.</p>
        </div>
        <button className="btn primary">＋ Add a need</button>
      </div>

      <div className="grid kpis">
        <div className="card kpi">
          <div className="kpi-top">Open needs<span className="kpi-icon">◎</span></div>
          <div className="kpi-value">{needs.length}</div>
          <div className="kpi-foot">Policy questions</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top">Evidence matched<span className="kpi-icon">⌕</span></div>
          <div className="kpi-value">{needs.length * 4}</div>
          <div className="kpi-foot">Candidate claims</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top">Briefs ready<span className="kpi-icon">▤</span></div>
          <div className="kpi-value">{needs.filter(n => n.state === "awaiting_approval").length}</div>
          <div className="kpi-foot">Awaiting approval</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top">Tracked impacts<span className="kpi-icon">↗</span></div>
          <div className="kpi-value">{needs.filter(n => n.state === "outcome_recorded").length}</div>
          <div className="kpi-foot">Outcome follow-up</div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div><h2>Assessment pipeline</h2><p>From policy need to evidence brief</p></div>
        </div>
        <div className="card-body">
          <div className="timeline">
            {[
              ["Need identified", "Policy question submitted for assessment"],
              ["Evidence matched", "Relevant claims identified and screened"],
              ["Currency gate", "Recent research confirmed current"],
              ["Context fit", "Evidence matches population and setting"],
              ["Gap identified", "Missing evidence logged"],
              ["Brief drafted", "AI copilot generates policy brief"],
              ["Brief reviewed", "SAGE expert quality check"],
              ["Approval gate", "Human decision required before sharing"],
            ].map((stage, i) => (
              <div key={i} className="timeline-item">
                <div className="timeline-rail">
                  <div className="timeline-dot"></div>
                  {i < 7 && <div className="timeline-line"></div>}
                </div>
                <div>
                  <h3>{stage[0]}</h3>
                  <p>{stage[1]}</p>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {needs.length > 0 && (
        <div className="card">
          <div className="card-head">
            <div><h2>Active policy needs</h2><p>Research questions awaiting evidence briefs</p></div>
          </div>
          <div className="card-body">
            <div className="grid" style={{ gap: 12 }}>
              {needs.map((need) => (
                <div key={need.id} className="paper-card" style={{ padding: 12 }}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
                    <div>
                      <div className="paper-title">{need.title}</div>
                      <div style={{ fontSize: 12, color: "var(--muted)", marginTop: 4 }}>
                        {need.is_example ? "📌 Example" : "🎯 Active"} · State: {need.state}
                      </div>
                    </div>
                    <button
                      className="btn primary"
                      style={{ whiteSpace: "nowrap", marginLeft: 12 }}
                      onClick={() => onCopilot(need.id)}
                    >
                      Generate brief
                    </button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
