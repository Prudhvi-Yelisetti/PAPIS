import { useState } from "react";
import Dashboard from "./pages/Dashboard";
import Inbox     from "./pages/Inbox";
import Projects  from "./pages/Projects";
import Analytics from "./pages/Analytics";

type Page = "dashboard" | "inbox" | "projects" | "analytics";

const NAV: { id: Page; label: string; icon: string }[] = [
  { id: "dashboard", label: "Dashboard", icon: "ti-layout-dashboard" },
  { id: "inbox",     label: "Inbox",     icon: "ti-inbox"            },
  { id: "projects",  label: "Projects",  icon: "ti-folder"           },
  { id: "analytics", label: "Analytics", icon: "ti-chart-bar"        },
];

export default function App() {
  const [page, setPage] = useState<Page>("dashboard");

  return (
    <div className="app-shell">
      <nav className="sidebar-nav">
        <div className="nav-logo">
          <span className="nav-logo__icon">◈</span>
          <span className="nav-logo__text">PAPIS</span>
        </div>
        <ul>
          {NAV.map(n => (
            <li key={n.id}>
              <button
                className={`nav-item ${page === n.id ? "nav-item--active" : ""}`}
                onClick={() => setPage(n.id)}
              >
                <i className={`ti ${n.icon}`} aria-hidden="true" />
                {n.label}
              </button>
            </li>
          ))}
        </ul>
      </nav>

      <div className="main-content">
        {page === "dashboard" && <Dashboard />}
        {page === "inbox"     && <Inbox     />}
        {page === "projects"  && <Projects  />}
        {page === "analytics" && <Analytics />}
      </div>
    </div>
  );
}