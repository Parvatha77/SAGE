// Hand-written types from FastAPI OpenAPI schema

export interface RunEvent {
  seq: number
  node: string
  status: "started" | "progress" | "finished" | "paused" | "failed"
  message: string
  counters: Record<string, number> | null
  cache_hit: boolean
  duration_ms: number | null
  created_at: string
}

export interface RunSummary {
  run_id: string
  status: string
  papers_scanned: number
  claims_extracted: number
  pairs_compared: number
  cases_created: number
  seconds: number
  cache_hit_rate: number
  is_replay: boolean
}

export type AgentGraphKind = "uc1" | "uc2"

export interface CaseListItem {
  id: string
  label: string
  confidence: string | null
  priority_score: number | null
  state: string
  needs_human_attention: boolean
  skeptic_verdict: string | null
}

export interface FieldComparison {
  field_name: string
  anchor_value: string | null
  new_value: string | null
  result: "similar" | "differs" | "unknown"
}

export interface AffectedItem {
  paper_id: string
  score: number | null
  score_components: Record<string, number> | null
  relation: string | null
}

export interface AuditEvent {
  actor: string
  event: string
  detail: string | null
  created_at: string
}

export interface ClaimOut {
  id: string
  claim_text: string
  source_sentence: string
  paper_id: string
  paper_title: string | null
  direction: string | null
  population: string | null
  design: string | null
  outcome_measure: string | null
  sample_size: number | null
  country_or_setting: string | null
  follow_up: string | null
}

export interface DecisionOut {
  action: string
  reason: string
  decided_by: string
  decided_at: string
  flagged_paper_ids: string[]
}

export interface EvidenceTimelineItem {
  year: number | null
  paper_id: string
  title: string | null
  relation: string | null
}

export interface CaseDetail {
  id: string
  label: string
  confidence: string | null
  rationale: string | null
  priority_score: number | null
  state: string
  needs_human_attention: boolean
  skeptic_verdict: string | null
  alternative_label: string | null
  skeptic_argument: string | null
  anchor_claim: ClaimOut | null
  new_claim: ClaimOut | null
  field_comparisons: FieldComparison[]
  affected_items: AffectedItem[]
  audit_events: AuditEvent[]
  decision: DecisionOut | null
  has_integrity_notice: boolean
  evidence_timeline: EvidenceTimelineItem[]
  next_step: string
}

export interface AssessmentOut {
  population_match: string
  design_match: string
  outcome_match: string
  relative_sample_strength: string
  integrity_risk: string
}

export interface StatsOut {
  by_label: Record<string, number>
  by_state: Record<string, number>
  decided_count: number
  total_cases: number
  revision_items: number
}

export interface RevisionItem {
  id: string
  case_id: string
  paper_id: string
  where_text: string | null
  note: string | null
  created_at: string
}

export interface RunResponse {
  run_id: string
  status: string
}

export const LABEL_DISPLAY: Record<string, string> = {
  confirms: "Confirms",
  extends: "Extends",
  differs_in_context: "Differs in context",
  possible_reproducibility_concern: "Possible reproducibility concern",
  retraction_impact: "Retraction impact",
  insufficient_information: "Insufficient information",
  unrelated: "Unrelated",
}

export const LABEL_COLOR: Record<string, string> = {
  confirms: "bg-green-100 text-green-800",
  extends: "bg-blue-100 text-blue-800",
  differs_in_context: "bg-yellow-100 text-yellow-800",
  possible_reproducibility_concern: "bg-orange-100 text-orange-800",
  retraction_impact: "bg-red-100 text-red-800",
  insufficient_information: "bg-gray-100 text-gray-600",
  unrelated: "bg-gray-100 text-gray-400",
}
