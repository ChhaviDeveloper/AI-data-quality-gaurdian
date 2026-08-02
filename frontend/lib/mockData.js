// Fallback data shown when NEXT_PUBLIC_API_BASE_URL is unset or unreachable,
// so the dashboard is demoable on its own before dashboard-api is deployed.
// Shaped to mirror what dashboard-api actually returns (see
// services/dashboard-api/main.py) -- values loosely modeled on the original
// hackathon mockup, not live data.

export const MOCK_DATASET = {
  batch_id: "b7e2f1a0-demo",
  dataset_name: "Audit_Master_Data_Jun26.csv",
  source_file: "gs://hack-team-ten-sorforce-dq-bucket/incoming/Audit_Master_Data_Jun26.csv",
  bq_dataset: "audit_controls",
  bq_table: "staging_audit_controls",
  schema_created_at: "2026-07-24T22:35:00Z",
  records_loaded: 125430,
  columns_count: 24,
  ai_model: "gemini-2.5-flash",
  region: "United States",
  uploaded_by: "Saheb Alam Shaikh",
  uploaded_at: "2026-07-24T22:32:00Z",
  status: "Ingestion Completed",
};

export const MOCK_CONFIDENCE = {
  pre_confidence_score: 62,
  post_confidence_score: 92,
};

export const MOCK_ISSUE_TOTALS = { total: 18, open: 12, closed: 6 };
export const MOCK_BUCKETS = {
  critical: { open: 3, closed: 2 },
  warning: { open: 6, closed: 2 },
  info: { open: 3, closed: 2 },
};

export const MOCK_ISSUES = [
  {
    rule_id: "R001", rule_name: "Application ID Completeness", issue_type: "Missing Values",
    application_id: "APP-104", application_name: "Customer 360 Dashboard",
    description: "Column 'Email' has 3,245 missing values (2.59%)", severity: "High",
    dimension: "Completeness", failed_count: 3245, total_records: 125430,
    recommended_remediation: "Populate missing email addresses using reference master data or mark as Not Available.",
    remediation_status: "Open", run_id: "run-demo-1",
  },
  {
    rule_id: "R006", rule_name: "Phone Format Validity", issue_type: "Invalid Format",
    application_id: "APP-112", application_name: "Customer Onboarding App",
    description: "Column 'Phone' has 1,987 invalid phone numbers", severity: "High",
    dimension: "Validity", failed_count: 1987, total_records: 125430,
    recommended_remediation: "Standardize phone numbers to E.164 format.",
    remediation_status: "In Progress", run_id: "run-demo-1",
  },
  {
    rule_id: "R002", rule_name: "Application ID Uniqueness", issue_type: "Duplicate Records",
    application_id: "APP-104", application_name: "Customer 360 Dashboard",
    description: "1,256 duplicate records identified based on 'Customer ID'", severity: "Medium",
    dimension: "Uniqueness", failed_count: 1256, total_records: 125430,
    recommended_remediation: "Remove duplicate records keeping the most recent entry.",
    remediation_status: "Open", run_id: "run-demo-1",
  },
  {
    rule_id: "R018", rule_name: "Age Range Validity", issue_type: "Out of Range",
    application_id: "APP-201", application_name: "Marketing Campaign Report",
    description: "Column 'Age' has 732 values out of valid range (0-120)", severity: "Medium",
    dimension: "Validity", failed_count: 732, total_records: 125430,
    recommended_remediation: "Correct age values or set to NULL if unavailable.",
    remediation_status: "In Progress", run_id: "run-demo-1",
  },
  {
    rule_id: "R019", rule_name: "State Code Consistency", issue_type: "Inconsistent Data",
    application_id: "APP-118", application_name: "Compliance Reporting",
    description: "Column 'State' has inconsistent state codes (CA, Calif, California)", severity: "Low",
    dimension: "Consistency", failed_count: 452, total_records: 125430,
    recommended_remediation: "Standardize state names using reference mapping.",
    remediation_status: "Closed", run_id: "run-demo-1",
  },
  {
    rule_id: "R020", rule_name: "Name Field Sanitization", issue_type: "Special Characters",
    application_id: "APP-118", application_name: "Compliance Reporting",
    description: "Column 'Name' contains special characters in 452 records", severity: "Low",
    dimension: "Validity", failed_count: 452, total_records: 125430,
    recommended_remediation: "Remove or replace special characters.",
    remediation_status: "Closed", run_id: "run-demo-1",
  },
];

export const MOCK_REGULATIONS = [
  { regulation_code: "CCPA", regulation_name: "California Consumer Privacy Act", data_category: "Personal Data", country: "United States" },
  { regulation_code: "CPRA", regulation_name: "California Privacy Rights Act", data_category: "Personal Data", country: "United States" },
  { regulation_code: "GLBA", regulation_name: "Gramm-Leach-Bliley Act", data_category: "Financial Data", country: "United States" },
  { regulation_code: "HIPAA", regulation_name: "Health Insurance Portability and Accountability Act", data_category: "Health Data", country: "United States" },
  { regulation_code: "SOX", regulation_name: "Sarbanes-Oxley Act", data_category: "Financial Data", country: "United States" },
];

export const MOCK_APPS_AT_RISK = [
  { application_id: "Customer 360 Dashboard", report_name: "Customer 360 Dashboard", impact_description: "Incorrect customer insights", severity: "Critical" },
  { application_id: "Monthly Revenue Report", report_name: "Monthly Revenue Report", impact_description: "Revenue variance & misreporting", severity: "High" },
  { application_id: "Marketing Campaign Report", report_name: "Marketing Campaign Report", impact_description: "Audience segmentation errors", severity: "Medium" },
  { application_id: "Compliance Reporting", report_name: "Compliance Reporting", impact_description: "Regulatory reporting failures", severity: "High" },
  { application_id: "Customer Onboarding App", report_name: "Customer Onboarding App", impact_description: "Onboarding delays/failures", severity: "Medium" },
];

export const MOCK_HISTORY = [
  { event_time: "2026-07-24T22:40:00Z", event_type: "Invalid Format", description: "Column 'Phone' has 1,987 invalid phone numbers -- AI Remediation Started", actor: "AI Data Guardian (Vertex AI)", status: "In Progress" },
  { event_time: "2026-07-24T22:38:00Z", event_type: "Missing Values", description: "Column 'Email' has 3,245 missing values -- Remediation Initiated", actor: "Saheb Alam Shaikh", status: "Open" },
  { event_time: "2026-07-24T22:35:00Z", event_type: "Inconsistent Data", description: "Column 'State' standardized using reference mapping", actor: "AI Data Guardian (Vertex AI)", status: "Closed" },
  { event_time: "2026-07-24T22:28:00Z", event_type: "Duplicate Records", description: "1,256 duplicate records identified", actor: "AI Data Guardian (Vertex AI)", status: "Closed" },
  { event_time: "2026-07-24T22:02:00Z", event_type: "System", description: "Dataset uploaded: Audit_Master_Data_Jun26.csv, 125,430 records loaded to BigQuery", actor: "System", status: "Completed" },
];

export const MOCK_RECOMMENDATIONS = [
  {
    proposal_id: "prop-1", rule_name: "Backup Requires Encryption", source: "failure_pattern",
    description: "Records with backup_enabled = Yes consistently have encryption_at_rest = No; propose flagging this combination.",
    confidence: 0.87, status: "pending", severity: "High", dimension: "Consistency",
  },
  {
    proposal_id: "prop-2", rule_name: "Target Drift: report_catalog vs staging", source: "target_drift",
    description: "12 application_ids present in staging are missing from report_catalog -- these records won't resolve to any downstream report.",
    confidence: 0.74, status: "pending", severity: "Medium", dimension: "Completeness",
  },
];
