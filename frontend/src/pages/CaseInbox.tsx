import { useState } from "react"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { getCases, startRun, getRun } from "../api/client"
import { CaseCard } from "../components/CaseCard"
import { LABEL_DISPLAY } from "../api/types"

const LABELS = ["confirms", "extends", "differs_in_context", "possible_reproducibility_concern", "retraction_impact", "insufficient_information"]

export function CaseInbox() {
  const qc = useQueryClient()
  const [labelFilter, setLabelFilter] = useState("")
  const [stateFilter, setStateFilter] = useState("")
  const [runStatus, setRunStatus] = useState<string | null>(null)

  const cases = useQuery({
    queryKey: ["cases", labelFilter, stateFilter],
    queryFn: () => getCases({
      label: labelFilter || undefined,
      state: stateFilter || undefined,
    }),
  })

  const runMutation = useMutation({
    mutationFn: () => startRun(),
    onSuccess: async (data) => {
      setRunStatus("running")
      const poll = async () => {
        const run = await getRun(data.run_id)
        setRunStatus(run.status)
        if (run.status === "running") setTimeout(poll, 3000)
        else qc.invalidateQueries({ queryKey: ["cases"] })
      }
      setTimeout(poll, 2000)
    },
  })

  return (
    <div className="p-6 space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-lg font-semibold text-gray-800">Case inbox</h1>
        <button
          onClick={() => runMutation.mutate()}
          disabled={runMutation.isPending || runStatus === "running"}
          className="rounded bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
        >
          {runStatus === "running" ? "Running discovery…" : "Run discovery"}
        </button>
      </div>

      {runStatus && runStatus !== "running" && (
        <p className="text-sm text-gray-500">Last run: {runStatus}</p>
      )}

      {/* Filters */}
      <div className="flex flex-wrap gap-3">
        <select
          value={labelFilter}
          onChange={e => setLabelFilter(e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
          aria-label="Filter by label"
        >
          <option value="">All labels</option>
          {LABELS.map(l => (
            <option key={l} value={l}>{LABEL_DISPLAY[l]}</option>
          ))}
        </select>
        <select
          value={stateFilter}
          onChange={e => setStateFilter(e.target.value)}
          className="rounded border border-gray-300 px-2 py-1 text-sm"
          aria-label="Filter by state"
        >
          <option value="">All states</option>
          <option value="ready_for_review">Ready for review</option>
          <option value="decided">Decided</option>
        </select>
        {(labelFilter || stateFilter) && (
          <button
            onClick={() => { setLabelFilter(""); setStateFilter("") }}
            className="text-xs text-blue-600 hover:underline"
          >
            Clear filters
          </button>
        )}
      </div>

      {/* List */}
      {cases.isLoading && <p className="text-sm text-gray-400">Loading…</p>}
      {cases.isError && <p className="text-sm text-red-500">Failed to load cases.</p>}
      {cases.data?.length === 0 && <p className="text-sm text-gray-400">No cases match your filters.</p>}
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {cases.data?.map(c => <CaseCard key={c.id} c={c} />)}
      </div>
    </div>
  )
}
