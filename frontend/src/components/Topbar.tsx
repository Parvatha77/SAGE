interface TopbarProps {
  page: string
  title: string
}

export function Topbar({ page, title }: TopbarProps) {
  const breadcrumbs: Record<string, string> = {
    overview: "Intelligence Overview",
    monitor: "Evidence Monitor",
    impact: "Research translation",
    outreach: "Communication workspace",
    evaluation: "Trust, quality and governance",
  }

  return (
    <header className="topbar">
      <div className="crumb">Workspace / {breadcrumbs[page] || title}</div>
      <div className="top-actions">
        <div className="searchbox">
          <span>⌕</span>
          <input placeholder="Search claims, cases, papers…" aria-label="Search" />
        </div>
        <button className="icon-btn" title="Notifications">♧</button>
        <div className="avatar" title="Research team">RT</div>
      </div>
    </header>
  )
}
