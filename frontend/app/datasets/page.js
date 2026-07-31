"use client";

import { useEffect, useState } from "react";
import { getDatasets } from "../../lib/api";

export default function DatasetsPage() {
  const [rows, setRows] = useState([]);

  useEffect(() => { getDatasets().then(setRows); }, []);

  return (
    <>
      <div className="page-title">Datasets</div>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -8, marginBottom: 16 }}>
        Every file ingested through gs://&lt;bucket&gt;/incoming/, one row per batch
        (dataset_registry, written by services/ingest).
      </p>

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
