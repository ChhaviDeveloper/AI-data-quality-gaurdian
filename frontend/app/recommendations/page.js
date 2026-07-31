"use client";

import { useEffect, useState } from "react";
import { SeverityBadge } from "../../components/Badge";
import { getRecommendations } from "../../lib/api";

export default function RecommendationsPage() {
  const [items, setItems] = useState([]);

  useEffect(() => { getRecommendations().then(setItems); }, []);

  return (
    <>
      <div className="page-title">AI-Generated Recommendations</div>
      <p style={{ color: "var(--muted)", fontSize: 13, marginTop: -8, marginBottom: 16 }}>
        New validation rules proposed by the ai-proposals service (failure-pattern mining +
        source/target drift detection), pending human review via tools/review_proposals.py.
      </p>

      <div className="grid" style={{ gridTemplateColumns: "1fr" }}>
        {items.map((rec) => (
          <div className="card" key={rec.proposal_id}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "start" }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: 14 }}>{rec.rule_name}</div>
                <div style={{ color: "var(--muted)", fontSize: 11, textTransform: "uppercase", marginTop: 2 }}>
                  {rec.source === "target_drift" ? "Target Drift Detection" : "Failure Pattern Mining"} -- {rec.dimension}
                </div>
              </div>
              <SeverityBadge severity={rec.severity} />
            </div>
            <p style={{ fontSize: 13, margin: "10px 0" }}>{rec.description}</p>
            <div style={{ fontSize: 12, color: "var(--muted)" }}>
              Confidence: {Math.round((rec.confidence || 0) * 100)}% -- Status: {rec.status}
            </div>
          </div>
        ))}
        {items.length === 0 && <div className="card empty-state">No pending recommendations.</div>}
      </div>
    </>
  );
}
