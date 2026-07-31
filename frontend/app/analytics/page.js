"use client";

const EMBED_URL = process.env.NEXT_PUBLIC_LOOKER_EMBED_URL || "";

export default function AnalyticsPage() {
  return (
    <>
      <div className="page-title">Analytics</div>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -8, marginBottom: 16 }}>
        Trend and historical charts, built in Looker Studio on top of the same BigQuery views
        (v_dq_confidence_trend, v_dq_issue_overview, v_dq_activity_log) the rest of this
        dashboard reads. Looker Studio is read-only -- use Data Quality Issues for Remediate/
        Accept actions.
      </p>

      {EMBED_URL ? (
        <div className="card" style={{ padding: 0, overflow: "hidden" }}>
          <iframe
            src={EMBED_URL}
            title="Looker Studio Analytics"
            width="100%"
            height="720"
            style={{ border: 0, display: "block" }}
            allowFullScreen
          />
        </div>
      ) : (
        <div className="card empty-state">
          No Looker Studio report configured yet. Set <code>NEXT_PUBLIC_LOOKER_EMBED_URL</code>{" "}
          in <code>frontend/.env.local</code> to your report&apos;s embed URL and rebuild.
          See the &quot;Looker Studio setup&quot; section of the repo README for the exact steps
          (data source = the v_dq_* views, then File &gt; Embed report to get the URL).
        </div>
      )}
    </>
  );
}
