#!/usr/bin/env python3
"""
One-time (or re-run-when-you-update-it) loader for the report_catalog
reference table. This table isn't pipeline output -- it's config your team
maintains describing which downstream reports read which application_ids,
seeded from specs/report_catalog_seed.csv.

Run after `terraform apply` has created the (empty) report_catalog table:

  python load_report_catalog_seed.py

Re-running replaces the table contents (WRITE_TRUNCATE) so editing the CSV
and re-running is the normal way to keep this up to date -- there's no
"append" mode here since this isn't event-sourced data.
"""
import os
import argparse

import pandas as pd
from google.cloud import bigquery

BQ_PROJECT = os.environ.get("BQ_PROJECT", "ai-data-quality-gaurdian")
BQ_DATASET = os.environ.get("BQ_DATASET", "audit_controls")
TABLE_NAME = "report_catalog"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv",
        default=os.path.join(os.path.dirname(__file__), "..", "specs", "report_catalog_seed.csv"),
    )
    args = ap.parse_args()

    df = pd.read_csv(args.csv, dtype=str)
    df["last_generated_at"] = pd.to_datetime(df["last_generated_at"], errors="coerce").dt.date

    client = bigquery.Client(project=BQ_PROJECT)
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{TABLE_NAME}"
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()
    print(f"Loaded {len(df)} rows into {table_id}")


if __name__ == "__main__":
    main()
