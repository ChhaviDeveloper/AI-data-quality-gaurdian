"""
Thin Vertex AI Gemini wrapper for dashboard-api's two AI-assisted endpoints:
recommended-remediation text (POST /api/issues/<rule_id>/remediate) and
root-cause summaries (GET /api/issues/<rule_id>/root-cause).

Deliberately copied (not imported) from
services/ai-proposals/gemini_client.py rather than shared as a library, same
reasoning as that file documents: each Cloud Run service stays
self-contained at build/deploy time. If Gemini model IDs change, update
GEMINI_MODEL here and in ai-proposals/gemini_client.py.
"""
import os
import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger("dashboard-api.gemini_helper")

GCP_PROJECT = os.environ.get("BQ_PROJECT", "ringed-hearth-504112-e3")
GCP_REGION = os.environ.get("GCP_REGION", "us-central1")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_REGION)
    return _client


def _call(prompt: str, fallback: Dict[str, Any]) -> Dict[str, Any]:
    try:
        client = _get_client()
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        parsed = _extract_json(response.text or "")
        return {**fallback, **parsed}
    except Exception:
        logger.exception("Gemini call failed; returning fallback")
        return fallback


def recommend_remediation(rule: Dict[str, Any]) -> Dict[str, Any]:
    """Given a failing rule (rule_name, description, severity, dimension,
    failed_count, total_records), ask Gemini for a short, actionable
    remediation recommendation -- what the "Remediate" button's suggestion
    text on the dashboard shows."""
    prompt = f"""You are a data-quality remediation assistant.

A validation rule is failing on an audit/controls dataset:
  rule_name: {rule.get('rule_name')}
  description: {rule.get('description')}
  dimension: {rule.get('dimension')}
  severity: {rule.get('severity')}
  failed_count: {rule.get('failed_count')} of {rule.get('total_records')} records

Return ONLY a JSON object with keys:
  recommended_remediation (one concise, actionable sentence -- e.g.
    "Populate missing email addresses using reference master data or mark as Not Available")
  remediation_type (one of: "auto_fixable", "requires_source_correction", "requires_manual_review")

No markdown fences, no extra commentary.
"""
    fallback = {
        "recommended_remediation": (
            f"Review and correct the {rule.get('dimension', 'data quality')} issue "
            f"affecting {rule.get('failed_count', 0)} record(s) for rule "
            f"{rule.get('rule_name', rule.get('rule_id'))}."
        ),
        "remediation_type": "requires_manual_review",
    }
    return _call(prompt, fallback)


def root_cause_summary(rule: Dict[str, Any], sample_failed_rows: List[dict]) -> Dict[str, Any]:
    """Given a failing rule and a small sample of the actual failed records,
    ask Gemini for a short root-cause narrative -- the "Root Cause Analysis
    Summary" panel."""
    sample = json.dumps(sample_failed_rows[:5], default=str)
    prompt = f"""You are a root-cause-analysis assistant for a data-quality audit pipeline.

Rule that failed:
  rule_name: {rule.get('rule_name')}
  description: {rule.get('description')}
  dimension: {rule.get('dimension')}
  severity: {rule.get('severity')}

Sample of the actual failed records (JSON array, may be partial):
{sample}

Return ONLY a JSON object with keys:
  root_cause (1-2 sentences: the most likely underlying cause of this pattern,
    e.g. "Upstream HR export drops the email field for contractor accounts")
  affected_pattern (short phrase describing what the failing records have in common)
  confidence (float 0-1)

No markdown fences, no extra commentary.
"""
    fallback = {
        "root_cause": "Unable to determine root cause automatically -- manual review of the failed records is required.",
        "affected_pattern": "Unknown",
        "confidence": 0.0,
    }
    return _call(prompt, fallback)


def _extract_json(text: str) -> Dict[str, Any]:
    text = text.strip().strip("`")
    if text.lower().startswith("json"):
        text = text[4:]
    start = text.find("{")
    if start == -1:
        return {}
    depth, end = 0, -1
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                end = i
                break
    candidate = text[start:end + 1] if end != -1 else text[start:]
    try:
        return json.loads(candidate)
    except Exception:
        return {}
