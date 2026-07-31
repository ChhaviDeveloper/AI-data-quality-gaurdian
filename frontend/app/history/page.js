"use client";

import { useEffect, useState } from "react";
import { StatusBadge } from "../../components/Badge";
import { getHistory } from "../../lib/api";

export default function HistoryPage() {
  const [rows, setRows] = useState([]);

  useEffect(() => { getHistory().then(setRows); }, []);

  return (
    <>
      <div className="page-title">History &amp; Activity Log</div>
      <div className="card">
        <table>
          <thead>
            <tr><th>Time</th><th>Event Type</th><th>Description</th><th>Actor</th><th>Status</th></tr>
          </thead>
          <tbody>
            {rows.map((h, i) => (
              <tr key={i}>
                <td>{h.event_time ? new Date(h.event_time).toLocaleString() : "--"}</td>
                <td>{h.event_type}</td>
                <td>{h.description}</td>
                <td>{h.actor}</td>
                <td>{h.status ? <StatusBadge status={h.status} /> : "--"}</td>
              </tr>
            ))}
            {rows.length === 0 && <tr><td colSpan={5} className="empty-state">No activity recorded yet.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
