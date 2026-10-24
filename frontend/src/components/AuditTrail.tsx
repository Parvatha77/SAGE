import type { AuditEvent } from "../api/types"

const ACTOR_STYLE: Record<string, string> = {
  system: "bg-gray-100 text-gray-600",
  editor: "bg-blue-100 text-blue-700",
  copilot: "bg-purple-100 text-purple-700",
}

export function AuditTrail({ events }: { events: AuditEvent[] }) {
  if (!events.length) return <p className="text-sm text-gray-400">No events yet.</p>
  return (
    <ol className="space-y-2">
      {events.map((e, i) => (
        <li key={i} className="flex gap-3 text-sm">
          <span className={`rounded px-1.5 py-0.5 text-xs font-medium self-start ${ACTOR_STYLE[e.actor] ?? "bg-gray-100"}`}>
            {e.actor}
          </span>
          <div>
            <span className="font-medium">{e.event.replace(/_/g, " ")}</span>
            {e.detail && <span className="ml-2 text-gray-500">{e.detail}</span>}
            <div className="text-xs text-gray-400">{new Date(e.created_at).toLocaleString()}</div>
          </div>
        </li>
      ))}
    </ol>
  )
}
