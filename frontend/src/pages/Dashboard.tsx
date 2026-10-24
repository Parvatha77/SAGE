import { useEffect, useState } from "react"
import { getStats, getCases, startRun } from "../api/client"
import type { StatsOut, CaseListItem } from "../api/types"
import { LABEL_DISPLAY } from "../api/types"

const LABEL_CHIP: Record<string, string> = {
  confirms: "good",
  extends: "info",
  differs_in_context: "neutral",
  possible_reproducibility_concern: "warn",
  retraction_impact: "crit",
  insufficient_information: "plain",
}

function priorityLabel(score: number | null): string {
  if (score == null) return "Low"
  if (score >= 70) return "High"
  if (score >= 40) return "Medium"
  return "Low"
}

function HBar({ label, value, max, cls }: { label: string; value: number; max: number; cls?: string }) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0
  return (
    <div className="hb">
      <span>{label}</span>
      <div className={`bar ${cls ?? ""}`}><i style={{ width: `${pct}%` }} /></div>
      <em>{value}</em>
    </div>
  )
}

interface Props {
  onOpenCase: () => void
  onOpenNeed: () => void
}

export function Dashboard({ onOpenCase }: Props) {
  const [stats, setStats] = useState<StatsOut | null>(null)
  const [highCases, setHighCases] = useState<CaseListItem[]>([])
  const [runId, setRunId] = useState<string | null>(null)
  const [running, setRunning] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  useEffect(() => {
    getStats().then(setStats).catch(() => setErr("Failed to load stats"))
    getCases().then((cases) =>
      setHighCases(cases.filter((c) => (c.priority_score ?? 0) >= 70 && c.state === "open").slice(0, 5))
    ).catch(() => {})
  }, [])

  async function handleRun() {
    setRunning(true)
    setRunId(null)
    try {
      const r = await startRun()
      setRunId(r.run_id)
    } catch {
      setErr("Failed to start run")
    } finally {
      setRunning(false)
    }
  }

  if (err && !stats) return <p className="empty">{err}</p>
  if (!stats) return <p className="empty">Loading…</p>

  const labelEntries = Object.entries(stats.by_label).filter(([k]) => k !== "unrelated")
  const labelMax = Math.max(...labelEntries.map(([, v]) => v), 1)
  const stateEntries = Object.entries(stats.by_state)
  const stateMax = Math.max(...stateEntries.map(([, v]) => v), 1)

  return (
    <>
      <p className="small" style={{ margin: "0 0 12px" }}>
        One view across both use cases. Run a new pipeline to discover new evidence pairs.
      </p>

      <div className="kpis">
        <div className="kpi"><b>{stats.total_cases}</b><span>total cases</span></div>
        <div className="kpi"><b>{stats.decided_count}</b><span>decided</span></div>
        <div className="kpi"><b>{stats.total_cases - stats.decided_count}</b><span>open</span></div>
        <div className="kpi"><b>{stats.revision_items}</b><span>revision items</span></div>
        {labelEntries.map(([k, v]) => (
          <div className="kpi" key={k}><b>{v}</b><span>{LABEL_DISPLAY[k] ?? k}</span></div>
        ))}
      </div>

      <div className="grid2">
        <div className="panel pad">
          <h3>Cases by label</h3>
          {labelEntries.map(([k, v]) => (
            <HBar key={k} label={LABEL_DISPLAY[k] ?? k} value={v} max={labelMax}
              cls={LABEL_CHIP[k] === "crit" ? "crit" : LABEL_CHIP[k] === "warn" ? "warn" : LABEL_CHIP[k] === "good" ? "good" : ""} />
          ))}
        </div>
        <div className="panel pad">
          <h3>Cases by state</h3>
          {stateEntries.map(([k, v]) => (
            <HBar key={k} label={k} value={v} max={stateMax} />
          ))}
        </div>
      </div>

      <div className="panel pad" style={{ marginBottom: 16 }}>
        <h3>Needs attention — high priority open cases</h3>
        {highCases.length === 0 && <p className="small" style={{ margin: 0 }}>No high-priority open cases.</p>}
        {highCases.map((c) => (
          <div className="alert" key={c.id}>
            <div className="t">
              <strong>{c.id}</strong>
              <br />
              <span className="small">
                {LABEL_DISPLAY[c.label] ?? c.label} · priority {priorityLabel(c.priority_score)}
              </span>
            </div>
            <button className="btn" onClick={onOpenCase}>Open case</button>
          </div>
        ))}
      </div>

      <div className="panel pad">
        <h3>Run pipeline</h3>
        <p className="small" style={{ margin: "0 0 10px" }}>
          Runs discovery → evidence → integrity → skeptic → ranker on all ingested papers.
        </p>
        <div className="btns">
          <button className="btn primary" onClick={handleRun} disabled={running}>
            {running ? "Starting…" : "Discover new evidence"}
          </button>
        </div>
        {runId && (
          <p className="small" style={{ marginTop: 8 }}>
            Run started: <span className="mono">{runId}</span> — switch to Evidence Currency Monitor to see results.
          </p>
        )}
        {err && <p className="err" style={{ marginTop: 6 }}>{err}</p>}
      </div>
    </>
  )
}
