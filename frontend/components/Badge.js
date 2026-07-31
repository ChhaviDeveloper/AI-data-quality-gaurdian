const SEVERITY_CLASS = {
  Critical: "badge-critical",
  High: "badge-high",
  Medium: "badge-medium",
  Low: "badge-low",
};

const STATUS_CLASS = {
  Open: "badge-open",
  "In Progress": "badge-progress",
  Closed: "badge-closed",
};

export function SeverityBadge({ severity }) {
  return <span className={`badge ${SEVERITY_CLASS[severity] || "badge-medium"}`}>{severity}</span>;
}

export function StatusBadge({ status }) {
  return <span className={`badge ${STATUS_CLASS[status] || "badge-open"}`}>{status}</span>;
}
