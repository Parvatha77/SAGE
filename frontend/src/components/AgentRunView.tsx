/**
 * AgentRunView — live animated visualisation of a pipeline agent run.
 * Supports UC1 (discovery → action) and UC2 (need_intake → tracker).
 */
import React, { useCallback, useEffect, useReducer, useRef, useState } from "react"
import { API_URL } from "../api/config"
import type { RunEvent, RunSummary, AgentGraphKind } from "../api/types"

// ---------------------------------------------------------------------------
// Graph topology
// ---------------------------------------------------------------------------

type NodeDef = {
  id: string
  label: string
  kind: "agent" | "gate" | "tracker"
  x: number
  y: number
}

type EdgeDef = { from: string; to: string }

const UC1_NODES: NodeDef[] = [
  { id: "discovery",   label: "Discovery",    kind: "agent",   x: 80,  y: 60 },
  { id: "evidence",    label: "Evidence",     kind: "agent",   x: 230, y: 60 },
  { id: "integrity",   label: "Integrity",    kind: "agent",   x: 380, y: 60 },
  { id: "skeptic",     label: "Skeptic",      kind: "agent",   x: 530, y: 60 },
  { id: "ranker",      label: "Ranker",       kind: "agent",   x: 680, y: 60 },
  { id: "review_gate", label: "Review Gate",  kind: "gate",    x: 530, y: 160 },
  { id: "action",      label: "Action",       kind: "tracker", x: 680, y: 160 },
]

const UC1_EDGES: EdgeDef[] = [
  { from: "discovery",   to: "evidence" },
  { from: "evidence",    to: "integrity" },
  { from: "integrity",   to: "skeptic" },
  { from: "skeptic",     to: "ranker" },
  { from: "ranker",      to: "review_gate" },
  { from: "review_gate", to: "action" },
]

const UC2_NODES: NodeDef[] = [
  { id: "need_intake",    label: "Need Intake",    kind: "agent",   x: 60,  y: 60 },
  { id: "matcher",        label: "Matcher",        kind: "agent",   x: 200, y: 60 },
  { id: "currency_gate",  label: "Currency Gate",  kind: "agent",   x: 340, y: 60 },
  { id: "context_fit",    label: "Context Fit",    kind: "agent",   x: 480, y: 60 },
  { id: "gap_check",      label: "Gap Check",      kind: "agent",   x: 620, y: 60 },
  { id: "brief_writer",   label: "Brief Writer",   kind: "agent",   x: 480, y: 160 },
  { id: "brief_checker",  label: "Brief Checker",  kind: "agent",   x: 340, y: 160 },
  { id: "approval_gate",  label: "Approval Gate",  kind: "gate",    x: 200, y: 160 },
  { id: "tracker",        label: "Tracker",        kind: "tracker", x: 60,  y: 160 },
]

const UC2_EDGES: EdgeDef[] = [
  { from: "need_intake",   to: "matcher" },
  { from: "matcher",       to: "currency_gate" },
  { from: "currency_gate", to: "context_fit" },
  { from: "context_fit",   to: "gap_check" },
  { from: "gap_check",     to: "brief_writer" },
  { from: "brief_writer",  to: "brief_checker" },
  { from: "brief_checker", to: "approval_gate" },
  { from: "approval_gate", to: "tracker" },
]

// ---------------------------------------------------------------------------
// State machine
// ---------------------------------------------------------------------------

type NodeState = "idle" | "running" | "done" | "paused" | "failed"

interface ViewState {
  nodeStates: Record<string, NodeState>
  nodeMessages: Record<string, string>
  traversedEdges: Set<string>
  events: RunEvent[]
  summary: RunSummary | null
  elapsed: number
  done: boolean
}

type Action =
  | { type: "EVENT"; event: RunEvent }
  | { type: "SUMMARY"; summary: RunSummary }
  | { type: "TICK"; elapsed: number }
  | { type: "DONE" }

function edgeKey(e: EdgeDef) { return `${e.from}→${e.to}` }

function reducer(state: ViewState, action: Action): ViewState {
  switch (action.type) {
    case "EVENT": {
      const e = action.event
      // deduplicate by seq
      if (state.events.some(x => x.seq === e.seq)) return state
      const events = [...state.events, e].sort((a, b) => a.seq - b.seq)
      const nodeStates = { ...state.nodeStates }
      const nodeMessages = { ...state.nodeMessages }
      const traversedEdges = new Set(state.traversedEdges)

      if (e.status === "started")  nodeStates[e.node] = "running"
      if (e.status === "progress") nodeStates[e.node] = "running"
      if (e.status === "finished") { nodeStates[e.node] = "done" }
      if (e.status === "paused")   nodeStates[e.node] = "paused"
      if (e.status === "failed")   nodeStates[e.node] = "failed"
      nodeMessages[e.node] = e.message

      // Mark edges as traversed when the source node finishes
      if (e.status === "finished" || e.status === "paused") {
        const edges = [...UC1_EDGES, ...UC2_EDGES].filter(x => x.from === e.node)
        edges.forEach(ed => traversedEdges.add(edgeKey(ed)))
      }

      return { ...state, events, nodeStates, nodeMessages, traversedEdges }
    }
    case "SUMMARY":
      return { ...state, summary: action.summary }
    case "TICK":
      return { ...state, elapsed: action.elapsed }
    case "DONE":
      return { ...state, done: true }
    default:
      return state
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const NODE_W = 110
const NODE_H = 44
const SVG_PADDING = 20

function nodeColour(kind: NodeDef["kind"]) {
  if (kind === "gate")    return { fill: "#fef3c7", stroke: "#d97706" }
  if (kind === "tracker") return { fill: "#ccfbf1", stroke: "#0d9488" }
  return { fill: "#ede9fe", stroke: "#7c3aed" }
}

function stateRing(s: NodeState) {
  if (s === "running") return "running-ring"
  if (s === "paused")  return "paused-ring"
  if (s === "failed")  return "failed-ring"
  return ""
}

function stateIcon(s: NodeState) {
  if (s === "done")    return "✓"
  if (s === "paused")  return "⏸"
  if (s === "failed")  return "✕"
  if (s === "running") return "⟳"
  return ""
}

function formatMs(ms: number | null) {
  if (ms == null) return ""
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`
}

// ---------------------------------------------------------------------------
// SVG graph
// ---------------------------------------------------------------------------

function GraphNode({ node, state: ns, message, reducedMotion }: {
  node: NodeDef
  state: NodeState
  message: string
  reducedMotion: boolean
}) {
  const col = nodeColour(node.kind)
  const ring = !reducedMotion ? stateRing(ns) : ""
  return (
    <g role="img" aria-label={`${node.label}: ${ns}`}>
      {ring && (
        <rect
          x={node.x - 4} y={node.y - 4}
          width={NODE_W + 8} height={NODE_H + 8}
          rx={10} ry={10}
          fill="none"
          stroke={ns === "running" ? "#7c3aed" : ns === "paused" ? "#d97706" : "#dc2626"}
          strokeWidth={2}
          className={`agent-ring ${ring}`}
        />
      )}
      <rect
        x={node.x} y={node.y} width={NODE_W} height={NODE_H}
        rx={8} ry={8}
        fill={ns === "idle" ? "#f3f4f6" : col.fill}
        stroke={ns === "idle" ? "#9ca3af" : col.stroke}
        strokeWidth={ns === "idle" ? 1 : 2}
      />
      <text x={node.x + NODE_W / 2} y={node.y + 16}
        textAnchor="middle" fontSize={11} fontWeight={600}
        fill={ns === "idle" ? "#9ca3af" : "#1f2937"}>
        {node.label}
      </text>
      <text x={node.x + NODE_W / 2} y={node.y + 30}
        textAnchor="middle" fontSize={10}
        fill={ns === "idle" ? "#d1d5db" : "#6b7280"}>
        {stateIcon(ns)} {ns}
      </text>
      {message && ns !== "idle" && (
        <title>{message}</title>
      )}
    </g>
  )
}

function GraphEdge({ edge, nodes, traversed, reducedMotion }: {
  edge: EdgeDef
  nodes: NodeDef[]
  traversed: boolean
  reducedMotion: boolean
}) {
  const from = nodes.find(n => n.id === edge.from)!
  const to   = nodes.find(n => n.id === edge.to)!
  if (!from || !to) return null

  const x1 = from.x + NODE_W
  const y1 = from.y + NODE_H / 2
  const x2 = to.x
  const y2 = to.y + NODE_H / 2

  // If going backwards/down, curve
  const dx = x2 - x1
  const cx1 = x1 + dx / 2
  const cx2 = x1 + dx / 2
  const d = `M ${x1} ${y1} C ${cx1} ${y1}, ${cx2} ${y2}, ${x2} ${y2}`

  return (
    <g>
      <path d={d} fill="none"
        stroke={traversed ? "#7c3aed" : "#d1d5db"}
        strokeWidth={traversed ? 2 : 1.5}
        markerEnd="url(#arrow)"
      />
      {traversed && !reducedMotion && (
        <circle r={4} fill="#7c3aed" opacity={0.8}>
          <animateMotion dur="0.8s" fill="freeze" path={d} />
        </circle>
      )}
    </g>
  )
}

function AgentGraph({ kind, nodeStates, nodeMessages, traversedEdges, reducedMotion }: {
  kind: AgentGraphKind
  nodeStates: Record<string, NodeState>
  nodeMessages: Record<string, string>
  traversedEdges: Set<string>
  reducedMotion: boolean
}) {
  const nodes = kind === "uc1" ? UC1_NODES : UC2_NODES
  const edges = kind === "uc1" ? UC1_EDGES : UC2_EDGES

  const maxX = Math.max(...nodes.map(n => n.x + NODE_W)) + SVG_PADDING
  const maxY = Math.max(...nodes.map(n => n.y + NODE_H)) + SVG_PADDING + 10

  return (
    <svg viewBox={`0 0 ${maxX} ${maxY}`} aria-label="Agent pipeline graph"
      style={{ width: "100%", overflow: "visible" }}>
      <defs>
        <marker id="arrow" viewBox="0 0 6 6" refX={5} refY={3}
          markerWidth={6} markerHeight={6} orient="auto">
          <path d="M 0 0 L 6 3 L 0 6 z" fill="#9ca3af" />
        </marker>
      </defs>
      {edges.map(e => (
        <GraphEdge key={edgeKey(e)} edge={e} nodes={nodes}
          traversed={traversedEdges.has(edgeKey(e))} reducedMotion={reducedMotion} />
      ))}
      {nodes.map(n => (
        <GraphNode key={n.id} node={n}
          state={nodeStates[n.id] ?? "idle"}
          message={nodeMessages[n.id] ?? ""}
          reducedMotion={reducedMotion} />
      ))}
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Log panel
// ---------------------------------------------------------------------------

function LogPanel({ events }: { events: RunEvent[] }) {
  const bottomRef = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (bottomRef.current && typeof bottomRef.current.scrollIntoView === "function") {
      bottomRef.current.scrollIntoView({ behavior: "smooth" })
    }
  }, [events])

  return (
    <div aria-live="polite" aria-label="Agent event log"
      style={{ fontFamily: "monospace", fontSize: 12, maxHeight: 220, overflowY: "auto",
               background: "#f9fafb", borderRadius: 8, padding: "8px 12px", marginTop: 12 }}>
      {events.map(e => (
        <div key={e.seq} style={{ marginBottom: 3, color: e.status === "failed" ? "#dc2626" : "#374151" }}>
          <span style={{ color: "#9ca3af", marginRight: 6 }}>
            {new Date(e.created_at).toLocaleTimeString()}
          </span>
          <span style={{
            fontWeight: 600,
            color: e.status === "finished" ? "#7c3aed" : e.status === "paused" ? "#d97706" : "#374151",
            marginRight: 6,
          }}>
            [{e.node}]
          </span>
          {e.message}
        </div>
      ))}
      <div ref={bottomRef} />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Counters strip
// ---------------------------------------------------------------------------

function CountersStrip({ summary, elapsed, isReplay }: {
  summary: RunSummary | null
  elapsed: number
  isReplay: boolean
}) {
  const tiles = [
    { label: "Papers",  value: summary?.papers_scanned ?? "—" },
    { label: "Pairs",   value: summary?.pairs_compared ?? "—" },
    { label: "Cases",   value: summary?.cases_created  ?? "—" },
    { label: "Seconds", value: summary ? summary.seconds.toFixed(1) : elapsed.toFixed(0) },
  ]
  return (
    <div style={{ display: "flex", gap: 16, flexWrap: "wrap", marginTop: 12 }}>
      {tiles.map(t => (
        <div key={t.label} style={{
          background: "#f3f4f6", borderRadius: 8, padding: "6px 16px", textAlign: "center", minWidth: 80,
        }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: "#1f2937" }}>{String(t.value)}</div>
          <div style={{ fontSize: 11, color: "#6b7280" }}>{t.label}</div>
        </div>
      ))}
      <div style={{
        background: isReplay ? "#fef9c3" : "#ecfdf5",
        borderRadius: 8, padding: "6px 16px", alignSelf: "center",
        fontSize: 12, color: isReplay ? "#854d0e" : "#065f46", fontWeight: 600,
      }}>
        {isReplay ? "Replaying saved model responses" : "Live model calls"}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Summary card
// ---------------------------------------------------------------------------

function SummaryCard({ summary, onRunAgain, onClear }: {
  summary: RunSummary
  onRunAgain: () => void
  onClear: () => void
}) {
  return (
    <div style={{ marginTop: 20, padding: 20, background: "#f0fdf4", borderRadius: 12, border: "1px solid #bbf7d0" }}>
      <h3 style={{ margin: "0 0 12px", color: "#15803d" }}>Run complete</h3>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill,minmax(140px,1fr))", gap: 8 }}>
        {[
          ["Cases created",  summary.cases_created],
          ["Pairs compared", summary.pairs_compared],
          ["Duration",       `${summary.seconds.toFixed(1)}s`],
          ["Cache hit rate", `${summary.cache_hit_rate}%`],
        ].map(([k, v]) => (
          <div key={String(k)} style={{ background: "white", borderRadius: 8, padding: "8px 14px" }}>
            <div style={{ fontSize: 18, fontWeight: 700, color: "#1f2937" }}>{String(v)}</div>
            <div style={{ fontSize: 11, color: "#6b7280" }}>{String(k)}</div>
          </div>
        ))}
      </div>
      <div style={{ marginTop: 16, display: "flex", gap: 10 }}>
        <button onClick={onRunAgain}
          style={{ padding: "8px 20px", background: "#7c3aed", color: "white", border: "none", borderRadius: 8, cursor: "pointer", fontWeight: 600 }}>
          Run again
        </button>
        <button onClick={onClear}
          style={{ padding: "8px 20px", background: "#f3f4f6", color: "#374151", border: "none", borderRadius: 8, cursor: "pointer" }}>
          Clear
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

async function fetchEvents(runId: string, after: number): Promise<RunEvent[]> {
  const res = await fetch(`${API_URL}/runs/${runId}/events?after=${after}`)
  if (!res.ok) return []
  return res.json()
}

async function fetchSummary(runId: string): Promise<RunSummary | null> {
  const res = await fetch(`${API_URL}/runs/${runId}/summary`)
  if (!res.ok) return null
  return res.json()
}

interface AgentRunViewProps {
  runId: string
  kind: AgentGraphKind
  onClose?: () => void
}

export function AgentRunView({ runId, kind, onClose }: AgentRunViewProps) {
  const reducedMotion =
    typeof window !== "undefined" && typeof window.matchMedia === "function"
      ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
      : false

  const [state, dispatch] = useReducer(reducer, {
    nodeStates: {}, nodeMessages: {}, traversedEdges: new Set(),
    events: [], summary: null, elapsed: 0, done: false,
  })

  const startRef = useRef(Date.now())
  const sseRef   = useRef<EventSource | null>(null)
  const pollRef  = useRef<ReturnType<typeof setInterval> | null>(null)
  const lastSeq  = useRef(-1)

  const stopAll = useCallback(() => {
    sseRef.current?.close()
    if (pollRef.current) clearInterval(pollRef.current)
  }, [])

  // Elapsed timer
  useEffect(() => {
    const t = setInterval(() => {
      dispatch({ type: "TICK", elapsed: (Date.now() - startRef.current) / 1000 })
    }, 500)
    return () => clearInterval(t)
  }, [])

  // SSE with polling fallback
  useEffect(() => {
    let usePoll = false

    const applyEvent = (e: RunEvent) => {
      dispatch({ type: "EVENT", event: e })
      lastSeq.current = Math.max(lastSeq.current, e.seq)
    }

    // Try SSE first
    try {
      const es = new EventSource(`${API_URL}/runs/${runId}/stream`)
      sseRef.current = es
      es.onmessage = (msg) => {
        try {
          const data = JSON.parse(msg.data)
          if (data.type === "done") {
            dispatch({ type: "DONE" })
            stopAll()
            fetchSummary(runId).then(s => s && dispatch({ type: "SUMMARY", summary: s }))
            return
          }
          applyEvent(data as RunEvent)
        } catch {}
      }
      es.onerror = () => {
        es.close()
        if (!usePoll) { usePoll = true; startPolling() }
      }
    } catch {
      startPolling()
    }

    function startPolling() {
      pollRef.current = setInterval(async () => {
        const events = await fetchEvents(runId, lastSeq.current)
        events.forEach(applyEvent)
        // Check if done
        const res = await fetch(`${API_URL}/runs/${runId}`)
        if (res.ok) {
          const run = await res.json()
          if (run.status === "done" || run.status === "error") {
            dispatch({ type: "DONE" })
            stopAll()
            const s = await fetchSummary(runId)
            if (s) dispatch({ type: "SUMMARY", summary: s })
          }
        }
      }, 1500)
    }

    return stopAll
  }, [runId, stopAll])

  return (
    <div style={{ fontFamily: "system-ui, sans-serif", padding: 20, maxWidth: 820 }}
      aria-label="Agent run view">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <h2 style={{ margin: 0, fontSize: 18, fontWeight: 700, color: "#1f2937" }}>
          {kind === "uc1" ? "Discovery Pipeline" : "Evidence-to-Impact Agent"}
        </h2>
        {onClose && (
          <button onClick={onClose} aria-label="Close run view"
            style={{ background: "none", border: "none", cursor: "pointer", fontSize: 20, color: "#6b7280" }}>
            ×
          </button>
        )}
      </div>

      <AgentGraph
        kind={kind}
        nodeStates={state.nodeStates}
        nodeMessages={state.nodeMessages}
        traversedEdges={state.traversedEdges}
        reducedMotion={reducedMotion}
      />

      <CountersStrip
        summary={state.summary}
        elapsed={state.elapsed}
        isReplay={state.summary?.is_replay ?? false}
      />

      <LogPanel events={state.events} />

      {state.done && state.summary && (
        <SummaryCard
          summary={state.summary}
          onRunAgain={() => window.location.reload()}
          onClear={onClose ?? (() => {})}
        />
      )}
    </div>
  )
}
