function colorFor(pct) {
  if (pct >= 85) return "#27ae60";
  if (pct >= 65) return "#f2994a";
  return "#e5484d";
}

function labelFor(pct) {
  if (pct >= 85) return "Excellent";
  if (pct >= 65) return "Moderate";
  return "Needs Attention";
}

export default function ScoreDonut({ pct = 0 }) {
  const color = colorFor(pct);
  const style = {
    background: `conic-gradient(${color} ${pct * 3.6}deg, #eef1f7 0deg)`,
  };
  return (
    <div className="donut" style={style}>
      <div className="donut-inner">
        <span className="pct" style={{ color }}>{Math.round(pct)}%</span>
        <span className="label">{labelFor(pct)}</span>
      </div>
    </div>
  );
}
