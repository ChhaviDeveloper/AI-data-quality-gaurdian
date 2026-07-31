"use client";

import { useEffect, useState } from "react";
import { SeverityBadge, StatusBadge } from "../../components/Badge";
import RootCauseModal from "../../components/RootCauseModal";
import { getIssues, remediateIssue, acceptIssue, getRootCause } from "../../lib/api";

export default function IssuesPage() {
  const [issues, setIssues] = useState([]);
  const [busyRuleId, setBusyRuleId] = useState(null);
  const [rootCause, setRootCause] = useState({ issue: null, data: null, loading: false });
  const [severityFilter, setSeverityFilter] = useState("All");

  useEffect(() => { getIssues().then(setIssues); }, []);

  async function handleRemediate(issue) {
    setBusyRuleId(issue.rule_id);
    try {
      await remediateIssue(issue.rule_id, issue.run_id);
      setIssues((prev) => prev.map((i) => i.rule_id === issue.rule_id ? { ...i, remediation_status: "In Progress" } : i));
    } finally { setBusyRuleId(null); }
  }

  async function handleAccept(issue) {
    setBusyRuleId(issue.rule_id);
    try {
      await acceptIssue(issue.rule_id, issue.run_id);
      setIssues((prev) => prev.map((i) => i.rule_id === issue.rule_id ? { ...i, remediation_status: "Closed" } : i));
    } finally { setBusyRuleId(null); }
  }

  async function handleRootCause(issue) {
    setRootCause({ issue, data: null, loading: true });
    const data = await getRootCause(issue.rule_id, issue.run_id);
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
              <th>Rule</th><th>Description</th><th>Severity</th><th>Dimension</th>
              <th>Failed / Total</th><th>Recommended Remediation</th><th>Actions</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((issue) => (
              <tr key={issue.rule_id}>
                <td><strong>{issue.rule_id}</strong><br />{issue.rule_name}</td>
                <td style={{ maxWidth: 240 }}>{issue.description}</td>
                <td><SeverityBadge severity={issue.severity} /></td>
                <td>{issue.dimension}</td>
                <td>{Number(issue.failed_count || 0).toLocaleString()} / {Number(issue.total_records || 0).toLocaleString()}</td>
                <td style={{ maxWidth: 220 }}>{issue.recommended_remediation || "--"}</td>
                <td>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
                    <button
                      className="btn btn-primary"
                      disabled={busyRuleId === issue.rule_id || issue.remediation_status === "Closed"}
                      onClick={() => handleRemediate(issue)}
                    >
                      Remediate
                    </button>
                    <button
                      className="btn btn-outline"
                      disabled={busyRuleId === issue.rule_id || issue.remediation_status === "Closed"}
                      onClick={() => handleAccept(issue)}
                    >
                      Accept
                    </button>
                    <button className="btn btn-link" onClick={() => handleRootCause(issue)}>
                      Root Cause
                    </button>
                  </div>
                </td>
                <td><StatusBadge status={issue.remediation_status || "Open"} /></td>
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
