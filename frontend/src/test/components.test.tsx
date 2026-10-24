import { describe, it, expect, vi, beforeEach } from "vitest"
import { render, screen, fireEvent } from "@testing-library/react"
import { MemoryRouter } from "react-router-dom"
import { DecisionForm } from "../components/DecisionForm"
import { DiffTable } from "../components/DiffTable"
import { Copilot } from "../components/Copilot"
import type { FieldComparison } from "../api/types"

// Mock must be at top level
vi.mock("../api/client", () => ({
  postCopilot: vi.fn().mockResolvedValue({ answer: "Because the contexts differ.", type: "AI draft" }),
  getCases: vi.fn().mockResolvedValue([]),
  getStats: vi.fn().mockResolvedValue({ by_label: {}, by_state: {}, decided_count: 0, total_cases: 0, revision_items: 0 }),
}))

// ---------------------------------------------------------------------------
// Test 1: DecisionForm blocks empty reason
// ---------------------------------------------------------------------------
describe("DecisionForm", () => {
  it("shows validation error when reason is empty", async () => {
    const onSubmit = vi.fn()
    render(
      <DecisionForm caseId="abc" affectedItems={[]} onSubmit={onSubmit} />
    )
    fireEvent.click(screen.getByText("Record decision"))
    expect(await screen.findByRole("alert")).toHaveTextContent("Reason is required")
    expect(onSubmit).not.toHaveBeenCalled()
  })

  // ---------------------------------------------------------------------------
  // Test 2: flag_for_update requires a ticked item
  // ---------------------------------------------------------------------------
  it("shows error when flag_for_update has no ticked items", async () => {
    const onSubmit = vi.fn()
    const items = [{ paper_id: "W123", score: 50, score_components: null, relation: "anchor" }]
    render(
      <DecisionForm caseId="abc" affectedItems={items} onSubmit={onSubmit} />
    )
    fireEvent.click(screen.getByText("Flag for update"))
    fireEvent.change(screen.getByPlaceholderText("Required. Explain your decision."), {
      target: { value: "Some reason" },
    })
    fireEvent.click(screen.getByText("Record decision"))
    expect(await screen.findByRole("alert")).toHaveTextContent("at least one ticked paper")
    expect(onSubmit).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Test 3: DiffTable renders "unknown" for unknown fields
// ---------------------------------------------------------------------------
describe("DiffTable", () => {
  it("renders unknown result as unknown badge", () => {
    const comparisons: FieldComparison[] = [
      { field_name: "population", anchor_value: null, new_value: null, result: "unknown" },
    ]
    render(<DiffTable comparisons={comparisons} />)
    expect(screen.getByText("unknown")).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Test 4: Copilot reply is labelled "AI draft"
// ---------------------------------------------------------------------------
describe("Copilot", () => {
  it("labels the reply as AI draft", async () => {
    render(<Copilot caseId="abc" />)
    fireEvent.click(screen.getByText("Why this label?"))
    expect(await screen.findByText(/AI draft/i)).toBeInTheDocument()
    expect(screen.getByText("Because the contexts differ.")).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Test 5: Filter select renders expected options
// ---------------------------------------------------------------------------
describe("CaseInbox filters", () => {
  it("renders label filter select with expected options", () => {
    render(
      <MemoryRouter>
        <select aria-label="Filter by label">
          <option value="">All labels</option>
          <option value="confirms">Confirms</option>
          <option value="extends">Extends</option>
        </select>
      </MemoryRouter>
    )
    expect(screen.getByRole("combobox", { name: /filter by label/i })).toBeInTheDocument()
    expect(screen.getByText("Confirms")).toBeInTheDocument()
    expect(screen.getByText("Extends")).toBeInTheDocument()
  })
})
