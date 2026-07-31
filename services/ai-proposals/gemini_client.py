"""
Thin wrapper around Vertex AI's Gemini models for generating rule proposals.

Replaces the root-level vertex_llm.py, which targeted the deprecated
text-bison@001 (PaLM 2) model via the older PredictionServiceClient. This
uses the current google-genai SDK against Vertex AI instead.

NOTE: Google's GenAI SDKs and model lineup move fast. If this stops working,
check https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models for
the current generally-available model ID and swap GEMINI_MODEL below --
the calling code doesn't need to change.
"""
import os
import json
import logging
from typing import Dict, Any, List

logger = logging.getLogger("ai-proposals.gemini_client")

GCP_PROJECT = os.environ.get("BQ_PROJECT", "ai-data-quality-gaurdian")
GCP_REGION = os.environ.get("GCP_REGION", "us-central1")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_client = None


def _get_client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(vertexai=True, project=GCP_PROJECT, location=GCP_REGION)
    return _client


PROMPT_INSTRUCTIONS = """You are a data-quality assistant for an audit/controls dataset.
You will be given (a) a list of validation rules that ALREADY exist, and
(b) example rows that failed one or more rules, OR a description of a
data-drift / mismatch pattern between a source table and a downstream
target table.

Propose ONE new validation rule that is NOT already covered by the existing
rules. Return ONLY a JSON object with keys:
  rule_name (short title string)
  description (one sentence rationale)
  expression (a pandas-query boolean expression identifying FAILING rows,
    e.g. "backup_enabled == 'Yes' and encryption_at_rest != 'Yes'")
  severity (one of Critical, High, Medium, Low)
  dimension (a short data-quality dimension label, e.g. Consistency, Validity)
  confidence (float between 0 and 1)
  suggested_tests (array of {input: {...}, expected: 'fail'|'pass'})

Produce the JSON object only, with no additional commentary, no markdown
fences.
"""


def build_prompt_from_failures(failed_by_rule: Dict[str, "pd.DataFrame"], existing_rule_ids: List[str],
                                max_examples: int = 8) -> str:
    examples = []
    for rule_id, df in failed_by_rule.items():
        if df is None or getattr(df, "empty", True):
            continue
        for _, row in df.head(2).iterrows():
            row_dict = {k: (None if _is_na(v) else str(v)) for k, v in row.to_dict().items()}
            examples.append({"already_failed_rule_id": rule_id, "row": row_dict})
            if len(examples) >= max_examples:
                break
        if len(examples) >= max_examples:
            break

    lines = [
        PROMPT_INSTRUCTIONS,
        f"Existing rule IDs already in the registry: {existing_rule_ids}",
        "",
        "Failed record examples (each already failed a DIFFERENT existing rule --"
        " look for a NEW pattern across them, not a restatement of an existing rule):",
    ]
    for ex in examples:
        lines.append(json.dumps(ex, ensure_ascii=False))
    if not examples:
        lines.append("[] # no failed examples provided")
    return "\n".join(lines)


def build_prompt_from_drift(mapping: dict, mismatch_count: int, sample_keys: List[str]) -> str:
    lines = [
        PROMPT_INSTRUCTIONS,
        "Instead of failed records, you are given a detected DATA-DRIFT / MISMATCH pattern:",
        json.dumps({
            "mapping_name": mapping.get("name"),
            "source_columns": mapping.get("source_columns"),
            "target_table": mapping.get("target_table"),
            "join_key": mapping.get("join_key"),
            "mismatch_count": mismatch_count,
            "sample_mismatched_keys": sample_keys[:10],
        }, ensure_ascii=False),
        "Propose a validation rule that would have caught this mismatch earlier.",
    ]
    return "\n".join(lines)


def _is_na(v):
    try:
        import pandas as pd
        return pd.isna(v)
    except Exception:
        return v is None


def call_gemini(prompt_text: str) -> Dict[str, Any]:
    """Calls Gemini via Vertex AI and returns a parsed proposal dict.

    Falls back to a safe placeholder (confidence 0.0) on any error so a
    Vertex outage never crashes the job -- the run just produces no new
    proposals that cycle, which is the safe failure mode.
    """
    try:
        client = _get_client()
        response = client.models.generate_content(model=GEMINI_MODEL, contents=prompt_text)
        raw_text = response.text or ""
        parsed = _extract_json(raw_text)
        return {
            "rule_name": parsed.get("rule_name", "AI Proposed Rule"),
            "description": parsed.get("description", ""),
            "expression": parsed.get("expression", ""),
            "severity": parsed.get("severity", "Medium"),
            "dimension": parsed.get("dimension", "Unknown"),
            "confidence": float(parsed.get("confidence", 0.0) or 0.0),
            "suggested_tests": parsed.get("suggested_tests", []),
        }
    except Exception:
        logger.exception("Gemini call failed; returning fallback placeholder")
        return {
            "rule_name": "AI Proposed Rule (fallback)",
            "description": "Vertex AI call failed or returned unparsable output; manual review required.",
            "expression": "",
            "severity": "Medium",
            "dimension": "Unknown",
            "confidence": 0.0,
            "suggested_tests": [],
        }


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
