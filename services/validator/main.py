"""
validator Cloud Run Job.

Runs registry-driven data-quality validation against the BigQuery staging
table (instead of a local CSV like the original
audit_validator_registry_single_loop.py), and additionally computes which
downstream/target tables are put at risk by the failures it finds.

Triggered after `ingest` publishes a `staging-loaded` Pub/Sub message
(wire a Cloud Run Jobs execution to that topic -- see README). Can also be
run on a schedule or by hand via `gcloud run jobs execute`.

Env vars:
  BQ_PROJECT, BQ_DATASET, STAGING_TABLE   -- where to read source data from
  BATCH_ID                                -- optional; defaults to latest batch in staging
  RULES_REGISTRY_PATH                     -- gs:// or local path to rules_registry.yaml
  TARGET_TABLE_REGISTRY_PATH              -- gs:// or local path to target_table_registry.yaml
  AUDIT_ASSESSMENT_DATE                   -- ISO date; defaults to "today" (UTC) if unset
  VALIDATION_COMPLETE_TOPIC               -- Pub/Sub topic name (default: validation-complete)

Local smoke test against a CSV (no BigQuery involved):
  python main.py --local-csv ../../../data/audit_data_150rows.csv \
      --local-rules ../../../specs/rules_registry.yaml \
      --local-out /tmp/validator_out
"""
import os
import sys
import json
import uuid
import logging
import argparse
from datetime import datetime, timezone

import yaml
import pandas as pd
from google.cloud import bigquery, pubsub_v1

from rules_engine import normalize_dataframe, run_all_rules
import gemini_helper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("validator")

BQ_PROJECT = os.environ.get("BQ_PROJECT", "ringed-hearth-504112-e3")
BQ_DATASET = os.environ.get("BQ_DATASET", "audit_controls")
STAGING_TABLE = os.environ.get("STAGING_TABLE", "staging_audit_controls")
BATCH_ID = os.environ.get("BATCH_ID")  # optional override
RULES_REGISTRY_PATH = os.environ.get(
    "RULES_REGISTRY_PATH", "gs://ringed-hearth-504112-e3-dq-bucket/specs/rules_registry.yaml"
)
TARGET_TABLE_REGISTRY_PATH = os.environ.get(
    "TARGET_TABLE_REGISTRY_PATH", "gs://ringed-hearth-504112-e3-dq-bucket/specs/target_table_registry.yaml"
)
VALIDATION_COMPLETE_TOPIC = os.environ.get("VALIDATION_COMPLETE_TOPIC", "validation-complete")

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


def _latest_batch_id():
    sql = f"""
        SELECT batch_id
        FROM `{BQ_PROJECT}.{BQ_DATASET}.{STAGING_TABLE}`
        ORDER BY loaded_at DESC
        LIMIT 1
    """
    rows = list(bq().query(sql).result())
    if not rows:
        raise RuntimeError(f"No rows found in {BQ_DATASET}.{STAGING_TABLE}; nothing to validate.")
    return rows[0]["batch_id"]


def _load_staging_df(batch_id):
    sql = f"""
        SELECT *
        FROM `{BQ_PROJECT}.{BQ_DATASET}.{STAGING_TABLE}`
        WHERE batch_id = @batch_id
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)]
    )
    return bq().query(sql, job_config=job_config).to_dataframe()


def _write_df(df: pd.DataFrame, table_name: str):
    if df.empty:
        logger.info("Nothing to write to %s (empty dataframe)", table_name)
        return
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{table_name}"
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND", autodetect=True)
    job = bq().load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()
    logger.info("Wrote %s rows to %s", len(df), table_id)


def compute_target_impact(failed_records: dict, target_mappings: list, run_id: str, run_ts: str,
                           resolver=None) -> pd.DataFrame:
    """
    For every mapping in target_table_registry.yaml, collect the join-key
    values of every record that failed one of its trigger_rule_ids, then
    look those keys up in the mapping's target_table (e.g. report_catalog)
    to find out exactly which downstream reports/records are affected.

    Only emits a row when a real match is found in the target table -- an
    application_id with no matching report produces no impact row, since
    nothing downstream is actually at risk. This is what makes
    target_impact_summary answer "which report does this bad record break?"
    instead of just "this rule failed."

    `resolver` is a callable(target_table, join_key, key_values) -> dict of
    {key_value: [row_dict, ...]}. Defaults to a live BigQuery lookup
    (_resolve_target_rows); _local_main() swaps in a CSV-backed resolver so
    this can be tested end-to-end with no GCP credentials at all.
    """
    resolver = resolver or _resolve_target_rows
    impact_rows = []
    for mapping in target_mappings or []:
        join_key = mapping.get("join_key")
        target_table = mapping.get("target_table")
        if not join_key or not target_table:
            continue

        # (rule_id, join_key_value) pairs to resolve, deduped for the query
        # but kept per-rule so every failure still gets its own impact row.
        candidates = []
        for rule_id in mapping.get("trigger_rule_ids", []):
            failed_df = failed_records.get(rule_id)
            if failed_df is None or failed_df.empty or join_key not in failed_df.columns:
                continue
            for _, row in failed_df.iterrows():
                key_val = row.get(join_key)
                if key_val is None or str(key_val).strip() == "":
                    continue  # can't resolve an impact for a blank/missing key
                candidates.append((rule_id, str(key_val).strip()))

        if not candidates:
            continue

        distinct_keys = sorted({key_val for _, key_val in candidates})
        try:
            resolved = resolver(target_table, join_key, distinct_keys)
        except Exception:
            logger.exception(
                "Could not query %s for mapping '%s' -- skipping impact resolution "
                "for this mapping this run (has it been created + seeded yet?)",
                target_table, mapping.get("name"),
            )
            continue

        for rule_id, key_val in candidates:
            for match in resolved.get(key_val, []):
                impact_rows.append({
                    "run_id": run_id,
                    "run_timestamp": run_ts,
                    "source_rule_id": rule_id,
                    "mapping_name": mapping.get("name", ""),
                    "join_key_value": key_val,
                    "target_table": target_table,
                    "impact_description": mapping.get("impact_description", ""),
                    "severity": mapping.get("severity", "Medium"),
                    "report_id": match.get("report_id"),
                    "report_name": match.get("report_name"),
                    "report_owner_team": match.get("report_owner_team"),
                    "consumers": match.get("consumers"),
                })

    return pd.DataFrame(impact_rows)


def _resolve_target_rows(target_table: str, join_key: str, key_values: list) -> dict:
    """Query `target_table` for rows whose `join_key` is in `key_values`.

    Returns {key_value: [row_dict, ...]} -- a list because one application
    can legitimately feed multiple reports (report_catalog is one row per
    report+application pair).
    """
    sql = f"""
        SELECT *
        FROM `{target_table}`
        WHERE {join_key} IN UNNEST(@key_values)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("key_values", "STRING", key_values)]
    )
    resolved = {}
    for row in bq().query(sql, job_config=job_config).result():
        row_dict = dict(row.items())
        key_val = str(row_dict.get(join_key, "")).strip()
        resolved.setdefault(key_val, []).append({
            "report_id": row_dict.get("report_id"),
            "report_name": row_dict.get("report_name"),
            "report_owner_team": row_dict.get("report_owner_team"),
            "consumers": row_dict.get("consumers"),
        })
    return resolved


def _make_local_resolver(catalog_csv_path: str):
    """Builds a resolver backed by a local CSV (e.g. report_catalog_seed.csv)
    instead of BigQuery, so target-impact resolution can be smoke-tested
    with zero GCP credentials. Ignores `target_table` (there's only one
    local catalog file) but matches the same call signature as the
    BigQuery-backed resolver.
    """
    catalog_df = pd.read_csv(catalog_csv_path, dtype=str).fillna("")

    def _resolve(target_table, join_key, key_values):
        if join_key not in catalog_df.columns:
            return {}
        subset = catalog_df[catalog_df[join_key].isin(key_values)]
        resolved = {}
        for _, row in subset.iterrows():
            key_val = str(row[join_key]).strip()
            resolved.setdefault(key_val, []).append({
                "report_id": row.get("report_id"),
                "report_name": row.get("report_name"),
                "report_owner_team": row.get("report_owner_team"),
                "consumers": row.get("consumers"),
            })
        return resolved

    return _resolve


def run(batch_id=None):
    run_id = str(uuid.uuid4())
    # A real datetime object, not .isoformat() -- BigQuery's pandas loader
    # can't convert a plain Python string into a TIMESTAMP-typed Arrow
    # column (rule_execution_summary/target_impact_summary both declare
    # run_timestamp as TIMESTAMP in terraform), so this must stay a
    # datetime instance all the way through to _write_df().
    run_ts = datetime.now(timezone.utc)

    rules = _read_yaml(RULES_REGISTRY_PATH).get("rules", [])
    try:
        target_mappings = _read_yaml(TARGET_TABLE_REGISTRY_PATH).get("mappings", [])
    except Exception:
        logger.warning(
            "Could not load %s -- target_impact_summary will be skipped. "
            "This file needs real downstream-table mappings from your team.",
            TARGET_TABLE_REGISTRY_PATH,
        )
        target_mappings = []

    batch_id = batch_id or BATCH_ID or _latest_batch_id()
    logger.info("Validating batch_id=%s", batch_id)

    df = _load_staging_df(batch_id)
    df = normalize_dataframe(df)

    assessment_date_str = os.environ.get("AUDIT_ASSESSMENT_DATE")
    assessment_date = (
        pd.Timestamp(assessment_date_str) if assessment_date_str
        else pd.Timestamp(datetime.now(timezone.utc).date())
    )

    results_df, failed_records = run_all_rules(df, rules, assessment_date)
    results_df["run_id"] = run_id
    results_df["run_timestamp"] = run_ts
    results_df["batch_id"] = batch_id

    failed_frames = []
    for rule_id, fdf in failed_records.items():
        if fdf.empty:
            continue
        tagged = fdf.copy()
        tagged.insert(0, "failed_rule_id", rule_id)
        tagged["run_id"] = run_id
        tagged["run_timestamp"] = run_ts
        tagged["batch_id"] = batch_id
        # BigQuery load needs consistent, string-safe columns for the free-form
        # source data; keep everything as string to avoid schema clashes
        # across differently-shaped failed-record subsets.
        failed_frames.append(tagged.astype(str))
    failed_df = pd.concat(failed_frames, ignore_index=True) if failed_frames else pd.DataFrame()

    impact_df = compute_target_impact(failed_records, target_mappings, run_id, run_ts)

    _write_df(results_df, "rule_execution_summary")
    _write_df(failed_df, "failed_records_detail")
    _write_df(impact_df, "target_impact_summary")

    dq_score = round(results_df["pass_percentage"].mean(), 2) if not results_df.empty else 0
    logger.info("Run %s complete. DQ score: %s%%", run_id, dq_score)

    _write_predicted_post_score(results_df, run_id, run_ts, batch_id, dq_score)

    _publish_validation_complete(run_id, batch_id, dq_score)
    return run_id, dq_score


def _write_predicted_post_score(results_df, run_id, run_ts, batch_id, dq_score):
    """Ask Gemini to project the confidence score this batch would reach if
    its currently-recommended remediations were applied, and write one row
    to dq_score_predictions -- the dashboard's v_dq_confidence_pre_post view
    reads this back as the "AI-Predicted Score After Remediation" card.
    Best-effort: a Gemini failure here (missing creds, quota, bad response)
    must never fail the validator run itself -- gemini_helper already falls
    back to a deterministic estimate internally, and this is additionally
    wrapped so even an unexpected error just skips the write."""
    try:
        rule_summaries = results_df[
            ["rule_id", "rule_name", "severity", "dimension", "total_records", "failed_count", "pass_percentage"]
        ].to_dict("records") if not results_df.empty else []
        prediction = gemini_helper.predict_post_remediation_score(dq_score, rule_summaries)
        pred_df = pd.DataFrame([{
            "batch_id": batch_id,
            "run_id": run_id,
            "run_timestamp": run_ts,
            "predicted_post_confidence_score": prediction.get("predicted_post_confidence_score"),
            "rationale": prediction.get("rationale"),
        }])
        _write_df(pred_df, "dq_score_predictions")
        logger.info(
            "Run %s: AI-predicted post-remediation score %s%% (pre: %s%%)",
            run_id, prediction.get("predicted_post_confidence_score"), dq_score,
        )
    except Exception:
        logger.exception(
            "Could not write a predicted post-remediation score for run %s -- "
            "the dashboard will fall back to its own deterministic estimate.",
            run_id,
        )


def _publish_validation_complete(run_id, batch_id, dq_score):
    topic_path = publisher().topic_path(BQ_PROJECT, VALIDATION_COMPLETE_TOPIC)
    payload = json.dumps({
        "run_id": run_id,
        "batch_id": batch_id,
        "dq_score": dq_score,
        "bq_project": BQ_PROJECT,
        "bq_dataset": BQ_DATASET,
    }).encode("utf-8")
    try:
        publisher().publish(topic_path, payload).result(timeout=10)
    except Exception:
        logger.exception(
            "Could not publish to %s (has terraform created the topic yet?)", topic_path
        )


def _local_main():
    """Run against a local CSV + local YAML files, writing CSV outputs
    instead of BigQuery -- mirrors the original local validator's behavior
    for quick iteration without touching GCP."""
    global RULES_REGISTRY_PATH
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-csv", required=True)
    ap.add_argument("--local-rules", required=True)
    ap.add_argument("--local-targets", default=None)
    ap.add_argument("--local-report-catalog", default=None,
                     help="CSV backing the target_table lookups (e.g. specs/report_catalog_seed.csv) "
                          "-- lets target-impact resolution run with zero GCP credentials.")
    ap.add_argument("--local-out", default="validator_out")
    args = ap.parse_args()

    os.makedirs(args.local_out, exist_ok=True)
    df = pd.read_csv(args.local_csv, dtype=str)
    if "batch_id" not in df.columns:
        df["batch_id"] = "local-test"
    df = normalize_dataframe(df)

    rules = _read_yaml(args.local_rules).get("rules", [])
    target_mappings = _read_yaml(args.local_targets).get("mappings", []) if args.local_targets else []

    resolver = _make_local_resolver(args.local_report_catalog) if args.local_report_catalog else (lambda *a: {})

    assessment_date = pd.Timestamp(datetime.now(timezone.utc).date())
    results_df, failed_records = run_all_rules(df, rules, assessment_date)
    impact_df = compute_target_impact(failed_records, target_mappings, "local-test", str(assessment_date), resolver=resolver)

    results_df.to_csv(os.path.join(args.local_out, "rule_execution_summary.csv"), index=False)
    impact_df.to_csv(os.path.join(args.local_out, "target_impact_summary.csv"), index=False)
    dq_score = round(results_df["pass_percentage"].mean(), 2) if not results_df.empty else 0
    print(f"DQ score: {dq_score}%")

    rule_summaries = results_df[
        ["rule_id", "rule_name", "severity", "dimension", "total_records", "failed_count", "pass_percentage"]
    ].to_dict("records") if not results_df.empty else []
    prediction = gemini_helper.predict_post_remediation_score(dq_score, rule_summaries)
    print(f"AI-predicted post-remediation score: {prediction.get('predicted_post_confidence_score')}% "
          f"({prediction.get('rationale')})")
    print(f"Wrote outputs to {args.local_out}/")


if __name__ == "__main__":
    if "--local-csv" in sys.argv:
        _local_main()
    else:
        run()
