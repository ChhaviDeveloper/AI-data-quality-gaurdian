"use client";

export default function RootCauseModal({ issue, data, loading, onClose }) {
  if (!issue) return null;
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h3>Root Cause Analysis -- {issue.rule_name}</h3>
        <p className="muted">{issue.description}</p>
        {loading ? (
          <p>Analyzing with Vertex AI...</p>
        ) : (
          <>
            <p><strong>Root cause:</strong> {data?.root_cause}</p>
            <p><strong>Affected pattern:</strong> {data?.affected_pattern}</p>
            {typeof data?.confidence === "number" && (
              <p className="muted">Confidence: {Math.round(data.confidence * 100)}%</p>
            )}
          </>
        )}
        <div style={{ textAlign: "right", marginTop: 14 }}>
          <button className="btn btn-outline" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}
