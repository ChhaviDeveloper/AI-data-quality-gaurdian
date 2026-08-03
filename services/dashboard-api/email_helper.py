"""
Sends the "Data Quality Remediation Required" notification email when
someone clicks Remediate on the dashboard (POST /api/issues/<rule_id>/remediate).

Ships with the same SMTP approach services/notifier already uses for its
new-rule-proposal alerts (same env var names: SMTP_HOST, SMTP_PORT,
SMTP_USER, SMTP_PASSWORD, SMTP_FROM) rather than inventing a second
convention. Deliberately copied, not imported/shared, same reasoning as
gemini_helper.py -- each Cloud Run service stays self-contained at
build/deploy time.

Sending is entirely best-effort: any failure (no SMTP creds configured, no
owner_contacts match, the placeholder demo domain bouncing, etc.) is caught
and logged, never raised, so a failed/skipped email never blocks the
Remediate action itself from completing.
"""
import os
import logging
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Any, Dict, Optional, Tuple

import bq

logger = logging.getLogger("dashboard-api.email_helper")

SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")
SMTP_FROM = os.environ.get("SMTP_FROM", SMTP_USER or "no-reply@example.com")

# How long the product owner has to act, by severity. Adjust to match your
# team's actual SLA policy -- these are reasonable audit/compliance defaults.
SLA_BY_SEVERITY = {
    "Critical": "24 hours",
    "High": "3 business days",
    "Medium": "7 business days",
    "Low": "14 business days",
}


def get_owner_contact(business_owner: Optional[str], technology_owner: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """Resolve a recipient email from owner_contacts. Tries business_owner
    first (they're the "product owner" for the app), falls back to
    technology_owner if there's no contact on file for the business owner.
    Returns (email, matched_owner_name) -- (None, None) if neither resolves."""
    for name in (business_owner, technology_owner):
        if not name:
            continue
        rows = bq.query(
            f"SELECT email FROM {bq.table('owner_contacts')} WHERE owner_name = @name LIMIT 1",
            params=[bq.bigquery.ScalarQueryParameter("name", "STRING", name)],
        )
        if rows:
            return rows[0]["email"], name
    return None, None


def build_email(issue: Dict[str, Any], recommendation: Dict[str, Any], sample_record: Optional[dict]) -> Dict[str, str]:
    """Builds the subject + plain-text body for the remediation-required
    email, covering the 7 sections the business asked for: issue summary,
    business impact, suggested remediation, evidence, required action, SLA."""
    severity = issue.get("severity", "Medium")
    sla = SLA_BY_SEVERITY.get(severity, "7 business days")
    app_label = issue.get("application_name") or issue.get("application_id") or "the affected application"

    subject = f"Data Quality Remediation Required: {severity} Failure -- {app_label}"

    issue_summary = (
        f"Rule {issue.get('rule_id')} ({issue.get('rule_name')}) failed for {app_label} "
        f"(application_id: {issue.get('application_id')}).\n"
        f"{issue.get('description', '')}"
    )

    business_impact = (
        f"This is a {severity}-severity {issue.get('dimension', 'data quality')} issue. "
        f"Left unresolved, it can propagate incorrect or non-compliant data into any downstream "
        f"reports or decisions that rely on {app_label}, and may put related regulatory "
        f"attestations at risk."
    )

    suggested_remediation = recommendation.get("recommended_remediation") or (
        "Review the affected record(s) and correct the underlying data at the source system."
    )

    if sample_record:
        evidence_lines = "\n".join(
            f"  - {k}: {v}" for k, v in sample_record.items()
            if k not in ("run_id", "run_timestamp", "batch_id", "failed_rule_id") and v not in (None, "")
        )
        evidence = f"Sample failing record:\n{evidence_lines}" if evidence_lines else "See the dashboard's Root Cause panel for the full failing record."
    else:
        evidence = "See the dashboard's Root Cause panel for the full failing record."

    required_action = (
        "Please review this issue in the AI Data Guardian dashboard, apply the suggested "
        "remediation (or an equivalent fix) at the source, and mark it Accepted once resolved "
        "or if the risk is knowingly accepted."
    )

    body = f"""Hello,

A data quality issue has been flagged as {severity} severity and requires your attention as the owner of {app_label}.

ISSUE SUMMARY
{issue_summary}

BUSINESS IMPACT
{business_impact}

SUGGESTED REMEDIATION
{suggested_remediation}

EVIDENCE
{evidence}

REQUIRED ACTION
{required_action}

SLA
Please resolve or respond within {sla} of this notification ({datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}).

-- AI Data Guardian (automated notification)
"""
    return {"subject": subject, "body": body}


def send_remediation_email(to_email: str, subject: str, body: str) -> bool:
    """Best-effort SMTP send. Returns True on success, False on any failure
    (missing creds, bad recipient domain, network error, etc.) -- never
    raises, so a failed send never blocks the Remediate action."""
    if not to_email:
        logger.info("No recipient email resolved; skipping remediation notification.")
        return False
    if not SMTP_USER or not SMTP_PASSWORD:
        logger.info(
            "SMTP_USER/SMTP_PASSWORD not configured; skipping remediation notification "
            "(would have sent to %s: %s)", to_email, subject,
        )
        return False
    try:
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = SMTP_FROM
        msg["To"] = to_email
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=15) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASSWORD)
            server.sendmail(SMTP_FROM, [to_email], msg.as_string())
        logger.info("Remediation notification sent to %s", to_email)
        return True
    except Exception:
        logger.exception("Failed to send remediation notification to %s", to_email)
        return False
