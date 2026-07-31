function fmtDate(iso) {
  if (!iso) return "--";
  try {
    return new Date(iso).toLocaleString(undefined, {
      year: "numeric", month: "short", day: "2-digit",
      hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

export default function TopBar({ dataset }) {
  if (!dataset) return null;
  return (
    <div className="topbar">
      <div className="topbar-item">
        <span className="label">Dataset</span>
        <span className="value">{dataset.dataset_name}</span>
      </div>
      <div className="topbar-item">
        <span className="label">BigQuery Dataset</span>
        <span className="value">{dataset.bq_dataset}</span>
      </div>
      <div className="topbar-item">
        <span className="label">Schema Created On</span>
        <span className="value">{fmtDate(dataset.schema_created_at)}</span>
      </div>
      <div className="topbar-item">
        <span className="label">Records Loaded</span>
        <span className="value">{Number(dataset.records_loaded || 0).toLocaleString()}</span>
      </div>
      <div className="topbar-item">
        <span className="label">AI Model</span>
        <span className="value">{dataset.ai_model}</span>
      </div>
      <div className="topbar-item">
        <span className="label">Region / Location</span>
        <span className="value">{dataset.region}</span>
      </div>
    </div>
  );
}
