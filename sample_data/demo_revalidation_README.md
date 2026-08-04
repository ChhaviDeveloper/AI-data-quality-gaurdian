# Re-validation demo dataset

Two CSVs, 50 rows each, same 50 `application_id`s (`APP-500`..`APP-549`) with
identical `criticality` / `data_classification` / `regulatory_scope` per row
-- only the actual control fields (owners, MFA, encryption, backups, access
review, evidence, DR test, vulnerabilities, policy exceptions) differ. Built
and score-verified locally against the real rules engine
(`services/validator/rules_engine.py` + `specs/rules_registry.yaml`), not
just eyeballed.

- `demo_revalidation_before.csv` -- dense, broad control gaps. Confidence
  score: **62.88%**.
- `demo_revalidation_after.csv` -- the same applications corrected (a
  handful of residual issues left on purpose so it's not a suspicious
  100%). Confidence score: **93.5%**.

## How to demo the Pre/Post Confidence Score moving on ONE dataset

This is the point of these two files: uploading them as two independent
datasets would just show up as two unrelated batches. To make the
Overview page's Pre/Post Confidence Score donuts actually animate
62.88% -> 93.5%, the *second* upload has to target the *same batch_id* as
the first, so the validator runs twice against one batch --
`v_dq_confidence_pre_post` compares a batch's first run to its most recent
run.

1. Datasets page -> leave "Target batch" as **New dataset** -> upload
   `demo_revalidation_before.csv`. Note the batch_id from the success
   message (or the Datasets table).
2. Wait for it to validate (Overview should show ~63%, matching pre==post
   since it's the batch's only run so far).
3. Datasets page -> set "Target batch" to that same batch (it'll show up
   in the dropdown as "Re-validate: demo_revalidation_before.csv (xxxxxxxx...)")
   -> upload `demo_revalidation_after.csv`.
4. This REPLACES that batch's rows in `staging_audit_controls` with the
   corrected data and re-runs the validator on it. Refresh Overview --
   Pre should now show 62.88% (first run) and Post should show 93.5%
   (latest run), with the "+X% Improvement" badge showing.
