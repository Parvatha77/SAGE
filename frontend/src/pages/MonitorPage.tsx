import { useEffect, useState } from "react"
import { getCases, getCase, postDecision } from "../api/client"
import type { CaseListItem, CaseDetail } from "../api/types"
import { LABEL_DISPLAY } from "../api/types"

/* ── helpers ── */
function labelChip(label: string) {
  const cls: Record<string, string> = {
    confirms: "good",
    extends: "info",
    differs_in_context: "neutral",
    possible_reproducibility_concern: "warn",
    retraction_impact: "crit",
    insufficient_information: "plain",
  }
  return <span className={`chip ${cls[label] ?? "plain"}`}>{LABEL_DISPLAY[label] ?? label}</span>
}

function priorityChip(score: number | null) {
  if (score == null || score < 40) return <span className="chip plain">Low priority</span>
  if (score < 70) return <span className="chip warn">Medium priority</span>
  return <span className="chip crit">High priority</span>
}

function confChip(conf: string | null) {
  if (!conf) return null
  return <span className="chip plain">Confidence: {conf}</span>
}

const ACTION_LABELS: Record<string, string> = {
  no_action: "No action needed",
  expert_review: "Request expert review",
  author_contact: "Draft author contact",
  flag_for_update: "Flag for update",
}

/* ── case list item ── */
function CaseItem({ c, selected, onClick }: { c: CaseListItem; selected: boolean; onClick: () => void }) {
  return (
    <button className={`item ${selected ? "selected" : ""}`} onClick={onClick}>
      <span className="mono">{c.id}</span>
      <span className="item-title">{c.label ? (LABEL_DISPLAY[c.label] ?? c.label) : "—"}</span>
      <span className="row">
        {labelChip(c.label)}
        {priorityChip(c.priority_score)}
        <span className={`chip ${c.state === "open" ? "plain" : "good"}`}>{c.state}</span>
      </span>
    </button>
  )
}

/* ── case detail ── */
function CaseDetailPanel({ id }: { id: string }) {
  const [detail, setDetail] = useState<CaseDetail | null>(null)
  const [loading, setLoading] = useState(true)
  const [pending, setPending] = useState<string | null>(null)
  const [reason, setReason] = useState("")
  const [decidedBy, setDecidedBy] = useState("editor@example.com")
  const [formErr, setFormErr] = useState("")
  const [saving, setSaving] = useState(false)
  const [toast, setToast] = useState("")

  useEffect(() => {
    setLoading(true)
    setDetail(null)
    setPending(null)
    setReason("")
    getCase(id).then(setDetail).finally(() => setLoading(false))
  }, [id])

  function showToast(msg: string) {
    setToast(msg)
    setTimeout(() => setToast(""), 3200)
  }

  async function confirm() {
    if (!reason.trim()) { setFormErr("Enter a reason before confirming."); return }
    if (!pending) return
    setSaving(true)
    setFormErr("")
    try {
      await postDecision(id, { action: pending, reason: reason.trim(), decided_by: decidedBy })
      showToast(ACTION_LABELS[pending] + " recorded.")
      // Reload case
      const updated = await getCase(id)
      setDetail(updated)
      setPending(null)
      setReason("")
    } catch {
      setFormErr("Failed to save decision.")
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <div className="panel"><div className="empty">Loading…</div></div>
  if (!detail) return <div className="panel"><div className="empty">Failed to load case.</div></div>

  const anchor = detail.anchor_claim
  const newClaim = detail.new_claim

  return (
    <article className="panel">
      {/* Head */}
      <div className="head">
        <span className="mono">{detail.id}</span>
        <h2>{anchor?.claim_text ?? detail.id}</h2>
        <div className="row">
          {labelChip(detail.label)}
          {priorityChip(detail.priority_score)}
          {confChip(detail.confidence)}
          {detail.needs_human_attention && <span className="chip warn">Needs attention</span>}
        </div>
        {detail.next_step && (
          <div className="suggest">
            <strong>Suggested next step.</strong> {detail.next_step}{" "}
            <span className="small">The system suggests. The editor decides.</span>
          </div>
        )}
      </div>

      {/* Evidence comparison */}
      {(anchor || newClaim) && (
        <div className="sec">
          <h3>How the evidence differs</h3>
          <div className="cmp">
            {anchor && (
              <div className="card">
                <div className="kind">Anchor claim</div>
                <div className="small">{anchor.paper_id}</div>
                <blockquote>{anchor.source_sentence}</blockquote>
                <div className="mono" style={{ marginTop: 6 }}>{anchor.paper_id}</div>
              </div>
            )}
            {newClaim && (
              <div className="card">
                <div className="kind">New claim</div>
                <div className="small">{newClaim.paper_id}</div>
                <blockquote>{newClaim.source_sentence}</blockquote>
                <div className="mono" style={{ marginTop: 6 }}>{newClaim.paper_id}</div>
              </div>
            )}
          </div>
          {detail.field_comparisons.length > 0 && (
            <div className="tw">
              <table>
                <thead>
                  <tr><th>Aspect</th><th>Anchor</th><th>New</th><th></th></tr>
                </thead>
                <tbody>
                  {detail.field_comparisons.map((fc) => (
                    <tr key={fc.field_name} className={fc.result === "differs" ? "diff-row" : ""}>
                      <td>{fc.field_name}</td>
                      <td>{fc.anchor_value ?? "—"}</td>
                      <td>{fc.new_value ?? "—"}</td>
                      <td>{fc.result === "differs" ? "Differs" : fc.result === "similar" ? "Similar" : "Unknown"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {/* Skeptic */}
      {(detail.skeptic_verdict || detail.skeptic_argument) && (
        <div className="sec">
          <div className="two">
            <div>
              <h3>Skeptic agent</h3>
              {detail.skeptic_argument && <p style={{ margin: "0 0 8px" }}>{detail.skeptic_argument}</p>}
              {detail.skeptic_verdict && <span className="chip neutral">{detail.skeptic_verdict}</span>}
            </div>
            <div>
              <h3>Integrity check</h3>
              {detail.has_integrity_notice
                ? <span className="chip crit">Notice confirmed</span>
                : <span className="chip good">No notices</span>}
            </div>
          </div>
        </div>
      )}

      {/* Affected items */}
      {detail.affected_items.length > 0 && (
        <div className="sec">
          <h3>Affected content, ranked by significance</h3>
          {detail.affected_items.map((a, i) => (
            <div className="aff-row" key={i}>
              <div>
                <div style={{ fontWeight: 500 }}>{a.paper_id}</div>
                <div className="small">{a.relation ?? ""}</div>
              </div>
              <div className="fit">
                <div className="bar" style={{ flex: 1 }}>
                  <i style={{ width: `${a.score ?? 0}%` }} />
                </div>
                <span>{a.score != null ? Math.round(a.score) : "—"}</span>
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Timeline */}
      {detail.evidence_timeline.length > 0 && (
        <div className="sec">
          <h3>Evidence timeline</h3>
          <ul className="tl">
            {detail.evidence_timeline.map((t, i) => (
              <li key={i}>
                <b>{t.year ?? "—"}</b>
                <span>{t.title ?? t.paper_id}{t.relation ? ` · ${t.relation}` : ""}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {/* Decision */}
      <div className="sec">
        <h3>Your decision</h3>
        {detail.state !== "open" ? (
          <div>
            <span className={`chip ${detail.state === "decided" ? "good" : "neutral"}`}>{detail.state}</span>
            {detail.decision && (
              <div style={{ marginTop: 8 }} className="small">
                <strong>{ACTION_LABELS[detail.decision.action] ?? detail.decision.action}</strong>
                {" · "}{detail.decision.reason}
                {" · "}{detail.decision.decided_by}
              </div>
            )}
          </div>
        ) : (
          <>
            {!pending && (
              <div className="btns">
                {Object.entries(ACTION_LABELS).map(([k, v]) => (
                  <button key={k} className="btn" onClick={() => { setPending(k); setFormErr("") }}>{v}</button>
                ))}
              </div>
            )}
            {pending && (
              <div className="form">
                <strong>{ACTION_LABELS[pending]}</strong>
                <label className="small" htmlFor="reason-input">Reason (required)</label>
                <textarea
                  id="reason-input"
                  rows={2}
                  placeholder="Why are you taking this action?"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                />
                <label className="small" htmlFor="decided-by">Decided by</label>
                <input
                  type="text"
                  id="decided-by"
                  value={decidedBy}
                  onChange={(e) => setDecidedBy(e.target.value)}
                />
                <div className="err">{formErr}</div>
                <div className="btns">
                  <button className="btn primary" onClick={confirm} disabled={saving}>
                    {saving ? "Saving…" : "Confirm"}
                  </button>
                  <button className="btn" onClick={() => { setPending(null); setFormErr("") }}>Cancel</button>
                </div>
              </div>
            )}
          </>
        )}
      </div>

      {/* Audit trail */}
      {detail.audit_events.length > 0 && (
        <div className="sec">
          <h3>Audit trail</h3>
          <ul className="audit">
            {detail.audit_events.map((e, i) => (
              <li key={i}>
                <time>{new Date(e.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</time>
                <span>{e.actor !== "system" && <strong>{e.actor} </strong>}{e.event}{e.detail ? ` — ${e.detail}` : ""}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {toast && <div className="toast">{toast}</div>}
    </article>
  )
}

/* ── page ── */
type Category = "all" | "demo" | "Health" | "Education" | "Psychology" | "Criminal Justice" | "Economics"

export function MonitorPage() {
  const [cases, setCases] = useState<CaseListItem[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [sub, setSub] = useState<"inbox" | "revision">("inbox")
  const [category, setCategory] = useState<Category>("demo")
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    getCases({ category })
      .then((data) => {
        setCases(data)
        if (data.length > 0) setSelectedId(data[0].id)
      })
      .catch(() => setErr("Failed to load cases."))
      .finally(() => setLoading(false))
  }, [category])

  // Cases are already filtered by backend based on category
  const filtered = cases

  const open = filtered.filter((c) => c.state === "open").length
  const high = filtered.filter((c) => c.state === "open" && (c.priority_score ?? 0) >= 70).length
  const decided = filtered.filter((c) => c.state !== "open").length

  return (
    <>
      <div className="stats">
        <span><b>{open}</b> cases to review</span>
        <span><b>{high}</b> high priority</span>
        <span><b>{decided}</b> decided</span>
      </div>
      <div className="layout">
        {/* Left panel */}
        <div className="panel">
          <div className="subnav">
            <button className={sub === "inbox" ? "active" : ""} onClick={() => setSub("inbox")}>Case inbox</button>
            <button className={sub === "revision" ? "active" : ""} onClick={() => setSub("revision")}>Revision list</button>
          </div>
          <div className="subnav" style={{ fontSize: "0.85rem", paddingTop: 8 }}>
            {(["demo", "Health", "Education", "Psychology", "Criminal Justice", "Economics", "all"] as Category[]).map((cat) => (
              <button
                key={cat}
                className={category === cat ? "active" : ""}
                onClick={() => setCategory(cat)}
              >
                {cat === "demo" ? "Demo cases" : cat === "all" ? "All cases" : cat}
              </button>
            ))}
          </div>
          {loading && <div className="empty">Loading…</div>}
          {err && <div className="empty" style={{ color: "var(--crit)" }}>{err}</div>}
          {!loading && filtered.length === 0 && !err && (
            <div className="empty">No cases in this category. Try another.</div>
          )}
          {filtered.map((c) => (
            <CaseItem
              key={c.id}
              c={c}
              selected={c.id === selectedId}
              onClick={() => setSelectedId(c.id)}
            />
          ))}
        </div>

        {/* Right panel */}
        {selectedId
          ? <CaseDetailPanel key={selectedId} id={selectedId} />
          : <div className="panel"><div className="empty">Select a case to review.</div></div>
        }
      </div>
    </>
  )
}
