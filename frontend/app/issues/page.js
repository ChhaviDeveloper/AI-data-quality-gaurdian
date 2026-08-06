"use client";

import { useEffect, useState } from "react";
import { SeverityBadge, StatusBadge } from "../../components/Badge";
import RootCauseModal from "../../components/RootCauseModal";
import { getIssues, remediateIssue, ignoreIssue, getRootCause } from "../../lib/api";

export default function IssuesPage() {
  const [issues, setIssues] = useState([]);
  const [busyKey, setBusyKey] = useState(null);
  const [rootCause, setRootCause] = useState({ issue: null, data: null, loading: false });
  const [severityFilter, setSeverityFilter] = useState("All");

  useEffect(() => { getIssues().then(setIssues); }, []);

  function issueKey(issue) {
    return `${issue.rule_id}::${issue.application_id || ""}`;
  }

  async function handleRemediate(issue) {
    const key = issueKey(issue);
    setBusyKey(key);
    try {
      const result = await remediateIssue(issue.rule_id, issue.run_id, issue.application_id);
      setIssues((prev) => prev.map((i) => issueKey(i) === key ? {
        ...i,
        remediation_status: "In Progress",
        last_notified_email: result?.notified_email,
        last_notification_status: result?.notification_status,
      } : i));
    } finally { setBusyKey(null); }
  }

  async function handleIgnore(issue) {
    const key = issueKey(issue);
    setBusyKey(key);
    try {
      await ignoreIssue(issue.rule_id, issue.run_id, issue.application_id);
      setIssues((prev) => prev.map((i) => issueKey(i) === key ? { ...i, remediation_status: "Closed" } : i));
    } finally { setBusyKey(null); }
  }

  async function handleRootCause(issue) {
    setRootCause({ issue, data: null, loading: true });
    const data = await getRootCause(issue.rule_id, issue.run_id, issue.application_id);
    setRootCause({ issue, data, loading: false });
  }

  const filtered = severityFilter === "All" ? issues : issues.filter((i) => i.severity === severityFilter);

  return (
    <>
      <div className="page-title">Data Quality Issues</div>

      <div className="card">
        <div style={{ display: "flex", gap: 8, marginBottom: 12 }}>
          {["All", "Critical", "High", "Medium", "Low"].map((s) => (
            <button
              key={s}
              className={`btn ${severityFilter === s ? "btn-primary" : "btn-outline"}`}
              onClick={() => setSeverityFilter(s)}
            >
              {s}
            </button>
          ))}
        </div>

        <table>
          <thead>
            <tr>
              <th>Rule</th><th>Application</th><th>Description</th><th>Severity</th><th>Dimension</th>
              <th>Recommended Remediation</th><th>Actions</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((issue) => (
              <tr key={issueKey(issue)}>
                <td><strong>{issue.rule_id}</strong><br />{issue.rule_name}</td>
                <td>{issue.application_name || issue.application_id || "--"}</td>
                <td style={{ maxWidth: 240 }}>{issue.description}</td>
                <td><SeverityBadge severity={issue.severity} /></td>
                <td>{issue.dimension}</td>
                <td style={{ maxWidth: 220 }}>{issue.recommended_remediation || "--"}</td>
                <td>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <button
                      className="btn btn-primary"
                      disabled={busyKey === issueKey(issue) || issue.remediation_status === "Closed"}
                      onClick={() => handleRemediate(issue)}
                    >
                      Remediate
                    </button>
                    <button
                      className="btn btn-outline"
                      disabled={busyKey === issueKey(issue) || issue.remediation_status === "Closed"}
                      onClick={() => handleIgnore(issue)}
                    >
                      Ignore
                    </button>
                    <button className="btn btn-link" onClick={() => handleRootCause(issue)}>
                      Root Cause
                    </button>
                  </div>
                </td>
                <td>
                  <StatusBadge status={issue.remediation_status || "Open"} />
                  {issue.last_notified_email && (
                    <div
                      style={{ fontSize: 11, color: "var(--muted)", marginTop: 4 }}
                      title={issue.last_notification_status || ""}
                    >
                      {issue.last_notification_status === "Sent" ? "✉ Notified: " : "✉ "}
                      {issue.last_notified_email}
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {filtered.length === 0 && (
              <tr><td colSpan={8} className="empty-state">No issues match this filter.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <RootCauseModal
        issue={rootCause.issue}
        data={rootCause.data}
        loading={rootCause.loading}
        onClose={() => setRootCause({ issue: null, data: null, loading: false })}
      />
    </>
  );
}
