import axios from "axios"
import type {
  AssessmentOut, CaseDetail, CaseListItem, RevisionItem,
  RunResponse, StatsOut,
} from "./types"

const BASE = import.meta.env.VITE_API_URL ?? "http://localhost:8000"

const api = axios.create({ baseURL: BASE })

export const getCases = (params?: {
  label?: string
  state?: string
  attention?: boolean
  category?: string
}) => api.get<CaseListItem[]>("/cases", { params }).then(r => r.data)

export const getCase = (id: string) =>
  api.get<CaseDetail>(`/cases/${id}`).then(r => r.data)

export const getAssessment = (id: string) =>
  api.get<AssessmentOut>(`/cases/${id}/assessment`).then(r => r.data)

export const postDecision = (
  id: string,
  body: { action: string; reason: string; decided_by: string; flagged_paper_ids?: string[] }
) => api.post(`/cases/${id}/decision`, body).then(r => r.data)

export const postCopilot = (id: string, body: { preset?: string; question?: string }) =>
  api.post<{ answer: string; type: string }>(`/cases/${id}/copilot`, body).then(r => r.data)

export const draftAuthorMessage = (id: string) =>
  api.post<{ draft: string }>(`/cases/${id}/draft-author-message`).then(r => r.data)

export const getStats = () => api.get<StatsOut>("/stats").then(r => r.data)

export const getRevisionItems = () =>
  api.get<RevisionItem[]>("/revision-items").then(r => r.data)

export const startRun = (limit?: number) =>
  api.post<RunResponse>("/runs", { limit }).then(r => r.data)

export const getRun = (id: string) =>
  api.get<{ run_id: string; status: string; cases_created: number }>(`/runs/${id}`).then(r => r.data)

export const getNeeds = () =>
  api.get<{ id: string; title: string; state: string; is_example: boolean }[]>("/needs").then(r => r.data)

export const startNeedRun = (needId: string) =>
  api.post<{ run_id: string; need_id: string; status: string }>(`/needs/${needId}/run`).then(r => r.data)

export const startDemoRun = (category?: string) =>
  api.post<{ run_id: string; status: string; demo_papers: number }>("/demo/run", { category }).then(r => r.data)

export const copilotAnalyze = (caseId: string, question: string) =>
  api.post<{ analysis: string }>("/copilot/analyze", { case_id: caseId, question }).then(r => r.data)

export const copilotGenerateBrief = (needId: string, caseIds: string[], audience?: string) =>
  api.post<{ brief: string; summary: string }>("/copilot/generate-brief", {
    need_id: needId,
    case_ids: caseIds,
    target_audience: audience || "policy makers"
  }).then(r => r.data)
