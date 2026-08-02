"use client";

import { useEffect, useState } from "react";
import {
  LineChart, Line, BarChart, Bar, Cell, XAxis, YAxis, CartesianGrid, Tooltip, Legend, ResponsiveContainer,
} from "recharts";
import { getAnalyticsTrend, getAnalyticsIssueOverview } from "../../lib/api";

const EMBED_URL = process.env.NEXT_PUBLIC_LOOKER_EMBED_URL || "";
const SEVERITY_COLOR = { Critical: "#e5484d", High: "#f2994a", Medium: "#f2c94c", Low: "#27ae60" };

export default function AnalyticsPage() {
  const [trend, setTrend] = useState([]);
  const [overview, setOverview] = useState([]);

  useEffect(() => {
    getAnalyticsTrend().then((rows) =>
      setTrend(rows.map((r) => ({
        ...r,
        run_label: r.run_timestamp ? new Date(r.run_timestamp).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }) : r.run_id?.slice(0, 8),
      })))
    );
    getAnalyticsIssueOverview().then(setOverview);
  }, []);

  return (
    <>
      <div className="page-title">Analytics</div>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -8, marginBottom: 16 }}>
        Trend and historical charts, built directly on the same BigQuery views
        (v_dq_confidence_trend, v_dq_issue_overview) the rest of this dashboard reads.
      </p>

      <div className="card" style={{ marginBottom: 18 }}>
        <div className="card-title">Confidence Score Trend Across Runs</div>
        {trend.length > 0 ? (
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={trend} margin={{ top: 8, right: 20, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="run_label" tick={{ fontSize: 11 }} />
              <YAxis domain={[0, 100]} tick={{ fontSize: 11 }} unit="%" />
              <Tooltip formatter={(v) => `${v}%`} />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="confidence_score" name="DQ Confidence Score" stroke="#2f6fed" strokeWidth={2} dot={{ r: 3 }} />
            </LineChart>
          </ResponsiveContainer>
        ) : (
          <div className="empty-state">No validation runs yet -- run the pipeline (or upload a dataset on the Datasets page) to see a trend.</div>
        )}
      </div>

      <div className="card" style={{ marginBottom: 18 }}>
        <div className="card-title">Issues by Severity (Latest Run)</div>
        {overview.length > 0 ? (
          <ResponsiveContainer width="100%" height={260}>
            <BarChart data={overview} margin={{ top: 8, right: 20, left: 0, bottom: 8 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border)" />
              <XAxis dataKey="severity" tick={{ fontSize: 12 }} />
              <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Bar dataKey="rules_with_issues" name="Rules with Issues">
                {overview.map((entry, i) => (
                  <Cell key={i} fill={SEVERITY_COLOR[entry.severity] || "#2f6fed"} />
                ))}
              </Bar>
              <Bar dataKey="failed_records" name="Failed Records" fill="#8fa0c8" />
            </BarChart>
          </ResponsiveContainer>
        ) : (
          <div className="empty-state">No issues to chart yet for the latest run.</div>
        )}
      </div>

      {EMBED_URL && (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <div className="card-title" style={{ padding: "16px 18px 0 18px" }}>Looker Studio (optional)</div>
          <iframe
            src={EMBED_URL}
            title="Looker Studio Analytics"
            width="100%"
            height="600"
            style={{ border: 0, display: "block" }}
            allowFullScreen
          />
        </div>
      )}
    </>
  );
}
