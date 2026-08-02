# Test dataset answer key

File: `sample_data/test_data_planted_issues.csv` (31 rows: 10 clean + 21 deliberately broken)

Verified by running the actual rule engine (`services/validator/rules_engine.py` +
`specs/rules_registry.yaml`) against this file directly -- every row below is the
real, confirmed output, not a manual guess. Overall DQ score: **93.95%**.

## Clean rows (should NOT appear as issues)

APP-301 through APP-310 -- ten realistic, fully compliant applications across a mix
of criticality/classification/regulatory combinations. None of these should show up
in Data Quality Issues.

## Planted issues, one rule at a time

| Row(s) | Rule | What's wrong |
|---|---|---|
| *(blank application_id)*, "Blank Application ID Test" | R001 Application ID Completeness | `application_id` left empty |
| APP-350 (x2), "Duplicate ID Test A/B" | R002 Application ID Uniqueness | Same `application_id` used twice |
| APP-311, "Missing Owner Test" | R003 Mandatory Ownership | `business_owner` blank on an Active app |
| APP-312, "Invalid Criticality Test" | R004 Valid Criticality | `criticality = Severe` (not an allowed value) |
| APP-313, "Inconsistent Casing Criticality Test" | R004 Valid Criticality | `criticality = critical` (lowercase -- inconsistent casing, fails the exact-match check) |
| APP-314, "Invalid YesNo Value Test" | R005 Valid Evidence Status | `evidence_submitted = Maybe` (not Yes/No) |
| APP-315, "Evidence Missing SOX Test" | R006 Evidence Submission Required | `regulatory_scope = SOX` but `evidence_submitted = No` |
| APP-316, "Access Review Missing Test" | R007 Access Review Required | Critical app with `access_review_completed = No` |
| APP-317, "Privileged Access Not Approved Test" | R008 Privileged Access Approval Required | `privileged_access_count = 3` but `privileged_access_approved = No` |
| APP-318, "MFA Disabled Test" | R009 MFA Compliance Check | High-criticality app with `mfa_enabled = No` |
| APP-319, "Encryption Disabled Test" | R010 Encryption Compliance Check | `data_classification = Restricted` but `encryption_at_rest = No` |
| APP-320, "Backup Disabled Test" | R011 Backup Compliance Check | Active Critical app with `backup_enabled = No` |
| APP-321, "DR Test Missing Test" | R012 DR Test Compliance | Critical app with `dr_test_completed = No` and no `dr_test_date` |
| APP-322, "Unapproved Vulnerability Test" | R013 Vulnerability Exception Validation | `vulnerability_status = Critical Open`, 3 open high vulns, no policy exception |
| APP-323, "Exception Expiry Missing Test" | R014 Exception Expiry Validation | `policy_exception = Yes` but `exception_expiry_date` blank |
| APP-324, "Exception Expired Test" | R014 Exception Expiry Validation | `policy_exception = Yes` with `exception_expiry_date = 15-01-2026` (already passed) |
| APP-325, "Future DR Date Test" | R015 Future DR Date Validation | `dr_test_date = 25-01-2027` (in the future) |
| APP-326, "Backup Without Encryption Test" | R016 Backup Requires Encryption | `backup_enabled = Yes` but `encryption_at_rest = No` |

## Multi-issue rows (realistic messy real-world cases)

**APP-330, "Messy Legacy Trading App"** -- deliberately a wreck, fires 9 rules at once:
R003 (missing technology_owner), R006 (SOX scope, no evidence), R007 (no access
review), R008 (privileged access not approved), R009 (MFA off), R010 (Confidential
data, no encryption), R011 (backup off), R012 (DR test missing), R014 (exception
expired). Good row to click "Root Cause" on -- lots of correlated failures on one
application.

**APP-331, "Partner Integration Gateway"** -- a more borderline case, fires exactly 2:
R009 (MFA off) and R011 (backup off), everything else compliant.

## What we found and fixed along the way

Running this file caught a real bug: **R003 (Mandatory Ownership)** originally read
`business_owner == ''`, which only matches a literal empty string. A genuinely blank
CSV cell parses as `NaN` in pandas, not `''`, so the rule silently never fired on
real missing-owner data -- confirmed by APP-311 not showing up on the first run.
Fixed in `specs/rules_registry.yaml` to also check `.isnull()`, same pattern R001
already used correctly. Re-verified after the fix: APP-311 and APP-330 both now
correctly flag R003.

## How to verify against the dashboard

1. Make sure the updated `specs/rules_registry.yaml` (with the R003 fix) is
   uploaded to `gs://ringed-hearth-504112-e3-dq-bucket/specs/rules_registry.yaml`
   -- re-run `scripts/manual_gcp_setup.sh` to sync it, or `gcloud storage cp` it
   directly.
2. Upload `test_data_planted_issues.csv` via the Datasets page drag-and-drop (or
   drop it into `gs://<bucket>/incoming/` directly if using the automatic trigger).
3. Compare what Data Quality Issues shows against the table above -- 16 distinct
   rule types, 21 broken rows, 10 clean rows, ~94% DQ score expected.
