#!/usr/bin/env python3
"""
One-time (or re-run-when-you-update-it) loader for the applicable_regulations
reference table -- same pattern as load_report_catalog_seed.py. This table
isn't pipeline output; it's the regulation-by-country reference set the
dashboard's "Applicable Laws & Regulations" panel reads, seeded from
specs/applicable_regulations_seed.csv.

Run after `terraform apply` has created the (empty) applicable_regulations
table:

  python load_applicable_regulations_seed.py

Re-running replaces the table contents (WRITE_TRUNCATE), so editing the CSV
(e.g. adding a country/regulation your data actually touches) and re-running
is the normal way to keep this current.
"""
import os
import argparse

import pandas as pd
from google.cloud import bigquery

BQ_PROJECT = os.environ.get("BQ_PROJECT", "ringed-hearth-504112-e3")
BQ_DATASET = os.environ.get("BQ_DATASET", "audit_controls")
TABLE_NAME = "applicable_regulations"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv",
        default=os.path.join(
            os.path.dirname(__file__), "..", "specs", "applicable_regulations_seed.csv"
        ),
    )
    args = ap.parse_args()

    df = pd.read_csv(args.csv, dtype=str)

    client = bigquery.Client(project=BQ_PROJECT)
    table_id = f"{BQ_PROJECT}.{BQ_DATASET}.{TABLE_NAME}"
    job_config = bigquery.LoadJobConfig(write_disposition="WRITE_TRUNCATE")
    job = client.load_table_from_dataframe(df, table_id, job_config=job_config)
    job.result()
    print(f"Loaded {len(df)} rows into {table_id}")


if __name__ == "__main__":
    main()
