import { useState } from "react"
import "./App.css"
import { Sidebar } from "./components/Sidebar"
import { Topbar } from "./components/Topbar"
import { CopilotPanel } from "./components/CopilotPanel"
import { Overview } from "./pages/Overview"
import { Monitor } from "./pages/Monitor"
import { Impact } from "./pages/Impact"
import { Outreach } from "./pages/Outreach"
import { Evaluation } from "./pages/Evaluation"

type Page = "overview" | "monitor" | "impact" | "outreach" | "evaluation"

export default function App() {
  const [page, setPage] = useState<Page>("overview")
  const [copilotOpen, setCopilotOpen] = useState(false)
  const [copilotCaseId, setCopilotCaseId] = useState("")

  const getPageTitle = () => {
    const titles: Record<Page, string> = {
      overview: "Intelligence Overview",
      monitor: "Evidence Monitor",
      impact: "Real-World Impact Studio",
      outreach: "Outreach Workspace",
      evaluation: "Evaluation & Audit",
    }
    return titles[page]
  }

  const openCopilot = (caseId: string) => {
    setCopilotCaseId(caseId)
    setCopilotOpen(true)
  }

  return (
    <div className="app">
      <div className="layout">
        <Sidebar currentPage={page} onNavigate={setPage} />
        <main className="main">
          <Topbar page={page} title={getPageTitle()} />
          <div className="content">
            {page === "overview" && <Overview />}
            {page === "monitor" && <Monitor onCopilot={openCopilot} />}
            {page === "impact" && <Impact onCopilot={openCopilot} />}
            {page === "outreach" && <Outreach />}
            {page === "evaluation" && <Evaluation />}
          </div>
        </main>
      </div>
      {/* Full-screen copilot side panel */}
      <CopilotPanel
        caseId={copilotCaseId}
        isOpen={copilotOpen}
        onClose={() => setCopilotOpen(false)}
      />
    </div>
  )
}
