"""
dashboard-api: REST API backing the custom AI Data Guardian dashboard
(frontend/). Read-only against the v_dq_* views in
sql/dashboard_views.sql, plus two write endpoints (POST /remediate,
POST /accept) that record the Remediate/Accept workflow into
remediation_actions.

Unlike the other services in this repo (ingest, doc-parser, validator,
ai-proposals, notifier, job-trigger), which are Eventarc-triggered Cloud
Run functions via functions-framework, this one is a plain multi-route
Cloud Run *service* (Flask + gunicorn) because a REST API called directly
by a frontend doesn't fit the single-entry-point cloud_event pattern the
rest of the repo uses. Deployed the same way (Cloud Run, GitHub Actions),
just a different Dockerfile CMD -- see Dockerfile.

Env vars:
  BQ_PROJECT, BQ_DATASET   -- same defaults as every other service
  GCP_REGION, GEMINI_MODEL -- passed through to gemini_helper.py
  ALLOWED_ORIGIN           -- CORS origin for the frontend (default "*";
                              tighten this before a real deployment)

Local run (needs Application Default Credentials with BigQuery read access):
  pip install -r requirements.txt
  python main.py
"""
import os
import re
import sys
import uuid
import logging
import tempfile
import subprocess
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_cors import CORS

import bq
import gemini_helper
import email_helper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dashboard-api")

app = Flask(__name__)
CORS(app, origins=os.environ.get("ALLOWED_ORIGIN", "*"))

# services/dashboard-api -> services -> <repo root>. Used to shell out to the
# sibling ingest/validator/ai-proposals CLI scripts for the upload flow below
# -- see /api/ingest. We reuse those scripts as-is (subprocess) rather than
# importing across service directories, matching this repo's existing
# "each service stays self-contained" pattern (see gemini_helper.py).
#
# This only works when dashboard-api runs from a full repo checkout (local
# execution -- see README "Local-only execution"), where the sibling
# services/ingest, services/validator, services/ai-proposals directories are
# actually present on disk. Once dashboard-api is deployed as its own
# isolated Cloud Run container (`gcloud run deploy --source
# services/dashboard-api`), the built image only contains this directory --
# those sibling scripts don't exist inside it. _local_pipeline_available()
# below detects which situation we're in and /api/ingest branches
# accordingly: local -> subprocess orchestration (synchronous, returns a
# DQ score immediately); deployed -> upload straight into the GCS bucket's
# incoming/ prefix and let the Eventarc-triggered pipeline (already deployed
# via deploy-triggers) pick it up and process it asynchronously instead.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
UPLOAD_SUBPROCESS_TIMEOUT = int(os.environ.get("UPLOAD_SUBPROCESS_TIMEOUT", "180"))
BUCKET_NAME = os.environ.get("BUCKET", f"{bq.BQ_PROJECT}-dq-bucket")


def _local_pipeline_available() -> bool:
    return os.path.isfile(os.path.join(REPO_ROOT, "services", "ingest", "main.py"))

# Severity -> dashboard bucket, matching the 3-bucket summary tile layout
# (Critical Issues / Warnings / Info) on top of the 4-level Critical/High/
# Medium/Low severity the rules registry actually uses.
SEVERITY_BUCKET = {
    "Critical": "critical",
    "High": "warning",
    "Medium": "warning",
    "Low": "info",
}


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


@app.get("/api/overview")
def overview():
    dataset_rows = bq.query(f"SELECT * FROM {bq.table('v_dq_dataset_summary')}")
    dataset = dataset_rows[0] if dataset_rows else None

    confidence = None
    if dataset:
        conf_rows = bq.query(
            f"SELECT * FROM {bq.table('v_dq_confidence_pre_post')} WHERE batch_id = @batch_id",
            params=[bq.bigquery.ScalarQueryParameter("batch_id", "STRING", dataset["batch_id"])],
        )
        confidence = conf_rows[0] if conf_rows else None

    issues = bq.query(f"SELECT * FROM {bq.table('v_dq_issues_by_application')}")
    total_issues = len(issues)
    open_issues = [i for i in issues if i.get("remediation_status") != "Closed"]
    closed_issues = [i for i in issues if i.get("remediation_status") == "Closed"]

    bucket_counts = {"critical": {"open": 0, "closed": 0}, "warning": {"open": 0, "closed": 0}, "info": {"open": 0, "closed": 0}}
    for issue in issues:
        bucket = SEVERITY_BUCKET.get(issue.get("severity"), "info")
        key = "closed" if issue.get("remediation_status") == "Closed" else "open"
        bucket_counts[bucket][key] += 1

    return jsonify({
        "dataset": dataset,
        "confidence": confidence,
        "issue_totals": {
            "total": total_issues,
            "open": len(open_issues),
            "closed": len(closed_issues),
        },
        "buckets": bucket_counts,
    })


@app.get("/api/issues")
def issues():
    """One row per (rule, application) that's currently failing in the
    latest run -- lets each affected application be remediated/accepted on
    its own instead of one status for the whole rule. See
    v_dq_issues_by_application in sql/dashboard_views.sql."""
    rows = bq.query(f"SELECT * FROM {bq.table('v_dq_issues_by_application')}")
    return jsonify(rows)


@app.get("/api/issues/<rule_id>/root-cause")
def issue_root_cause(rule_id):
    run_id = request.args.get("run_id")
    application_id = request.args.get("application_id")
    issue_rows = bq.query(
        f"""SELECT * FROM {bq.table('v_dq_issues_by_application')}
            WHERE rule_id = @rule_id {_and_run(run_id)} {_and_app(application_id)}
            LIMIT 1""",
        params=_issue_params(rule_id, run_id, application_id),
    )
    if not issue_rows:
        return jsonify({"error": f"No issue found for rule_id={rule_id}"}), 404
    issue = issue_rows[0]

    # Root-cause context: this application's own failed record(s) if we know
    # which application, otherwise fall back to a sample across all
    # applications failing this rule (old rule-level behavior).
    sample_rows = bq.query(
        f"""SELECT * FROM {bq.table('failed_records_detail')}
            WHERE failed_rule_id = @rule_id {_and_run(run_id)} {_and_app(application_id)}
            LIMIT 5""",
        params=_issue_params(rule_id, run_id, application_id),
    )
    summary = gemini_helper.root_cause_summary(issue, sample_rows)
    return jsonify({"rule_id": rule_id, "application_id": application_id, **summary})


@app.post("/api/issues/<rule_id>/remediate")
def remediate_issue(rule_id):
    body = request.get_json(silent=True) or {}
    run_id = body.get("run_id")
    application_id = body.get("application_id")
    if not application_id:
        return jsonify({"error": "application_id is required in the request body"}), 400

    issue_rows = bq.query(
        f"""SELECT * FROM {bq.table('v_dq_issues_by_application')}
            WHERE rule_id = @rule_id AND application_id = @application_id {_and_run(run_id)}
            LIMIT 1""",
        params=_issue_params(rule_id, run_id, application_id),
    )
    if not issue_rows:
        return jsonify({"error": f"No open issue found for rule_id={rule_id}, application_id={application_id}"}), 404
    issue = issue_rows[0]

    recommendation = gemini_helper.recommend_remediation(issue)

    # Notify the product owner -- best-effort, never blocks the remediation
    # action itself. See email_helper.py for the lookup/send/compose logic.
    owner_email, matched_owner = email_helper.get_owner_contact(
        issue.get("business_owner"), issue.get("technology_owner")
    )
    if owner_email:
        sample_rows = bq.query(
            f"""SELECT * FROM {bq.table('failed_records_detail')}
                WHERE failed_rule_id = @rule_id AND application_id = @application_id {_and_run(run_id)}
                LIMIT 1""",
            params=_issue_params(rule_id, run_id, application_id),
        )
        email_content = email_helper.build_email(issue, recommendation, sample_rows[0] if sample_rows else None)
        sent = email_helper.send_remediation_email(owner_email, email_content["subject"], email_content["body"])
        notification_status = "Sent" if sent else "Failed"
    else:
        email_content = None
        notification_status = "Skipped: no contact on file"

    now = datetime.now(timezone.utc)
    row = {
        "action_id": str(uuid.uuid4()),
        "run_id": issue["run_id"],
        "rule_id": rule_id,
        "application_id": application_id,
        "batch_id": body.get("batch_id"),
        "issue_type": issue.get("dimension"),
        "issue_description": issue.get("description"),
        "recommended_remediation": recommendation.get("recommended_remediation"),
        "action_type": "Remediate",
        "status": "In Progress",
        "initiated_by": body.get("initiated_by", "dashboard-user"),
        "initiated_at": now.isoformat(),
        "completed_at": None,
        "remediation_details": recommendation.get("remediation_type"),
        "notified_email": owner_email,
        "notification_status": notification_status,
    }
    bq.insert_row("remediation_actions", row)
    return jsonify(row), 201


@app.post("/api/issues/<rule_id>/accept")
def accept_issue(rule_id):
    body = request.get_json(silent=True) or {}
    run_id = body.get("run_id")
    application_id = body.get("application_id")
    if not application_id:
        return jsonify({"error": "application_id is required in the request body"}), 400

    issue_rows = bq.query(
        f"""SELECT * FROM {bq.table('v_dq_issues_by_application')}
            WHERE rule_id = @rule_id AND application_id = @application_id {_and_run(run_id)}
            LIMIT 1""",
        params=_issue_params(rule_id, run_id, application_id),
    )
    if not issue_rows:
        return jsonify({"error": f"No open issue found for rule_id={rule_id}, application_id={application_id}"}), 404
    issue = issue_rows[0]

    now = datetime.now(timezone.utc)
    row = {
        "action_id": str(uuid.uuid4()),
        "run_id": issue["run_id"],
        "rule_id": rule_id,
        "application_id": application_id,
        "batch_id": body.get("batch_id"),
        "issue_type": issue.get("dimension"),
        "issue_description": issue.get("description"),
        "recommended_remediation": issue.get("recommended_remediation"),
        "action_type": "Accept",
        "status": "Closed",
        "initiated_by": body.get("initiated_by", "dashboard-user"),
        "initiated_at": now.isoformat(),
        "completed_at": now.isoformat(),
        "remediation_details": body.get("note", "Accepted as-is; no remediation applied."),
    }
    bq.insert_row("remediation_actions", row)
    return jsonify(row), 201


@app.post("/api/ingest")
def ingest_dataset():
    """Upload a CSV straight from the dashboard and run the whole local
    pipeline against it: ingest -> validator -> ai-proposals, in that order,
    each as a subprocess of the sibling service script (same code path
    proven out via the CLI walkthrough in the README). Synchronous -- the
    request blocks until all three steps finish, so the frontend should show
    a loading state for anywhere from ~10-60s depending on Gemini latency.
    """
    if "file" not in request.files:
        return jsonify({"error": "No file uploaded (expected multipart field 'file')"}), 400
    upload = request.files["file"]
    if not upload.filename or not upload.filename.lower().endswith(".csv"):
        return jsonify({"error": "Only .csv files are supported"}), 400

    tmp_dir = tempfile.mkdtemp(prefix="dq_upload_")
    tmp_path = os.path.join(tmp_dir, upload.filename)
    upload.save(tmp_path)

    if not _local_pipeline_available():
        return _ingest_via_gcs_upload(upload.filename, tmp_path)

    child_env = {**os.environ, "BQ_PROJECT": bq.BQ_PROJECT, "BQ_DATASET": bq.BQ_DATASET}

    logger.info("Ingesting uploaded file %s", upload.filename)
    ingest_result = subprocess.run(
        [sys.executable, "main.py", "--local-csv", tmp_path, "--local-to-bq"],
        cwd=os.path.join(REPO_ROOT, "services", "ingest"),
        capture_output=True, text=True, env=child_env, timeout=UPLOAD_SUBPROCESS_TIMEOUT,
    )
    if ingest_result.returncode != 0:
        logger.error("ingest failed: %s", ingest_result.stderr[-4000:])
        return jsonify({"error": "Ingest step failed", "details": ingest_result.stderr[-4000:]}), 500

    batch_match = re.search(r"batch_id=([0-9a-fA-F-]+)", ingest_result.stdout)
    if not batch_match:
        return jsonify({"error": "Ingest ran but no batch_id was found in its output", "stdout": ingest_result.stdout}), 500
    batch_id = batch_match.group(1)

    logger.info("Validating batch_id=%s", batch_id)
    validator_result = subprocess.run(
        [sys.executable, "main.py"],
        cwd=os.path.join(REPO_ROOT, "services", "validator"),
        capture_output=True, text=True, timeout=UPLOAD_SUBPROCESS_TIMEOUT,
        env={**child_env, "BATCH_ID": batch_id},
    )
    validator_log = validator_result.stdout + validator_result.stderr
    if validator_result.returncode != 0:
        logger.error("validator failed: %s", validator_result.stderr[-4000:])
        return jsonify({
            "batch_id": batch_id,
            "error": "Ingest succeeded but validation failed",
            "details": validator_result.stderr[-4000:],
        }), 207

    run_match = re.search(r"Run ([0-9a-fA-F-]+) complete", validator_log)
    score_match = re.search(r"DQ score:\s*([\d.]+)%", validator_log)
    run_id = run_match.group(1) if run_match else None
    dq_score = float(score_match.group(1)) if score_match else None

    logger.info("Mining new rule proposals for run_id=%s", run_id)
    new_proposals = None
    try:
        proposals_result = subprocess.run(
            [sys.executable, "main.py"],
            cwd=os.path.join(REPO_ROOT, "services", "ai-proposals"),
            capture_output=True, text=True, env=child_env, timeout=UPLOAD_SUBPROCESS_TIMEOUT,
        )
        proposals_log = proposals_result.stdout + proposals_result.stderr
        if proposals_result.returncode == 0:
            pm = re.search(r"Wrote (\d+) new proposal", proposals_log)
            new_proposals = int(pm.group(1)) if pm else 0
        else:
            logger.warning("ai-proposals step failed (non-fatal): %s", proposals_result.stderr[-2000:])
    except Exception:
        logger.exception("ai-proposals step raised (non-fatal)")

    return jsonify({
        "batch_id": batch_id,
        "run_id": run_id,
        "dq_score": dq_score,
        "new_proposals": new_proposals,
        "dataset_name": upload.filename,
    }), 201


def _ingest_via_gcs_upload(filename: str, tmp_path: str):
    """Cloud Run deployed-container path: no sibling scripts on disk, so
    upload straight to gs://<bucket>/incoming/ instead and let the
    already-deployed Eventarc pipeline (ingest-trigger -> ingest ->
    staging-loaded -> trigger-validator -> validator job -> ... ) process it.
    Asynchronous -- there's no DQ score to return yet, just a confirmation
    the file is on its way through the pipeline."""
    from google.cloud import storage

    unique_name = f"{uuid.uuid4().hex[:8]}_{filename}"
    blob_path = f"incoming/{unique_name}"
    try:
        client = storage.Client(project=bq.BQ_PROJECT)
        blob = client.bucket(BUCKET_NAME).blob(blob_path)
        blob.upload_from_filename(tmp_path)
    except Exception:
        logger.exception("Could not upload %s to gs://%s/%s", filename, BUCKET_NAME, blob_path)
        return jsonify({"error": f"Could not upload to gs://{BUCKET_NAME}/{blob_path}"}), 500

    return jsonify({
        "mode": "async",
        "gcs_uri": f"gs://{BUCKET_NAME}/{blob_path}",
        "message": (
            "Uploaded to Cloud Storage. The ingest -> validator -> ai-proposals -> notifier "
            "pipeline will run automatically via Eventarc, usually within a few seconds to a "
            "minute. Refresh the Datasets or Overview page shortly to see results."
        ),
    }), 202


@app.get("/api/analytics/trend")
def analytics_trend():
    rows = bq.query(f"SELECT * FROM {bq.table('v_dq_confidence_trend')} ORDER BY run_timestamp ASC")
    return jsonify(rows)


@app.get("/api/analytics/issue-overview")
def analytics_issue_overview():
    rows = bq.query(f"SELECT * FROM {bq.table('v_dq_issue_overview')}")
    return jsonify(rows)


@app.get("/api/regulations")
def regulations():
    rows = bq.query(f"SELECT * FROM {bq.table('v_dq_regulations')}")
    return jsonify(rows)


@app.get("/api/impacted-apps")
def impacted_apps():
    rows = bq.query(f"SELECT * FROM {bq.table('v_dq_apps_at_risk')}")
    return jsonify(rows)


@app.get("/api/history")
def history():
    limit = int(request.args.get("limit", 50))
    rows = bq.query(f"SELECT * FROM {bq.table('v_dq_activity_log')} LIMIT {limit}")
    return jsonify(rows)


@app.get("/api/datasets")
def datasets():
    rows = bq.query(f"SELECT * FROM {bq.table('dataset_registry')} ORDER BY uploaded_at DESC")
    return jsonify(rows)


@app.get("/api/recommendations")
def recommendations():
    status_filter = request.args.get("status")
    sql = f"SELECT * FROM {bq.table('rule_proposals')}"
    params = []
    if status_filter:
        sql += " WHERE status = @status"
        params.append(bq.bigquery.ScalarQueryParameter("status", "STRING", status_filter))
    sql += " ORDER BY created_at DESC"
    rows = bq.query(sql, params=params)
    return jsonify(rows)


def _and_run(run_id: str | None) -> str:
    return "AND run_id = @run_id" if run_id else ""


def _and_app(application_id: str | None) -> str:
    return "AND application_id = @application_id" if application_id else ""


def _issue_params(rule_id: str, run_id: str | None, application_id: str | None = None):
    params = [bq.bigquery.ScalarQueryParameter("rule_id", "STRING", rule_id)]
    if run_id:
        params.append(bq.bigquery.ScalarQueryParameter("run_id", "STRING", run_id))
    if application_id:
        params.append(bq.bigquery.ScalarQueryParameter("application_id", "STRING", application_id))
    return params


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
