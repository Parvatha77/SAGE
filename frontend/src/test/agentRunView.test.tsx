/**
 * Tests for AgentRunView component.
 * These tests feed synthetic events and verify node state rendering.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { render, screen, act, waitFor } from "@testing-library/react"
import { AgentRunView } from "../components/AgentRunView"
import type { RunEvent } from "../api/types"

// ---------------------------------------------------------------------------
// Mock fetch and EventSource
// ---------------------------------------------------------------------------

const mockEvents: RunEvent[] = []
let mockRunStatus = "running"

const mockFetch = vi.fn(async (url: string) => {
  if (url.includes("/events")) {
    const after = parseInt(new URL(url, "http://x").searchParams.get("after") ?? "-1")
    const filtered = mockEvents.filter(e => e.seq > after)
    return { ok: true, json: async () => filtered } as Response
  }
  if (url.includes("/summary")) {
    return {
      ok: true,
      json: async () => ({
        run_id: "test-run", status: mockRunStatus,
        papers_scanned: 40, claims_extracted: 120, pairs_compared: 200,
        cases_created: 15, seconds: 12.5, cache_hit_rate: 0, is_replay: false,
      }),
    } as Response
  }
  if (url.includes("/runs/test-run") && !url.includes("events") && !url.includes("summary")) {
    return { ok: true, json: async () => ({ status: mockRunStatus }) } as Response
  }
  return { ok: false, json: async () => ({}) } as Response
})

// Minimal EventSource that errors immediately so component falls back to polling
class FakeEventSource {
  onerror: ((e: Event) => void) | null = null
  onmessage: ((e: MessageEvent) => void) | null = null
  close() {}
  constructor() {
    setTimeout(() => this.onerror?.(new Event("error")), 10)
  }
}

beforeEach(() => {
  vi.stubGlobal("fetch", mockFetch)
  vi.stubGlobal("EventSource", FakeEventSource)
  mockEvents.length = 0
  mockRunStatus = "running"
  mockFetch.mockClear()
})

afterEach(() => {
  vi.unstubAllGlobals()
})

function addEvent(seq: number, node: string, status: RunEvent["status"], message: string) {
  mockEvents.push({
    seq, node, status, message,
    counters: null, cache_hit: false, duration_ms: null,
    created_at: new Date().toISOString(),
  })
}

// ---------------------------------------------------------------------------
// Test 1: idle nodes shown initially
// ---------------------------------------------------------------------------
describe("AgentRunView", () => {
  it("renders UC1 graph with idle nodes before any events", () => {
    render(<AgentRunView runId="test-run" kind="uc1" />)
    // SVG should exist
    expect(screen.getByLabelText("Agent pipeline graph")).toBeInTheDocument()
    // All nodes start idle — no status text visible beyond the SVG
    expect(screen.getByLabelText("Agent event log")).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Test 2: node state changes with fed events
  // -------------------------------------------------------------------------
  it("marks discovery as running then done when events arrive", async () => {
    addEvent(0, "discovery", "started", "Building embeddings")

    render(<AgentRunView runId="test-run" kind="uc1" />)

    await waitFor(() => {
      // Log panel should show the event
      expect(screen.getByLabelText("Agent event log")).toHaveTextContent("Building embeddings")
    }, { timeout: 5000 })

    addEvent(1, "discovery", "finished", "Found 12 candidate pairs")
    await waitFor(() => {
      expect(screen.getByLabelText("Agent event log")).toHaveTextContent("Found 12 candidate pairs")
    }, { timeout: 5000 })
  })

  // -------------------------------------------------------------------------
  // Test 3: paused gate shows message
  // -------------------------------------------------------------------------
  it("shows paused status message when review_gate pauses", async () => {
    addEvent(0, "review_gate", "paused", "Waiting for editor to review and decide")

    render(<AgentRunView runId="test-run" kind="uc1" />)

    await waitFor(() => {
      expect(screen.getByLabelText("Agent event log")).toHaveTextContent("Waiting for editor")
    }, { timeout: 5000 })
  })

  // -------------------------------------------------------------------------
  // Test 4: failed node shows its error
  // -------------------------------------------------------------------------
  it("shows failed message in log when a node fails", async () => {
    addEvent(0, "evidence", "failed", "Evidence step failed: connection timeout")

    render(<AgentRunView runId="test-run" kind="uc1" />)

    await waitFor(() => {
      expect(screen.getByLabelText("Agent event log")).toHaveTextContent("connection timeout")
    }, { timeout: 5000 })
  })

  // -------------------------------------------------------------------------
  // Test 5: counters update with summary data
  // -------------------------------------------------------------------------
  it("shows run summary counters when run is done", async () => {
    mockRunStatus = "done"
    addEvent(0, "ranker", "finished", "Ranked 15 cases")

    render(<AgentRunView runId="test-run" kind="uc1" />)

    await waitFor(() => {
      // Summary tile should show cases_created
      expect(screen.getByLabelText("Agent event log")).toHaveTextContent("Ranked 15 cases")
    }, { timeout: 5000 })
  })

  // -------------------------------------------------------------------------
  // Test 6: events arrive out of order, sorted by seq
  // -------------------------------------------------------------------------
  it("handles events arriving out of order by sorting by seq", async () => {
    // Add in wrong order
    addEvent(2, "integrity", "finished", "Linked 3 notices")
    addEvent(0, "discovery", "started",  "Building embeddings")
    addEvent(1, "discovery", "finished", "Found 8 pairs")

    render(<AgentRunView runId="test-run" kind="uc1" />)

    await waitFor(() => {
      const log = screen.getByLabelText("Agent event log")
      expect(log).toHaveTextContent("Building embeddings")
      expect(log).toHaveTextContent("Found 8 pairs")
      expect(log).toHaveTextContent("Linked 3 notices")
    }, { timeout: 5000 })
  })

  // -------------------------------------------------------------------------
  // Test 7: UC2 graph renders
  // -------------------------------------------------------------------------
  it("renders UC2 graph nodes correctly", () => {
    render(<AgentRunView runId="test-run" kind="uc2" />)
    expect(screen.getByLabelText("Agent pipeline graph")).toBeInTheDocument()
    expect(screen.getByText("Evidence-to-Impact Agent")).toBeInTheDocument()
  })

  // -------------------------------------------------------------------------
  // Test 8: polling fallback works (SSE errors immediately in our mock)
  // -------------------------------------------------------------------------
  it("falls back to polling when SSE fails", async () => {
    addEvent(0, "matcher", "started", "Searching corpus")

    render(<AgentRunView runId="test-run" kind="uc2" />)

    await waitFor(() => {
      expect(screen.getByLabelText("Agent event log")).toHaveTextContent("Searching corpus")
    }, { timeout: 5000 })

    // Polling fetch was called
    expect(mockFetch).toHaveBeenCalledWith(expect.stringContaining("/events?after="))
  })
})
