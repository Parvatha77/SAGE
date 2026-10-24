export function Outreach() {
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Communication workspace</div>
          <h1>Outreach Studio</h1>
          <p className="subtitle">Prepare evidence-led emails, expert-review requests and collaboration proposals. Drafting is separate from sending.</p>
        </div>
        <span className="badge amber">Approval required</span>
      </div>

      <div className="grid kpis">
        <div className="card kpi">
          <div className="kpi-top">Drafts prepared<span className="kpi-icon">✉</span></div>
          <div className="kpi-value">3</div>
          <div className="kpi-foot">Pending review</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top">Outreach history<span className="kpi-icon">↗</span></div>
          <div className="kpi-value">8</div>
          <div className="kpi-foot">Sent communications</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top">Collaboration open<span className="kpi-icon">◎</span></div>
          <div className="kpi-value">2</div>
          <div className="kpi-foot">Active discussions</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top">Approval required<span className="kpi-icon">◷</span></div>
          <div className="kpi-value">1</div>
          <div className="kpi-foot">Before sending</div>
        </div>
      </div>

      <div className="card">
        <div className="card-head">
          <div><h2>Message builder</h2><p>Draft communication from an opportunity or reviewed case</p></div>
        </div>
        <div className="card-body">
          <div className="grid three-col" style={{ gap: 12 }}>
            <div className="field">
              <label>Recipient organization</label>
              <input placeholder="Policy team / research group" />
            </div>
            <div className="field">
              <label>Email address</label>
              <input type="email" placeholder="name@organization.org" />
            </div>
            <div className="field">
              <label>Purpose</label>
              <select>
                <option>Share evidence and explore collaboration</option>
                <option>Request expert review</option>
                <option>Propose research partnership</option>
              </select>
            </div>
          </div>
          <div className="field">
            <label>Message context</label>
            <textarea placeholder="Summarize the evidence and why it matters..." />
          </div>
          <button className="btn primary">✧ Generate email draft</button>
        </div>
      </div>
    </>
  )
}
