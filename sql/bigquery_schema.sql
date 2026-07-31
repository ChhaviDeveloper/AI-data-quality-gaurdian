-- Manual-apply mirror of cloud-pipeline/terraform/main.tf.
-- Prefer applying via Terraform Cloud (push to /cloud-pipeline/terraform,
-- or wherever your workspace is scoped). This file is here so anyone can
-- eyeball the schema without reading HCL, or paste it into the BigQuery
-- console for a quick manual setup while Terraform access is being sorted out.

CREATE SCHEMA IF NOT EXISTS `ai-data-quality-gaurdian.audit_controls`
OPTIONS (location = 'US');

CREATE TABLE IF NOT EXISTS `ai-data-quality-gaurdian.audit_controls.rule_execution_summary` (
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

CREATE TABLE IF NOT EXISTS `ai-data-quality-gaurdian.audit_controls.target_impact_summary` (
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

CREATE TABLE IF NOT EXISTS `ai-data-quality-gaurdian.audit_controls.rule_proposals` (
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

CREATE TABLE IF NOT EXISTS `ai-data-quality-gaurdian.audit_controls.rules_registry_history` (
  generated_at TIMESTAMP NOT NULL,
  source_document STRING,
  rule_count INT64,
  registry_yaml STRING
)
PARTITION BY DATE(generated_at);

-- report_catalog: resolves a bad application_id into the actual downstream
-- reports it feeds. Reference/config table, seeded from
-- specs/report_catalog_seed.csv via tools/load_report_catalog_seed.py.
CREATE TABLE IF NOT EXISTS `ai-data-quality-gaurdian.audit_controls.report_catalog` (
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
CREATE TABLE IF NOT EXISTS `ai-data-quality-gaurdian.audit_controls.dataset_registry` (
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
-- issue row on the dashboard. One row per action taken on a
-- rule_execution_summary issue (not per failed record -- this is
-- issue-level, failed_records_detail stays the row-level source of truth).
-- Written by dashboard-api's POST /remediate and POST /accept; read back
-- by v_dq_issues_detail (joined) to show current Status per issue.
CREATE TABLE IF NOT EXISTS `ai-data-quality-gaurdian.audit_controls.remediation_actions` (
  action_id STRING NOT NULL,
  run_id STRING NOT NULL,
  rule_id STRING NOT NULL,
  batch_id STRING,
  issue_type STRING,
  issue_description STRING,
  recommended_remediation STRING,
  action_type STRING,        -- 'Remediate' | 'Accept'
  status STRING,             -- 'Open' | 'In Progress' | 'Closed'
  initiated_by STRING,
  initiated_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP,
  remediation_details STRING
)
PARTITION BY DATE(initiated_at)
CLUSTER BY run_id, rule_id;

-- applicable_regulations: reference/config table, seeded from
-- specs/applicable_regulations_seed.csv via
-- tools/load_applicable_regulations_seed.py -- same pattern as
-- report_catalog. Maps a regulation to the country/data-category it
-- applies to; the dashboard filters this by the country(ies) detected in
-- the active dataset (dataset_registry.region / report_catalog rows) to
-- show only relevant regulations, matching the screenshot's "Applicable
-- Laws & Regulations" panel.
CREATE TABLE IF NOT EXISTS `ai-data-quality-gaurdian.audit_controls.applicable_regulations` (
  regulation_code STRING NOT NULL,
  regulation_name STRING,
  description STRING,
  data_category STRING,      -- e.g. Personal Data, Financial Data, Health Data
  country STRING,
  authority STRING,
  source_url STRING
)
CLUSTER BY country, regulation_code;
