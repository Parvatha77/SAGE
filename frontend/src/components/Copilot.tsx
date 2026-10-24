import { useState } from "react"
import { postCopilot } from "../api/client"

const PRESETS = [
  { key: "why_label", label: "Why this label?" },
  { key: "what_differs", label: "What differs?" },
  { key: "draft_context_note", label: "Draft context note" },
  { key: "summarise_for_manager", label: "Summarise for manager" },
  { key: "what_to_check_next", label: "What to check next?" },
]

export function Copilot({ caseId }: { caseId: string }) {
  const [reply, setReply] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [question, setQuestion] = useState("")
  const [error, setError] = useState<string | null>(null)

  const ask = async (preset?: string, q?: string) => {
    setLoading(true)
    setError(null)
    setReply(null)
    try {
      const res = await postCopilot(caseId, { preset, question: q })
      setReply(res.answer)
    } catch {
      setError("Copilot unavailable. Try again.")
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap gap-2">
        {PRESETS.map(p => (
          <button
            key={p.key}
            onClick={() => ask(p.key)}
            disabled={loading}
            className="rounded-full border border-purple-200 bg-purple-50 px-3 py-1 text-xs font-medium text-purple-700 hover:bg-purple-100 disabled:opacity-50"
          >
            {p.label}
          </button>
        ))}
      </div>

      <div className="flex gap-2">
        <input
          value={question}
          onChange={e => setQuestion(e.target.value)}
          placeholder="Ask a custom question…"
          className="flex-1 rounded border border-gray-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-purple-400"
          onKeyDown={e => e.key === "Enter" && question.trim() && ask(undefined, question)}
        />
        <button
          onClick={() => question.trim() && ask(undefined, question)}
          disabled={loading || !question.trim()}
          className="rounded bg-purple-600 px-3 py-1.5 text-sm text-white hover:bg-purple-700 disabled:opacity-50"
        >
          Ask
        </button>
      </div>

      {loading && <p className="text-sm text-gray-400">Thinking…</p>}
      {error && <p className="text-sm text-red-500">{error}</p>}
      {reply && (
        <div className="rounded border border-purple-200 bg-purple-50 p-3">
          <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-purple-500">AI draft — review before use</p>
          <p className="whitespace-pre-wrap text-sm text-gray-800">{reply}</p>
        </div>
      )}
    </div>
  )
}
