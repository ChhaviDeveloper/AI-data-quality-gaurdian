#!/usr/bin/env python3
"""
One-time (or re-run-when-you-update-it) loader for the owner_contacts
reference table -- same pattern as load_report_catalog_seed.py /
load_applicable_regulations_seed.py. This table isn't pipeline output; it's
the name -> email mapping dashboard-api's POST /remediate needs to know who
to send the "Data Quality Remediation Required" email to, since the ingested
audit CSV only ever carries owner *names* (business_owner/technology_owner),
never an email address. Seeded from specs/owner_contacts_seed.csv.

The shipped seed CSV covers every real-looking business_owner/technology_owner
name found in sample_data/*.csv, with placeholder @dq-guardian-demo.test
addresses that won't actually deliver -- except two names (Rakesh Iyer,
Divya Kulkarni, the owners of the two multi-issue demo apps APP-330/APP-331
in test_data_planted_issues.csv) which are mapped to real inboxes so a live
Remediate click during the Friday demo actually sends visible mail. Edit the
CSV and re-run this script to point any other name at a real address.

Run after `terraform apply` / manual_gcp_setup.sh has created the (empty)
owner_contacts table:

  python load_owner_contacts_seed.py

Re-running replaces the table contents (WRITE_TRUNCATE), so editing the CSV
and re-running is the normal way to keep this current.
"""
import os
import argparse

import pandas as pd
from google.cloud import bigquery

BQ_PROJECT = os.environ.get("BQ_PROJECT", "ringed-hearth-504112-e3")
BQ_DATASET = os.environ.get("BQ_DATASET", "audit_controls")
TABLE_NAME = "owner_contacts"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--csv",
        default=os.path.join(os.path.dirname(__file__), "..", "specs", "owner_contacts_seed.csv"),
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
