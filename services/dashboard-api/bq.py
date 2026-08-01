"""
Thin BigQuery query helper shared by all dashboard-api routes. All reads go
through the v_dq_* views in sql/dashboard_views.sql (never base tables
directly), so the API stays agnostic to schema changes underneath the views.
"""
import os
import logging

from google.cloud import bigquery

logger = logging.getLogger("dashboard-api.bq")

BQ_PROJECT = os.environ.get("BQ_PROJECT", "ringed-hearth-504112-e3")
BQ_DATASET = os.environ.get("BQ_DATASET", "audit_controls")

_client = None


def client() -> bigquery.Client:
    global _client
    if _client is None:
        _client = bigquery.Client(project=BQ_PROJECT)
    return _client


def table(name: str) -> str:
    return f"`{BQ_PROJECT}.{BQ_DATASET}.{name}`"


def query(sql: str, params: list | None = None) -> list[dict]:
    job_config = bigquery.QueryJobConfig(query_parameters=params or [])
    rows = client().query(sql, job_config=job_config).result()
    return [dict(row.items()) for row in rows]


def insert_row(table_name: str, row: dict):
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{table_name}"
    errors = client().insert_rows_json(table_id, [row])
    if errors:
        raise RuntimeError(f"Insert into {table_id} failed: {errors}")
