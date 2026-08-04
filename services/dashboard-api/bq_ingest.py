"""
Lets someone validate data that's already sitting in a BigQuery table,
instead of only ever uploading a CSV. Deliberately copied (not imported)
from services/ingest/main.py's staging-load logic rather than shared as a
library -- same "each Cloud Run service stays self-contained at build time"
reasoning as gemini_helper.py/email_helper.py.

Mirrors the CSV path exactly once the data is a DataFrame: tag it with
batch_id/loaded_at/source_file lineage columns, append into
staging_audit_controls, write a dataset_registry row, and publish
staging-loaded on Pub/Sub. That Pub/Sub message is what the already-deployed
Eventarc trigger (trigger-validator) reacts to, so a BigQuery-sourced batch
gets validated through the exact same async pipeline a GCS-uploaded CSV
does -- no separate "BQ validator" path needed.

Local smoke test (needs Application Default Credentials with BigQuery
read/write access):
  python3 -c "from bq_ingest import ingest_from_bigquery_table; print(ingest_from_bigquery_table('project.dataset.table'))"
"""
import os
import re
import uuid
import logging
from datetime import datetime, timezone

import pandas as pd
from google.cloud import bigquery, pubsub_v1

logger = logging.getLogger("dashboard-api.bq_ingest")

BQ_PROJECT = os.environ.get("BQ_PROJECT", "ringed-hearth-504112-e3")
BQ_DATASET = os.environ.get("BQ_DATASET", "audit_controls")
STAGING_TABLE = os.environ.get("STAGING_TABLE", "staging_audit_controls")
DATASET_REGISTRY_TABLE = os.environ.get("DATASET_REGISTRY_TABLE", "dataset_registry")
STAGING_LOADED_TOPIC = os.environ.get("STAGING_LOADED_TOPIC", "staging-loaded")

_TABLE_REF_RE = re.compile(r"^[\w-]+\.[\w-]+\.[\w-]+$")

_bq_client = None
_publisher = None


def _bq() -> bigquery.Client:
    global _bq_client
    if _bq_client is None:
        _bq_client = bigquery.Client(project=BQ_PROJECT)
    return _bq_client


def _publisher_client():
    global _publisher
    if _publisher is None:
        _publisher = pubsub_v1.PublisherClient()
    return _publisher


class BQIngestError(ValueError):
    """Raised for anything the caller should surface as a 400, not a 500 --
    bad table reference, missing required column, empty table, etc."""


def ingest_from_bigquery_table(source_table: str, uploaded_by: str = "dashboard-user") -> dict:
    """source_table must be fully-qualified: project.dataset.table. Returns
    {batch_id, row_count, source_table}."""
    if not _TABLE_REF_RE.match(source_table or ""):
        raise BQIngestError(
            f"'{source_table}' doesn't look like a fully-qualified BigQuery table "
            "(expected project.dataset.table)."
        )

    try:
        df = _bq().query(f"SELECT * FROM `{source_table}`").to_dataframe()
    except Exception as exc:
        raise BQIngestError(f"Could not read {source_table}: {exc}") from exc

    if df.empty:
        raise BQIngestError(f"{source_table} has no rows.")

    if "application_id" not in df.columns:
        raise BQIngestError(
            f"{source_table} has no application_id column -- the rules engine keys every "
            "check off of it, so this table can't be validated as-is."
        )

    batch_id = str(uuid.uuid4())
    loaded_at = datetime.now(timezone.utc)

    # Stringify every value while preserving real NULLs (so R00x's .isnull()
    # checks still work) -- matches pd.read_csv(dtype=str)'s behavior on the
    # CSV path, and keeps this batch type-consistent with the existing
    # all-STRING staging_audit_controls schema regardless of what native
    # BigQuery types the source table actually used.
    df = df.astype(object).where(pd.notnull(df), None)
    for col in df.columns:
        df[col] = df[col].apply(lambda v: v if v is None else str(v))

    df["batch_id"] = batch_id
    df["loaded_at"] = loaded_at.isoformat()
    df["source_file"] = f"bq://{source_table}"

    row_count = _load_dataframe_to_staging(df)
    logger.info("Loaded %s rows from %s into staging as batch %s", row_count, source_table, batch_id)

    _write_dataset_registry(
        batch_id=batch_id,
        source_uri=f"bq://{source_table}",
        dataset_name=source_table.split(".")[-1],
        row_count=row_count,
        columns_count=max(len(df.columns) - 3, 0),
        loaded_at=loaded_at,
        uploaded_by=uploaded_by,
    )
    _publish_staging_loaded(batch_id, row_count, f"bq://{source_table}")

    return {"batch_id": batch_id, "row_count": row_count, "source_table": source_table}


def _load_dataframe_to_staging(df: pd.DataFrame) -> int:
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{STAGING_TABLE}"
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_APPEND", autodetect=True)
    load_job = _bq().load_table_from_dataframe(df, table_id, job_config=job_config)
    load_job.result()
    return len(df)


def _write_dataset_registry(batch_id, source_uri, dataset_name, row_count, columns_count, loaded_at, uploaded_by):
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
        "ai_model": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
        "region": os.environ.get("DATA_REGION", "United States"),
        "uploaded_by": uploaded_by,
        "uploaded_at": loaded_at.isoformat(),
        "status": "Ingestion Completed",
    }
    try:
        errors = _bq().insert_rows_json(table_id, [row])
        if errors:
            logger.error("BigQuery insert errors writing to %s: %s", table_id, errors)
    except Exception:
        logger.exception("Could not write dataset_registry row for batch %s", batch_id)


def _publish_staging_loaded(batch_id: str, row_count: int, source_file: str):
    topic_path = _publisher_client().topic_path(BQ_PROJECT, STAGING_LOADED_TOPIC)
    payload = (
        f'{{"batch_id": "{batch_id}", "row_count": {row_count}, '
        f'"source_file": "{source_file}", "staging_table": '
        f'"{BQ_PROJECT}.{BQ_DATASET}.{STAGING_TABLE}"}}'
    ).encode("utf-8")
    try:
        _publisher_client().publish(topic_path, payload).result(timeout=10)
    except Exception:
        logger.exception("Could not publish to %s -- validator won't auto-trigger for batch %s", topic_path, batch_id)
