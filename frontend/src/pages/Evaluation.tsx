export function Evaluation() {
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Trust, quality and governance</div>
          <h1>Evaluation & Audit</h1>
          <p className="subtitle">Monitor pipeline performance, false positives, reviewer feedback and traceable agent actions.</p>
        </div>
        <span className="badge gray">Metrics and logs</span>
      </div>

      <div className="grid kpis">
        <div className="card kpi">
          <div className="kpi-top">Pipeline runs<span className="kpi-icon">▷</span></div>
          <div className="kpi-value">12</div>
          <div className="kpi-foot">This session</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top">Cases created<span className="kpi-icon">✓</span></div>
          <div className="kpi-value">976</div>
          <div className="kpi-foot">From 1,064 papers</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top">Skeptic reviewed<span className="kpi-icon">◎</span></div>
          <div className="kpi-value">508</div>
          <div className="kpi-foot">Quality checked</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top">Human decisions<span className="kpi-icon">▤</span></div>
          <div className="kpi-value">22</div>
          <div className="kpi-foot">Cases reviewed</div>
        </div>
      </div>

      <div className="grid two-col">
        <div className="card">
          <div className="card-head">
            <div><h2>Quality gates</h2><p>Before cases reach human review</p></div>
          </div>
          <div className="card-body">
            <div className="signal-list">
              {[
                ["Exact source match", "Every extracted claim links back to source passage"],
                ["Skeptic review", "All high-confidence cases get adversarial QA"],
                ["Human approval gates", "No external outreach without authorization"],
                ["Evidence grounding", "All briefs cite specific papers and quotes"],
              ].map((item, i) => (
                <div key={i} className="signal">
                  <div className="signal-icon">✓</div>
                  <div className="signal-copy">
                    <h3>{item[0]}</h3>
                    <p>{item[1]}</p>
                  </div>
                  <span className="badge green">Required</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-head">
            <div><h2>Recent audit events</h2><p>Actions in this session</p></div>
          </div>
          <div className="card-body">
            <div className="signal-list">
              {[
                ["Pipeline initialized", "Demo data loaded · 976 cases"],
                ["Demo cases inserted", "25 curated cases across 5 domains"],
                ["Backend verified", "API endpoints responding"],
                ["Frontend rebuilt", "New UI deployed"],
                ["CORS configured", "Port 5174 connected"],
              ].map((item, i) => (
                <div key={i} className="signal">
                  <div className="signal-icon">·</div>
                  <div className="signal-copy">
                    <h3>{item[0]}</h3>
                    <p style={{ fontSize: 11, color: "var(--muted)", margin: "4px 0 0" }}>{item[1]}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </>
  )
}
