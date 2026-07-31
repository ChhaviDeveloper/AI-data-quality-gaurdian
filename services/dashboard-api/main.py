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
import uuid
import logging
from datetime import datetime, timezone

from flask import Flask, jsonify, request
from flask_cors import CORS

import bq
import gemini_helper

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("dashboard-api")

app = Flask(__name__)
CORS(app, origins=os.environ.get("ALLOWED_ORIGIN", "*"))

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

    issues = bq.query(f"SELECT * FROM {bq.table('v_dq_issues_with_status')}")
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
    rows = bq.query(f"SELECT * FROM {bq.table('v_dq_issues_with_status')}")
    return jsonify(rows)


@app.get("/api/issues/<rule_id>/root-cause")
def issue_root_cause(rule_id):
    run_id = request.args.get("run_id")
    rule_rows = bq.query(
        f"""SELECT * FROM {bq.table('v_dq_issues_with_status')}
            WHERE rule_id = @rule_id {"AND run_id = @run_id" if run_id else ""}
            LIMIT 1""",
        params=_rule_params(rule_id, run_id),
    )
    if not rule_rows:
        return jsonify({"error": f"No issue found for rule_id={rule_id}"}), 404
    rule = rule_rows[0]

    sample_rows = bq.query(
        f"""SELECT * FROM {bq.table('failed_records_detail')}
            WHERE failed_rule_id = @rule_id {"AND run_id = @run_id" if run_id else ""}
            LIMIT 5""",
        params=_rule_params(rule_id, run_id),
    )
    summary = gemini_helper.root_cause_summary(rule, sample_rows)
    return jsonify({"rule_id": rule_id, **summary})


@app.post("/api/issues/<rule_id>/remediate")
def remediate_issue(rule_id):
    body = request.get_json(silent=True) or {}
    run_id = body.get("run_id")
    rule_rows = bq.query(
        f"""SELECT * FROM {bq.table('v_dq_issues_with_status')}
            WHERE rule_id = @rule_id {"AND run_id = @run_id" if run_id else ""}
            LIMIT 1""",
        params=_rule_params(rule_id, run_id),
    )
    if not rule_rows:
        return jsonify({"error": f"No open issue found for rule_id={rule_id}"}), 404
    rule = rule_rows[0]

    recommendation = gemini_helper.recommend_remediation(rule)
    now = datetime.now(timezone.utc)
    row = {
        "action_id": str(uuid.uuid4()),
        "run_id": rule["run_id"],
        "rule_id": rule_id,
        "batch_id": body.get("batch_id"),
        "issue_type": rule.get("dimension"),
        "issue_description": rule.get("description"),
        "recommended_remediation": recommendation.get("recommended_remediation"),
        "action_type": "Remediate",
        "status": "In Progress",
        "initiated_by": body.get("initiated_by", "dashboard-user"),
        "initiated_at": now.isoformat(),
        "completed_at": None,
        "remediation_details": recommendation.get("remediation_type"),
    }
    bq.insert_row("remediation_actions", row)
    return jsonify(row), 201


@app.post("/api/issues/<rule_id>/accept")
def accept_issue(rule_id):
    body = request.get_json(silent=True) or {}
    run_id = body.get("run_id")
    rule_rows = bq.query(
        f"""SELECT * FROM {bq.table('v_dq_issues_with_status')}
            WHERE rule_id = @rule_id {"AND run_id = @run_id" if run_id else ""}
            LIMIT 1""",
        params=_rule_params(rule_id, run_id),
    )
    if not rule_rows:
        return jsonify({"error": f"No open issue found for rule_id={rule_id}"}), 404
    rule = rule_rows[0]

    now = datetime.now(timezone.utc)
    row = {
        "action_id": str(uuid.uuid4()),
        "run_id": rule["run_id"],
        "rule_id": rule_id,
        "batch_id": body.get("batch_id"),
        "issue_type": rule.get("dimension"),
        "issue_description": rule.get("description"),
        "recommended_remediation": rule.get("recommended_remediation"),
        "action_type": "Accept",
        "status": "Closed",
        "initiated_by": body.get("initiated_by", "dashboard-user"),
        "initiated_at": now.isoformat(),
        "completed_at": now.isoformat(),
        "remediation_details": body.get("note", "Accepted as-is; no remediation applied."),
    }
    bq.insert_row("remediation_actions", row)
    return jsonify(row), 201


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


def _rule_params(rule_id: str, run_id: str | None):
    params = [bq.bigquery.ScalarQueryParameter("rule_id", "STRING", rule_id)]
    if run_id:
        params.append(bq.bigquery.ScalarQueryParameter("run_id", "STRING", run_id))
    return params


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)
