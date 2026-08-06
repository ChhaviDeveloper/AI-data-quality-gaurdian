"""
Thin Vertex AI Gemini wrapper for the validator's one AI-assisted step:
predicting the confidence score a batch would reach if its currently
recommended remediations were actually applied (the "AI-Predicted Score
After Remediation" card on the dashboard).

Deliberately copied (not imported) from services/dashboard-api/gemini_helper.py
and services/ai-proposals/gemini_client.py rather than shared as a library --
same reasoning those files document: each Cloud Run service stays
self-contained at build/deploy time. If Gemini model IDs change, update
GEMINI_MODEL here too.
"""
import os
import json
import logging
from typing import Any, Dict, List

logger = logging.getLogger("validator.gemini_helper")

GCP_PROJECT = os.environ.get("BQ_PROJECT", "ringed-hearth-504112-e3")
GCP_REGION = os.environ.get("GCP_REGION", "us-central1")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

# Deterministic safety net if the Gemini call fails, times out, or returns
# something unparsable -- so a validator run never blocks or errors out on
# this step. Same per-severity assumption the dashboard used before this
# feature existed: how much of a severity's currently-failing rows a
# suggested remediation would plausibly resolve.
FIX_RATE = {"Critical": 0.75, "High": 0.85, "Medium": 0.90, "Low": 0.95}

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_REGION)
    return _client


def _deterministic_fallback(rule_summaries: List[Dict[str, Any]], pre_score: float) -> Dict[str, Any]:
    if not rule_summaries:
        return {"predicted_post_confidence_score": pre_score, "rationale": "No rule results to project from."}
    predicted = []
    for r in rule_summaries:
        total = r.get("total_records") or 0
        failed = r.get("failed_count") or 0
        passed = total - failed
        fix = FIX_RATE.get(r.get("severity"), 0.90)
        predicted.append(((passed + failed * fix) / total * 100) if total else 100.0)
    score = round(sum(predicted) / len(predicted), 2)
    return {
        "predicted_post_confidence_score": score,
        "rationale": "Estimated from a per-severity fix-rate assumption (Gemini call unavailable).",
    }


def predict_post_remediation_score(pre_score: float, rule_summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Given the batch's actual current confidence score and its per-rule
    results (rule_id, rule_name, severity, dimension, total_records,
    failed_count, pass_percentage), ask Gemini to project what the overall
    confidence score would become if every currently-recommended
    remediation were carried out. Nothing in the underlying data is
    touched -- this is a projection only.

    Returns {"predicted_post_confidence_score": float 0-100, "rationale": str}.
    Falls back to a deterministic per-severity estimate (see FIX_RATE above)
    if the Gemini call fails or its answer can't be parsed/trusted.
    """
    fallback = _deterministic_fallback(rule_summaries, pre_score)
    failing = [r for r in rule_summaries if (r.get("failed_count") or 0) > 0]
    if not failing:
        return {"predicted_post_confidence_score": pre_score, "rationale": "No open issues to remediate."}

    prompt = f"""You are a data-quality remediation-impact assistant for an audit/controls dataset.

The dataset's current overall confidence score (average pass percentage across all
validation rules) is {pre_score}%.

Here are the rules currently failing on this batch, as a JSON array. Each item has
rule_id, rule_name, severity, dimension, total_records, failed_count, pass_percentage:
{json.dumps(failing, default=str)}

For each failing rule, an AI-generated remediation would be suggested to the data/control
owner (e.g. populate a missing field from a source system, correct an invalid value,
submit missing evidence, renew an expired exception, enable a required control like MFA
or encryption). Estimate realistically what fraction of each rule's currently-failing
records such a remediation would resolve if actually carried out -- mechanical/data-entry
issues (missing fields, format errors, stale dates) are usually highly fixable; rules that
represent a real control gap needing a genuine action (actually enabling MFA, obtaining an
access approval, completing a DR test) are harder to guarantee fixed just because a
suggestion was made.

Return ONLY a JSON object with keys:
  predicted_post_confidence_score (number between {pre_score} and 100 -- your estimate of the
    dataset's overall confidence score if all the recommended remediations were applied)
  rationale (1-2 sentences explaining the estimate, mentioning which rule(s) are the biggest
    remaining risk even after remediation)

No markdown fences, no extra commentary.
"""
    try:
        client = _get_client()
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        parsed = _extract_json(response.text or "")
        score = float(parsed.get("predicted_post_confidence_score"))
        # Sanity-clamp: a "post remediation" projection should never be
        # below the current score or above 100 -- if Gemini's number fails
        # that basic check, it's not trustworthy enough to show.
        if not (pre_score <= score <= 100):
            raise ValueError(f"predicted score {score} outside [{pre_score}, 100]")
        return {
            "predicted_post_confidence_score": round(score, 2),
            "rationale": parsed.get("rationale") or fallback["rationale"],
        }
    except Exception:
        logger.exception("Gemini post-remediation prediction failed; using deterministic fallback")
        return fallback


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
