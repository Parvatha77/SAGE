import { useState, useEffect } from "react"

interface ToolCall {
  type: "started" | "result"
  tool: string
  input?: string
  result?: string
  cases?: any[]
  papers?: any[]
}

interface CopilotPanelProps {
  caseId: string
  isOpen: boolean
  onClose: () => void
}

export function CopilotPanel({ caseId, isOpen, onClose }: CopilotPanelProps) {
  const [query, setQuery] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([])
  const [answer, setAnswer] = useState("")
  const [citations, setCitations] = useState<any[]>([])
  const [model, setModel] = useState("")
  const [latency, setLatency] = useState(0)
  const [showToolSteps, setShowToolSteps] = useState(false)

  const handleSend = async () => {
    if (!query.trim() || isLoading) return

    const currentQuery = query
    setQuery("")  // Clear input immediately for better UX

    setIsLoading(true)
    setToolCalls([])
    setAnswer("")
    setCitations([])
    setModel("")
    setLatency(0)

    try {
      const response = await fetch(
        `http://localhost:8000/copilot/reason?case_id=${caseId}&query=${encodeURIComponent(currentQuery)}&nocache=${Date.now()}`,
        { method: "POST" }
      )

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
              const msg = JSON.parse(line.slice(6))

              if (msg.type === "tool_started") {
                setToolCalls((prev) => [...prev, { type: "started", tool: msg.tool, input: msg.input }])
              } else if (msg.type === "tool_result") {
                setToolCalls((prev) => [
                  ...prev,
                  { type: "result", tool: msg.tool, result: msg.result, cases: msg.cases, papers: msg.papers }
                ])
              } else if (msg.type === "answer") {
                setAnswer(msg.text)
                setCitations(msg.citations || [])
              } else if (msg.type === "done") {
                setModel(msg.model || "unknown")
                setLatency(msg.latency_ms || 0)
                setIsLoading(false)
              } else if (msg.type === "error") {
                setAnswer(`Error: ${msg.message}`)
                setIsLoading(false)
              }
            } catch (e) {
              console.error("SSE parse error:", e)
            }
          }
        }
      }
    } catch (err) {
      console.error("Copilot error:", err)
      setAnswer(`Error: ${String(err)}`)
      setIsLoading(false)
    }
  }

  if (!isOpen) return null

  return (
    <div style={{
      position: "fixed",
      right: 0,
      top: 0,
      bottom: 0,
      width: "420px",
      background: "var(--bg, white)",
      borderLeft: "1px solid var(--border, #ddd)",
      boxShadow: "-2px 0 8px rgba(0,0,0,0.08)",
      zIndex: 1000,
      display: "flex",
      flexDirection: "column",
      animation: "slideIn 0.3s ease-out",
      "@keyframes slideIn": {
        from: { transform: "translateX(100%)" },
        to: { transform: "translateX(0)" }
      }
    }}>
      {/* Header */}
      <div style={{
        padding: "16px",
        borderBottom: "1px solid var(--border, #eee)",
        display: "flex",
        justifyContent: "space-between",
        alignItems: "center"
      }}>
        <div>
          <div style={{ fontSize: "14px", fontWeight: 600, color: "var(--text, #000)" }}>
            ✧ Evidence Copilot
          </div>
          <div style={{ fontSize: "12px", color: "var(--muted, #888)" }}>
            AI research assistant
          </div>
        </div>
        <button
          onClick={onClose}
          style={{
            background: "none",
            border: "none",
            fontSize: "20px",
            cursor: "pointer",
            color: "var(--muted, #888)",
            padding: "4px"
          }}
        >
          ×
        </button>
      </div>

      {/* Content */}
      <div style={{
        flex: 1,
        overflowY: "auto",
        padding: "16px",
        display: "flex",
        flexDirection: "column",
        gap: "12px"
      }}>
        {/* Tool calls & progress */}
        {isLoading && toolCalls.length > 0 && (
          <div style={{
            padding: "12px",
            background: "var(--surface, #f5f5f5)",
            borderRadius: "6px",
            fontSize: "13px"
          }}>
            <div style={{ display: "flex", alignItems: "center", gap: "8px", marginBottom: "8px" }}>
              <div style={{
                width: "12px",
                height: "12px",
                borderRadius: "50%",
                background: "#4a90e2",
                animation: "pulse 1s infinite",
                "@keyframes pulse": {
                  "0%, 100%": { opacity: 1 },
                  "50%": { opacity: 0.5 }
                }
              }} />
              <strong>Agent is working...</strong>
            </div>
            <div style={{ fontSize: "12px", color: "var(--muted, #666)" }}>
              {toolCalls.map((tc, i) => (
                <div key={i} style={{ marginBottom: "4px" }}>
                  {tc.type === "started" ? (
                    <span>→ Calling {tc.tool}...</span>
                  ) : (
                    <span style={{ color: "#5cb85c" }}>✓ {tc.tool} — {tc.result}</span>
                  )}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Answer */}
        {answer && (
          <div style={{
            padding: "12px",
            background: "var(--surface-light, #f9f9f9)",
            borderRadius: "6px",
            fontSize: "13px",
            lineHeight: "1.6",
            whiteSpace: "pre-wrap",
            wordWrap: "break-word"
          }}>
            {answer}
          </div>
        )}

        {/* Citations */}
        {citations.length > 0 && (
          <div style={{
            display: "flex",
            gap: "6px",
            flexWrap: "wrap",
            fontSize: "12px"
          }}>
            {citations.map((c, i) => (
              <span
                key={i}
                style={{
                  padding: "4px 8px",
                  background: c.type === "anchor" ? "#e3f2fd" : "#f0f4c3",
                  borderRadius: "12px",
                  color: "var(--text, #333)",
                  maxWidth: "180px",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap"
                }}
                title={c.text}
              >
                {c.type === "anchor" ? "📌" : "📄"} {c.text}
              </span>
            ))}
          </div>
        )}

        {/* How agent worked (collapsible) */}
        {toolCalls.length > 0 && (
          <div style={{
            padding: "8px",
            background: "var(--surface, #fafafa)",
            borderRadius: "6px",
            fontSize: "12px"
          }}>
            <button
              onClick={() => setShowToolSteps(!showToolSteps)}
              style={{
                background: "none",
                border: "none",
                cursor: "pointer",
                color: "#4a90e2",
                fontWeight: 500,
                textAlign: "left",
                width: "100%",
                padding: "4px",
                fontSize: "12px"
              }}
            >
              {showToolSteps ? "▼" : "▶"} How the agent worked ({toolCalls.filter(t => t.type === "result").length} steps)
            </button>
            {showToolSteps && (
              <div style={{ marginTop: "8px", paddingLeft: "8px", borderLeft: "2px solid #ddd" }}>
                {toolCalls.map((tc, i) => (
                  <div key={i} style={{ marginBottom: "6px", fontSize: "11px" }}>
                    {tc.type === "started" && (
                      <div style={{ color: "#666" }}>
                        <strong>→ {tc.tool}</strong>
                        <div style={{ fontSize: "10px", color: "#999", marginTop: "2px" }}>
                          Input: {tc.input}
                        </div>
                      </div>
                    )}
                    {tc.type === "result" && (
                      <div style={{ color: "#5cb85c" }}>
                        <strong>✓ {tc.tool}</strong>
                        <div style={{ fontSize: "10px", color: "#666", marginTop: "2px" }}>
                          {tc.result}
                        </div>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Input area */}
      <div style={{
        padding: "12px",
        borderTop: "1px solid var(--border, #eee)",
        display: "flex",
        flexDirection: "column",
        gap: "8px"
      }}>
        <textarea
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault()
              handleSend()
            }
          }}
          placeholder="Ask a question... (Enter to send, Shift+Enter for new line)"
          style={{
            width: "100%",
            padding: "10px",
            border: "1px solid var(--border, #ddd)",
            borderRadius: "6px",
            fontSize: "13px",
            fontFamily: "inherit",
            resize: "none",
            height: "50px",
            color: "var(--text, #000)",
            background: "var(--bg, white)",
            boxSizing: "border-box"
          }}
        />
        <button
          onClick={handleSend}
          disabled={isLoading || !query.trim()}
          style={{
            padding: "8px 12px",
            background: isLoading ? "#ccc" : "#4a90e2",
            color: "white",
            border: "none",
            borderRadius: "4px",
            fontSize: "12px",
            fontWeight: 500,
            cursor: isLoading ? "not-allowed" : "pointer",
            opacity: isLoading ? 0.7 : 1
          }}
        >
          {isLoading ? "⊙ Analyzing..." : "Send"}
        </button>
      </div>

      {/* Footer: Model + latency */}
      {model && (
        <div style={{
          padding: "8px 12px",
          fontSize: "11px",
          color: "var(--muted, #888)",
          borderTop: "1px solid var(--border, #eee)",
          display: "flex",
          justifyContent: "space-between",
          background: "var(--surface, #fafafa)"
        }}>
          <span>{model}</span>
          <span>{latency}ms</span>
        </div>
      )}
    </div>
  )
}
