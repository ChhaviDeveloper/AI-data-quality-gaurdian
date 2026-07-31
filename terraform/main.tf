terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = ">= 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

# ---------------------------------------------------------------------------
# GCS -- the pipeline's landing bucket. services/ingest, services/doc-parser
# etc. all default their BUCKET env var to var.bucket_name, so this needs to
# exist before any Eventarc trigger pointing at it can be created (that
# wiring happens in GitHub Actions, not here -- see README "Deploying").
# ---------------------------------------------------------------------------
resource "google_storage_bucket" "dq_bucket" {
  name                        = var.bucket_name
  location                    = var.bucket_location
  uniform_bucket_level_access = true
  force_destroy               = false

  # incoming/*.csv and functional-docs/*.docx are populated by whoever's
  # running the demo (see README step 4) -- not created here since GCS has
  # no real "folders", just object-name prefixes.
}

# One-time project prerequisite for ANY GCS-triggered Eventarc trigger
# (doc-parser on functional-docs/, ingest on incoming/): GCS publishes
# object-finalize events by having its own service agent publish to Pub/Sub
# under the hood, so that service agent needs publisher rights. Deploying
# doc-parser/ingest's Eventarc triggers fails with a permissions error
# without this -- easy to miss since it's not obviously related to either
# service's own service account.
data "google_storage_project_service_account" "gcs_account" {}

resource "google_project_iam_member" "gcs_pubsub_publisher" {
  project = var.project_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${data.google_storage_project_service_account.gcs_account.email_address}"
}

# The rules/target-table registries are read straight from GCS by
# services/validator and services/ai-proposals (RULES_REGISTRY_PATH /
# TARGET_TABLE_REGISTRY_PATH default to gs://<bucket>/specs/...). Keeping
# these as bucket objects managed by Terraform means `terraform apply`
# re-uploads the latest checked-in copy every time -- if you're hand-editing
# rules_registry.yaml via tools/review_proposals.py between applies, that
# workflow writes directly to GCS and this resource will overwrite it on the
# next apply. Comment this out once the registry is being actively
# maintained via the approve/reject flow instead of the checked-in file.
resource "google_storage_bucket_object" "rules_registry_seed" {
  name         = "specs/rules_registry.yaml"
  bucket       = google_storage_bucket.dq_bucket.name
  source       = "${path.module}/../specs/rules_registry.yaml"
  content_type = "application/x-yaml"
}

resource "google_storage_bucket_object" "target_table_registry_seed" {
  name         = "specs/target_table_registry.yaml"
  bucket       = google_storage_bucket.dq_bucket.name
  source       = "${path.module}/../specs/target_table_registry.yaml"
  content_type = "application/x-yaml"
}

# ---------------------------------------------------------------------------
# BigQuery
# ---------------------------------------------------------------------------
# NOTE: `audit_controls` and `staging_audit_controls` may already exist from
# the local/manual runbook steps your team already ran. If so, set
# create_dataset=false and `terraform import` the dataset before applying,
# or Terraform will try (and fail) to create something that's already there.
resource "google_bigquery_dataset" "audit_controls" {
  count      = var.create_dataset ? 1 : 0
  dataset_id = var.dataset_id
  location   = "US"
}

# staging_audit_controls and failed_records_detail are intentionally NOT
# defined here: both are wide, variable-column tables created via
# autodetect on first load by the ingest/validator services. Managing their
# schema in Terraform would fight with autodetect every time a new column
# shows up in the source CSV.

resource "google_bigquery_table" "rule_execution_summary" {
  dataset_id = var.dataset_id
  table_id   = "rule_execution_summary"

  time_partitioning {
    type  = "DAY"
    field = "run_timestamp"
  }
  clustering = ["rule_id", "batch_id"]

  schema = jsonencode([
    { name = "rule_id", type = "STRING", mode = "REQUIRED" },
    { name = "rule_name", type = "STRING", mode = "NULLABLE" },
    { name = "description", type = "STRING", mode = "NULLABLE" },
    { name = "severity", type = "STRING", mode = "NULLABLE" },
    { name = "dimension", type = "STRING", mode = "NULLABLE" },
    { name = "total_records", type = "INT64", mode = "NULLABLE" },
    { name = "failed_count", type = "INT64", mode = "NULLABLE" },
    { name = "passed_count", type = "INT64", mode = "NULLABLE" },
    { name = "pass_percentage", type = "FLOAT64", mode = "NULLABLE" },
    { name = "status", type = "STRING", mode = "NULLABLE" },
    { name = "run_id", type = "STRING", mode = "REQUIRED" },
    { name = "run_timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "batch_id", type = "STRING", mode = "REQUIRED" },
  ])
}

resource "google_bigquery_table" "target_impact_summary" {
  dataset_id = var.dataset_id
  table_id   = "target_impact_summary"

  time_partitioning {
    type  = "DAY"
    field = "run_timestamp"
  }
  clustering = ["source_rule_id", "target_table"]

  schema = jsonencode([
    { name = "run_id", type = "STRING", mode = "REQUIRED" },
    { name = "run_timestamp", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "source_rule_id", type = "STRING", mode = "NULLABLE" },
    { name = "mapping_name", type = "STRING", mode = "NULLABLE" },
    { name = "join_key_value", type = "STRING", mode = "NULLABLE" },
    { name = "target_table", type = "STRING", mode = "NULLABLE" },
    { name = "impact_description", type = "STRING", mode = "NULLABLE" },
    { name = "severity", type = "STRING", mode = "NULLABLE" },
    { name = "report_id", type = "STRING", mode = "NULLABLE" },
    { name = "report_name", type = "STRING", mode = "NULLABLE" },
    { name = "report_owner_team", type = "STRING", mode = "NULLABLE" },
    { name = "consumers", type = "STRING", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "rule_proposals" {
  dataset_id = var.dataset_id
  table_id   = "rule_proposals"

  time_partitioning {
    type  = "DAY"
    field = "created_at"
  }
  clustering = ["status", "source"]

  schema = jsonencode([
    { name = "proposal_id", type = "STRING", mode = "REQUIRED" },
    { name = "created_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "created_by", type = "STRING", mode = "NULLABLE" },
    { name = "status", type = "STRING", mode = "NULLABLE" },
    { name = "source", type = "STRING", mode = "NULLABLE" },
    { name = "run_id", type = "STRING", mode = "NULLABLE" },
    { name = "confidence", type = "FLOAT64", mode = "NULLABLE" },
    { name = "rule_name", type = "STRING", mode = "NULLABLE" },
    { name = "description", type = "STRING", mode = "NULLABLE" },
    { name = "expression", type = "STRING", mode = "NULLABLE" },
    { name = "severity", type = "STRING", mode = "NULLABLE" },
    { name = "dimension", type = "STRING", mode = "NULLABLE" },
    { name = "matched_count", type = "INT64", mode = "NULLABLE" },
    { name = "suggested_tests", type = "STRING", mode = "NULLABLE" },
    { name = "notes", type = "STRING", mode = "NULLABLE" },
    { name = "reviewed_by", type = "STRING", mode = "NULLABLE" },
    { name = "reviewed_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "reviewer_note", type = "STRING", mode = "NULLABLE" },
    { name = "approved_rule_id", type = "STRING", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "rules_registry_history" {
  dataset_id = var.dataset_id
  table_id   = "rules_registry_history"

  time_partitioning {
    type  = "DAY"
    field = "generated_at"
  }

  schema = jsonencode([
    { name = "generated_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "source_document", type = "STRING", mode = "NULLABLE" },
    { name = "rule_count", type = "INT64", mode = "NULLABLE" },
    { name = "registry_yaml", type = "STRING", mode = "NULLABLE" },
  ])
}

# report_catalog: the "target table" that resolves a bad application_id into
# the actual downstream reports it feeds. One row per (report, application)
# pair -- a report that covers 10 applications has 10 rows. Seeded from
# specs/report_catalog_seed.csv via tools/load_report_catalog_seed.py; treat
# this as a reference/config table your team maintains, not pipeline output.
resource "google_bigquery_table" "report_catalog" {
  dataset_id = var.dataset_id
  table_id   = "report_catalog"

  clustering = ["application_id", "report_id"]

  schema = jsonencode([
    { name = "report_id", type = "STRING", mode = "REQUIRED" },
    { name = "report_name", type = "STRING", mode = "NULLABLE" },
    { name = "application_id", type = "STRING", mode = "REQUIRED" },
    { name = "report_type", type = "STRING", mode = "NULLABLE" },
    { name = "regulatory_body", type = "STRING", mode = "NULLABLE" },
    { name = "report_owner_team", type = "STRING", mode = "NULLABLE" },
    { name = "consumers", type = "STRING", mode = "NULLABLE" },
    { name = "refresh_frequency", type = "STRING", mode = "NULLABLE" },
    { name = "last_generated_at", type = "DATE", mode = "NULLABLE" },
    { name = "report_status", type = "STRING", mode = "NULLABLE" },
    { name = "data_fields_used", type = "STRING", mode = "NULLABLE" },
  ])
}

# ---------------------------------------------------------------------------
# Added for the custom dashboard (see sql/bigquery_schema.sql for the
# matching manual-apply DDL and rationale on each table).
# ---------------------------------------------------------------------------
resource "google_bigquery_table" "dataset_registry" {
  dataset_id = var.dataset_id
  table_id   = "dataset_registry"

  time_partitioning {
    type  = "DAY"
    field = "uploaded_at"
  }
  clustering = ["batch_id"]

  schema = jsonencode([
    { name = "batch_id", type = "STRING", mode = "REQUIRED" },
    { name = "dataset_name", type = "STRING", mode = "NULLABLE" },
    { name = "source_file", type = "STRING", mode = "NULLABLE" },
    { name = "gcs_uri", type = "STRING", mode = "NULLABLE" },
    { name = "bq_dataset", type = "STRING", mode = "NULLABLE" },
    { name = "bq_table", type = "STRING", mode = "NULLABLE" },
    { name = "schema_created_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "records_loaded", type = "INT64", mode = "NULLABLE" },
    { name = "columns_count", type = "INT64", mode = "NULLABLE" },
    { name = "ai_model", type = "STRING", mode = "NULLABLE" },
    { name = "region", type = "STRING", mode = "NULLABLE" },
    { name = "uploaded_by", type = "STRING", mode = "NULLABLE" },
    { name = "uploaded_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "status", type = "STRING", mode = "NULLABLE" },
  ])
}

resource "google_bigquery_table" "remediation_actions" {
  dataset_id = var.dataset_id
  table_id   = "remediation_actions"

  time_partitioning {
    type  = "DAY"
    field = "initiated_at"
  }
  clustering = ["run_id", "rule_id"]

  schema = jsonencode([
    { name = "action_id", type = "STRING", mode = "REQUIRED" },
    { name = "run_id", type = "STRING", mode = "REQUIRED" },
    { name = "rule_id", type = "STRING", mode = "REQUIRED" },
    { name = "batch_id", type = "STRING", mode = "NULLABLE" },
    { name = "issue_type", type = "STRING", mode = "NULLABLE" },
    { name = "issue_description", type = "STRING", mode = "NULLABLE" },
    { name = "recommended_remediation", type = "STRING", mode = "NULLABLE" },
    { name = "action_type", type = "STRING", mode = "NULLABLE" },
    { name = "status", type = "STRING", mode = "NULLABLE" },
    { name = "initiated_by", type = "STRING", mode = "NULLABLE" },
    { name = "initiated_at", type = "TIMESTAMP", mode = "REQUIRED" },
    { name = "completed_at", type = "TIMESTAMP", mode = "NULLABLE" },
    { name = "remediation_details", type = "STRING", mode = "NULLABLE" },
  ])
}

# applicable_regulations: reference/config, seeded from
# specs/applicable_regulations_seed.csv via
# tools/load_applicable_regulations_seed.py -- same pattern as report_catalog.
resource "google_bigquery_table" "applicable_regulations" {
  dataset_id = var.dataset_id
  table_id   = "applicable_regulations"

  clustering = ["country", "regulation_code"]

  schema = jsonencode([
    { name = "regulation_code", type = "STRING", mode = "REQUIRED" },
    { name = "regulation_name", type = "STRING", mode = "NULLABLE" },
    { name = "description", type = "STRING", mode = "NULLABLE" },
    { name = "data_category", type = "STRING", mode = "NULLABLE" },
    { name = "country", type = "STRING", mode = "NULLABLE" },
    { name = "authority", type = "STRING", mode = "NULLABLE" },
    { name = "source_url", type = "STRING", mode = "NULLABLE" },
  ])
}

# ---------------------------------------------------------------------------
# Pub/Sub -- the "wiring" between pipeline stages
# ---------------------------------------------------------------------------
resource "google_pubsub_topic" "staging_loaded" {
  name = "staging-loaded"
}

resource "google_pubsub_topic" "validation_complete" {
  name = "validation-complete"
}

resource "google_pubsub_topic" "new_proposal" {
  name = "new-proposal"
}

# Cloud Run services/jobs, Eventarc triggers, and Pub/Sub push subscriptions
# to the job-trigger functions are deployed via GitHub Actions (gcloud),
# matching the pattern already used elsewhere in this repo -- see
# ../README.md for the exact commands. Keeping container-dependent
# infrastructure out of Terraform avoids a chicken-and-egg problem where
# `terraform apply` fails because no image has been pushed yet.
