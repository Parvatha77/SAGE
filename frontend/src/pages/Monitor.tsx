import { useEffect, useState } from "react"
import { getCases, getCase, startDemoRun } from "../api/client"
import type { CaseListItem, CaseDetail } from "../api/types"

interface MonitorProps {
  onCopilot: (context: string) => void
}

export function Monitor({ onCopilot }: MonitorProps) {
  const [cases, setCases] = useState<CaseListItem[]>([])
  const [selected, setSelected] = useState<CaseDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState("all")
  const [runningDemo, setRunningDemo] = useState(false)

  useEffect(() => {
    setLoading(true)
    // Map filter to category for backend
    const filterMap: Record<string, string | undefined> = {
      "all": undefined,
      "demo": "demo",
      "Health": "Health",
      "Education": "Education",
      "Psychology": "Psychology",
      "Education-Technology": "Education-Technology",
      "Mental-Health": "Mental-Health",
      "Evidence-Based-Policy": "Evidence-Based-Policy",
    }
    getCases({ category: filterMap[filter] })
      .then(setCases)
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [filter])

  function selectCase(id: string) {
    getCase(id)
      .then(setSelected)
      .catch(console.error)
  }

  async function handleStartDiscovery() {
    setRunningDemo(true)
    // Use current filter if set, otherwise "demo"
    const category = filter !== "all" && filter !== "demo" ? filter : "demo"
    try {
      const run = await startDemoRun(category)
      console.log("Demo run started:", run)

      // Stream SSE events using fetch
      const response = await fetch(`http://localhost:8000/demo/run/${run.run_id}/stream`)
      if (!response.body) throw new Error("No response body")

      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ""

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split("\n")
        buffer = lines[lines.length - 1]

        for (let i = 0; i < lines.length - 1; i++) {
          const line = lines[i].trim()
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6))
              console.log("Demo event:", data)

              if (data.type === "done") {
                console.log("Demo completed, refreshing cases...")
                // Refresh cases list
                await new Promise(r => setTimeout(r, 500))
                setFilter("demo")
                getCases({ category: "demo" }).then(setCases).catch(console.error)
                setRunningDemo(false)
              }
            } catch (e) {
              console.error("SSE parse error:", e)
            }
          }
        }
      }

      setRunningDemo(false)
    } catch (err) {
      console.error("Demo run error:", err)
      setRunningDemo(false)
    }
  }

  function handleCopilotQuestion(caseId: string) {
    onCopilot(caseId)
  }

  const open = cases.filter((c) => c.state === "open").length
  const high = cases.filter((c) => c.priority_score && c.priority_score >= 70).length

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Use case 01 / Evidence currency</div>
          <h1>Evidence Monitor</h1>
          <p className="subtitle">Discover new studies and notices, compare structured claims, and route evidence-backed cases to review.</p>
        </div>
        <button
          className="btn primary"
          onClick={handleStartDiscovery}
          disabled={runningDemo}
          style={{ opacity: runningDemo ? 0.6 : 1, cursor: runningDemo ? "not-allowed" : "pointer" }}
        >
          {runningDemo ? "⊙ Running..." : "▷ Start live discovery"}
        </button>
      </div>

      <div className="grid kpis">
        <div className="card kpi">
          <div className="kpi-top">Open cases<span className="kpi-icon">⌕</span></div>
          <div className="kpi-value">{open}</div>
          <div className="kpi-foot">Awaiting decision</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top">High priority<span className="kpi-icon">◷</span></div>
          <div className="kpi-value">{high}</div>
          <div className="kpi-foot">Score ≥ 70%</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top">Total cases<span className="kpi-icon">▤</span></div>
          <div className="kpi-value">{cases.length}</div>
          <div className="kpi-foot">Pipeline output</div>
        </div>
        <div className="card kpi">
          <div className="kpi-top">Categories<span className="kpi-icon">▥</span></div>
          <div className="kpi-value">5</div>
          <div className="kpi-foot">Demo domains</div>
        </div>
      </div>

      <div className="grid two-col">
        <div className="card">
          <div className="card-head">
            <div><h2>Case inbox</h2><p>Select a case to inspect evidence and compare research findings.</p></div>
            <span className="badge gray">Real + demo data</span>
          </div>
          <div className="card-body">
            <div className="filter-row" style={{ marginBottom: 14 }}>
              <select value={filter} onChange={(e) => setFilter(e.target.value)}>
                <option value="all">All cases</option>
                <option value="Education">📚 Education</option>
                <option value="MentalHealth">🧠 Mental Health</option>
                <option value="Science">🔬 Science & Research</option>
              </select>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Case / Claim</th>
                    <th>Label</th>
                    <th>Confidence</th>
                    <th>Status</th>
                  </tr>
                </thead>
                <tbody>
                  {cases.slice(0, 10).map((c) => (
                    <tr key={c.id} onClick={() => selectCase(c.id)} style={{ cursor: "pointer" }}>
                      <td><div className="table-title">{c.id}</div></td>
                      <td><span className="badge">{c.label}</span></td>
                      <td>{c.confidence || "—"}</td>
                      <td><span className="badge gray">{c.state}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        {selected && (
          <div className="grid" style={{ gap: 16 }}>
            <div className="card">
              <div className="card-head">
                <div><h2>Case details</h2><p>{selected.label}</p></div>
                {selected.needs_human_attention && <span className="badge amber">Needs attention</span>}
              </div>
              <div className="card-body">
                <div className="paper-card" style={{ marginBottom: 10 }}>
                  <div className="paper-label">ANCHOR CLAIM</div>
                  <div className="paper-title">{selected.anchor_claim?.paper_title || "Paper A"}</div>
                  <div className="quote">{selected.anchor_claim?.claim_text}</div>
                  <div className="meta-line"><span>DOI: {selected.anchor_claim?.paper_id}</span></div>
                </div>
                <div className="paper-card">
                  <div className="paper-label">NEW EVIDENCE</div>
                  <div className="paper-title">{selected.new_claim?.paper_title || "Paper B"}</div>
                  <div className="quote">{selected.new_claim?.claim_text}</div>
                  <div className="meta-line"><span>DOI: {selected.new_claim?.paper_id}</span></div>
                </div>
                <button
                  className="btn primary"
                  style={{ width: "100%", marginTop: 12 }}
                  onClick={() => handleCopilotQuestion(selected.id)}
                >
                  ✧ Ask Copilot about this case
                </button>
              </div>
            </div>

            <div className="card">
              <div className="card-head"><div><h2>AI briefing</h2><p>Source-grounded summary</p></div></div>
              <div className="card-body">
                <p style={{ fontSize: 12, lineHeight: 1.6, color: "var(--muted)" }}>{selected.rationale || "Analysis pending."}</p>
                {selected.skeptic_verdict && (
                  <div style={{ marginTop: 12, padding: 10, background: "var(--surface-soft)", borderRadius: 6, fontSize: 11 }}>
                    <strong>Skeptic review:</strong> {selected.skeptic_verdict}
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
