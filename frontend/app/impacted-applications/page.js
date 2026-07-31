"use client";

import { useEffect, useState } from "react";
import { SeverityBadge } from "../../components/Badge";
import { getImpactedApps } from "../../lib/api";

export default function ImpactedApplicationsPage() {
  const [apps, setApps] = useState([]);

  useEffect(() => { getImpactedApps().then(setApps); }, []);

  return (
    <>
      <div className="page-title">Impacted Applications &amp; Reports</div>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -8, marginBottom: 16 }}>
        Resolved live against report_catalog for the latest validator run -- an application
        only appears here if it actually feeds a real downstream report.
      </p>

      <div className="card">
        <table>
          <thead>
            <tr><th>Application ID</th><th>Report</th><th>Owner Team</th><th>Consumers</th><th>Impact</th><th>Risk</th></tr>
          </thead>
          <tbody>
            {apps.map((a, i) => (
              <tr key={i}>
                <td>{a.application_id}</td>
                <td>{a.report_name} <span style={{ color: "var(--muted)", fontSize: 11 }}>({a.report_id})</span></td>
                <td>{a.report_owner_team}</td>
                <td>{a.consumers}</td>
                <td style={{ maxWidth: 260 }}>{a.impact_description}</td>
                <td><SeverityBadge severity={a.severity} /></td>
              </tr>
            ))}
            {apps.length === 0 && <tr><td colSpan={6} className="empty-state">No applications at risk in the latest run.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
