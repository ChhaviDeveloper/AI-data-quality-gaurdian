import {
  MOCK_DATASET, MOCK_CONFIDENCE, MOCK_ISSUE_TOTALS, MOCK_BUCKETS,
  MOCK_ISSUES, MOCK_REGULATIONS, MOCK_APPS_AT_RISK, MOCK_HISTORY, MOCK_RECOMMENDATIONS,
} from "./mockData";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL || "";

async function getJson(path, fallback) {
  if (!API_BASE) return fallback;
  try {
    const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
    if (!res.ok) throw new Error(`${path} -> ${res.status}`);
    return await res.json();
  } catch (err) {
    console.warn(`dashboard-api unreachable for ${path}, using mock data:`, err.message);
    return fallback;
  }
}

async function postJson(path, body) {
  if (!API_BASE) {
    // No backend configured -- simulate success so the UI is demoable.
    return { ok: true, mocked: true, ...body };
  }
  const res = await fetch(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
}

export async function getOverview() {
  return getJson("/api/overview", {
    dataset: MOCK_DATASET,
    confidence: MOCK_CONFIDENCE,
    issue_totals: MOCK_ISSUE_TOTALS,
    buckets: MOCK_BUCKETS,
  });
}

export async function getIssues() {
  return getJson("/api/issues", MOCK_ISSUES);
}

export async function getRegulations() {
  return getJson("/api/regulations", MOCK_REGULATIONS);
}

export async function getRegulationViolations() {
  return getJson("/api/regulations/violations", []);
}

export async function getImpactedApps() {
  return getJson("/api/impacted-apps", MOCK_APPS_AT_RISK);
}

export async function getHistory() {
  return getJson("/api/history", MOCK_HISTORY);
}

export async function getDatasets() {
  return getJson("/api/datasets", [MOCK_DATASET]);
}

export async function getRecommendations() {
  return getJson("/api/recommendations", MOCK_RECOMMENDATIONS);
}

export async function remediateIssue(ruleId, runId, applicationId) {
  return postJson(`/api/issues/${ruleId}/remediate`, { run_id: runId, application_id: applicationId });
}

export async function acceptIssue(ruleId, runId, applicationId) {
  return postJson(`/api/issues/${ruleId}/accept`, { run_id: runId, application_id: applicationId });
}

export async function getRootCause(ruleId, runId, applicationId) {
  const qs = new URLSearchParams();
  if (runId) qs.set("run_id", runId);
  if (applicationId) qs.set("application_id", applicationId);
  const query = qs.toString();
  return getJson(
    `/api/issues/${ruleId}/root-cause${query ? `?${query}` : ""}`,
    {
      rule_id: ruleId,
      application_id: applicationId,
      root_cause: "Demo mode: connect NEXT_PUBLIC_API_BASE_URL to a deployed dashboard-api to get a real Vertex AI-generated root cause summary.",
      affected_pattern: "N/A (mock data)",
      confidence: 0,
    },
  );
}

export async function getAnalyticsTrend() {
  return getJson("/api/analytics/trend", []);
}

export async function getAnalyticsIssueOverview() {
  return getJson("/api/analytics/issue-overview", []);
}

// Uploads a CSV and runs the full ingest -> validator -> ai-proposals
// pipeline against it. Unlike the getters above, this has no mock fallback
// -- it needs a real dashboard-api to do anything, so we throw instead of
// silently pretending to succeed.
export async function uploadDataset(file, onStatus) {
  if (!API_BASE) {
    throw new Error(
      "No dashboard-api configured (NEXT_PUBLIC_API_BASE_URL is unset). " +
      "Set it in frontend/.env.local and restart the dev server."
    );
  }
  onStatus?.("Uploading and ingesting...");
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_BASE}/api/ingest`, { method: "POST", body: form });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.error || body.details || `Upload failed (${res.status})`);
  }
  return body;
}

// Validates data that's already sitting in a BigQuery table, instead of
// only ever uploading a CSV. Same "no mock fallback" reasoning as
// uploadDataset -- it needs a real dashboard-api to do anything.
export async function ingestFromBigQueryTable(sourceTable) {
  if (!API_BASE) {
    throw new Error(
      "No dashboard-api configured (NEXT_PUBLIC_API_BASE_URL is unset). " +
      "Set it in frontend/.env.local and restart the dev server."
    );
  }
  const res = await fetch(`${API_BASE}/api/ingest-bq`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ source_table: sourceTable }),
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    throw new Error(body.error || `Request failed (${res.status})`);
  }
  return body;
}

export const isLiveMode = () => Boolean(API_BASE);
