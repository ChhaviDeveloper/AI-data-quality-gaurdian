-- Manual-apply mirror of cloud-pipeline/terraform/main.tf.
-- Prefer applying via Terraform Cloud (push to /cloud-pipeline/terraform,
-- or wherever your workspace is scoped). This file is here so anyone can
-- eyeball the schema without reading HCL, or paste it into the BigQuery
-- console for a quick manual setup while Terraform access is being sorted out.

CREATE SCHEMA IF NOT EXISTS `ringed-hearth-504112-e3.audit_controls`
OPTIONS (location = 'US');

CREATE TABLE IF NOT EXISTS `ringed-hearth-504112-e3.audit_controls.rule_execution_summary` (
  rule_id STRING NOT NULL,
  rule_name STRING,
  description STRING,
  severity STRING,
  dimension STRING,
  total_records INT64,
  failed_count INT64,
  passed_count INT64,
  pass_percentage FLOAT64,
  status STRING,
  run_id STRING NOT NULL,
  run_timestamp TIMESTAMP NOT NULL,
  batch_id STRING NOT NULL
)
PARTITION BY DATE(run_timestamp)
CLUSTER BY rule_id, batch_id;

-- One row per validator run -- Vertex AI's estimate of the confidence score
-- a batch would reach if all its currently-recommended remediations were
-- actually applied. Written once by services/validator right after it
-- writes rule_execution_summary for that run (see gemini_helper.py there).
-- v_dq_confidence_pre_post joins this in as the "post" score; if a run has
-- no row here yet (Gemini call failed, or an older run predates this
-- feature), the view falls back to a deterministic per-severity estimate
-- instead of showing nothing.
CREATE TABLE IF NOT EXISTS `ringed-hearth-504112-e3.audit_controls.dq_score_predictions` (
  batch_id STRING NOT NULL,
  run_id STRING NOT NULL,
  run_timestamp TIMESTAMP NOT NULL,
  predicted_post_confidence_score FLOAT64,
  rationale STRING
)
PARTITION BY DATE(run_timestamp)
CLUSTER BY batch_id, run_id;

CREATE TABLE IF NOT EXISTS `ringed-hearth-504112-e3.audit_controls.target_impact_summary` (
  run_id STRING NOT NULL,
  run_timestamp TIMESTAMP NOT NULL,
  source_rule_id STRING,
  mapping_name STRING,
  join_key_value STRING,
  target_table STRING,
  impact_description STRING,
  severity STRING,
  report_id STRING,
  report_name STRING,
  report_owner_team STRING,
  consumers STRING
)
PARTITION BY DATE(run_timestamp)
CLUSTER BY source_rule_id, target_table;

CREATE TABLE IF NOT EXISTS `ringed-hearth-504112-e3.audit_controls.rule_proposals` (
  proposal_id STRING NOT NULL,
  created_at TIMESTAMP NOT NULL,
  created_by STRING,
  status STRING,
  source STRING,
  run_id STRING,
  confidence FLOAT64,
  rule_name STRING,
  description STRING,
  expression STRING,
  severity STRING,
  dimension STRING,
  matched_count INT64,
  suggested_tests STRING,
  notes STRING,
  reviewed_by STRING,
  reviewed_at TIMESTAMP,
  reviewer_note STRING,
  approved_rule_id STRING
)
PARTITION BY DATE(created_at)
CLUSTER BY status, source;

CREATE TABLE IF NOT EXISTS `ringed-hearth-504112-e3.audit_controls.rules_registry_history` (
  generated_at TIMESTAMP NOT NULL,
  source_document STRING,
  rule_count INT64,
  registry_yaml STRING
)
PARTITION BY DATE(generated_at);

-- report_catalog: resolves a bad application_id into the actual downstream
-- reports it feeds. Reference/config table, seeded from
-- specs/report_catalog_seed.csv via tools/load_report_catalog_seed.py.
CREATE TABLE IF NOT EXISTS `ringed-hearth-504112-e3.audit_controls.report_catalog` (
  report_id STRING NOT NULL,
  report_name STRING,
  application_id STRING NOT NULL,
  report_type STRING,
  regulatory_body STRING,
  report_owner_team STRING,
  consumers STRING,
  refresh_frequency STRING,
  last_generated_at DATE,
  report_status STRING,
  data_fields_used STRING
)
CLUSTER BY application_id, report_id;

-- staging_audit_controls and failed_records_detail are deliberately left
-- out here too -- see the comment in terraform/main.tf for why.

-- ---------------------------------------------------------------------------
-- Added for the custom dashboard (replaces/supplements the Looker Studio
-- plan referenced elsewhere in this README) -- see dashboard_views.sql for
-- the read views these feed, and services/dashboard-api for the API layer
-- that serves the frontend.
-- ---------------------------------------------------------------------------

-- dataset_registry: one row per ingested file/batch. Populated by
-- services/ingest at the end of a successful load. Powers the dashboard's
-- top bar + left-sidebar "Dataset Summary" panel.
CREATE TABLE IF NOT EXISTS `ringed-hearth-504112-e3.audit_controls.dataset_registry` (
  batch_id STRING NOT NULL,
  dataset_name STRING,
  source_file STRING,
  gcs_uri STRING,
  bq_dataset STRING,
  bq_table STRING,
  schema_created_at TIMESTAMP,
  records_loaded INT64,
  columns_count INT64,
  ai_model STRING,
  region STRING,
  uploaded_by STRING,
  uploaded_at TIMESTAMP,
  status STRING
)
PARTITION BY DATE(uploaded_at)
CLUSTER BY batch_id;

-- remediation_actions: tracks the Remediate / Accept workflow shown per
-- issue row on the dashboard. One row per action taken on a specific
-- (rule_id, application_id) pair within a run -- e.g. "MFA Compliance Check
-- failing for APP-318" is tracked separately from the same rule failing for
-- APP-330, since each application typically needs its own owner/fix/timeline.
-- application_id is nullable to tolerate any pre-migration rows that predate
-- this column (rule-level-only actions from before per-application tracking
-- was added). Written by dashboard-api's POST /remediate and POST /accept;
-- read back by v_dq_issues_by_application (joined) to show current Status.
CREATE TABLE IF NOT EXISTS `ringed-hearth-504112-e3.audit_controls.remediation_actions` (
  action_id STRING NOT NULL,
  run_id STRING NOT NULL,
  rule_id STRING NOT NULL,
  application_id STRING,
  batch_id STRING,
  issue_type STRING,
  issue_description STRING,
  recommended_remediation STRING,
  action_type STRING,        -- 'Remediate' | 'Accept'
  status STRING,             -- 'Open' | 'In Progress' | 'Closed'
  initiated_by STRING,
  initiated_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP,
  remediation_details STRING,
  notified_email STRING,     -- recipient the "Remediation Required" email was sent/attempted to
  notification_status STRING -- 'Sent' | 'Failed' | 'Skipped: no contact on file' | 'Skipped: SMTP not configured' | NULL (Accept actions don't notify)
)
PARTITION BY DATE(initiated_at)
CLUSTER BY run_id, rule_id, application_id;

-- Migration for projects where remediation_actions already existed before
-- application_id/notified_email/notification_status were added (CREATE
-- TABLE IF NOT EXISTS above is a no-op on an existing table -- it won't add
-- new columns). Safe to re-run.
ALTER TABLE `ringed-hearth-504112-e3.audit_controls.remediation_actions`
  ADD COLUMN IF NOT EXISTS application_id STRING;
ALTER TABLE `ringed-hearth-504112-e3.audit_controls.remediation_actions`
  ADD COLUMN IF NOT EXISTS notified_email STRING;
ALTER TABLE `ringed-hearth-504112-e3.audit_controls.remediation_actions`
  ADD COLUMN IF NOT EXISTS notification_status STRING;

-- applicable_regulations: reference/config table, seeded from
-- specs/applicable_regulations_seed.csv via
-- tools/load_applicable_regulations_seed.py -- same pattern as
-- report_catalog. Maps a regulation to the country/data-category it
-- applies to; the dashboard filters this by the country(ies) detected in
-- the active dataset (dataset_registry.region / report_catalog rows) to
-- show only relevant regulations, matching the screenshot's "Applicable
-- Laws & Regulations" panel.
CREATE TABLE IF NOT EXISTS `ringed-hearth-504112-e3.audit_controls.applicable_regulations` (
  regulation_code STRING NOT NULL,
  regulation_name STRING,
  description STRING,
  data_category STRING,      -- e.g. Personal Data, Financial Data, Health Data
  country STRING,
  authority STRING,
  source_url STRING
)
CLUSTER BY country, regulation_code;

-- owner_contacts: reference/config table, seeded from
-- specs/owner_contacts_seed.csv via tools/load_owner_contacts_seed.py --
-- same pattern as report_catalog/applicable_regulations. Maps the
-- business_owner/technology_owner *names* that show up in the ingested
-- audit CSV to a real email address, since the CSV itself only ever
-- carries names. Looked up by dashboard-api's POST /remediate to decide
-- who the "Data Quality Remediation Required" email goes to (business_owner
-- checked first, technology_owner as fallback -- see email_helper.py).
CREATE TABLE IF NOT EXISTS `ringed-hearth-504112-e3.audit_controls.owner_contacts` (
  owner_name STRING NOT NULL,
  email STRING NOT NULL,
  note STRING
)
CLUSTER BY owner_name;
