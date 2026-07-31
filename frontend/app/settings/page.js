"use client";

import { isLiveMode } from "../../lib/api";

export default function SettingsPage() {
  const live = isLiveMode();
  const lookerConfigured = Boolean(process.env.NEXT_PUBLIC_LOOKER_EMBED_URL);
  return (
    <>
      <div className="page-title">Settings</div>
      <div className="card">
        <div className="card-title">Connection</div>
        <p style={{ fontSize: 13 }}>
          Mode: <strong>{live ? "Live (dashboard-api)" : "Demo (mock data)"}</strong>
        </p>
        <p style={{ fontSize: 13, color: "var(--muted)" }}>
          Set <code>NEXT_PUBLIC_API_BASE_URL</code> in <code>frontend/.env.local</code> to the
          deployed dashboard-api Cloud Run URL to switch to live data. See .env.example.
        </p>
      </div>

      <div className="card section">
        <div className="card-title">Analytics (Looker Studio)</div>
        <p style={{ fontSize: 13 }}>
          Report embed: <strong>{lookerConfigured ? "Configured" : "Not configured"}</strong>
        </p>
        <p style={{ fontSize: 13, color: "var(--muted)" }}>
          Set <code>NEXT_PUBLIC_LOOKER_EMBED_URL</code> to enable the Analytics page. See the
          &quot;Looker Studio setup&quot; section of the repo README.
        </p>
      </div>

      <div className="card section">
        <div className="card-title">About</div>
        <p style={{ fontSize: 13 }}>
          AI Data Guardian dashboard for the cloud-pipeline data-quality project. Backend:
          services/dashboard-api. Pipeline: services/ingest, services/validator,
          services/ai-proposals. See the repo README for the full architecture.
        </p>
      </div>
    </>
  );
}
