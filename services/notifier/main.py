"""
notifier Cloud Function -- alerts reviewers when ai-proposals writes a new
candidate rule.

Triggered by Pub/Sub messages on the `new-proposal` topic (published by
services/ai-proposals/main.py). The message payload is the proposal dict
(proposal_id, rule_name, description, expression, confidence, source, ...).

MAIL PROVIDER IS NOT DECIDED YET -- this ships with MAIL_PROVIDER=log_only
by default, which just logs the alert (visible in Cloud Logging) instead of
sending anything, so the function deploys and runs cleanly with zero setup.
Swap MAIL_PROVIDER to 'sendgrid' or 'smtp' once you've picked a provider and
stored its credentials in Secret Manager -- see the two stub functions below.

Deploy as a Cloud Function (2nd gen) with a Pub/Sub trigger, or as a small
Cloud Run service using functions-framework the same way as doc-parser/ingest.
"""
import os
import json
import base64
import logging

import functions_framework

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("notifier")

MAIL_PROVIDER = os.environ.get("MAIL_PROVIDER", "log_only")  # log_only | sendgrid | smtp
# TEMPORARY default recipient for testing -- override with the
# NOTIFY_RECIPIENTS env var once you have a real distribution list.
NOTIFY_RECIPIENTS = os.environ.get("NOTIFY_RECIPIENTS", "chhavi.srivastava.wrk@gmail.com")


@functions_framework.cloud_event
def main(cloud_event):
    envelope = cloud_event.data.get("message", {})
    raw = envelope.get("data", "")
    try:
        proposal = json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception:
        logger.exception("Could not decode Pub/Sub message payload")
        return ("bad message", 200)

    subject = f"[Audit DQ] New rule proposal: {proposal.get('rule_name', 'unknown')}"
    body = _format_body(proposal)

    if MAIL_PROVIDER == "sendgrid":
        _send_via_sendgrid(subject, body)
    elif MAIL_PROVIDER == "smtp":
        _send_via_smtp(subject, body)
    else:
        logger.info("MAIL_PROVIDER=log_only -- alert not emailed, just logged:\n%s\n%s", subject, body)

    return ("ok", 200)


def _format_body(proposal: dict) -> str:
    return (
        f"Source: {proposal.get('source')}\n"
        f"Confidence: {proposal.get('confidence')}\n"
        f"Rule name: {proposal.get('rule_name')}\n"
        f"Description: {proposal.get('description')}\n"
        f"Expression: {proposal.get('expression')}\n"
        f"Matched rows: {proposal.get('matched_count')}\n"
        f"Notes: {proposal.get('notes')}\n\n"
        f"Review with: python cloud-pipeline/tools/review_proposals.py"
    )


def _send_via_sendgrid(subject: str, body: str):
    """Requires SENDGRID_API_KEY in Secret Manager, mounted as an env var,
    and a verified sender identity in your SendGrid account."""
    if not NOTIFY_RECIPIENTS:
        logger.warning("NOTIFY_RECIPIENTS not set; skipping SendGrid send.")
        return
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail
        sg = sendgrid.SendGridAPIClient(api_key=os.environ["SENDGRID_API_KEY"])
        mail = Mail(
            from_email=os.environ.get("SENDGRID_FROM_EMAIL", "no-reply@example.com"),
            to_emails=NOTIFY_RECIPIENTS.split(","),
            subject=subject,
            plain_text_content=body,
        )
        sg.send(mail)
    except Exception:
        logger.exception("SendGrid send failed")


def _send_via_smtp(subject: str, body: str):
    """Requires SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASSWORD in Secret Manager."""
    if not NOTIFY_RECIPIENTS:
        logger.warning("NOTIFY_RECIPIENTS not set; skipping SMTP send.")
        return
    try:
        import smtplib
        from email.mime.text import MIMEText
        msg = MIMEText(body)
        msg["Subject"] = subject
        msg["From"] = os.environ.get("SMTP_FROM", "no-reply@example.com")
        msg["To"] = NOTIFY_RECIPIENTS
        with smtplib.SMTP(os.environ["SMTP_HOST"], int(os.environ.get("SMTP_PORT", "587"))) as server:
            server.starttls()
            server.login(os.environ["SMTP_USER"], os.environ["SMTP_PASSWORD"])
            server.sendmail(msg["From"], NOTIFY_RECIPIENTS.split(","), msg.as_string())
    except Exception:
        logger.exception("SMTP send failed")
