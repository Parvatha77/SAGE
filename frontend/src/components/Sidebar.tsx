type Page = "overview" | "monitor" | "impact" | "outreach" | "evaluation"

interface SidebarProps {
  currentPage: Page
  onNavigate: (page: Page) => void
}

export function Sidebar({ currentPage, onNavigate }: SidebarProps) {
  const navItems: Array<{ page: Page; icon: string; label: string; badge?: number }> = [
    { page: "overview", icon: "▦", label: "Intelligence Overview" },
    { page: "monitor", icon: "⌕", label: "Evidence Monitor", badge: 18 },
    { page: "impact", icon: "◎", label: "Impact Studio" },
    { page: "outreach", icon: "✉", label: "Outreach Workspace" },
  ]

  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-mark">S</div>
        <div>
          <div className="brand-name">SAGE Research</div>
          <div className="brand-sub">Intelligence platform</div>
        </div>
      </div>

      <div>
        <div className="nav-group-label">Workspace</div>
        <nav className="nav" aria-label="Main navigation">
          {navItems.map((item) => (
            <button
              key={item.page}
              className={currentPage === item.page ? "active" : ""}
              onClick={() => onNavigate(item.page)}
            >
              <span className="nav-icon">{item.icon}</span>
              {item.label}
              {item.badge && <span className="badge" style={{ marginLeft: "auto", background: "#DCEBE8", color: "#1C5B57" }}>{item.badge}</span>}
            </button>
          ))}
        </nav>
      </div>

      <div>
        <div className="nav-group-label">Governance</div>
        <nav className="nav">
          <button onClick={() => onNavigate("evaluation")}>
            <span className="nav-icon">▥</span>
            Evaluation & Audit
          </button>
        </nav>
      </div>

      <div className="sidebar-bottom">
        <div className="demo-note">
          <strong>Prototype environment</strong>
          Live discovery and email delivery require connected services.
        </div>
      </div>
    </aside>
  )
}
