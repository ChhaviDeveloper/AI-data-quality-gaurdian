# AI Data Quality Guardian -- cloud-pipeline

GCP-native audit data-quality pipeline + dashboard. Started as a rebuild of
an earlier local-scripts MVP (kept in its own `cloud-pipeline` folder in the
original hackathon repo to avoid touching those scripts); this copy is now
its own standalone project/repo, so this folder IS the repo root --
`.github/workflows/deploy-cloud-pipeline.yml` already lives where GitHub
expects it, no extra nesting or moving files around (see Deploying).

## What this replaces / reuses

| Root script | Cloud equivalent | Notes |
|---|---|---|
| `python_scripts/functional_parser.py` | `services/doc-parser` | Same parsing logic, wrapped as an Eventarc-triggered Cloud Run service. Copied (not imported) so the service is self-contained at build time. |
| `python_scripts/load_data_from_gcs_to_stg.py` | `services/ingest` | Adds `batch_id` / `loaded_at` / `source_file` lineage columns before loading, which the original script didn't do. |
| `audit_validator_registry_single_loop.py` | `services/validator` + `rules_engine.py` | Reads from BigQuery instead of a local CSV. Fixes two real bugs found by dry-running this against `sample_data/audit_data_150rows.csv` -- see "Bugs fixed" below. |
| `vertex_llm.py` + `vertex_from_failed_csv.py` | `services/ai-proposals` + `gemini_client.py` | Swapped the deprecated `text-bison@001` model for a current Gemini model via `google-genai`. Added dedupe against existing rules/pending proposals (the local `specs/pending_rules.json` had the same "backup requires encryption" idea proposed 4 separate times). Added the target-table drift check (new capability, not in the original). |
| `review_pending_rules.py` | `tools/review_proposals.py` | Same approve/reject flow, pointed at BigQuery `rule_proposals` and the GCS-hosted `rules_registry.yaml` instead of local files. |
| *(new)* | `services/notifier` | Email alert on new proposals. **Mail provider not decided yet** -- ships as a safe no-op (`MAIL_PROVIDER=log_only`) until you pick SendGrid/SMTP/etc. and store credentials in Secret Manager. |
| *(new)* | `services/job-trigger` | Bridges Pub/Sub messages to Cloud Run Jobs executions (Eventarc can trigger Cloud Run *services* directly but not *Jobs*). Deployed twice with different env vars -- see the workflow. |
| *(new)* | `report_catalog` table + `specs/report_catalog_seed.csv` | The "which reports does this bad record break" feature -- see below. Real sample data, not a placeholder. |

## Architecture

```
GCS gs://ringed-hearth-504112-e3-dq-bucket/
  functional-docs/*.docx --(Eventarc)--> doc-parser --> specs/rules_registry.yaml (GCS)
                                                      --> rules_registry_history (BQ)

  incoming/*.csv --(Eventarc)--> ingest --> staging_audit_controls (BQ, +batch_id/loaded_at)
                                         --> Pub/Sub: staging-loaded
                                                |
                                                v
                                     trigger-validator (job-trigger)
                                                |
                                                v
                                          validator (Cloud Run Job)
                                     --> rule_execution_summary (BQ)
                                     --> failed_records_detail (BQ)
                                     --> target_impact_summary (BQ)  [resolved against report_catalog]
                                     --> Pub/Sub: validation-complete
                                                |
                                                v
                                  trigger-ai-proposals (job-trigger)
                                                |
                                                v
                                      ai-proposals (Cloud Run Job)
                                --> rule_proposals (BQ)  [failure-pattern + target-drift mining]
                                --> Pub/Sub: new-proposal
                                                |
                                                v
                                            notifier --> email (once a provider is picked)

  report_catalog (BQ) -- reference table, NOT pipeline output. Seeded once
  (and re-seeded whenever it changes) from specs/report_catalog_seed.csv via
  tools/load_report_catalog_seed.py. Maps application_id -> which reports
  read it, so a bad record resolves to a real report_id/report_name instead
  of just "rule R002 failed".

  Human reviews with tools/review_proposals.py
     --> approved rule appended to rules_registry.yaml (GCS)
     --> next validator run picks it up automatically

  Looker Studio dashboard reads: rule_execution_summary, failed_records_detail,
  target_impact_summary, rule_proposals
```

## The report_catalog / target-impact feature

`specs/report_catalog_seed.csv` is sample data modeling ~10 realistic
downstream reports (a SOX quarterly certification, an RBI AML oversight
report, a vulnerability risk dashboard, an executive scorecard, etc.), each
listing which `application_id`s it reads and which source columns it cares
about. It's deliberately built against the real edge cases in
`sample_data/audit_data_150rows.csv` -- e.g. the duplicated `APP-027` row
feeds `RPT-DUPCHECK`, the non-standard `Enabled`/`Encrypted` values on
`APP-013` feed `RPT-SOX-QCERT`, the expired exception on `APP-030` feeds
`RPT-VULN-RISK`.

`specs/target_table_registry.yaml` maps rule clusters (identity, ownership,
vulnerability/exception, security posture, access governance, timeliness)
to `report_catalog`. When the validator finds a failed record, it looks up
`report_catalog` by `application_id` and only writes a `target_impact_summary`
row when a real report match is found -- an application with no reports
produces no impact row, since nothing downstream is actually at risk.

This is sample/example data, not your real reports -- **replace
`report_catalog_seed.csv` with your team's actual downstream reports**
whenever you have them (same columns, just real `report_id`/`report_name`/
`application_id`s). Re-run `tools/load_report_catalog_seed.py` after editing
it; it's a reference table your team maintains, not something the pipeline
generates.

## Bugs fixed (found by dry-running against real data, not just guessing)

Running the validator locally against the uploaded `audit_data_150rows.csv`
(a 150-row file full of deliberate edge cases -- duplicate IDs, missing
owners, non-numeric fields, expired exceptions, malformed dates) caught two
real issues:

1. The original `RuleContext` was missing `future_dr_dates()`, which rule
   R015 calls -- it was silently a no-op every run (this was fixed in the
   first pass of this folder).
2. Four other python-type rules (R002 uniqueness, R005 yes/no validity,
   R012 DR-test validity, R014 exception-expiry validity) returned a single
   aggregate `True`/`False` for the whole table instead of a per-row result.
   The engine treated any bare bool as "no failures," so these four rules
   silently never flagged anything in the original script, no matter how
   bad the data was -- confirmed by the very first local demo report
   showing all four at 100% pass. Fixed by adding proper `*_mask()` methods
   to `RuleContext` (`duplicated_mask`, `invalid_yes_no_mask`,
   `dr_test_invalid_mask`, `exception_expiry_invalid_mask`) that return a
   per-row boolean Series, and updating `rules_registry.yaml` +
   `functional_parser.py`'s `RULE_TEMPLATES` to call them. Verified: DQ
   score on the edge-case file went from a meaningless 80.63% (when a
   half-fixed version flagged ALL 151 rows for one duplicate) to a correct
   99.05%, with R002 correctly flagging just the 2 actually-duplicated
   `APP-027` rows.

## What's genuinely new vs. your original MVP scope

- **Lineage**: every staging row is tagged with `batch_id`/`loaded_at`/`source_file`, so you can always trace a failed record back to the exact upload that caused it.
- **Target-impact table resolved against real data**: `report_catalog` isn't just a config mapping -- the validator queries it live and attaches the actual `report_id`/`report_name`/`consumers` to every impacted record.
- **Target drift detection**: `ai-proposals` runs a live anti-join between the current staging batch and each configured target table, and asks Gemini to turn any mismatch into a candidate rule -- this is the "data sampling on current and target tables" capability you asked for.
- **Dedupe**: proposals are checked against both the existing rules registry and prior pending/approved proposals before being written, so you don't get the same idea proposed repeatedly.
- **Auditable registry history**: every regeneration of `rules_registry.yaml` is snapshotted to `rules_registry_history`, so you can show "here's how the rule set evolved" in the demo.

## One thing this still can't do until you decide

**`services/notifier` doesn't send email yet.** Pick a provider (SendGrid is the least setup for a hackathon: one API key in Secret Manager) and I'll wire it in, or hand it to whoever's free to do it -- the stub function and TODOs are already in `main.py`.

## Local testing (no GCP required)

Every service's `main.py` has a `--local-*` mode for testing the core logic without touching GCS/BigQuery/Pub-Sub. The validator's local mode can now test the full report-impact resolution too, via `--local-report-catalog`:

```bash
cd services/doc-parser && python main.py --local-doc ../../../../Functional_Document_Hackathon_v1.0.docx --local-out /tmp/registry.yaml

cd services/ingest && python main.py --local-csv ../../../sample_data/audit_data_150rows.csv --local-out /tmp/tagged.csv

cd services/validator && python main.py \
  --local-csv ../../sample_data/audit_data_150rows.csv \
  --local-rules ../../specs/rules_registry.yaml \
  --local-targets ../../specs/target_table_registry.yaml \
  --local-report-catalog ../../specs/report_catalog_seed.csv \
  --local-out /tmp/validator_out
```

`ai-proposals` already runs standalone (`python main.py`) against real BigQuery/Vertex AI -- it was never Cloud-Run-only. `notifier` now has `--local-latest` (reads the newest row from `rule_proposals` directly instead of decoding a Pub/Sub message).

## Local-only execution (no Cloud Run / Cloud Build / Artifact Registry needed)

If your billing account can't (or you don't want to) unlock Cloud Run/Cloud Build/Artifact Registry -- some free-trial accounts require an extra prepayment step for those specifically, separate from just having billing linked -- you can run the entire pipeline as plain Python processes against the real GCP backing services (BigQuery, GCS, Pub/Sub, Vertex AI), which don't require that. Same data, same Gemini calls, same BigQuery tables the dashboard reads; just no containers.

1. **GCP setup, skipping Cloud Run entirely**: `cd scripts && PROJECT_ID=<your-project-id> ENABLE_CLOUD_RUN=false bash manual_gcp_setup.sh` (false is the default -- you can omit it). Also needs `gcloud auth application-default login` once, so the Python client libraries below can authenticate.
2. **Seed reference tables**: `python tools/load_report_catalog_seed.py && python tools/load_applicable_regulations_seed.py`
3. **Ingest a file straight into real BigQuery** (skips the GCS bucket + Eventarc trigger entirely):
   ```bash
   cd services/ingest
   BQ_PROJECT=<your-project-id> python main.py --local-csv ../../sample_data/audit_data_150rows.csv --local-to-bq
   ```
   Prints a `batch_id` -- note it (or just let the next step default to "latest batch").
4. **Run the validator against that real batch**:
   ```bash
   cd services/validator
   BQ_PROJECT=<your-project-id> RULES_REGISTRY_PATH=../../specs/rules_registry.yaml TARGET_TABLE_REGISTRY_PATH=../../specs/target_table_registry.yaml python main.py
   ```
   (No `--local-csv` flag this time -- that flag switches to the fully-offline smoke-test path instead. Omitting it runs the real BigQuery-backed path and writes results back to `rule_execution_summary`, `failed_records_detail`, `target_impact_summary`.)
5. **Run ai-proposals** (mines the run above for new rule candidates): `cd services/ai-proposals && BQ_PROJECT=<your-project-id> python main.py`
6. **Run notifier** on whatever ai-proposals just wrote: `cd services/notifier && BQ_PROJECT=<your-project-id> python main.py --local-latest`
7. **Run dashboard-api locally**: `cd services/dashboard-api && BQ_PROJECT=<your-project-id> python main.py` (serves on `localhost:8080`)
8. **Run the frontend locally**, pointed at it: set `NEXT_PUBLIC_API_BASE_URL=http://localhost:8080` in `frontend/.env.local`, then `cd frontend && npm install && npm run dev`

Re-running steps 3-6 with a new CSV re-validates and re-mines, same as the Cloud Run pipeline would -- you're just triggering each step by hand instead of Eventarc/Pub-Sub doing it automatically. `job-trigger` isn't needed at all in this mode (it only exists to bridge Pub/Sub -> Cloud Run Jobs).

## Deploying

1. **GCS bucket + BigQuery tables + Pub/Sub topics** -- two equivalent options, pick one (not both):
   - **Terraform** (`cloud-pipeline/terraform/`): `terraform init && terraform apply` from that directory, with GCP application-default credentials for `var.project_id` set up. Creates the landing bucket (`var.bucket_name`, must be globally unique -- rename it in `variables.tf` if it's taken), uploads `specs/rules_registry.yaml` + `specs/target_table_registry.yaml` into it, and creates all the BigQuery tables. If `audit_controls` or the bucket already exist from earlier manual steps, set `create_dataset = false` / `terraform import` them first instead of letting `apply` try (and fail) to create something that's already there.
   - **Plain gcloud/bq/gsutil, no Terraform** (`cloud-pipeline/scripts/manual_gcp_setup.sh`): does the exact same thing as idempotent CLI commands -- no Terraform state to manage. Run `cd cloud-pipeline/scripts && PROJECT_ID=ringed-hearth-504112-e3 ./manual_gcp_setup.sh`. Safe to re-run any time (every command either no-ops or uses `CREATE ... IF NOT EXISTS` / `CREATE OR REPLACE`).
2. **Seed the report_catalog reference table**: `python tools/load_report_catalog_seed.py` (after the table exists from step 1). Re-run this any time you update `report_catalog_seed.csv` with real reports.
3. **Cloud Run services/jobs + Eventarc wiring** (GitHub Actions): the workflow is already at `.github/workflows/deploy-cloud-pipeline.yml`, right where GitHub expects it -- nothing to move. One-time prerequisites: run `scripts/setup_workload_identity.sh` (see "CI/CD setup" below) and add the `WIF_PROVIDER`/`WIF_SERVICE_ACCOUNT` GitHub secrets it prints out. It's `workflow_dispatch`-only (manual, pick a target from the dropdown) on purpose, since every run spends part of your GCP budget. Deploy order: `doc-parser`, `ingest`, `validator`, `ai-proposals`, `notifier` first (or `all`), then `triggers` once those services/jobs exist, then `dashboard-api` and `frontend`.

Note: `ci/deploy-cloud-pipeline.yml` and `docs/deploy_dashboard_jobs_snippet.yml` are stale leftovers from an earlier draft where this project was still nested inside a bigger repo -- both are marked SUPERSEDED at the top and can be deleted; the real, current workflow is only `.github/workflows/deploy-cloud-pipeline.yml`.

## CI/CD setup (GitHub Actions + Workload Identity Federation)

1. Push this project to your GitHub repo as-is (this folder is the repo root).
2. Run `scripts/setup_workload_identity.sh` once (`PROJECT_ID=ringed-hearth-504112-e3 GITHUB_REPO=your-username/your-repo-name ./setup_workload_identity.sh`) -- creates a Workload Identity Pool restricted to your repo, a deployer service account GitHub Actions impersonates (no long-lived key), and a separate narrower-permission runtime service account for the actual Cloud Run services/jobs. Prints the two secret values you need next.
3. Add those as GitHub repo secrets: Settings > Secrets and variables > Actions > New repository secret -- `WIF_PROVIDER` and `WIF_SERVICE_ACCOUNT`.
4. (Optional) Add a repo *variable* (not secret) `LOOKER_EMBED_URL` once you have a Looker Studio report -- the frontend deploy job reads it.
5. Go to the Actions tab, run "Deploy Cloud Pipeline", pick a target from the dropdown.
4. Upload a functional doc to `gs://ringed-hearth-504112-e3-dq-bucket/functional-docs/` and a CSV (e.g. `sample_data/audit_data_150rows.csv`) to `gs://ringed-hearth-504112-e3-dq-bucket/incoming/` to kick off an end-to-end run.
5. **Seed the applicable_regulations reference table**: `python tools/load_applicable_regulations_seed.py` (after step 1). Re-run when you add a country/regulation.
6. **Deploy `dashboard-api`** (Cloud Run service, not a job): `gcloud run deploy dashboard-api --source services/dashboard-api --region europe-west1 --allow-unauthenticated` (tighten auth before sharing outside the team). Note its URL.
7. **Deploy `frontend`**: `cd frontend && gcloud run deploy dashboard-frontend --source . --region europe-west1 --allow-unauthenticated --build-env-vars-file=<(echo "NEXT_PUBLIC_API_BASE_URL: <dashboard-api URL from step 6>")` -- or build/push the Docker image yourself with `--build-arg NEXT_PUBLIC_API_BASE_URL=...` (and `NEXT_PUBLIC_LOOKER_EMBED_URL` once you have it, see below). Remember: these are `NEXT_PUBLIC_*` vars, baked in at *build* time, not runtime.

## Custom dashboard (`services/dashboard-api` + `frontend/`)

Replaces the originally-planned Looker-Studio-only dashboard with a full interactive UI matching the team's mockup: Overview, Analytics, Data Quality Issues (with Remediate/Accept actions + AI root-cause analysis), Recommendations, Regulations, Impacted Applications, History, Datasets, Settings.

- `services/dashboard-api`: Flask + Gunicorn Cloud Run service (not an Eventarc function like the rest -- it's a plain REST API called directly by the frontend). Reads exclusively through the `v_dq_*` views in `sql/dashboard_views.sql`. Writes `remediation_actions` rows on `POST /issues/<rule_id>/remediate` and `/accept`. Calls Gemini (via `gemini_helper.py`, same pattern as `services/ai-proposals/gemini_client.py`) to generate the remediation recommendation text and root-cause summaries on demand.
- `frontend/`: Next.js app, no backend framework beyond `dashboard-api`. Runs standalone against built-in mock data (`lib/mockData.js`) if `NEXT_PUBLIC_API_BASE_URL` is unset, so it's demoable before the pipeline is fully deployed. Local dev: `cd frontend && npm install && npm run dev`.

## Looker Studio setup (Analytics page)

The Analytics page embeds a Looker Studio report via `NEXT_PUBLIC_LOOKER_EMBED_URL`. Looker Studio is read-only BI (no write-back), so it complements -- not replaces -- the Remediate/Accept workflow in Data Quality Issues. To set it up:

1. Go to [lookerstudio.google.com](https://lookerstudio.google.com), create a new report.
2. Add a BigQuery data source: project `ringed-hearth-504112-e3`, dataset `audit_controls`. Add each of these as a data source (all already exist as views, seeded with real pipeline output once a run has happened): `v_dq_confidence_trend` (confidence score over time -- line chart), `v_dq_issue_overview` (issues by severity -- bar chart), `v_dq_activity_log` (recent runs/proposals -- table).
3. Build 2-3 charts on those data sources (a trend line + a severity bar chart is enough for a hackathon demo).
4. `File > Embed report`, enable embedding, and set sharing so the people who'll view the dashboard can access it (either "Anyone with the link" or restricted to your Google Workspace domain -- match your data-sensitivity requirements here since this is audit/compliance data).
5. Copy the embed URL (looks like `https://lookerstudio.google.com/embed/reporting/<report-id>/page/<page-id>`) into `frontend/.env.local` as `NEXT_PUBLIC_LOOKER_EMBED_URL`, then rebuild/redeploy the frontend.

## Not done yet / explicitly out of scope for this pass

- The Looker Studio *report itself* isn't built -- report creation needs your Google account in the Looker Studio UI (see setup steps above); everything it needs on the data side (the views) already exists.
- `services/notifier` mail provider (see above).
- Root-cause / remediation-recommendation Gemini calls in `dashboard-api` aren't cached anywhere except `remediation_actions` -- repeated "Root Cause" clicks on the same issue re-call Gemini each time (fine for a hackathon demo; add caching before scaling usage).
