"""
ingest Cloud Run service.

Triggered by Eventarc on GCS object-finalize events under:
  gs://<BUCKET>/incoming/*.csv

For each new raw CSV:
  1. Downloads it and tags every row with a batch_id (uuid4) and loaded_at
     timestamp, so every row in BigQuery can be traced back to the exact
     file/run that loaded it (this is the "lineage" the validator and
     target-impact steps key off of).
  2. Loads the tagged rows into the BigQuery staging table
     (audit_controls.staging_audit_controls), appending rather than
     overwriting so history accumulates run over run.
  3. Publishes a `staging-loaded` Pub/Sub message so the validator job can
     be triggered for just this batch.

This replaces the local root-level python_scripts/load_data_from_gcs_to_stg.py
for the cloud-native path; that script's plain load_table_from_uri() approach
is kept as a reference for the manual/local workflow.

Local smoke test (writes to a local CSV copy, skips GCS/BQ/PubSub):
  python main.py --local-csv ../../../data/audit_data_150rows.csv --local-out /tmp/tagged.csv
"""
import os
import io
import uuid
import logging
import argparse
from datetime import datetime, timezone

import functions_framework
import pandas as pd
from google.cloud import storage, bigquery, pubsub_v1

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("ingest")

BUCKET = os.environ.get("BUCKET", "ringed-hearth-504112-e3-dq-bucket")
BQ_PROJECT = os.environ.get("BQ_PROJECT", "ringed-hearth-504112-e3")
BQ_DATASET = os.environ.get("BQ_DATASET", "audit_controls")
STAGING_TABLE = os.environ.get("STAGING_TABLE", "staging_audit_controls")
INCOMING_PREFIX = os.environ.get("INCOMING_PREFIX", "incoming/")
STAGING_LOADED_TOPIC = os.environ.get("STAGING_LOADED_TOPIC", "staging-loaded")
DATASET_REGISTRY_TABLE = os.environ.get("DATASET_REGISTRY_TABLE", "dataset_registry")
# "Region/Location" as shown on the dashboard is a data-governance region
# (which country's regulations apply), not the GCP infra region -- set this
# per source system if it's not always the US.
DATA_REGION = os.environ.get("DATA_REGION", "United States")
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")

_storage_client = None
_bq_client = None
_publisher = None


def storage_client():
    global _storage_client
    if _storage_client is None:
        _storage_client = storage.Client()
    return _storage_client


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


@functions_framework.cloud_event
def main(cloud_event):
    data = cloud_event.data or {}
    bucket_name = data.get("bucket")
    name = data.get("name")
    logger.info("Received GCS event for gs://%s/%s", bucket_name, name)

    if not name or not name.startswith(INCOMING_PREFIX) or not name.lower().endswith(".csv"):
        logger.info("Ignoring object outside %s or not a .csv file", INCOMING_PREFIX)
        return ("ignored", 200)

    blob = storage_client().bucket(bucket_name).blob(name)
    metadata = blob.metadata or {}
    # If the uploader tagged this file with an existing batch_id (dashboard-api's
    # "re-validate this batch" flow -- see bq_ingest.py for the BigQuery-table
    # equivalent), reuse it and REPLACE that batch's rows instead of minting a
    # new batch_id and appending. Appending corrected rows under the same
    # batch_id would leave the old flawed rows sitting right alongside them
    # (duplicate application_ids, doubled counts) -- replace is what actually
    # lets the SAME batch's Pre/Post confidence score (v_dq_confidence_pre_post)
    # show a real before/after improvement on a second validator run.
    override_batch_id = (metadata.get("batch_id") or "").strip() or None
    batch_id = override_batch_id or str(uuid.uuid4())
    loaded_at = datetime.now(timezone.utc)

    raw_bytes = blob.download_as_bytes()
    df = pd.read_csv(io.BytesIO(raw_bytes), dtype=str)

    df["batch_id"] = batch_id
    df["loaded_at"] = loaded_at.isoformat()
    df["source_file"] = f"gs://{bucket_name}/{name}"

    if override_batch_id:
        row_count = _replace_batch_rows(df, batch_id)
        logger.info("Replaced batch %s in staging with %s corrected rows", batch_id, row_count)
    else:
        row_count = _load_dataframe_to_staging(df)
        logger.info("Loaded %s rows into staging as new batch %s", row_count, batch_id)

    _write_dataset_registry(
        batch_id=batch_id,
        source_uri=f"gs://{bucket_name}/{name}",
        dataset_name=os.path.basename(name),
        row_count=row_count,
        # -3 for the batch_id/loaded_at/source_file lineage columns we just added
        columns_count=max(len(df.columns) - 3, 0),
        loaded_at=loaded_at,
        uploaded_by=metadata.get("uploaded_by", "Unknown"),
    )
    _publish_staging_loaded(batch_id, row_count, f"gs://{bucket_name}/{name}")
    return ("ok", 200)


def _load_dataframe_to_staging(df: pd.DataFrame) -> int:
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{STAGING_TABLE}"
    # Load via a dataframe (not load_table_from_uri) so we can attach
    # batch_id/loaded_at/source_file lineage columns before the data lands.
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND", autodetect=True)
    load_job = bq().load_table_from_dataframe(df, table_id, job_config=job_config)
    load_job.result()
    return len(df)


def _replace_batch_rows(df: pd.DataFrame, batch_id: str) -> int:
    """Deletes this batch_id's existing rows from staging, then loads the
    corrected dataframe under the same batch_id. A plain WRITE_APPEND would
    leave the old (flawed) rows and the new (corrected) rows both in
    staging at once -- this is what actually makes it a *re-validation* of
    the batch instead of just more data piling up under the same label."""
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{STAGING_TABLE}"
    delete_job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("batch_id", "STRING", batch_id)]
    )
    bq().query(f"DELETE FROM `{table_id}` WHERE batch_id = @batch_id", job_config=delete_job_config).result()
    return _load_dataframe_to_staging(df)


def _write_dataset_registry(
    batch_id: str,
    source_uri: str,
    dataset_name: str,
    row_count: int,
    columns_count: int,
    loaded_at: datetime,
    uploaded_by: str,
):
    """Powers the dashboard's top bar + 'Dataset Summary' sidebar panel.
    Best-effort: a failure here shouldn't fail the ingest run (staging load
    and the staging-loaded Pub/Sub message already succeeded)."""
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{DATASET_REGISTRY_TABLE}"
    row = {
        "batch_id": batch_id,
        "dataset_name": dataset_name,
        "source_file": source_uri,
        "gcs_uri": source_uri,
        "bq_dataset": BQ_DATASET,
        "bq_table": STAGING_TABLE,
        "schema_created_at": loaded_at.isoformat(),
        "records_loaded": row_count,
        "columns_count": columns_count,
        "ai_model": GEMINI_MODEL,
        "region": DATA_REGION,
        "uploaded_by": uploaded_by,
        "uploaded_at": loaded_at.isoformat(),
        "status": "Ingestion Completed",
    }
    try:
        errors = bq().insert_rows_json(table_id, [row])
        if errors:
            logger.error("dataset_registry insert had errors: %s", errors)
    except Exception:
        logger.exception("Could not write dataset_registry row for batch %s", batch_id)


def _publish_staging_loaded(batch_id: str, row_count: int, source_file: str):
    topic_path = publisher().topic_path(BQ_PROJECT, STAGING_LOADED_TOPIC)
    payload = (
        f'{{"batch_id": "{batch_id}", "row_count": {row_count}, '
        f'"source_file": "{source_file}", "staging_table": '
        f'"{BQ_PROJECT}.{BQ_DATASET}.{STAGING_TABLE}"}}'
    ).encode("utf-8")
    try:
        publisher().publish(topic_path, payload).result(timeout=10)
    except Exception:
        logger.exception(
            "Could not publish to %s (has terraform created the topic yet?)", topic_path
        )


def _local_main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--local-csv", required=True)
    ap.add_argument("--local-out", default="tagged.csv")
    ap.add_argument(
        "--local-to-bq", action="store_true",
        help="Also load the tagged rows into the real BigQuery staging table and write a "
             "dataset_registry row -- the no-Cloud-Run path (skips GCS/Eventarc entirely, "
             "goes local file -> real BigQuery directly). Needs Application Default "
             "Credentials (gcloud auth application-default login) with BigQuery write access.",
    )
    ap.add_argument(
        "--batch-id",
        help="Reuse an existing batch_id and REPLACE its rows in staging instead of minting a "
             "new batch_id and appending -- the local-mode equivalent of dashboard-api's "
             "'re-validate this batch' flow. See _replace_batch_rows.",
    )
    args = ap.parse_args()

    batch_id = args.batch_id or str(uuid.uuid4())
    loaded_at = datetime.now(timezone.utc)

    df = pd.read_csv(args.local_csv, dtype=str)
    df["batch_id"] = batch_id
    df["loaded_at"] = loaded_at.isoformat()
    df["source_file"] = args.local_csv
    df.to_csv(args.local_out, index=False)
    print(f"Wrote {len(df)} tagged rows to {args.local_out}")

    if args.local_to_bq:
        if args.batch_id:
            row_count = _replace_batch_rows(df, batch_id)
            print(f"Replaced batch {batch_id} in {BQ_PROJECT}.{BQ_DATASET}.{STAGING_TABLE} with {row_count} corrected rows")
        else:
            row_count = _load_dataframe_to_staging(df)
            print(f"Loaded {row_count} rows into {BQ_PROJECT}.{BQ_DATASET}.{STAGING_TABLE} (batch {batch_id})")
        _write_dataset_registry(
            batch_id=batch_id,
            source_uri=args.local_csv,
            dataset_name=os.path.basename(args.local_csv),
            row_count=row_count,
            columns_count=max(len(df.columns) - 3, 0),
            loaded_at=loaded_at,
            uploaded_by=os.environ.get("USER", "local"),
        )
        print(f"batch_id={batch_id}  <- pass this to validator's BATCH_ID env var")


if __name__ == "__main__":
    _local_main()
