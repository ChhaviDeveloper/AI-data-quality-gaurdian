#!/usr/bin/env python3
"""
review_proposals.py -- human-in-the-loop CLI for the cloud pipeline.

Cloud-native equivalent of the root-level review_pending_rules.py, pointed
at BigQuery `rule_proposals` instead of a local specs/pending_rules.json,
and at the GCS-hosted rules_registry.yaml instead of a local file.

Run this from a machine with `gcloud auth login --update-adc` already done
(or any environment with BigQuery/Storage credentials), e.g.:

  python review_proposals.py

Approving a proposal:
  1. Marks it 'approved' in BigQuery (with reviewer + timestamp).
  2. Assigns the next rule_id and appends it to rules_registry.yaml in GCS.
  3. The next validator run picks the new rule up automatically -- no
     redeploy needed, since the registry is read fresh from GCS every run.
"""
import os
import uuid
from datetime import datetime, timezone

import yaml
from google.cloud import bigquery, storage

BQ_PROJECT = os.environ.get("BQ_PROJECT", "ringed-hearth-504112-e3")
BQ_DATASET = os.environ.get("BQ_DATASET", "audit_controls")
RULES_REGISTRY_GCS_PATH = os.environ.get(
    "RULES_REGISTRY_PATH", "gs://ringed-hearth-504112-e3-dq-bucket/specs/rules_registry.yaml"
)

bq_client = bigquery.Client(project=BQ_PROJECT)


def list_pending():
    sql = f"""
        SELECT proposal_id, rule_name, description, expression, severity,
               dimension, confidence, source, matched_count, created_at
        FROM `{BQ_PROJECT}.{BQ_DATASET}.rule_proposals`
        WHERE status = 'pending'
        ORDER BY created_at DESC
    """
    return list(bq_client.query(sql).result())


def _read_registry():
    bucket_name, blob_path = RULES_REGISTRY_GCS_PATH[len("gs://"):].split("/", 1)
    blob = storage.Client().bucket(bucket_name).blob(blob_path)
    return yaml.safe_load(blob.download_as_text())


def _write_registry(registry):
    bucket_name, blob_path = RULES_REGISTRY_GCS_PATH[len("gs://"):].split("/", 1)
    blob = storage.Client().bucket(bucket_name).blob(blob_path)
    blob.upload_from_string(yaml.safe_dump(registry, sort_keys=False), content_type="text/yaml")


def _next_rule_id(rules):
    nums = []
    for r in rules:
        rid = r.get("rule_id", "")
        try:
            nums.append(int(str(rid).replace("R", "")))
        except Exception:
            continue
    return f"R{str((max(nums) + 1) if nums else 1).zfill(3)}"


def approve(proposal, reviewer, note):
    registry = _read_registry()
    rules = registry.get("rules", [])
    new_rule_id = _next_rule_id(rules)
    rules.append({
        "rule_id": new_rule_id,
        "rule_name": proposal["rule_name"],
        "severity": proposal["severity"] or "High",
        "dimension": proposal["dimension"] or "Unknown",
        "type": "expression",
        "expression": proposal["expression"],
        "description": proposal["description"],
    })
    registry["rules"] = rules
    _write_registry(registry)

    sql = f"""
        UPDATE `{BQ_PROJECT}.{BQ_DATASET}.rule_proposals`
        SET status = 'approved', reviewed_by = @reviewer, reviewed_at = @reviewed_at,
            reviewer_note = @note, approved_rule_id = @rule_id
        WHERE proposal_id = @proposal_id
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("reviewer", "STRING", reviewer),
        bigquery.ScalarQueryParameter("reviewed_at", "TIMESTAMP", datetime.now(timezone.utc)),
        bigquery.ScalarQueryParameter("note", "STRING", note),
        bigquery.ScalarQueryParameter("rule_id", "STRING", new_rule_id),
        bigquery.ScalarQueryParameter("proposal_id", "STRING", proposal["proposal_id"]),
    ])
    bq_client.query(sql, job_config=job_config).result()
    print(f"Approved. New rule_id: {new_rule_id} (registry updated in GCS).")


def reject(proposal, reviewer, note):
    sql = f"""
        UPDATE `{BQ_PROJECT}.{BQ_DATASET}.rule_proposals`
        SET status = 'rejected', reviewed_by = @reviewer, reviewed_at = @reviewed_at,
            reviewer_note = @note
        WHERE proposal_id = @proposal_id
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("reviewer", "STRING", reviewer),
        bigquery.ScalarQueryParameter("reviewed_at", "TIMESTAMP", datetime.now(timezone.utc)),
        bigquery.ScalarQueryParameter("note", "STRING", note),
        bigquery.ScalarQueryParameter("proposal_id", "STRING", proposal["proposal_id"]),
    ])
    bq_client.query(sql, job_config=job_config).result()
    print("Rejected.")


def main():
    proposals = list_pending()
    if not proposals:
        print("No pending proposals.")
        return

    for i, p in enumerate(proposals, 1):
        print(f"{i}. [{p['source']}] {p['rule_name']} (confidence {p['confidence']}, matched {p['matched_count']})")

    choice = input("\nProposal number to review (or 'q' to quit): ").strip()
    if choice.lower() == "q":
        return
    p = proposals[int(choice) - 1]

    print(f"\nRule name : {p['rule_name']}")
    print(f"Description: {p['description']}")
    print(f"Expression : {p['expression']}")
    print(f"Severity/Dimension: {p['severity']} / {p['dimension']}")

    action = input("Approve (a) / Reject (r) / Skip (s): ").strip().lower()
    if action == "s":
        return
    reviewer = input("Reviewer name: ").strip() or "unknown"
    note = input("Optional note: ").strip()

    if action == "a":
        approve(dict(p), reviewer, note)
    elif action == "r":
        reject(dict(p), reviewer, note)


if __name__ == "__main__":
    main()
