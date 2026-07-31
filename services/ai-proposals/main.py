"""
ai-proposals Cloud Run Job -- the "self-learning" piece of the pipeline.

Triggered after `validator` publishes a `validation-complete` Pub/Sub
message. Looks for validation rules that don't exist yet, from two angles:

  1. Failure-pattern mining: takes this run's failed_records_detail rows,
     shows Gemini a sample alongside the list of rules that ALREADY exist,
     and asks for one new rule that isn't a restatement of an existing one.
     This is the cloud equivalent of the root-level vertex_from_failed_csv.py.

  2. Target-table drift: for every mapping in target_table_registry.yaml
     that has a `target_table` + `join_key`, runs a live anti-join between
     the current staging batch and that target table in BigQuery. If rows
     exist in staging with a join key that's missing from the target table
     (or vice versa isn't checked here, but easy to add), that's exactly
     the "current vs target mismatch" signal from your project idea --
     Gemini turns it into a proposed rule.

Every candidate proposal is deduped against both the existing rules
registry and any already-pending/approved proposal with the same
expression, before being written to BigQuery `rule_proposals` and
triggering a `new-proposal` Pub/Sub message for the notifier.

Env vars: see validator/main.py for the shared ones (BQ_PROJECT, BQ_DATASET,
STAGING_TABLE, RULES_REGISTRY_PATH, TARGET_TABLE_REGISTRY_PATH), plus:
  RUN_ID                 -- optional; which validation run to mine (defaults to latest)
  NEW_PROPOSAL_TOPIC     -- Pub/Sub topic name (default: new-proposal)
  GEMINI_MODEL           -- default gemini-2.5-flash (see gemini_client.py)
"""
import os
import json
import uuid
import logging
from datetime import datetime, timezone

import yaml
import pandas as pd
from google.cloud import bigquery, pubsub_v1

from gemini_client import build_prompt_from_failures, build_prompt_from_drift, call_gemini

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ai-proposals")

BQ_PROJECT = os.environ.get("BQ_PROJECT", "ai-data-quality-gaurdian")
BQ_DATASET = os.environ.get("BQ_DATASET", "audit_controls")
STAGING_TABLE = os.environ.get("STAGING_TABLE", "staging_audit_controls")
RUN_ID = os.environ.get("RUN_ID")
RULES_REGISTRY_PATH = os.environ.get(
    "RULES_REGISTRY_PATH", "gs://ai-data-quality-gaurdian-dq-bucket/specs/rules_registry.yaml"
)
TARGET_TABLE_REGISTRY_PATH = os.environ.get(
    "TARGET_TABLE_REGISTRY_PATH", "gs://ai-data-quality-gaurdian-dq-bucket/specs/target_table_registry.yaml"
)
NEW_PROPOSAL_TOPIC = os.environ.get("NEW_PROPOSAL_TOPIC", "new-proposal")
MIN_CONFIDENCE_TO_KEEP = float(os.environ.get("MIN_CONFIDENCE_TO_KEEP", "0.5"))

_bq_client = None
_publisher = None


def bq():
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=BQ_PROJECT)
    return _bq_client


def publisher():
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


def _read_yaml(path):
    if path.startswith("gs://"):
        from google.cloud import storage
        bucket_name, blob_path = path[len("gs://"):].split("/", 1)
        blob = storage.Client().bucket(bucket_name).blob(blob_path)
        return yaml.safe_load(blob.download_as_text())
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _latest_run_id():
    sql = f"""
        SELECT run_id FROM `{BQ_PROJECT}.{BQ_DATASET}.rule_execution_summary`
        ORDER BY run_timestamp DESC LIMIT 1
    """
    rows = list(bq().query(sql).result())
    return rows[0]["run_id"] if rows else None


def _load_failed_records(run_id) -> dict:
    sql = f"""
        SELECT * FROM `{BQ_PROJECT}.{BQ_DATASET}.failed_records_detail`
        WHERE run_id = @run_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
    )
    df = bq().query(sql, job_config=job_config).to_dataframe()
    if df.empty or "failed_rule_id" not in df.columns:
        return {}
    return {rid: g.reset_index(drop=True) for rid, g in df.groupby("failed_rule_id")}


def _existing_proposal_expressions() -> set:
    """Expressions already proposed (pending or approved) -- avoids the kind
    of duplicate-proposal pileup seen in the local specs/pending_rules.json
    (the same 'backup requires encryption' idea was proposed 4 times)."""
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.rule_proposals"
    try:
        sql = f"""
            SELECT DISTINCT expression FROM `{table_id}`
            WHERE status IN ('pending', 'approved') AND expression != ''
        """
        return {row["expression"] for row in bq().query(sql).result()}
    except Exception:
        logger.warning("rule_proposals table not found yet (run terraform first); assuming no history.")
        return set()


def _make_proposal_row(parsed: dict, source: str, matched_count: int, run_id: str, notes: str) -> dict:
    return {
        "proposal_id": f"P-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:8]}",
        # Real datetime object, not .isoformat() -- BigQuery's pandas loader
        # can't convert a plain Python string into the TIMESTAMP-typed
        # created_at column (same bug class fixed in validator/main.py).
        "created_at": datetime.now(timezone.utc),
        "created_by": "AI",
        "status": "pending",
        "source": source,
        "run_id": run_id,
        "confidence": parsed.get("confidence", 0.0),
        "rule_name": parsed.get("rule_name", ""),
        "description": parsed.get("description", ""),
        "expression": parsed.get("expression", ""),
        "severity": parsed.get("severity", "Medium"),
        "dimension": parsed.get("dimension", "Unknown"),
        "matched_count": matched_count,
        "suggested_tests": json.dumps(parsed.get("suggested_tests", [])),
        "notes": notes,
    }


def _validate_expression(df: pd.DataFrame, expr: str):
    if not expr or not expr.strip():
        return False, 0, "Empty expression"
    try:
        matched = df.query(expr)
        return True, len(matched), None
    except Exception as e:
        return False, 0, str(e)


def mine_failure_patterns(run_id, existing_rule_ids, existing_expressions, staging_df) -> list:
    failed_by_rule = _load_failed_records(run_id)
    if not failed_by_rule:
        logger.info("No failed records for run %s -- nothing to mine.", run_id)
        return []

    prompt = build_prompt_from_failures(failed_by_rule, existing_rule_ids)
    parsed = call_gemini(prompt)

    if parsed.get("expression") in existing_expressions:
        logger.info("Gemini proposed an expression that's already pending/approved -- skipping.")
        return []
    if parsed.get("confidence", 0.0) < MIN_CONFIDENCE_TO_KEEP:
        logger.info("Proposal confidence %.2f below threshold -- skipping.", parsed.get("confidence", 0.0))
        return []

    valid, matched_count, err = _validate_expression(staging_df, parsed.get("expression", ""))
    notes = "Auto-generated from failure-pattern mining." if valid else f"Expression failed local validation: {err}"
    return [_make_proposal_row(parsed, "failure_pattern", matched_count, run_id, notes)]


def mine_target_drift(run_id, existing_expressions, target_mappings, batch_id) -> list:
    proposals = []
    for mapping in target_mappings or []:
        target_table = mapping.get("target_table")
        join_key = mapping.get("join_key")
        if not target_table or not join_key:
            continue
        try:
            sql = f"""
                SELECT s.{join_key} AS mismatched_key
                FROM `{BQ_PROJECT}.{BQ_DATASET}.{STAGING_TABLE}` s
                LEFT JOIN `{target_table}` t ON s.{join_key} = t.{join_key}
                WHERE s.batch_id = @batch_id AND t.{join_key} IS NULL
                LIMIT 50
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)]
            )
            rows = list(bq().query(sql, job_config=job_config).result())
        except Exception:
            logger.warning(
                "Could not run drift check against %s (does it exist / is join_key '%s' valid?). "
                "Skipping this mapping until confirmed.", target_table, join_key,
            )
            continue

        if not rows:
            continue

        sample_keys = [str(r["mismatched_key"]) for r in rows]
        prompt = build_prompt_from_drift(mapping, len(rows), sample_keys)
        parsed = call_gemini(prompt)
        if parsed.get("expression") in existing_expressions:
            continue
        if parsed.get("confidence", 0.0) < MIN_CONFIDENCE_TO_KEEP:
            continue
        proposals.append(_make_proposal_row(
            parsed, "target_drift", len(rows), run_id,
            f"Detected {len(rows)} row(s) in staging with '{join_key}' missing from {target_table}.",
        ))
    return proposals


def _write_proposals(proposals: list):
    if not proposals:
        logger.info("No new proposals this run.")
        return
    df = pd.DataFrame(proposals)
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.rule_proposals"
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND", autodetect=True)
    job = bq().load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()
    logger.info("Wrote %s new proposal(s) to %s", len(df), table_id)

    topic_path = publisher().topic_path(BQ_PROJECT, NEW_PROPOSAL_TOPIC)
    for p in proposals:
        try:
            publisher().publish(topic_path, json.dumps(p, default=str).encode("utf-8")).result(timeout=10)
        except Exception:
            logger.exception("Could not publish new-proposal message (has terraform created the topic?)")


def run():
    run_id = RUN_ID or _latest_run_id()
    if not run_id:
        logger.info("No validation runs found yet -- nothing to do.")
        return

    registry = _read_yaml(RULES_REGISTRY_PATH)
    existing_rules = registry.get("rules", [])
    existing_rule_ids = [r["rule_id"] for r in existing_rules]
    existing_expressions = {r.get("expression", "") for r in existing_rules} | _existing_proposal_expressions()

    try:
        target_mappings = _read_yaml(TARGET_TABLE_REGISTRY_PATH).get("mappings", [])
    except Exception:
        target_mappings = []

    sql = f"""
        SELECT batch_id FROM `{BQ_PROJECT}.{BQ_DATASET}.rule_execution_summary`
        WHERE run_id = @run_id LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
    )
    batch_rows = list(bq().query(sql, job_config=job_config).result())
    batch_id = batch_rows[0]["batch_id"] if batch_rows else None

    staging_sql = f"SELECT * FROM `{BQ_PROJECT}.{BQ_DATASET}.{STAGING_TABLE}` WHERE batch_id = @batch_id"
    staging_job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)]
    )
    staging_df = bq().query(staging_sql, job_config=staging_job_config).to_dataframe() if batch_id else pd.DataFrame()

    proposals = []
    proposals += mine_failure_patterns(run_id, existing_rule_ids, existing_expressions, staging_df)
    if batch_id:
        proposals += mine_target_drift(run_id, existing_expressions, target_mappings, batch_id)

    _write_proposals(proposals)


if __name__ == "__main__":
    run()
