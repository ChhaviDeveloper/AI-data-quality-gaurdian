-- Read-only BigQuery views feeding the Looker Studio dashboard.
-- These sit on top of the pipeline's existing tables (rule_execution_summary,
-- target_impact_summary, rule_proposals) -- no new base tables, no write-back.
-- Run once with: bq query --use_legacy_sql=false < cloud-pipeline/sql/dashboard_views.sql

-- 1. Confidence score trend -- one row per validator run.
CREATE OR REPLACE VIEW `ai-data-quality-gaurdian.audit_controls.v_dq_confidence_trend` AS
SELECT
  run_id,
  batch_id,
  run_timestamp,
  ROUND(AVG(pass_percentage), 2) AS confidence_score,
  COUNTIF(status = 'Failed') AS rules_failed,
  COUNTIF(status = 'Passed') AS rules_passed,
  COUNT(*) AS rules_evaluated,
  SUM(failed_count) AS total_failed_records
FROM `ai-data-quality-gaurdian.audit_controls.rule_execution_summary`
GROUP BY run_id, batch_id, run_timestamp;

-- 2. Issue counts by severity, latest run only.
CREATE OR REPLACE VIEW `ai-data-quality-gaurdian.audit_controls.v_dq_issue_overview` AS
WITH latest AS (
  SELECT run_id FROM `ai-data-quality-gaurdian.audit_controls.rule_execution_summary`
  ORDER BY run_timestamp DESC LIMIT 1
)
SELECT
  r.severity,
  COUNTIF(r.status = 'Failed') AS rules_with_issues,
  SUM(r.failed_count) AS failed_records
FROM `ai-data-quality-gaurdian.audit_controls.rule_execution_summary` r
JOIN latest USING (run_id)
GROUP BY r.severity;

-- 3. Per-rule issue detail, latest run, failed rules only.
CREATE OR REPLACE VIEW `ai-data-quality-gaurdian.audit_controls.v_dq_issues_detail` AS
WITH latest AS (
  SELECT run_id FROM `ai-data-quality-gaurdian.audit_controls.rule_execution_summary`
  ORDER BY run_timestamp DESC LIMIT 1
)
SELECT
  r.rule_id, r.rule_name, r.description, r.severity, r.dimension,
  r.failed_count, r.total_records, r.pass_percentage, r.status, r.run_timestamp
FROM `ai-data-quality-gaurdian.audit_controls.rule_execution_summary` r
JOIN latest USING (run_id)
WHERE r.status != 'Passed'
ORDER BY r.failed_count DESC;

-- 4. Applications / reports at risk, latest run.
CREATE OR REPLACE VIEW `ai-data-quality-gaurdian.audit_controls.v_dq_apps_at_risk` AS
WITH latest AS (
  SELECT run_id FROM `ai-data-quality-gaurdian.audit_controls.rule_execution_summary`
  ORDER BY run_timestamp DESC LIMIT 1
)
SELECT
  t.join_key_value AS application_id,
  t.report_id, t.report_name, t.report_owner_team, t.consumers,
  t.source_rule_id AS rule_id, t.severity, t.impact_description
FROM `ai-data-quality-gaurdian.audit_controls.target_impact_summary` t
JOIN latest USING (run_id)
ORDER BY
  CASE t.severity WHEN 'Critical' THEN 1 WHEN 'High' THEN 2 WHEN 'Medium' THEN 3 ELSE 4 END;

-- 5. Activity/history log -- validator runs + AI proposal events, merged.
CREATE OR REPLACE VIEW `ai-data-quality-gaurdian.audit_controls.v_dq_activity_log` AS
SELECT * FROM (
  SELECT
    run_timestamp AS event_time,
    'Validation Run' AS event_type,
    CONCAT('Run ', run_id, ': ', CAST(ROUND(AVG(pass_percentage), 2) AS STRING),
           '% avg pass rate, ', CAST(SUM(failed_count) AS STRING), ' failed records') AS description,
    'System' AS actor,
    CAST(NULL AS STRING) AS status
  FROM `ai-data-quality-gaurdian.audit_controls.rule_execution_summary`
  GROUP BY run_id, run_timestamp

  UNION ALL

  SELECT
    created_at AS event_time,
    CONCAT('AI Proposal (', source, ')') AS event_type,
    CONCAT(rule_name, ' -- confidence ', CAST(confidence AS STRING)) AS description,
    created_by AS actor,
    status
  FROM `ai-data-quality-gaurdian.audit_controls.rule_proposals`
)
ORDER BY event_time DESC;

-- ---------------------------------------------------------------------------
-- Added for the custom dashboard (services/dashboard-api + frontend/),
-- which replaces the Looker Studio plan. Backed by the new tables in
-- bigquery_schema.sql: dataset_registry, remediation_actions,
-- applicable_regulations.
-- ---------------------------------------------------------------------------

-- 6. Latest ingested dataset -- top bar + "Dataset Summary" sidebar panel.
CREATE OR REPLACE VIEW `ai-data-quality-gaurdian.audit_controls.v_dq_dataset_summary` AS
SELECT *
FROM `ai-data-quality-gaurdian.audit_controls.dataset_registry`
ORDER BY uploaded_at DESC
LIMIT 1;

-- 7. Pre/post confidence score per batch -- first validator run on a batch
-- vs. the most recent one, so re-running the validator after remediation
-- shows the "+X% Improvement" the screenshot displays. A batch that has
-- only been validated once will show pre == post (0% improvement), which
-- is correct -- nothing's been remediated and re-checked yet.
CREATE OR REPLACE VIEW `ai-data-quality-gaurdian.audit_controls.v_dq_confidence_pre_post` AS
WITH batch_runs AS (
  SELECT
    batch_id,
    run_id,
    run_timestamp,
    ROUND(AVG(pass_percentage), 2) AS confidence_score,
    ROW_NUMBER() OVER (PARTITION BY batch_id ORDER BY run_timestamp ASC) AS rn_first,
    ROW_NUMBER() OVER (PARTITION BY batch_id ORDER BY run_timestamp DESC) AS rn_last
  FROM `ai-data-quality-gaurdian.audit_controls.rule_execution_summary`
  GROUP BY batch_id, run_id, run_timestamp
)
SELECT
  batch_id,
  MAX(IF(rn_first = 1, confidence_score, NULL)) AS pre_confidence_score,
  MAX(IF(rn_last = 1, confidence_score, NULL)) AS post_confidence_score,
  MAX(IF(rn_last = 1, run_id, NULL)) AS latest_run_id,
  MAX(IF(rn_last = 1, run_timestamp, NULL)) AS latest_run_timestamp
FROM batch_runs
GROUP BY batch_id;

-- 8. Issues (latest run) joined with their current remediation status --
-- "Remediate / Accept / Status" columns on the dashboard. Defaults to
-- 'Open' with no recommendation until dashboard-api's POST /remediate (or
-- the ai-proposals service) writes the first remediation_actions row for
-- that (run_id, rule_id).
CREATE OR REPLACE VIEW `ai-data-quality-gaurdian.audit_controls.v_dq_issues_with_status` AS
WITH latest AS (
  SELECT run_id FROM `ai-data-quality-gaurdian.audit_controls.rule_execution_summary`
  ORDER BY run_timestamp DESC LIMIT 1
),
latest_action AS (
  SELECT
    rule_id,
    run_id,
    ARRAY_AGG(
      STRUCT(status, recommended_remediation, action_type, completed_at)
      ORDER BY initiated_at DESC LIMIT 1
    )[OFFSET(0)] AS latest
  FROM `ai-data-quality-gaurdian.audit_controls.remediation_actions`
  GROUP BY rule_id, run_id
)
SELECT
  r.rule_id, r.rule_name, r.description, r.severity, r.dimension,
  r.failed_count, r.total_records, r.pass_percentage, r.status AS rule_status,
  r.run_id, r.run_timestamp,
  COALESCE(a.latest.status, 'Open') AS remediation_status,
  a.latest.recommended_remediation AS recommended_remediation,
  a.latest.action_type AS last_action_type,
  a.latest.completed_at AS last_action_completed_at
FROM `ai-data-quality-gaurdian.audit_controls.rule_execution_summary` r
JOIN latest USING (run_id)
LEFT JOIN latest_action a ON a.rule_id = r.rule_id AND a.run_id = r.run_id
WHERE r.status != 'Passed'
ORDER BY r.failed_count DESC;

-- 9. Applicable regulations, latest dataset's region first. The API filters
-- further by the country(ies) actually present in the active batch; this
-- view just surfaces the full reference set ordered so the relevant
-- country floats to the top.
CREATE OR REPLACE VIEW `ai-data-quality-gaurdian.audit_controls.v_dq_regulations` AS
SELECT
  reg.regulation_code, reg.regulation_name, reg.description,
  reg.data_category, reg.country, reg.authority, reg.source_url,
  (reg.country = (SELECT region FROM `ai-data-quality-gaurdian.audit_controls.v_dq_dataset_summary`)) AS matches_active_dataset
FROM `ai-data-quality-gaurdian.audit_controls.applicable_regulations` reg
ORDER BY matches_active_dataset DESC, reg.country, reg.regulation_code;
