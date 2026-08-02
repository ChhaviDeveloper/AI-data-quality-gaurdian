"use client";

import { useEffect, useRef, useState } from "react";
import { getDatasets, uploadDataset, isLiveMode } from "../../lib/api";

export default function DatasetsPage() {
  const [rows, setRows] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const [status, setStatus] = useState(null); // { type: 'info'|'success'|'error', message }
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef(null);

  function refresh() {
    getDatasets().then(setRows);
  }

  useEffect(() => { refresh(); }, []);

  async function handleFile(file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setStatus({ type: "error", message: "Only .csv files are supported." });
      return;
    }
    setBusy(true);
    setStatus({ type: "info", message: `Ingesting ${file.name}...` });
    try {
      const result = await uploadDataset(file, (msg) => setStatus({ type: "info", message: msg }));
      if (result.mode === "async") {
        setStatus({ type: "success", message: result.message || "Uploaded -- processing automatically in the cloud." });
      } else {
        const scoreText = result.dq_score != null ? `${result.dq_score}% DQ score` : "score pending";
        const proposalsText = result.new_proposals ? `, ${result.new_proposals} new rule proposal(s)` : "";
        setStatus({
          type: "success",
          message: `Done -- batch ${result.batch_id.slice(0, 8)}... validated, ${scoreText}${proposalsText}. ` +
                   `Check Overview / Data Quality Issues for results.`,
        });
      }
      refresh();
    } catch (err) {
      setStatus({ type: "error", message: err.message || "Upload failed." });
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <div className="page-title">Datasets</div>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -8, marginBottom: 16 }}>
        Every file ingested, one row per batch (dataset_registry, written by services/ingest).
        Drop a CSV below to run it through ingest, validation, and AI rule mining right from
        here -- no terminal needed.
      </p>

      <div className="card" style={{ marginBottom: 18 }}>
        <div
          className={`dropzone${dragActive ? " active" : ""}`}
          onClick={() => !busy && fileInputRef.current?.click()}
          onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
          onDragLeave={() => setDragActive(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragActive(false);
            if (!busy) handleFile(e.dataTransfer.files?.[0]);
          }}
        >
          <input
            ref={fileInputRef}
            type="file"
            accept=".csv"
            style={{ display: "none" }}
            onChange={(e) => handleFile(e.target.files?.[0])}
            disabled={busy}
          />
          {busy ? (
            <span>Processing -- ingesting, validating, and mining rule proposals. This can take up to a minute...</span>
          ) : (
            <span><strong>Click to upload</strong> or drag and drop a CSV file here</span>
          )}
        </div>
        {status && <div className={`upload-status ${status.type}`}>{status.message}</div>}
        {!isLiveMode() && (
          <div className="upload-status info" style={{ marginTop: 8 }}>
            NEXT_PUBLIC_API_BASE_URL isn&apos;t set, so uploads won&apos;t work yet -- see frontend/.env.local.
          </div>
        )}
      </div>

      <div className="card">
        <table>
          <thead>
            <tr>
              <th>Dataset</th><th>Uploaded By</th><th>Uploaded At</th>
              <th>Records</th><th>Columns</th><th>Region</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.batch_id}>
                <td>{d.dataset_name}</td>
                <td>{d.uploaded_by}</td>
                <td>{d.uploaded_at ? new Date(d.uploaded_at).toLocaleString() : "--"}</td>
                <td>{Number(d.records_loaded || 0).toLocaleString()}</td>
                <td>{d.columns_count}</td>
                <td>{d.region}</td>
                <td>{d.status}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={7} className="empty-state">No datasets ingested yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
