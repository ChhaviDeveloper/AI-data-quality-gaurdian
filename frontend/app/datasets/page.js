"use client";

import { useEffect, useRef, useState } from "react";
import { getDatasets, uploadDataset, ingestFromBigQueryTable, isLiveMode } from "../../lib/api";

export default function DatasetsPage() {
  const [rows, setRows] = useState([]);
  const [dragActive, setDragActive] = useState(false);
  const [status, setStatus] = useState(null); // { type: 'info'|'success'|'error', message }
  const [busy, setBusy] = useState(false);
  const fileInputRef = useRef(null);
  const [bqTable, setBqTable] = useState("");
  const [bqStatus, setBqStatus] = useState(null);
  const [bqBusy, setBqBusy] = useState(false);
  const [targetBatch, setTargetBatch] = useState(""); // "" = new dataset, else an existing batch_id to re-validate

  function refresh() {
    getDatasets().then(setRows);
  }

  useEffect(() => { refresh(); }, []);

  // One option per distinct batch_id, labeled with its most recent dataset_name
  // (dataset_registry gets a new row every time a batch is re-validated, so
  // the same batch_id can appear more than once in rows).
  const batchOptions = Array.from(
    rows.reduce((map, d) => {
      if (!map.has(d.batch_id) || new Date(d.uploaded_at) > new Date(map.get(d.batch_id).uploaded_at)) {
        map.set(d.batch_id, d);
      }
      return map;
    }, new Map()).values()
  );

  async function handleFile(file) {
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".csv")) {
      setStatus({ type: "error", message: "Only .csv files are supported." });
      return;
    }
    setBusy(true);
    setStatus({ type: "info", message: `Ingesting ${file.name}...` });
    try {
      const result = await uploadDataset(file, (msg) => setStatus({ type: "info", message: msg }), targetBatch || undefined);
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

  async function handleBqSubmit(e) {
    e.preventDefault();
    const table = bqTable.trim();
    if (!table) return;
    setBqBusy(true);
    setBqStatus({ type: "info", message: `Loading ${table} into staging...` });
    try {
      const result = await ingestFromBigQueryTable(table, targetBatch || undefined);
      setBqStatus({ type: "success", message: result.message || `Loaded ${result.row_count} rows -- validating automatically.` });
      refresh();
    } catch (err) {
      setBqStatus({ type: "error", message: err.message || "Could not load that table." });
    } finally {
      setBqBusy(false);
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
        <div className="card-title">Target batch</div>
        <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -4, marginBottom: 12 }}>
          Leave as "New dataset" for a normal upload. Pick an existing batch to REPLACE its rows
          with corrected data and re-validate it -- that's what moves the Pre/Post Confidence
          Score on Overview, since it compares a batch's first and most recent run.
        </p>
        <select
          value={targetBatch}
          onChange={(e) => setTargetBatch(e.target.value)}
          style={{ padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 6, minWidth: 320 }}
        >
          <option value="">New dataset</option>
          {batchOptions.map((d) => (
            <option key={d.batch_id} value={d.batch_id}>
              Re-validate: {d.dataset_name} ({d.batch_id.slice(0, 8)}...)
            </option>
          ))}
        </select>
      </div>

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

      <div className="card" style={{ marginBottom: 18 }}>
        <div className="card-title">Validate a BigQuery table</div>
        <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -4, marginBottom: 12 }}>
          Already have the data in BigQuery? Point at it directly instead of exporting a CSV --
          it's loaded into staging and validated the same way. Needs an application_id column.
        </p>
        <form onSubmit={handleBqSubmit} style={{ display: "flex", gap: 8 }}>
          <input
            type="text"
            value={bqTable}
            onChange={(e) => setBqTable(e.target.value)}
            placeholder="project.dataset.table"
            disabled={bqBusy}
            style={{ flex: 1, padding: "8px 10px", border: "1px solid var(--border)", borderRadius: 6 }}
          />
          <button type="submit" className="btn btn-primary" disabled={bqBusy || !bqTable.trim()}>
            {bqBusy ? "Loading..." : "Validate"}
          </button>
        </form>
        {bqStatus && <div className={`upload-status ${bqStatus.type}`} style={{ marginTop: 8 }}>{bqStatus.message}</div>}
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
            {rows.map((d, i) => (
              <tr key={`${d.batch_id}-${i}`}>
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
