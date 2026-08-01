"""
job-trigger Cloud Function -- generic Pub/Sub -> Cloud Run Jobs bridge.

Eventarc can trigger Cloud Run *services* directly from a Pub/Sub topic, but
Cloud Run *Jobs* (used for validator and ai-proposals, since they're batch
steps with a clear start/end) need something to call jobs.run() on their
behalf. This function is that "something". Deploy one instance per
(topic, job) pair with different env vars:

  Instance "trigger-validator":
    subscribes to `staging-loaded`, runs the `validator` job,
    ENV_OVERRIDE_KEYS=batch_id=BATCH_ID

  Instance "trigger-ai-proposals":
    subscribes to `validation-complete`, runs the `ai-proposals` job,
    ENV_OVERRIDE_KEYS=run_id=RUN_ID

Env vars:
  TARGET_JOB_NAME     -- Cloud Run Job name to execute
  TARGET_REGION       -- region the job lives in
  ENV_OVERRIDE_KEYS   -- comma-separated "payload_key=ENV_VAR_NAME" pairs
"""
import os
import json
import base64
import logging

import functions_framework
from google.cloud import run_v2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("job-trigger")

PROJECT = os.environ.get("BQ_PROJECT", "ringed-hearth-504112-e3")
TARGET_JOB_NAME = os.environ["TARGET_JOB_NAME"]
TARGET_REGION = os.environ.get("TARGET_REGION", "europe-west1")
ENV_OVERRIDE_KEYS = os.environ.get("ENV_OVERRIDE_KEYS", "")


@functions_framework.cloud_event
def main(cloud_event):
    envelope = cloud_event.data.get("message", {})
    raw = envelope.get("data", "")
    try:
        payload = json.loads(base64.b64decode(raw).decode("utf-8"))
    except Exception:
        payload = {}

    overrides = []
    for pair in ENV_OVERRIDE_KEYS.split(","):
        if not pair or "=" not in pair:
            continue
        payload_key, env_var = pair.split("=", 1)
        if payload_key in payload:
            overrides.append(run_v2.EnvVar(name=env_var, value=str(payload[payload_key])))

    client = run_v2.JobsClient()
    job_path = client.job_path(PROJECT, TARGET_REGION, TARGET_JOB_NAME)
    container_overrides = (
        [run_v2.RunJobRequest.Overrides.ContainerOverride(env=overrides)] if overrides else None
    )
    request = run_v2.RunJobRequest(
        name=job_path,
        overrides=run_v2.RunJobRequest.Overrides(container_overrides=container_overrides)
        if container_overrides else None,
    )
    operation = client.run_job(request=request)
    logger.info("Triggered %s (operation: %s)", job_path, operation.operation.name)
    return ("ok", 200)
