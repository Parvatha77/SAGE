import { useEffect, useState } from "react"

const API = "http://localhost:8000"

// ── Types ──────────────────────────────────────────────────────────────────

interface Need {
  id: string
  title: string
  state: string
  is_example: boolean
  need_text?: string
  audience?: string
  jurisdiction?: string
  deadline?: string
}

interface Match {
  id: string
  claim_text: string
  source_sentence: string
  paper_title: string
  paper_year: number
  fit_score: number
  included: boolean
  currency_status: string
  currency_note: string
  context_fit_level: string
}

interface Brief {
  text: string
  status: string
  version: number
}

interface Check {
  check_name: string
  passed: boolean
  detail: string
}

interface NeedDetail extends Need {
  matches: Match[]
  brief: Brief | null
  checks: Check[]
  readiness_score: number | null
  gap: { reason: string; idea_text: string } | null
  topic_keywords: string[]
}

// ── Helpers ────────────────────────────────────────────────────────────────

async function api<T>(path: string, opts?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, opts)
  if (!r.ok) throw new Error(await r.text())
  return r.json()
}

function VerdictCard({ score, checks, matches }: {
  score: number | null
  checks: Check[]
  matches: Match[]
}) {
  const challenged = matches.filter(m => ["retracted", "challenged"].includes(m.currency_status)).length
  const included = matches.filter(m => m.included)
  const goodCtx = included.filter(m => m.context_fit_level === "good").length

  let verdict = "Not enough data"
  let verdictColor = "var(--ink-muted)"
  let verdictBg = "var(--surface)"
  let verdictIcon = "○"

  if (score !== null) {
    if (challenged > 0) {
      verdict = "Not ready — evidence challenged"
      verdictColor = "#dc2626"
      verdictBg = "#fef2f2"
      verdictIcon = "✗"
    } else if (score >= 65 && goodCtx >= 1 && included.length >= 2) {
      verdict = "Ready to recommend"
      verdictColor = "#15803d"
      verdictBg = "#f0fdf4"
      verdictIcon = "✓"
    } else if (score >= 40) {
      verdict = "Promising — needs more evidence"
      verdictColor = "#b45309"
      verdictBg = "#fffbeb"
      verdictIcon = "◑"
    } else {
      verdict = "Evidence too limited to act on"
      verdictColor = "#6b7280"
      verdictBg = "#f9fafb"
      verdictIcon = "○"
    }
  }

  return (
    <div style={{
      background: verdictBg,
      border: `1.5px solid ${verdictColor}`,
      borderRadius: 10,
      padding: "1rem 1.2rem",
      marginBottom: "1.2rem",
    }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <span style={{ fontSize: "1.3rem", color: verdictColor }}>{verdictIcon}</span>
        <strong style={{ fontSize: "1.05rem", color: verdictColor }}>{verdict}</strong>
        {score !== null && (
          <span style={{
            marginLeft: "auto", fontSize: "0.8rem", color: verdictColor,
            background: verdictBg, padding: "2px 8px", borderRadius: 20,
            border: `1px solid ${verdictColor}`,
          }}>
            Readiness {score}/100
          </span>
        )}
      </div>
      <div style={{ display: "flex", gap: 16, flexWrap: "wrap" as const, fontSize: "0.82rem", color: "var(--ink-muted)" }}>
        <span>📄 {included.length} claims included</span>
        <span>⚠️ {challenged} challenged</span>
        <span>🌍 {goodCtx} good context fit</span>
        <span>✅ {checks.filter(c => c.passed).length}/{checks.length} quality checks</span>
      </div>
    </div>
  )
}

function MatchRow({ m }: { m: Match }) {
  const currColor = m.currency_status === "current" ? "#15803d"
    : m.currency_status === "challenged" ? "#dc2626"
    : m.currency_status === "retracted" ? "#dc2626"
    : "var(--ink-muted)"

  return (
    <div style={{
      padding: "0.7rem 0.9rem",
      borderBottom: "1px solid var(--border)",
      opacity: m.included ? 1 : 0.5,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 4 }}>
        <span style={{ fontSize: "0.78rem", color: "var(--ink-muted)" }}>
          {m.paper_title?.slice(0, 60)}{m.paper_title?.length > 60 ? "…" : ""} · {m.paper_year}
        </span>
        <div style={{ display: "flex", gap: 6, flexShrink: 0, marginLeft: 8 }}>
          <span style={{ fontSize: "0.72rem", color: currColor, fontWeight: 600 }}>
            {m.currency_status ?? "unknown"}
          </span>
          <span style={{ fontSize: "0.72rem", color: "var(--ink-muted)" }}>
            fit {Math.round((m.fit_score ?? 0) * 100)}%
          </span>
        </div>
      </div>
      <p style={{ margin: 0, fontSize: "0.84rem", lineHeight: 1.5 }}>
        "{m.source_sentence?.slice(0, 160)}{(m.source_sentence?.length ?? 0) > 160 ? "…" : ""}"
      </p>
      {m.currency_note && (
        <p style={{ margin: "4px 0 0", fontSize: "0.75rem", color: currColor }}>{m.currency_note}</p>
      )}
    </div>
  )
}

function NeedDetail({ need }: { need: Need }) {
  const [detail, setDetail] = useState<NeedDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [running, setRunning] = useState(false)
  const [runId, setRunId] = useState<string | null>(null)
  const [approving, setApproving] = useState(false)
  const [approver, setApprover] = useState("")
  const [copilotQ, setCopilotQ] = useState("")
  const [copilotA, setCopilotA] = useState("")
  const [copilotLoading, setCopilotLoading] = useState(false)
  const [tab, setTab] = useState<"overview" | "matches" | "brief" | "checks">("overview")

  useEffect(() => {
    setLoading(true)
    api<NeedDetail>(`/needs/${need.id}`)
      .then(setDetail)
      .finally(() => setLoading(false))
  }, [need.id, runId])

  async function handleRun() {
    setRunning(true)
    try {
      const r = await api<{ run_id: string }>(`/needs/${need.id}/run`, { method: "POST" })
      setRunId(r.run_id)
      // poll until done
      const poll = setInterval(async () => {
        const s = await api<{ status: string }>(`/needs/runs/${r.run_id}`)
        if (s.status !== "running") {
          clearInterval(poll)
          setRunning(false)
          const d = await api<NeedDetail>(`/needs/${need.id}`)
          setDetail(d)
        }
      }, 2000)
    } catch {
      setRunning(false)
    }
  }

  async function handleApprove() {
    if (!approver) return
    setApproving(true)
    try {
      const d = await api<NeedDetail>(`/needs/${need.id}/approve`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ approver, reason: "Approved via UI" }),
      })
      setDetail(d)
    } finally {
      setApproving(false)
    }
  }

  async function handleCopilot(preset?: string) {
    setCopilotLoading(true)
    setCopilotA("")
    try {
      const r = await api<{ answer: string }>(`/needs/${need.id}/copilot`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(preset ? { preset } : { question: copilotQ }),
      })
      setCopilotA(r.answer)
    } finally {
      setCopilotLoading(false)
    }
  }

  if (loading) return <article className="panel"><div className="empty">Loading…</div></article>
  if (!detail) return <article className="panel"><div className="empty">Failed to load.</div></article>

  const canRun = !["running", "awaiting_approval", "approved", "submitted", "outcome_recorded"].includes(detail.state)
  const needsApproval = detail.state === "awaiting_approval"
  const included = detail.matches.filter(m => m.included)

  return (
    <article className="panel" style={{ overflowY: "auto" }}>
      {/* Header */}
      <div className="head">
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 4 }}>
          <span className="chip plain">{detail.state.replace(/_/g, " ")}</span>
          {detail.is_example && <span className="chip neutral">Example</span>}
          {detail.jurisdiction && <span className="chip neutral">{detail.jurisdiction}</span>}
        </div>
        <h2 style={{ margin: "4px 0 6px", fontSize: "1.1rem" }}>{detail.title}</h2>
        {detail.need_text && (
          <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--ink-muted)" }}>{detail.need_text}</p>
        )}
        {detail.audience && (
          <p style={{ margin: "4px 0 0", fontSize: "0.78rem", color: "var(--ink-muted)" }}>
            Audience: {detail.audience}
          </p>
        )}
      </div>

      {/* Verdict card — always shown once run */}
      {detail.matches.length > 0 && (
        <div style={{ padding: "0 1rem" }}>
          <VerdictCard
            score={detail.readiness_score}
            checks={detail.checks}
            matches={detail.matches}
          />
        </div>
      )}

      {/* Run button */}
      {canRun && (
        <div style={{ padding: "0 1rem 1rem" }}>
          <button
            className="btn primary"
            onClick={handleRun}
            disabled={running}
            style={{ background: "var(--accent)" }}
          >
            {running ? "⏳ Running evidence assessment…" : "▶ Run Evidence-to-Impact Assessment"}
          </button>
          <p style={{ fontSize: "0.78rem", color: "var(--ink-muted)", margin: "6px 0 0" }}>
            Searches all {detail.topic_keywords?.join(", ")} papers, checks currency, generates policy brief.
          </p>
        </div>
      )}

      {/* Approval gate */}
      {needsApproval && (
        <div style={{ padding: "0 1rem 1rem" }}>
          <div style={{
            background: "#fffbeb", border: "1.5px solid #f59e0b",
            borderRadius: 8, padding: "0.8rem 1rem",
          }}>
            <strong style={{ color: "#b45309" }}>Awaiting approval</strong>
            <p style={{ fontSize: "0.82rem", margin: "4px 0 8px", color: "#92400e" }}>
              Review the brief and evidence below, then approve to proceed to submission.
            </p>
            <div style={{ display: "flex", gap: 8 }}>
              <input
                value={approver}
                onChange={e => setApprover(e.target.value)}
                placeholder="Your name"
                style={{
                  flex: 1, padding: "5px 10px", borderRadius: 5,
                  border: "1px solid #d1d5db", fontSize: "0.85rem",
                }}
              />
              <button
                onClick={handleApprove}
                disabled={approving || !approver}
                style={{
                  background: "#15803d", color: "#fff", border: "none",
                  borderRadius: 5, padding: "5px 14px", cursor: "pointer", fontSize: "0.85rem",
                }}
              >
                {approving ? "Approving…" : "Approve & send"}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Tabs */}
      {detail.matches.length > 0 && (
        <>
          <div style={{ display: "flex", borderBottom: "1px solid var(--border)", padding: "0 1rem" }}>
            {(["overview", "matches", "brief", "checks"] as const).map(t => (
              <button
                key={t}
                onClick={() => setTab(t)}
                style={{
                  background: "none", border: "none", padding: "8px 12px",
                  fontSize: "0.82rem", cursor: "pointer",
                  color: tab === t ? "var(--accent)" : "var(--ink-muted)",
                  borderBottom: tab === t ? "2px solid var(--accent)" : "2px solid transparent",
                  textTransform: "capitalize",
                }}
              >
                {t === "matches" ? `Evidence (${included.length} included)` : t}
              </button>
            ))}
          </div>

          {/* Overview tab */}
          {tab === "overview" && (
            <div style={{ padding: "1rem" }}>
              <h4 style={{ margin: "0 0 8px", fontSize: "0.9rem" }}>AI Copilot</h4>
              <div style={{ display: "flex", flexWrap: "wrap" as const, gap: 6, marginBottom: 10 }}>
                {[
                  ["strongest_evidence", "Strongest evidence"],
                  ["explain_in_3_lines", "Summarise in 3 lines"],
                  ["questions_to_expect", "Policymaker questions"],
                  ["risks_and_limits", "Risks & limits"],
                ].map(([preset, label]) => (
                  <button
                    key={preset}
                    onClick={() => handleCopilot(preset)}
                    disabled={copilotLoading}
                    style={{
                      background: "var(--surface)", border: "1px solid var(--border)",
                      borderRadius: 20, padding: "4px 12px", fontSize: "0.78rem",
                      cursor: "pointer", color: "var(--ink)",
                    }}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div style={{ display: "flex", gap: 6, marginBottom: 10 }}>
                <input
                  value={copilotQ}
                  onChange={e => setCopilotQ(e.target.value)}
                  onKeyDown={e => e.key === "Enter" && copilotQ && handleCopilot()}
                  placeholder="Ask about this evidence…"
                  style={{
                    flex: 1, padding: "5px 10px", borderRadius: 5,
                    border: "1px solid var(--border)", fontSize: "0.82rem",
                    background: "var(--surface)", color: "var(--ink)",
                  }}
                />
                <button
                  onClick={() => handleCopilot()}
                  disabled={!copilotQ || copilotLoading}
                  style={{
                    background: "var(--accent)", color: "#fff", border: "none",
                    borderRadius: 5, padding: "5px 12px", cursor: "pointer", fontSize: "0.82rem",
                  }}
                >
                  Ask
                </button>
              </div>
              {copilotLoading && <p style={{ fontSize: "0.82rem", color: "var(--ink-muted)" }}>Thinking…</p>}
              {copilotA && (
                <div style={{
                  background: "var(--surface)", border: "1px solid var(--border)",
                  borderRadius: 8, padding: "0.8rem", fontSize: "0.85rem",
                  lineHeight: 1.6, whiteSpace: "pre-wrap",
                }}>
                  {copilotA}
                </div>
              )}

              {detail.gap && (
                <div style={{
                  marginTop: "1rem", background: "#fffbeb",
                  border: "1px solid #f59e0b", borderRadius: 8, padding: "0.8rem",
                }}>
                  <strong style={{ color: "#b45309", fontSize: "0.85rem" }}>Evidence gap detected</strong>
                  <p style={{ margin: "4px 0 0", fontSize: "0.82rem", color: "#92400e" }}>{detail.gap.reason}</p>
                  {detail.gap.idea_text && (
                    <p style={{ margin: "4px 0 0", fontSize: "0.8rem", color: "#b45309" }}>
                      Suggestion: {detail.gap.idea_text}
                    </p>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Evidence matches tab */}
          {tab === "matches" && (
            <div>
              {detail.matches.length === 0
                ? <div className="empty">No matches yet — run assessment first.</div>
                : detail.matches.map(m => <MatchRow key={m.id} m={m} />)
              }
            </div>
          )}

          {/* Brief tab */}
          {tab === "brief" && (
            <div style={{ padding: "1rem" }}>
              {detail.brief
                ? (
                  <>
                    <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
                      <span style={{ fontSize: "0.8rem", color: "var(--ink-muted)" }}>
                        Version {detail.brief.version} · {detail.brief.status}
                      </span>
                    </div>
                    <div style={{
                      background: "var(--surface)", border: "1px solid var(--border)",
                      borderRadius: 8, padding: "1rem", fontSize: "0.88rem",
                      lineHeight: 1.7, whiteSpace: "pre-wrap",
                    }}>
                      {detail.brief.text}
                    </div>
                  </>
                )
                : <div className="empty">Brief not yet generated. Run the assessment first.</div>
              }
            </div>
          )}

          {/* Checks tab */}
          {tab === "checks" && (
            <div style={{ padding: "1rem" }}>
              {detail.checks.length === 0
                ? <div className="empty">No quality checks run yet.</div>
                : detail.checks.map((c, i) => (
                  <div key={i} style={{
                    display: "flex", alignItems: "flex-start", gap: 10,
                    padding: "0.5rem 0", borderBottom: "1px solid var(--border)",
                  }}>
                    <span style={{ fontSize: "1rem", color: c.passed ? "#15803d" : "#dc2626", flexShrink: 0 }}>
                      {c.passed ? "✓" : "✗"}
                    </span>
                    <div>
                      <div style={{ fontSize: "0.85rem", fontWeight: 600 }}>
                        {c.check_name.replace(/_/g, " ")}
                      </div>
                      <div style={{ fontSize: "0.78rem", color: "var(--ink-muted)" }}>{c.detail}</div>
                    </div>
                  </div>
                ))
              }
            </div>
          )}
        </>
      )}
    </article>
  )
}

// ── Main page ──────────────────────────────────────────────────────────────

export function ImpactPage() {
  const [needs, setNeeds] = useState<Need[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)
  const [importing, setImporting] = useState(false)

  async function load() {
    setLoading(true)
    try {
      const data = await api<Need[]>("/needs")
      setNeeds(data)
      if (data.length > 0 && !selectedId) setSelectedId(data[0].id)
    } catch {
      setErr("Failed to load needs.")
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  async function importNeeds() {
    setImporting(true)
    try {
      await api("/needs/import", { method: "POST" })
      await load()
    } finally {
      setImporting(false)
    }
  }

  const selected = needs.find(n => n.id === selectedId)
  const open = needs.filter(n => !["approved", "submitted", "outcome_recorded"].includes(n.state)).length
  const approved = needs.filter(n => n.state === "approved").length

  return (
    <>
      <div className="stats">
        <span><b>{needs.length}</b> policy needs</span>
        <span><b>{open}</b> in progress</span>
        <span><b>{approved}</b> approved</span>
      </div>
      <div className="layout">
        {/* Left panel — needs list */}
        <div className="panel">
          <div className="subnav" style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span className="small" style={{ padding: "6px 10px" }}>Policy need radar</span>
            {needs.length === 0 && !loading && (
              <button
                onClick={importNeeds}
                disabled={importing}
                style={{
                  background: "var(--accent)", color: "#fff", border: "none",
                  borderRadius: 5, padding: "4px 10px", fontSize: "0.75rem",
                  cursor: "pointer", margin: "4px",
                }}
              >
                {importing ? "Importing…" : "Load examples"}
              </button>
            )}
          </div>

          {loading && <div className="empty">Loading…</div>}
          {err && <div className="empty" style={{ color: "var(--crit)" }}>{err}</div>}
          {!loading && needs.length === 0 && !err && (
            <div className="empty" style={{ padding: "1rem", textAlign: "center" as const }}>
              <p style={{ marginBottom: 8 }}>No policy needs loaded yet.</p>
              <button
                onClick={importNeeds}
                disabled={importing}
                style={{
                  background: "var(--accent)", color: "#fff", border: "none",
                  borderRadius: 6, padding: "6px 16px", cursor: "pointer",
                }}
              >
                {importing ? "Loading…" : "Load example needs"}
              </button>
            </div>
          )}

          {needs.map(n => {
            const stateColor = n.state === "approved" ? "#15803d"
              : n.state === "awaiting_approval" ? "#b45309"
              : n.state === "gap" ? "#dc2626"
              : "var(--ink-muted)"
            return (
              <button
                key={n.id}
                className={`item ${n.id === selectedId ? "selected" : ""}`}
                onClick={() => setSelectedId(n.id)}
              >
                <span className="item-title">{n.title}</span>
                <span className="row">
                  <span style={{ fontSize: "0.72rem", color: stateColor }}>
                    {n.state.replace(/_/g, " ")}
                  </span>
                  {n.is_example && <span className="chip neutral" style={{ fontSize: "0.68rem" }}>example</span>}
                </span>
              </button>
            )
          })}
        </div>

        {/* Right panel — detail */}
        {selected
          ? <NeedDetail key={selected.id} need={selected} />
          : <div className="panel"><div className="empty">Select a need to view its evidence assessment.</div></div>
        }
      </div>
    </>
  )
}
