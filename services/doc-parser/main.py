"""
doc-parser Cloud Run service.

Triggered by Eventarc on GCS object-finalize events under:
  gs://<BUCKET>/functional-docs/*.docx

For each new/updated functional document:
  1. Downloads the docx from GCS (functional_parser.py handles gs:// paths).
  2. Regenerates specs/rules_registry.yaml and writes it back to GCS.
  3. Appends a version snapshot to BigQuery `rules_registry_history` so
     every registry change is auditable (who/what changed the rules, when).

Local smoke test (no GCP needed for the parse step, only for GCS I/O):
  python main.py --local-doc ../../../Functional_Document_Hackathon_v1.0.docx --local-out /tmp/rules_registry.yaml

Deploy (see cloud-pipeline/README.md for the full command + Eventarc trigger).
"""
import os
import sys
import logging
import argparse
from datetime import datetime, timezone

import functions_framework
import yaml
from google.cloud import bigquery

from functional_parser import generate_rules_registry_from_functional_doc

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("doc-parser")

BUCKET = os.environ.get("BUCKET", "ai-data-quality-gaurdian-dq-bucket")
BQ_PROJECT = os.environ.get("BQ_PROJECT", "ai-data-quality-gaurdian")
BQ_DATASET = os.environ.get("BQ_DATASET", "audit_controls")
REGISTRY_GCS_PATH = os.environ.get("REGISTRY_GCS_PATH", f"gs://{BUCKET}/specs/rules_registry.yaml")
DOC_PREFIX = os.environ.get("DOC_PREFIX", "functional-docs/")

_bq_client = None


def bq():
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=BQ_PROJECT)
    return _bq_client


@functions_framework.cloud_event
def main(cloud_event):
    """Entry point for the Eventarc GCS-finalize CloudEvent."""
    data = cloud_event.data or {}
    bucket = data.get("bucket")
    name = data.get("name")
    logger.info("Received GCS event for gs://%s/%s", bucket, name)

    if not name or not name.startswith(DOC_PREFIX) or not name.lower().endswith(".docx"):
        logger.info("Ignoring object outside %s or not a .docx file", DOC_PREFIX)
        return ("ignored", 200)

    source_path = f"gs://{bucket}/{name}"
    logger.info("Parsing functional document: %s", source_path)

    registry = generate_rules_registry_from_functional_doc(source_path, REGISTRY_GCS_PATH)

    rule_count = len(registry.get("rules", []))
    logger.info("Wrote %s rules to %s", rule_count, REGISTRY_GCS_PATH)

    _record_registry_history(source_path, rule_count, registry)
    return ("ok", 200)


def _record_registry_history(source_path, rule_count, registry):
    """Append a version snapshot to audit_controls.rules_registry_history.

    Non-fatal if the table doesn't exist yet (run terraform first) -- we log
    and continue so a missing history table never blocks the actual parse.
    """
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.rules_registry_history"
    row = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_document": source_path,
        "rule_count": rule_count,
        "registry_yaml": yaml.safe_dump(registry, sort_keys=False),
    }
    try:
        errors = bq().insert_rows_json(table_id, [row])
        if errors:
            logger.error("BigQuery insert errors writing to %s: %s", table_id, errors)
    except Exception:
        logger.exception(
            "Could not write registry history to %s (has terraform been applied yet?)",
            table_id,
        )


def _local_main():
    """Run the parser locally against a local .docx, skipping GCS/BigQuery.

    Useful for testing the parsing logic itself before wiring up Cloud Run.
    """
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-doc", required=True)
    ap.add_argument("--local-out", default="rules_registry.yaml")
    args = ap.parse_args()
    registry = generate_rules_registry_from_functional_doc(args.local_doc, args.local_out)
    print(f"Wrote {len(registry['rules'])} rules to {args.local_out}")


if __name__ == "__main__":
    _local_main()
