#!/usr/bin/env bash
# Non-Terraform path: does everything terraform/main.tf + sql/bigquery_schema.sql
# do, as plain gcloud/bq/gsutil commands. Use this instead of Terraform if you'd
# rather not deal with Terraform state -- there is no functional difference in
# what gets created; it's the same GCS bucket, same BigQuery tables, uploaded
# the same way. Safe to re-run (every step is idempotent: `bq mk` and
# `gsutil mb` no-op if the resource already exists, `bq query` DDL uses
# CREATE TABLE IF NOT EXISTS / CREATE OR REPLACE VIEW).
#
# Usage: PROJECT_ID=ai-data-quality-gaurdian BUCKET_NAME=ai-data-quality-gaurdian-dq-bucket ./manual_gcp_setup.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-ai-data-quality-gaurdian}"
REGION="${REGION:-europe-west1}"
BUCKET_LOCATION="${BUCKET_LOCATION:-US}"   # matches the BigQuery dataset's location
BUCKET_NAME="${BUCKET_NAME:-ai-data-quality-gaurdian-dq-bucket}"
DATASET_ID="${DATASET_ID:-audit_controls}"

echo "== Project: $PROJECT_ID | Bucket: gs://$BUCKET_NAME | Region: $REGION =="

echo "-- Setting active project --"
gcloud config set project "$PROJECT_ID"

echo "-- Enabling required APIs --"
gcloud services enable \
  bigquery.googleapis.com \
  storage.googleapis.com \
  pubsub.googleapis.com \
  run.googleapis.com \
  eventarc.googleapis.com \
  aiplatform.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com

echo "-- Creating GCS bucket (no-op if it already exists) --"
gsutil mb -p "$PROJECT_ID" -l "$BUCKET_LOCATION" -b on "gs://$BUCKET_NAME" 2>/dev/null \
  || echo "   bucket already exists or name taken elsewhere -- if the latter, pick a new BUCKET_NAME"

echo "-- Uploading rule/target registries the validator + ai-proposals services read from GCS --"
gsutil cp ../specs/rules_registry.yaml "gs://$BUCKET_NAME/specs/rules_registry.yaml"
gsutil cp ../specs/target_table_registry.yaml "gs://$BUCKET_NAME/specs/target_table_registry.yaml"

echo "-- Creating BigQuery dataset + tables (CREATE ... IF NOT EXISTS, safe to re-run) --"
bq query --project_id="$PROJECT_ID" --use_legacy_sql=false < ../sql/bigquery_schema.sql

echo "-- Creating dashboard views (CREATE OR REPLACE, safe to re-run) --"
bq query --project_id="$PROJECT_ID" --use_legacy_sql=false < ../sql/dashboard_views.sql

echo "-- Creating Pub/Sub topics (no-op if they already exist) --"
for topic in staging-loaded validation-complete new-proposal; do
  gcloud pubsub topics create "$topic" 2>/dev/null || echo "   topic $topic already exists"
done

echo "-- Granting the GCS service agent Pub/Sub publish rights (one-time project prereq for ANY GCS-triggered Eventarc trigger -- doc-parser, ingest) --"
# The GCS service agent email is always PROJECT_NUMBER@gs-project-accounts.iam.gserviceaccount.com
PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${PROJECT_NUMBER}@gs-project-accounts.iam.gserviceaccount.com" \
  --role="roles/pubsub.publisher" --condition=None >/dev/null

echo "== Done. Next: seed reference tables (tools/load_report_catalog_seed.py, tools/load_applicable_regulations_seed.py), then deploy the services. =="
