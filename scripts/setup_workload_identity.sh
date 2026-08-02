#!/usr/bin/env bash
# One-time setup: lets GitHub Actions deploy to this GCP project WITHOUT a
# long-lived service-account key sitting in GitHub secrets. Creates:
#   1. A Workload Identity Pool + OIDC provider trusting
#      token.actions.githubusercontent.com, restricted to ONE specific
#      GitHub repo (so a compromised token elsewhere can't impersonate this).
#   2. A "deployer" service account GitHub Actions impersonates to run
#      gcloud/terraform commands (needs broad deploy permissions).
#   3. A "runtime" service account attached to the actual Cloud Run
#      services/jobs at runtime (narrower permissions -- BigQuery, Storage,
#      Pub/Sub, Vertex AI -- this is NOT the same identity as the deployer).
#
# Prints the two values you paste into GitHub repo secrets at the end:
#   WIF_PROVIDER, WIF_SERVICE_ACCOUNT
#
# Usage:
#   PROJECT_ID=ringed-hearth-504112-e3 \
#   GITHUB_REPO="your-github-username/your-repo-name" \
#   ./setup_workload_identity.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:-ringed-hearth-504112-e3}"
GITHUB_REPO="${GITHUB_REPO:?Set GITHUB_REPO=owner/repo-name before running this}"
POOL_ID="${POOL_ID:-github-actions-pool}"
PROVIDER_ID="${PROVIDER_ID:-github-actions-provider}"
DEPLOYER_SA_NAME="${DEPLOYER_SA_NAME:-github-actions-deployer}"
RUNTIME_SA_NAME="${RUNTIME_SA_NAME:-dq-pipeline-runtime}"

PROJECT_NUMBER=$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')
DEPLOYER_SA_EMAIL="${DEPLOYER_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"
RUNTIME_SA_EMAIL="${RUNTIME_SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "== Project: $PROJECT_ID (#$PROJECT_NUMBER) | GitHub repo: $GITHUB_REPO =="

echo "-- Enabling IAM Credentials API (needed for WIF) --"
gcloud services enable iamcredentials.googleapis.com --project "$PROJECT_ID"

echo "-- Creating Workload Identity Pool (no-op if it exists) --"
gcloud iam workload-identity-pools create "$POOL_ID" \
  --project="$PROJECT_ID" --location="global" \
  --display-name="GitHub Actions Pool" 2>/dev/null || echo "   pool already exists"

echo "-- Creating OIDC provider trusting GitHub, restricted to $GITHUB_REPO --"
gcloud iam workload-identity-pools providers create-oidc "$PROVIDER_ID" \
  --project="$PROJECT_ID" --location="global" \
  --workload-identity-pool="$POOL_ID" \
  --display-name="GitHub Actions Provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='${GITHUB_REPO}'" \
  --issuer-uri="https://token.actions.githubusercontent.com" 2>/dev/null || echo "   provider already exists"

echo "-- Creating deployer service account (impersonated by GitHub Actions) --"
gcloud iam service-accounts create "$DEPLOYER_SA_NAME" \
  --project="$PROJECT_ID" \
  --display-name="GitHub Actions deployer" 2>/dev/null || echo "   deployer SA already exists"

echo "-- Granting deployer SA the roles it needs to build/deploy everything --"
for role in \
  roles/run.admin \
  roles/storage.admin \
  roles/bigquery.admin \
  roles/pubsub.admin \
  roles/eventarc.admin \
  roles/artifactregistry.admin \
  roles/cloudbuild.builds.editor \
  roles/iam.serviceAccountUser
do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${DEPLOYER_SA_EMAIL}" \
    --role="$role" --condition=None >/dev/null
done

echo "-- Allowing the GitHub repo (via the WIF provider) to impersonate the deployer SA --"
gcloud iam service-accounts add-iam-policy-binding "$DEPLOYER_SA_EMAIL" \
  --project="$PROJECT_ID" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/attribute.repository/${GITHUB_REPO}"

echo "-- Creating runtime service account (attached to Cloud Run services/jobs, NOT the deployer) --"
gcloud iam service-accounts create "$RUNTIME_SA_NAME" \
  --project="$PROJECT_ID" \
  --display-name="DQ pipeline runtime" 2>/dev/null || echo "   runtime SA already exists"

echo "-- Granting runtime SA the roles the pipeline services actually need at runtime --"
for role in \
  roles/bigquery.dataEditor \
  roles/bigquery.jobUser \
  roles/storage.objectAdmin \
  roles/pubsub.publisher \
  roles/pubsub.subscriber \
  roles/aiplatform.user \
  roles/run.developer
do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:${RUNTIME_SA_EMAIL}" \
    --role="$role" --condition=None >/dev/null
done

echo ""
echo "================================================================"
echo "Add these as GitHub repo secrets (Settings > Secrets and variables"
echo "> Actions > New repository secret):"
echo ""
echo "  WIF_PROVIDER      = projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL_ID}/providers/${PROVIDER_ID}"
echo "  WIF_SERVICE_ACCOUNT = ${DEPLOYER_SA_EMAIL}"
echo ""
echo "Runtime service account (reference this in the workflow's"
echo "--service-account flags, already set as RUNTIME_SA_EMAIL there):"
echo "  RUNTIME_SA_EMAIL  = ${RUNTIME_SA_EMAIL}"
echo "================================================================"
