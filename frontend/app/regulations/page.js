"use client";

import { useEffect, useState } from "react";
import { getRegulations, getRegulationViolations } from "../../lib/api";
import { SeverityBadge } from "../../components/Badge";

export default function RegulationsPage() {
  const [regs, setRegs] = useState([]);
  const [violations, setViolations] = useState([]);

  useEffect(() => {
    getRegulations().then(setRegs);
    getRegulationViolations().then(setViolations);
  }, []);

  const matchCount = regs.filter((r) => r.matches_active_dataset).length;
  const totalViolations = regs.reduce((sum, r) => sum + (r.open_violation_count || 0), 0);

  return (
    <>
      <div className="page-title">Applicable Laws &amp; Regulations</div>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -8, marginBottom: 16 }}>
        Reference set from applicable_regulations (specs/applicable_regulations_seed.csv).
        Rows highlighted in blue apply to the region of the most recently ingested dataset
        {matchCount > 0 && ` (${matchCount} matching regulation${matchCount === 1 ? "" : "s"})`}.
        {totalViolations > 0 && (
          <> <strong style={{ color: "var(--red)" }}>{totalViolations} open violation{totalViolations === 1 ? "" : "s"}</strong> across
          {" "}{new Set(violations.map((v) => v.regulation_code)).size} regulation{new Set(violations.map((v) => v.regulation_code)).size === 1 ? "" : "s"} right now.</>
        )}
      </p>

      <div className="card">
        <table>
          <thead>
            <tr><th>Code</th><th>Regulation</th><th>Description</th><th>Applies To</th><th>Country</th><th>Authority</th></tr>
          </thead>
          <tbody>
            {regs.map((r) => (
              <tr
                key={r.regulation_code}
                style={r.matches_active_dataset ? { background: "#eef3fe" } : undefined}
              >
                <td>
                  <strong>{r.regulation_code}</strong>
                  {r.matches_active_dataset && (
                    <span className="badge" style={{ background: "#dbe6fd", color: "var(--blue)", marginLeft: 6 }}>
                      Applies to your data
                    </span>
                  )}
                  {r.open_violation_count > 0 && (
                    <span className="badge" style={{ background: "#fdeceb", color: "var(--red)", marginLeft: 6 }}>
                      {r.open_violation_count} open violation{r.open_violation_count === 1 ? "" : "s"}
                    </span>
                  )}
                </td>
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

      {violations.length > 0 && (
        <div className="card section">
          <div className="card-title">Regulation Violations</div>
          <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -4, marginBottom: 12 }}>
            Applications whose regulatory_scope names one of the regulations above, with a
            still-open Data Quality Issue right now -- see v_regulation_violations.
          </p>
          <table>
            <thead>
              <tr><th>Regulation</th><th>Application</th><th>Rule</th><th>Description</th><th>Severity</th></tr>
            </thead>
            <tbody>
              {violations.map((v, i) => (
                <tr key={i}>
                  <td><strong>{v.regulation_code}</strong></td>
                  <td>{v.application_name || v.application_id}</td>
                  <td>{v.rule_id}<br />{v.rule_name}</td>
                  <td style={{ maxWidth: 280 }}>{v.description}</td>
                  <td><SeverityBadge severity={v.severity} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}
