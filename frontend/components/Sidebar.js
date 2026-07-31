"use client";

import { usePathname } from "next/navigation";
import Link from "next/link";

const NAV = [
  { href: "/", label: "Overview", icon: "🏠" },
  { href: "/analytics", label: "Analytics", icon: "📈" },
  { href: "/issues", label: "Data Quality Issues", icon: "📋" },
  { href: "/recommendations", label: "Recommendations", icon: "💡" },
  { href: "/regulations", label: "Regulations", icon: "📜" },
  { href: "/impacted-applications", label: "Impacted Applications", icon: "🗂️" },
  { href: "/history", label: "History", icon: "🕘" },
  { href: "/datasets", label: "Datasets", icon: "🗄️" },
  { href: "/settings", label: "Settings", icon: "⚙️" },
];

export default function Sidebar() {
  const pathname = usePathname();
  return (
    <aside className="sidebar">
      <div className="brand">
        <div className="brand-icon">🛡️</div>
        <div>
          <div className="brand-title">AI Data Guardian</div>
          <div className="brand-sub">Data Quality &amp; Governance</div>
        </div>
      </div>

      <nav>
        {NAV.map((item) => (
          <Link
            key={item.href}
            href={item.href}
            className={`nav-item ${pathname === item.href ? "active" : ""}`}
          >
            <span>{item.icon}</span>
            <span>{item.label}</span>
          </Link>
        ))}
      </nav>

      <div className="sidebar-footer">
        <strong>Dataset Summary</strong>
        <div className="row"><span>Status</span><span>✅ Ingestion Completed</span></div>
        <div className="row"><span>Powered by</span><span>Vertex AI</span></div>
      </div>
    </aside>
  );
}
