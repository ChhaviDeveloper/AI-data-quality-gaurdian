"use client";

import { useEffect, useState } from "react";
import { getRegulations } from "../../lib/api";

export default function RegulationsPage() {
  const [regs, setRegs] = useState([]);

  useEffect(() => { getRegulations().then(setRegs); }, []);

  return (
    <>
      <div className="page-title">Applicable Laws &amp; Regulations</div>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -8, marginBottom: 16 }}>
        Reference set from applicable_regulations (specs/applicable_regulations_seed.csv),
        filtered by the country detected for the active dataset.
      </p>

      <div className="card">
        <table>
          <thead>
            <tr><th>Code</th><th>Regulation</th><th>Description</th><th>Applies To</th><th>Country</th><th>Authority</th></tr>
          </thead>
          <tbody>
            {regs.map((r) => (
              <tr key={r.regulation_code}>
                <td><strong>{r.regulation_code}</strong></td>
                <td>{r.regulation_name}</td>
                <td style={{ maxWidth: 320 }}>{r.description}</td>
                <td>{r.data_category}</td>
                <td>{r.country}</td>
                <td>{r.authority}</td>
              </tr>
            ))}
            {regs.length === 0 && <tr><td colSpan={6} className="empty-state">No regulations loaded.</td></tr>}
          </tbody>
        </table>
      </div>
    </>
  );
}
