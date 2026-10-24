import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { getNeeds, startNeedRun } from "../api/client"
import { AgentRunView } from "../components/AgentRunView"

export function NeedsPage() {
  const [activeRun, setActiveRun] = useState<{ runId: string; title: string } | null>(null)
  const [launching, setLaunching] = useState<string | null>(null)

  const { data: needs, isLoading } = useQuery({ queryKey: ["needs"], queryFn: getNeeds })

  async function handleRun(needId: string, title: string) {
    setLaunching(needId)
    try {
      const run = await startNeedRun(needId)
      setActiveRun({ runId: run.run_id, title })
    } finally {
      setLaunching(null)
    }
  }

  if (activeRun) {
    return (
      <div className="p-6">
        <div className="mb-4 text-sm text-gray-500">Running: <strong>{activeRun.title}</strong></div>
        <AgentRunView
          runId={activeRun.runId}
          kind="uc2"
          onClose={() => setActiveRun(null)}
        />
      </div>
    )
  }

  if (isLoading) return <div className="p-8 text-gray-400">Loading needs…</div>

  return (
    <div className="space-y-4 p-6">
      <h1 className="text-xl font-bold text-gray-800">Policy Needs</h1>
      {(!needs || needs.length === 0) && (
        <p className="text-sm text-gray-400">No needs loaded. Import needs.json via the API.</p>
      )}
      <div className="space-y-3">
        {needs?.map(n => (
          <div key={n.id}
            className="flex items-center justify-between rounded-lg border bg-white p-4">
            <div>
              <p className="font-semibold text-gray-800">{n.title}</p>
              <div className="mt-1 flex gap-2">
                <span className={`rounded px-2 py-0.5 text-xs font-medium ${
                  n.state === "approved" ? "bg-green-100 text-green-700" :
                  n.state === "running"  ? "bg-violet-100 text-violet-700" :
                  "bg-gray-100 text-gray-600"
                }`}>{n.state}</span>
                {n.is_example && (
                  <span className="rounded bg-yellow-100 px-2 py-0.5 text-xs text-yellow-700">
                    example
                  </span>
                )}
              </div>
            </div>
            <button
              onClick={() => handleRun(n.id, n.title)}
              disabled={launching === n.id}
              className="rounded bg-violet-600 px-4 py-1.5 text-sm font-semibold text-white hover:bg-violet-700 disabled:opacity-50"
            >
              {launching === n.id ? "Starting…" : "Run need"}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}
