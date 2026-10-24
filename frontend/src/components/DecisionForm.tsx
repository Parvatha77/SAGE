import { useState } from "react"
import type { AffectedItem } from "../api/types"

interface Props {
  caseId: string
  affectedItems: AffectedItem[]
  onSubmit: (data: {
    action: string
    reason: string
    decided_by: string
    flagged_paper_ids: string[]
  }) => Promise<void>
  error?: string | null
}

const ACTIONS = [
  { value: "no_action", label: "No action needed" },
  { value: "expert_review", label: "Request expert review" },
  { value: "author_contact", label: "Draft author contact" },
  { value: "flag_for_update", label: "Flag for update" },
]

export function DecisionForm({ affectedItems, onSubmit, error }: Props) {
  const [action, setAction] = useState("no_action")
  const [reason, setReason] = useState("")
  const [decidedBy, setDecidedBy] = useState("")
  const [flagged, setFlagged] = useState<string[]>([])
  const [submitting, setSubmitting] = useState(false)
  const [validationError, setValidationError] = useState<string | null>(null)

  const toggleFlag = (paperId: string) => {
    setFlagged(prev =>
      prev.includes(paperId) ? prev.filter(p => p !== paperId) : [...prev, paperId]
    )
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setValidationError(null)

    if (!reason.trim()) {
      setValidationError("Reason is required.")
      return
    }
    if (action === "flag_for_update" && flagged.length === 0) {
      setValidationError("Flag for update requires at least one ticked paper.")
      return
    }

    setSubmitting(true)
    try {
      await onSubmit({ action, reason, decided_by: decidedBy || "editor", flagged_paper_ids: flagged })
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" aria-label="Decision form">
      <div>
        <label className="block text-sm font-medium mb-1">Action</label>
        <div className="flex flex-wrap gap-2">
          {ACTIONS.map(a => (
            <button
              key={a.value}
              type="button"
              onClick={() => setAction(a.value)}
              className={`rounded-full border px-3 py-1 text-sm transition ${
                action === a.value
                  ? "border-blue-600 bg-blue-50 text-blue-700 font-medium"
                  : "border-gray-200 text-gray-600 hover:border-gray-400"
              }`}
            >
              {a.label}
            </button>
          ))}
        </div>
      </div>

      {action === "flag_for_update" && affectedItems.length > 0 && (
        <div>
          <label className="block text-sm font-medium mb-1">Tick papers to flag</label>
          <ul className="space-y-1">
            {affectedItems.map(item => (
              <li key={item.paper_id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  id={`flag-${item.paper_id}`}
                  checked={flagged.includes(item.paper_id)}
                  onChange={() => toggleFlag(item.paper_id)}
                  className="accent-blue-600"
                />
                <label htmlFor={`flag-${item.paper_id}`} className="truncate max-w-xs text-gray-700">
                  {item.paper_id.split("/").pop()} ({item.relation ?? "related"}, score {item.score?.toFixed(1)})
                </label>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div>
        <label htmlFor="reason" className="block text-sm font-medium mb-1">
          Reason <span className="text-red-500">*</span>
        </label>
        <textarea
          id="reason"
          value={reason}
          onChange={e => setReason(e.target.value)}
          rows={3}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="Required. Explain your decision."
        />
      </div>

      <div>
        <label htmlFor="decidedBy" className="block text-sm font-medium mb-1">Your name / ID</label>
        <input
          id="decidedBy"
          value={decidedBy}
          onChange={e => setDecidedBy(e.target.value)}
          className="w-full rounded border border-gray-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          placeholder="editor@example.com"
        />
      </div>

      {(validationError || error) && (
        <p role="alert" className="text-sm text-red-600">{validationError || error}</p>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
      >
        {submitting ? "Saving…" : "Record decision"}
      </button>
    </form>
  )
}
