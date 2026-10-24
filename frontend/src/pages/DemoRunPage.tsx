import { useState, useEffect, useRef } from "react"

const API = "http://localhost:8000"

type EventRow = {
  seq: number
  node: string
  status: string
  message: string
  counters?: Record<string, number> | null
  duration_ms?: number | null
}

type Message = {
  id: string
  role: "user" | "assistant"
  text: string
}

const NODE_LABEL: Record<string, string> = {
  discovery: "Build embeddings",
  pairing: "Find candidate pairs",
  relevance: "Relevance check",
  compare: "Field comparisons",
  classify: "Classify relationships",
  skeptic: "Adversarial review",
  ranker: "Rank by priority",
}

const NODE_DESCRIPTION: Record<string, string> = {
  discovery: "Extracting and embedding paper claims",
  pairing: "Finding candidate claim pairs to compare",
  relevance: "Checking whether pairs are relevant",
  compare: "Comparing field-by-field differences",
  classify: "Classifying relationship type (confirms/contradicts/etc)",
  skeptic: "Running adversarial review for quality",
  ranker: "Prioritizing cases by significance",
}

export function DemoRunPage() {
  const [running, setRunning] = useState(false)
  const [runId, setRunId] = useState<string | null>(null)
  const [events, setEvents] = useState<EventRow[]>([])
  const [done, setDone] = useState(false)
  const [casesCreated, setCasesCreated] = useState(0)
  const [resetInfo, setResetInfo] = useState<{ papers: number; cases: number } | null>(null)
  const [error, setError] = useState<string | null>(null)

  // Copilot chat
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "init",
      role: "assistant",
      text: "Hi! I'm the Evidence Analysis Copilot. Ask me about the live pipeline, how claims are analyzed, or what you're seeing in real time.",
    },
  ])
  const [input, setInput] = useState("")
  const [copilotLoading, setCopilotLoading] = useState(false)

  const esRef = useRef<EventSource | null>(null)
  const logRef = useRef<HTMLDivElement>(null)
  const chatRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (logRef.current) {
      logRef.current.scrollTop = logRef.current.scrollHeight
    }
  }, [events])

  useEffect(() => {
    if (chatRef.current) {
      chatRef.current.scrollTop = chatRef.current.scrollHeight
    }
  }, [messages])

  useEffect(() => {
    return () => esRef.current?.close()
  }, [])

  async function startRun() {
    setRunning(true)
    setDone(false)
    setEvents([])
    setCasesCreated(0)
    setError(null)
    setResetInfo(null)
    esRef.current?.close()

    try {
      const res = await fetch(`${API}/demo/run`, { method: "POST" })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      setRunId(data.run_id)
      setResetInfo({ papers: data.demo_papers, cases: data.reset?.cases ?? 0 })

      const es = new EventSource(`${API}/demo/run/${data.run_id}/stream`)
      esRef.current = es

      es.onmessage = (e) => {
        const payload = JSON.parse(e.data)
        if (payload.type === "done") {
          setCasesCreated(payload.cases_created ?? 0)
          setDone(true)
          setRunning(false)
          es.close()
          return
        }
        setEvents((prev) => {
          if (prev.find((x) => x.seq === payload.seq)) return prev
          return [...prev, payload]
        })
      }

      es.onerror = () => {
        setError("Connection lost — check backend logs")
        setRunning(false)
        es.close()
      }
    } catch (err: unknown) {
      setError(String(err))
      setRunning(false)
    }
  }

  async function sendMessage() {
    if (!input.trim()) return
    const userMsg = input.trim()
    setInput("")

    // Add user message
    const msgId = Date.now().toString()
    setMessages((prev) => [...prev, { id: msgId, role: "user", text: userMsg }])

    // Simulate copilot response (in real app, call an API)
    setCopilotLoading(true)
    setTimeout(() => {
      const responses: Record<string, string> = {
        pipeline: "The pipeline has 7 stages: 1) Embedding - convert claims to vectors, 2) Pairing - find candidate matches, 3) Relevance - filter to relevant pairs, 4) Comparison - analyze field differences, 5) Classification - assign labels (confirms/contradicts/extends), 6) Skeptic - adversarial review, 7) Ranker - prioritize by importance.",
        claims: "Each paper contains multiple claims. We extract them, embed them semantically, then pair similar claims across papers to identify relationships.",
        cases: "A 'case' represents a relationship between two claims. We classify each as: confirms (same finding), extends (generalizes to new context), contradicts (opposite finding), or retraction_impact (involving retracted paper).",
        accuracy: "Quality depends on claim extraction accuracy, embedding quality, and skeptic review. Real papers are complex—the skeptic catches edge cases.",
        duration: "Each stage processes cases in parallel. Typical demo runs 2-3 minutes. Speed depends on LLM response time.",
        default: "That's a great question! The system analyzes research papers to find relationships between claims. Each case shows how evidence from different papers relates—whether findings confirm, extend, or contradict each other.",
      }

      const key = Object.keys(responses).find((k) =>
        userMsg.toLowerCase().includes(k)
      )
      const reply = responses[key] || responses.default

      setMessages((prev) => [...prev, { id: (Date.now() + 1).toString(), role: "assistant", text: reply }])
      setCopilotLoading(false)
    }, 600)
  }

  const steps = ["discovery", "pairing", "relevance", "compare", "classify", "skeptic", "ranker"]
  const finishedNodes = new Set(events.filter((e) => e.status === "finished").map((e) => e.node))
  const currentIdx = done ? steps.length : steps.findIndex((s) => steps.includes(s) && !finishedNodes.has(s))
  const activeNode = events.length > 0 ? events[events.length - 1].node : null

  return (
    <div style={{ maxWidth: 1400, margin: "0 auto", padding: "1.5rem" }}>
      <h2 style={{ fontFamily: "var(--font-head)", fontSize: "1.4rem", marginBottom: 6 }}>
        Live Pipeline Analysis
      </h2>
      <p style={{ color: "var(--ink-muted)", marginBottom: "1.5rem", fontSize: "0.9rem" }}>
        Watch the evidence pipeline execute in real time across 7 stages with live AI copilot support.
      </p>

      {/* Main layout: left (pipeline) + right (copilot) */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 320px", gap: 20 }}>
        {/* LEFT: Pipeline section */}
        <div>
          <button
            onClick={startRun}
            disabled={running}
            style={{
              background: running ? "var(--ink-muted)" : "var(--accent)",
              color: "#fff",
              border: "none",
              borderRadius: 6,
              padding: "0.7rem 1.6rem",
              fontSize: "1rem",
              fontFamily: "var(--font-body)",
              fontWeight: 500,
              cursor: running ? "not-allowed" : "pointer",
              marginBottom: "1.5rem",
              transition: "background 0.2s",
            }}
          >
            {running ? "⏳ Agents working…" : done ? "▶ Run Again" : "▶ Run Live Analysis"}
          </button>

          {resetInfo && (
            <p style={{ fontSize: "0.82rem", color: "var(--ink-muted)", marginBottom: "1.5rem" }}>
              Reset {resetInfo.cases} existing cases from {resetInfo.papers} demo papers — running fresh.
            </p>
          )}

          {/* Agent progress timeline */}
          {(running || done || events.length > 0) && (
            <div
              style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: "1.2rem",
                marginBottom: "1.5rem",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", marginBottom: 12 }}>
                <span style={{ fontSize: "0.9rem", fontWeight: 500 }}>AI investigation progress</span>
                {running && (
                  <span
                    style={{
                      marginLeft: 8,
                      width: 8,
                      height: 8,
                      borderRadius: "50%",
                      background: "var(--accent)",
                      animation: "pulse 1.5s infinite",
                    }}
                  />
                )}
              </div>

              {/* Timeline */}
              <div>
                {steps.map((step, idx) => {
                  const finished = finishedNodes.has(step)
                  const isActive = !done && activeNode === step
                  const isFuture = idx > currentIdx && !done
                  return (
                    <div
                      key={step}
                      style={{
                        display: "flex",
                        alignItems: "flex-start",
                        marginBottom: idx < steps.length - 1 ? 16 : 0,
                      }}
                    >
                      {/* Timeline dot */}
                      <div
                        style={{
                          width: 20,
                          height: 20,
                          borderRadius: "50%",
                          background: finished ? "#16a34a" : isActive ? "var(--accent)" : isFuture ? "var(--border)" : "#e5e7eb",
                          border: isActive ? "2px solid var(--accent)" : "none",
                          display: "flex",
                          alignItems: "center",
                          justifyContent: "center",
                          fontSize: "0.65rem",
                          color: finished || isActive ? "#fff" : "var(--ink-muted)",
                          fontWeight: "bold",
                          marginRight: 12,
                          flexShrink: 0,
                          transition: "background 0.4s",
                        }}
                      >
                        {finished && "✓"}
                        {isActive && "⟳"}
                      </div>

                      {/* Timeline line (vertical connector) */}
                      {idx < steps.length - 1 && (
                        <div
                          style={{
                            position: "absolute",
                            left: 28,
                            top: "auto",
                            width: 2,
                            height: 16,
                            background: finished ? "#16a34a" : isFuture ? "var(--border)" : "#e5e7eb",
                            marginBottom: -16,
                          }}
                        />
                      )}

                      {/* Step info */}
                      <div style={{ flex: 1 }}>
                        <div
                          style={{
                            fontSize: "0.9rem",
                            fontWeight: finished || isActive ? 500 : 400,
                            color: finished || isActive ? "inherit" : "var(--ink-muted)",
                          }}
                        >
                          {NODE_LABEL[step]}
                        </div>
                        <div style={{ fontSize: "0.75rem", color: "var(--ink-muted)", marginTop: 2 }}>
                          {NODE_DESCRIPTION[step]}
                        </div>
                        {finished && (
                          <div style={{ fontSize: "0.75rem", color: "#16a34a", marginTop: 4 }}>
                            ✓ Completed
                          </div>
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          )}

          {/* Live log */}
          {events.length > 0 && (
            <div
              ref={logRef}
              style={{
                background: "var(--surface)",
                border: "1px solid var(--border)",
                borderRadius: 8,
                padding: "1rem",
                fontFamily: "monospace",
                fontSize: "0.75rem",
                maxHeight: 300,
                overflowY: "auto",
                lineHeight: 1.5,
              }}
            >
              {events.map((e) => (
                <div key={e.seq} style={{ marginBottom: 4, opacity: e.status === "finished" ? 1 : 0.7 }}>
                  <span
                    style={{
                      color: e.status === "finished" ? "#16a34a" : e.status === "failed" ? "#dc2626" : "var(--accent)",
                      marginRight: 8,
                    }}
                  >
                    {e.status === "finished" ? "✓" : e.status === "failed" ? "✗" : "▸"}
                  </span>
                  <span style={{ color: "var(--ink-muted)", marginRight: 8 }}>
                    [{NODE_LABEL[e.node] ?? e.node}]
                  </span>
                  <span>{e.message}</span>
                  {e.duration_ms != null && (
                    <span style={{ color: "var(--ink-muted)", marginLeft: 6 }}>
                      {(e.duration_ms / 1000).toFixed(1)}s
                    </span>
                  )}
                </div>
              ))}
              {running && (
                <div style={{ color: "var(--accent)", marginTop: 4 }}>● live…</div>
              )}
            </div>
          )}

          {/* Done summary */}
          {done && (
            <div
              style={{
                marginTop: "1.5rem",
                padding: "1rem 1.2rem",
                background: "#f0fdf4",
                border: "1px solid #86efac",
                borderRadius: 8,
              }}
            >
              <strong style={{ color: "#15803d" }}>✓ Pipeline complete</strong>
              <p style={{ margin: "0.5rem 0 0", fontSize: "0.9rem", color: "#166534" }}>
                {casesCreated} new cases created. Switch to the Monitor tab to review them.
              </p>
            </div>
          )}

          {error && (
            <div
              style={{
                marginTop: "1rem",
                padding: "0.8rem 1rem",
                background: "#fef2f2",
                border: "1px solid #fca5a5",
                borderRadius: 8,
                color: "#dc2626",
                fontSize: "0.85rem",
              }}
            >
              {error}
            </div>
          )}
        </div>

        {/* RIGHT: Copilot chat */}
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            background: "var(--surface)",
            border: "1px solid var(--border)",
            borderRadius: 8,
            height: 500,
          }}
        >
          <div style={{ padding: "1rem", borderBottom: "1px solid var(--border)" }}>
            <div style={{ fontSize: "0.9rem", fontWeight: 500 }}>AI Copilot</div>
            <div style={{ fontSize: "0.75rem", color: "var(--ink-muted)", marginTop: 2 }}>
              Ask about the pipeline or cases
            </div>
          </div>

          {/* Chat messages */}
          <div
            ref={chatRef}
            style={{
              flex: 1,
              overflowY: "auto",
              padding: "1rem",
              fontSize: "0.8rem",
              lineHeight: 1.5,
            }}
          >
            {messages.map((msg) => (
              <div
                key={msg.id}
                style={{
                  marginBottom: 12,
                  display: "flex",
                  justifyContent: msg.role === "user" ? "flex-end" : "flex-start",
                }}
              >
                <div
                  style={{
                    maxWidth: "85%",
                    padding: "0.6rem 0.8rem",
                    borderRadius: 6,
                    background: msg.role === "user" ? "var(--accent)" : "var(--ink-muted)",
                    color: msg.role === "user" ? "#fff" : "var(--surface)",
                    wordWrap: "break-word",
                  }}
                >
                  {msg.text}
                </div>
              </div>
            ))}
            {copilotLoading && (
              <div style={{ color: "var(--ink-muted)", fontSize: "0.75rem" }}>
                Copilot thinking…
              </div>
            )}
          </div>

          {/* Chat input */}
          <div style={{ padding: "0.8rem", borderTop: "1px solid var(--border)" }}>
            <div style={{ display: "flex", gap: 6 }}>
              <input
                type="text"
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !copilotLoading) sendMessage()
                }}
                placeholder="Ask..."
                disabled={copilotLoading}
                style={{
                  flex: 1,
                  border: "1px solid var(--border)",
                  borderRadius: 4,
                  padding: "0.4rem 0.6rem",
                  fontSize: "0.8rem",
                  fontFamily: "var(--font-body)",
                }}
              />
              <button
                onClick={sendMessage}
                disabled={copilotLoading || !input.trim()}
                style={{
                  background: copilotLoading || !input.trim() ? "var(--ink-muted)" : "var(--accent)",
                  color: "#fff",
                  border: "none",
                  borderRadius: 4,
                  padding: "0.4rem 0.8rem",
                  fontSize: "0.75rem",
                  cursor: copilotLoading || !input.trim() ? "not-allowed" : "pointer",
                  fontWeight: 500,
                }}
              >
                Send
              </button>
            </div>
          </div>
        </div>
      </div>

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.5; }
        }
      `}</style>
    </div>
  )
}
