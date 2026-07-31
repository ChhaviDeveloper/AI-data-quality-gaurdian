"use client";

import { useEffect, useState } from "react";
import TopBar from "../components/TopBar";
import ScoreDonut from "../components/ScoreDonut";
import { SeverityBadge, StatusBadge } from "../components/Badge";
import RootCauseModal from "../components/RootCauseModal";
import {
  getOverview, getIssues, getRegulations, getImpactedApps, getHistory,
  remediateIssue, acceptIssue, getRootCause,
} from "../lib/api";

export default function OverviewPage() {
  const [overview, setOverview] = useState(null);
  const [issues, setIssues] = useState([]);
  const [regulations, setRegulations] = useState([]);
  const [apps, setApps] = useState([]);
  const [history, setHistory] = useState([]);
  const [busyRuleId, setBusyRuleId] = useState(null);
  const [rootCause, setRootCause] = useState({ issue: null, data: null, loading: false });

  async function loadAll() {
    const [ov, is, regs, ap, hist] = await Promise.all([
      getOverview(), getIssues(), getRegulations(), getImpactedApps(), getHistory(),
    ]);
    setOverview(ov);
    setIssues(is);
    setRegulations(regs);
    setApps(ap);
    setHistory(hist);
  }

  useEffect(() => { loadAll(); }, []);

  async function handleRemediate(issue) {
    setBusyRuleId(issue.rule_id);
    try {
      await remediateIssue(issue.rule_id, issue.run_id);
      setIssues((prev) => prev.map((i) => i.rule_id === issue.rule_id ? { ...i, remediation_status: "In Progress" } : i));
    } finally {
      setBusyRuleId(null);
    }
  }

  async function handleAccept(issue) {
    setBusyRuleId(issue.rule_id);
    try {
      await acceptIssue(issue.rule_id, issue.run_id);
      setIssues((prev) => prev.map((i) => i.rule_id === issue.rule_id ? { ...i, remediation_status: "Closed" } : i));
    } finally {
      setBusyRuleId(null);
    }
  }

  async function handleRootCause(issue) {
    setRootCause({ issue, data: null, loading: true });
    const data = await getRootCause(issue.rule_id, issue.run_id);
    setRootCause({ issue, data, loading: false });
  }

  const pre = overview?.confidence?.pre_confidence_score ?? 0;
  const post = overview?.confidence?.post_confidence_score ?? 0;
  const improvement = post - pre;
  const totals = overview?.issue_totals || { total: 0, open: 0, closed: 0 };
  const buckets = overview?.buckets || {};

  return (
    <>
      <TopBar dataset={overview?.dataset} />

      <div className="grid grid-3">
        <div className="card">
          <div className="card-title">Pre Data Confidence Score ⓘ</div>
          <div className="score-row">
            <ScoreDonut pct={pre} />
            <p style={{ fontSize: 13, color: "var(--muted)" }}>
              Vertex AI has analyzed your data and identified quality issues affecting confidence.
            </p>
          </div>
        </div>

        <div className="card">
          <div className="card-title">Data Quality Overview ⓘ</div>
          <div className="grid grid-4" style={{ gap: 10 }}>
            <div className="tile">
              <div className="num" style={{ color: "var(--red)" }}>{totals.total}</div>
              <div className="name">Total Issues</div>
              <div className="oc">Open: {totals.open} | Closed: {totals.closed}</div>
            </div>
            <div className="tile">
              <div className="num" style={{ color: "var(--red)" }}>{(buckets.critical?.open || 0) + (buckets.critical?.closed || 0)}</div>
              <div className="name">Critical Issues</div>
              <div className="oc">Open: {buckets.critical?.open || 0} | Closed: {buckets.critical?.closed || 0}</div>
            </div>
            <div className="tile">
              <div className="num" style={{ color: "var(--orange)" }}>{(buckets.warning?.open || 0) + (buckets.warning?.closed || 0)}</div>
              <div className="name">Warnings</div>
              <div className="oc">Open: {buckets.warning?.open || 0} | Closed: {buckets.warning?.closed || 0}</div>
            </div>
            <div className="tile">
              <div className="num" style={{ color: "var(--green)" }}>{(buckets.info?.open || 0) + (buckets.info?.closed || 0)}</div>
              <div className="name">Info</div>
              <div className="oc">Open: {buckets.info?.open || 0} | Closed: {buckets.info?.closed || 0}</div>
            </div>
          </div>
        </div>

        <div className="card">
          <div className="card-title">Post Data Confidence Score ⓘ</div>
          <div className="score-row">
            <ScoreDonut pct={post} />
            <div>
              <p style={{ fontSize: 13, color: "var(--muted)", marginBottom: 6 }}>
                Great job! Issues resolved successfully and data quality has improved.
              </p>
              {improvement !== 0 && (
                <span className="badge badge-closed">
                  {improvement > 0 ? "+" : ""}{Math.round(improvement)}% Improvement
                </span>
              )}
            </div>
          </div>
        </div>
      </div>

      <div className="two-col section">
        <div className="card">
          <div className="card-title">Data Quality Issues</div>
          <table>
            <thead>
              <tr>
                <th>Issue Type</th><th>Description</th><th>Severity</th>
                <th>Recommended Remediation</th><th>Actions</th><th>Status</th>
              </tr>
            </thead>
            <tbody>
              {issues.slice(0, 6).map((issue) => (
                <tr key={issue.rule_id}>
                  <td>{issue.issue_type || issue.dimension}</td>
                  <td>{issue.description}</td>
                  <td><SeverityBadge severity={issue.severity} /></td>
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
              {issues.length === 0 && (
                <tr><td colSpan={6} className="empty-state">No open issues.</td></tr>
              )}
            </tbody>
          </table>
          <div style={{ marginTop: 8, fontSize: 12, color: "var(--muted)" }}>
            Showing {Math.min(issues.length, 6)} of {issues.length} issues
          </div>
        </div>

        <div className="card">
          <div className="card-title">Applicable Laws &amp; Regulations ⓘ</div>
          <table>
            <thead><tr><th>Regulation</th><th>Applies To</th></tr></thead>
            <tbody>
              {regulations.slice(0, 6).map((r) => (
                <tr key={r.regulation_code}>
                  <td><strong>{r.regulation_code}</strong><br /><span style={{ color: "var(--muted)", fontSize: 11 }}>{r.regulation_name}</span></td>
                  <td>{r.data_category}</td>
                </tr>
              ))}
              {regulations.length === 0 && (
                <tr><td colSpan={2} className="empty-state">No regulations mapped yet.</td></tr>
              )}
            </tbody>
          </table>

          <div className="card-title" style={{ marginTop: 18 }}>Applications / Reports at Risk ⚠</div>
          <table>
            <thead><tr><th>Application / Report</th><th>Impact</th><th>Risk</th></tr></thead>
            <tbody>
              {apps.slice(0, 5).map((a, i) => (
                <tr key={i}>
                  <td>{a.report_name || a.application_id}</td>
                  <td>{a.impact_description}</td>
                  <td><SeverityBadge severity={a.severity} /></td>
                </tr>
              ))}
              {apps.length === 0 && (
                <tr><td colSpan={3} className="empty-state">No applications at risk.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>

      <div className="card section">
        <div className="card-title">History &amp; Activity Log</div>
        <table>
          <thead><tr><th>Time</th><th>Event</th><th>Description</th><th>Actor</th><th>Status</th></tr></thead>
          <tbody>
            {history.slice(0, 5).map((h, i) => (
              <tr key={i}>
                <td>{h.event_time ? new Date(h.event_time).toLocaleString() : "--"}</td>
                <td>{h.event_type}</td>
                <td>{h.description}</td>
                <td>{h.actor}</td>
                <td>{h.status ? <StatusBadge status={h.status} /> : "--"}</td>
              </tr>
            ))}
            {history.length === 0 && (
              <tr><td colSpan={5} className="empty-state">No activity yet.</td></tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="footer-note">✨ Powered by Vertex AI -- Intelligent analysis, recommendations and automated remediation for trusted data.</div>

      <RootCauseModal
        issue={rootCause.issue}
        data={rootCause.data}
        loading={rootCause.loading}
        onClose={() => setRootCause({ issue: null, data: null, loading: false })}
      />
    </>
  );
}
