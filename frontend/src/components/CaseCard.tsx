import { Link } from "react-router-dom"
import type { CaseListItem } from "../api/types"
import { LabelChip } from "./LabelChip"

export function CaseCard({ c }: { c: CaseListItem }) {
  return (
    <Link
      to={`/cases/${c.id}`}
      className="block rounded-lg border border-gray-200 bg-white px-4 py-3 hover:border-blue-300 hover:shadow-sm transition"
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex flex-wrap items-center gap-2">
          <LabelChip label={c.label} />
          {c.needs_human_attention && (
            <span className="text-xs text-orange-600 font-medium">⚠ Attention</span>
          )}
          {c.state === "decided" && (
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">Decided</span>
          )}
        </div>
        <span className="text-xs text-gray-400 whitespace-nowrap">
          Priority {c.priority_score?.toFixed(1) ?? "—"}
        </span>
      </div>
      <p className="mt-1 text-xs text-gray-400">{c.id.slice(0, 8)}</p>
      {c.skeptic_verdict && (
        <p className="mt-1 text-xs text-gray-500">Skeptic: {c.skeptic_verdict}</p>
      )}
    </Link>
  )
}
