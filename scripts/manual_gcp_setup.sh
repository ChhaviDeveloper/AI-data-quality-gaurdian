#!/usr/bin/env bash
# Non-Terraform path: does everything terraform/main.tf + sql/bigquery_schema.sql
# do, as plain gcloud/bq commands. Use this instead of Terraform if you'd
# rather not deal with Terraform state -- there is no functional difference in
# what gets created; it's the same GCS bucket, same BigQuery tables, uploaded
# the same way. Safe to re-run (every step checks existence first or uses
# CREATE TABLE IF NOT EXISTS / CREATE OR REPLACE VIEW, so nothing errors out
# on a second run).
#
# Usage: PROJECT_ID=ringed-hearth-504112-e3 BUCKET_NAME=ringed-hearth-504112-e3-dq-bucket ./manual_gcp_setup.sh
#
# ENABLE_CLOUD_RUN=false (default) skips Cloud Run / Cloud Build / Artifact
# Registry / Eventarc entirely -- those four APIs require a fully-verified
# ("prepaid") billing account on some free-trial accounts (India in
# particular), separate from just having a billing account linked. If you
# hit `UREQ_PROJECT_BILLING_NOT_OPEN` on those specifically, don't fight it --
# leave this false and run the pipeline as local Python processes instead
# (see README "Local-only execution"). Set ENABLE_CLOUD_RUN=true once you've
# completed the prepayment and want to deploy containers to Cloud Run.
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-ringed-hearth-504112-e3}"
REGION="${REGION:-europe-west1}"
BUCKET_LOCATION="${BUCKET_LOCATION:-US}"   # matches the BigQuery dataset's location
BUCKET_NAME="${BUCKET_NAME:-ringed-hearth-504112-e3-dq-bucket}"
DATASET_ID="${DATASET_ID:-audit_controls}"
ENABLE_CLOUD_RUN="${ENABLE_CLOUD_RUN:-false}"

echo "== Project: $PROJECT_ID | Bucket: gs://$BUCKET_NAME | Region: $REGION | Cloud Run APIs: $ENABLE_CLOUD_RUN =="

echo "-- Setting active project --"
gcloud config set project "$PROJECT_ID"

echo "-- Enabling core APIs (BigQuery, Storage, Pub/Sub, Vertex AI) --"
gcloud services enable \
  bigquery.googleapis.com \
  storage.googleapis.com \
  pubsub.googleapis.com \
  aiplatform.googleapis.com

if [ "$ENABLE_CLOUD_RUN" = "true" ]; then
  echo "-- Enabling Cloud Run / Cloud Build / Artifact Registry / Eventarc --"
  gcloud services enable \
    run.googleapis.com \
    eventarc.googleapis.com \
    cloudbuild.googleapis.com \
    artifactregistry.googleapis.com
else
  echo "-- Skipping Cloud Run / Cloud Build / Artifact Registry / Eventarc (ENABLE_CLOUD_RUN=false) --"
  echo "   Run each service as a local Python process instead -- see README 'Local-only execution'."
fi

echo "-- Creating GCS bucket (no-op if it already exists) --"
# Using `gcloud storage` (not `gsutil`) -- Google's current recommendation,
# and it surfaces real errors instead of a generic guess. We explicitly
# check existence first so a genuine creation failure (bad name, no
# permission, etc.) isn't swallowed and mistaken for "already exists".
if gcloud storage buckets describe "gs://$BUCKET_NAME" >/dev/null 2>&1; then
  echo "   bucket already exists, skipping creation"
else
  gcloud storage buckets create "gs://$BUCKET_NAME" \
    --project="$PROJECT_ID" --location="$BUCKET_LOCATION" --uniform-bucket-level-access
fi

echo "-- Uploading rule/target registries the validator + ai-proposals services read from GCS --"
gcloud storage cp ../specs/rules_registry.yaml "gs://$BUCKET_NAME/specs/rules_registry.yaml"
gcloud storage cp ../specs/target_table_registry.yaml "gs://$BUCKET_NAME/specs/target_table_registry.yaml"

echo "-- Creating BigQuery dataset + tables (CREATE ... IF NOT EXISTS, safe to re-run) --"
bq query --project_id="$PROJECT_ID" --use_legacy_sql=false < ../sql/bigquery_schema.sql

echo "-- Creating dashboard views (CREATE OR REPLACE, safe to re-run) --"
bq query --project_id="$PROJECT_ID" --use_legacy_sql=false < ../sql/dashboard_views.sql

echo "-- Creating Pub/Sub topics (no-op if they already exist) --"
for topic in staging-loaded validation-complete new-proposal; do
  if gcloud pubsub topics describe "$topic" --project="$PROJECT_ID" >/dev/null 2>&1; then
    echo "   topic $topic already exists"
  else
    gcloud pubsub topics create "$topic" --project="$PROJECT_ID"
  fi
done

if [ "$ENABLE_CLOUD_RUN" = "true" ]; then
  echo "-- Ensuring the GCS service agent exists (it's provisioned lazily -- doesn't exist until something forces it) --"
  gcloud storage service-agent --project="$PROJECT_ID" >/dev/null

  echo "-- Granting the GCS service agent Pub/Sub publish rights (one-time project prereq for ANY GCS-triggered Eventarc trigger -- doc-parser, ingest) --"
  # The GCS service agent email is always PROJECT_NUMBER@gs-project-accounts.iam.gserviceaccount.com.
  # Even after the service-agent command above returns, IAM sometimes takes a
  # little while to recognize the newly-provisioned identity -- retry a few
  # times with a short wait instead of failing outright on the first race.
  PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
  GCS_AGENT="serviceAccount:${PROJECT_NUMBER}@gs-project-accounts.iam.gserviceaccount.com"
  attempt=1
  until gcloud projects add-iam-policy-binding "$PROJECT_ID" \
      --member="$GCS_AGENT" --role="roles/pubsub.publisher" --condition=None >/dev/null 2>/tmp/gcs_agent_grant_err; do
    if [ "$attempt" -ge 6 ]; then
      echo "   Still failing after $attempt attempts -- last error:"
      cat /tmp/gcs_agent_grant_err
      echo "   This only blocks the GCS-triggered Eventarc triggers (doc-parser-trigger, ingest-trigger)."
      echo "   Everything else (dashboard-api, frontend, validator/ai-proposals jobs) is unaffected --"
      echo "   safe to continue, then just re-run this script later to retry this one grant."
      break
    fi
    echo "   Not ready yet (attempt $attempt/6) -- waiting 15s for the service agent to propagate..."
    attempt=$((attempt + 1))
    sleep 15
  done
else
  echo "-- Skipping GCS->Pub/Sub Eventarc IAM grant (only needed for Cloud Run triggers) --"
fi

echo "== Done. Next: seed reference tables (tools/load_report_catalog_seed.py, tools/load_applicable_regulations_seed.py), then run the pipeline locally -- see README 'Local-only execution'. =="
