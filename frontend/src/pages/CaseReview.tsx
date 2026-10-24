import { useState } from "react"
import { useParams, Link } from "react-router-dom"
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query"
import { getCase, getAssessment, postDecision } from "../api/client"
import { LABEL_DISPLAY } from "../api/types"
import { LabelChip } from "../components/LabelChip"
import { DiffTable } from "../components/DiffTable"
import { Meter } from "../components/Meter"
import { AuditTrail } from "../components/AuditTrail"
import { DecisionForm } from "../components/DecisionForm"
import { Copilot } from "../components/Copilot"

export function CaseReview() {
  const { id } = useParams<{ id: string }>()
  const qc = useQueryClient()
  const [decisionError, setDecisionError] = useState<string | null>(null)

  const caseQ = useQuery({ queryKey: ["case", id], queryFn: () => getCase(id!) })
  const assessQ = useQuery({ queryKey: ["assessment", id], queryFn: () => getAssessment(id!) })

  const decisionMutation = useMutation({
    mutationFn: (data: Parameters<typeof postDecision>[1]) => postDecision(id!, data),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["case", id] }),
    onError: (err: any) => {
      const msg = err?.response?.data?.detail ?? "Failed to record decision."
      setDecisionError(typeof msg === "string" ? msg : JSON.stringify(msg))
    },
  })

  if (caseQ.isLoading) return <div className="p-8 text-gray-400">Loading…</div>
  if (caseQ.isError) return <div className="p-8 text-red-500">Case not found.</div>

  const c = caseQ.data!
  const a = assessQ.data

  const suggestedNext = c.next_step || "Review the source sentences and field comparisons, then record a decision."

  return (
    <div className="mx-auto max-w-4xl space-y-6 p-6">
      {/* Header */}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link to="/cases" className="text-xs text-blue-600 hover:underline">← Cases</Link>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            <LabelChip label={c.label} />
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
              {c.confidence ?? "—"} confidence
            </span>
            <span className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-500">
              Priority {c.priority_score?.toFixed(1) ?? "—"}
            </span>
            {c.state === "decided" && (
              <span className="rounded-full bg-green-100 px-2 py-0.5 text-xs text-green-700">Decided</span>
            )}
            {c.needs_human_attention && (
              <span className="rounded-full bg-orange-100 px-2 py-0.5 text-xs text-orange-700">⚠ Attention needed</span>
            )}
          </div>
          <p className="mt-1 text-xs text-gray-400">{c.id}</p>
        </div>
      </div>

      {/* Suggested next step */}
      <div className="rounded border-l-4 border-blue-400 bg-blue-50 px-4 py-2 text-sm text-blue-800">
        <strong>Suggested next step:</strong> {suggestedNext}
      </div>

      {/* Source sentences side by side */}
      <Section title="Source sentences">
        <div className="grid gap-4 sm:grid-cols-2">
          <ClaimBox title="Anchor" claim={c.anchor_claim} />
          <ClaimBox title="New" claim={c.new_claim} />
        </div>
      </Section>

      {/* Field comparisons */}
      <Section title="Field comparisons">
        <DiffTable comparisons={c.field_comparisons} />
      </Section>

      {/* Rationale */}
      {c.rationale && (
        <Section title="Rationale">
          <p className="text-sm text-gray-700">{c.rationale}</p>
        </Section>
      )}

      {/* Assessment meters */}
      {a && (
        <Section title="Assessment">
          <div className="flex flex-wrap gap-6">
            <Meter label="Population match" value={a.population_match} />
            <Meter label="Design match" value={a.design_match} />
            <Meter label="Outcome match" value={a.outcome_match} />
            <Meter label="Relative sample" value={a.relative_sample_strength} />
            <Meter label="Integrity risk" value={a.integrity_risk} />
          </div>
        </Section>
      )}

      {/* Skeptic */}
      {c.skeptic_verdict && (
        <Section title="Skeptic review">
          <p className="text-sm">
            <strong>Verdict:</strong> {c.skeptic_verdict}
            {c.alternative_label && <> → suggested: <em>{LABEL_DISPLAY[c.alternative_label] ?? c.alternative_label}</em></>}
          </p>
          {c.skeptic_argument && <p className="mt-1 text-sm text-gray-600">{c.skeptic_argument}</p>}
        </Section>
      )}

      {/* Affected papers */}
      {c.affected_items.length > 0 && (
        <Section title="Affected papers">
          <ul className="space-y-1 text-sm">
            {c.affected_items.map(item => (
              <li key={item.paper_id} className="flex items-center gap-2">
                <span className="rounded bg-gray-100 px-1.5 py-0.5 text-xs text-gray-600">
                  {item.relation ?? "related"}
                </span>
                <span className="truncate text-gray-700">{item.paper_id.split("/").pop()}</span>
                <span className="ml-auto text-xs text-gray-400">score {item.score?.toFixed(1)}</span>
              </li>
            ))}
          </ul>
        </Section>
      )}

      {/* Evidence timeline */}
      {c.evidence_timeline.length > 0 && (
        <Section title="Evidence timeline">
          <ol className="relative border-l border-gray-200 ml-2 space-y-3">
            {c.evidence_timeline.map(item => (
              <li key={item.paper_id} className="ml-4">
                <span className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border border-white bg-gray-300" />
                <div className="flex items-baseline gap-2">
                  <span className="text-xs font-semibold text-gray-500 w-10 shrink-0">{item.year ?? "?"}</span>
                  <span className="text-sm text-gray-800 truncate">{item.title ?? item.paper_id.split("/").pop()}</span>
                  <span className="ml-auto shrink-0 rounded-full bg-gray-100 px-1.5 py-0.5 text-xs text-gray-500">
                    {item.relation ?? "related"}
                  </span>
                </div>
              </li>
            ))}
          </ol>
        </Section>
      )}

      {/* Copilot */}
      <Section title="Copilot">
        <Copilot caseId={c.id} />
      </Section>

      {/* Decision */}
      <Section title="Decision">
        {c.decision ? (
          <div className="rounded border bg-green-50 p-4 text-sm">
            <p><strong>Action:</strong> {c.decision.action.replace(/_/g, " ")}</p>
            <p><strong>Reason:</strong> {c.decision.reason}</p>
            <p><strong>Decided by:</strong> {c.decision.decided_by}</p>
            <p className="text-xs text-gray-400">{new Date(c.decision.decided_at).toLocaleString()}</p>
          </div>
        ) : (
          <DecisionForm
            caseId={c.id}
            affectedItems={c.affected_items}
            onSubmit={data => decisionMutation.mutateAsync(data)}
            error={decisionError}
          />
        )}
      </Section>

      {/* Audit trail */}
      <Section title="Audit trail">
        <AuditTrail events={c.audit_events} />
      </Section>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border bg-white p-4">
      <h2 className="mb-3 text-sm font-semibold text-gray-700">{title}</h2>
      {children}
    </div>
  )
}

function ClaimBox({ title, claim }: { title: string; claim: { claim_text: string; source_sentence: string; paper_title?: string | null } | null }) {
  if (!claim) return <div className="rounded border border-dashed border-gray-200 p-3 text-sm text-gray-400">No claim</div>
  return (
    <div className="rounded border border-gray-200 p-3 space-y-2">
      <p className="text-xs font-semibold text-gray-500 uppercase">{title}</p>
      {claim.paper_title && <p className="text-xs text-gray-400 truncate">{claim.paper_title}</p>}
      <blockquote className="border-l-2 border-gray-300 pl-2 text-sm italic text-gray-600">
        "{claim.source_sentence}"
      </blockquote>
      <p className="text-sm text-gray-800">{claim.claim_text}</p>
    </div>
  )
}
