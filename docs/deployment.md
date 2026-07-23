# Deployment Guide

CI/CD pipeline, Google Cloud Run deployment, and production configuration for pf-rates.

## Overview

The service is deployed to **Google Cloud Run** via **GitHub Actions** (`.github/workflows/deploy.yml`).

**Key characteristics:**
- Automatic deployment on push to `main` (after manual approval)
- Trivy security scanning (blocks on CRITICAL/HIGH vulnerabilities)
- Multi-stage Docker build with non-root final image
- Scale-to-zero configuration (min 0 instances)
- Shared database managed by [pf-db](../pf-db)

## Pipeline overview

| Event | Jobs |
| --- | --- |
| Pull request to `main` | `test` to `build` (lint, pytest, Docker build, Trivy scan) |
| Push to `main` | `test` to `build` to `gate` (pause) to `deploy` to `notify-success` |

### Job details

**`test` job** - runs on every PR and push:
1. Lint with ruff, run static analysis (vulture, mypy, jscpd), and run pytest with coverage. No Docker.

**`build` job** - runs on every PR and push (needs: `test`):
1. Build the Docker image locally (not pushed) for scanning.
2. Scan the image with **Trivy**: uploads a SARIF report to the GitHub Security tab and blocks the pipeline on unfixed CRITICAL/HIGH CVEs.
3. On push to `main` only: tag the image for Artifact Registry and upload it as a GitHub Actions artifact (expires after 1 day).

**`gate` job** - runs only on push to `main` (needs: `build`):
1. Pauses for manual approval via the `production` GitHub environment.
2. Configure required reviewers in Settings to Environments to production. Rejecting or cancelling does not send any notification.

**`deploy` job** - runs only on push to `main`, requires the `GCP` GitHub environment (needs: `gate`):
1. Authenticate to GCP using a service-account key.
2. Assert that Artifact Registry vulnerability scanning is disabled (cost control - approximately $5/month per image if enabled).
3. Load the image artifact and push it to Artifact Registry (`us-central1`, repository `pf-rates`) tagged with the commit SHA and `latest`.
4. Deploy the Cloud Run **Service** (`pf-rates`) with the new image.

> **Migrations** are handled by [pf-db](../pf-db) - a separate Cloud Run Job applies all pending migrations before pf-rates receives traffic.

**`notify-failure` job** - runs on push to `main` if `test`, `build`, or `deploy` fail:
1. Sends a failure email via SMTP. Does not fire on cancellation or gate rejection.

**`notify-success` job** - runs on push to `main` after a successful deploy:
1. Sends a confirmation email via SMTP.

## Pipeline invariants

**Never violate these rules:**

1. **Migrations before traffic** - the `pf-db` Cloud Run Job must apply all pending migrations before either service receives traffic. pf-rates ships no migration tooling.

2. **DB URL via `--set-secrets` only** - never `--set-env-vars`
   ```bash
   # Correct
   --set-secrets=PF_DATABASE_URL=pf-db-url:latest
   
   # Wrong (exposes secret in gcloud describe)
   --set-env-vars=PF_DATABASE_URL=postgresql://...
   ```

3. **AR scanning stays disabled** - pipeline uses Trivy (approximately $5/month if enabled)
   ```bash
   # Artifact Registry scanning is intentionally disabled
   # Trivy runs in the pipeline instead (free, faster)
   ```

4. **`--min-instances=0`** - intentional scale-to-zero; do not change without approval
   - Zero compute cost when idle
   - Cold starts acceptable for this use case

5. **Image tagged with both `github.sha` and `latest`** - deploy references SHA, not `latest`
   ```bash
   # Both tags are pushed
   us-central1-docker.pkg.dev/PROJECT/pf-rates/app:abc123def
   us-central1-docker.pkg.dev/PROJECT/pf-rates/app:latest
   
   # Deploy uses SHA for immutability
   --image=us-central1-docker.pkg.dev/PROJECT/pf-rates/app:abc123def
   ```

6. **Non-root container** - Dockerfile switches to `appuser` in final stage
   ```dockerfile
   # Final stage runs as non-root
   USER appuser
   CMD ["uvicorn", "financial_data.interfaces.api.main:app", ...]
   ```

7. **Multi-stage build** - final stage copies only the venv; do not add `COPY src ./src`
   ```dockerfile
   # Correct (only venv)
   COPY --from=builder /app/.venv /app/.venv
   
   # Wrong (duplicates source, breaks PATH)
   COPY src ./src
   ```

## GitHub Secrets

Configure the following secrets in the repository (Settings to Secrets and variables to Actions):

| Secret | Required | Description |
| --- | --- | --- |
| `GCP_SA_KEY` | Yes | Service-account JSON key with the roles listed in the deploy workflow header. |
| `GCP_PROJECT_ID` | Yes | GCP project ID. |
| `PF_DATABASE_URL` | Yes | Connection string stored in Secret Manager (injected into Cloud Run at runtime). |
| `PF_RATES_API_KEY` | Yes | API key for client authentication; stored in Secret Manager and injected into the service at runtime. |
| `GCP_CLOUD_SQL_INSTANCE` | optional | Cloud SQL instance in `PROJECT:REGION:INSTANCE` format (leave empty for Option A). |
| `MAIL_SERVER` | Yes | SMTP server hostname (e.g. `smtp.gmail.com`). |
| `MAIL_PORT` | Yes | SMTP port (e.g. `587` for STARTTLS). |
| `MAIL_USERNAME` | Yes | SMTP username / sender address. |
| `MAIL_PASSWORD` | Yes | SMTP password or app-specific password. |
| `MAIL_FROM` | Yes | Sender display address (e.g. `pf-rates CI <you@gmail.com>`). |
| `MAIL_TO` | Yes | Recipient address(es), comma-separated. |

> **BCCH credentials** (`FINANCIAL_DATA_BCCH_API_USER` / `FINANCIAL_DATA_BCCH_API_PASSWORD`) are listed in the workflow header for reference. They are not currently injected into Cloud Run automatically - add `--set-secrets` entries in the deploy step if your environment requires them.

### Database options

The pipeline supports two database configurations, controlled by the optional `GCP_CLOUD_SQL_INSTANCE` secret:

| Option | Setup | `GCP_CLOUD_SQL_INSTANCE` |
| --- | --- | --- |
| **A - external DB** (e.g. Neon, Supabase) | Set `PF_DATABASE_URL` in Secret Manager pointing to the external host | leave the secret **empty** |
| **B - Cloud SQL** | Use the shared Cloud SQL instance managed by pf-db | set to `PROJECT:us-central1:pf-db` |

## Cloud Run configuration

| Setting | Value | Notes |
|---|---|---|
| **Region** | `us-central1` | Must match Artifact Registry region |
| **Min instances** | `0` | Scale to zero when idle |
| **Max instances** | `2` | Prevent runaway scaling |
| **Memory** | `512 MiB` | Sufficient for rate data workloads |
| **CPU** | `1` | Single vCPU |
| **Port** | `8080` | Cloud Run injects `PORT` env var (app listens on 8001 in dev) |
| **Service account** | `pf-rates@<PROJECT>.iam.gserviceaccount.com` | Needs `roles/secretmanager.secretAccessor` |
| **Secrets** | `PF_DATABASE_URL` and `PF_RATES_API_KEY` from Secret Manager | Never use `--set-env-vars` |

### Service account permissions

The Cloud Run service account needs:

```bash
# Allow reading secrets at runtime
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:pf-rates@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

## One-time GCP setup

The full bootstrap sequence (enable APIs, create Artifact Registry repository, Cloud SQL instance, Secret Manager secret, service account, IAM bindings) is documented in the comment block at the top of `.github/workflows/deploy.yml`.

### Quick checklist

1. Enable required APIs:
   ```bash
   gcloud services enable run.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
   ```

2. Create Artifact Registry repository:
   ```bash
   gcloud artifacts repositories create pf-rates \
     --repository-format=docker \
     --location=us-central1
   ```

3. Create Secret Manager secrets:
   ```bash
   echo -n "postgresql+asyncpg://..." | gcloud secrets create pf-db-url --data-file=-
   echo -n "your-secure-api-key" | gcloud secrets create pf-rates-api-key --data-file=-
   ```

4. Create service account and grant permissions:
   ```bash
   gcloud iam service-accounts create pf-rates
   gcloud projects add-iam-policy-binding PROJECT_ID \
     --member="serviceAccount:pf-rates@PROJECT_ID.iam.gserviceaccount.com" \
     --role="roles/secretmanager.secretAccessor"
   ```

5. Configure GitHub Secrets (see table above)

## Manual deployment

If you need to deploy manually (e.g., for testing):

```bash
# 1. Authenticate
gcloud auth login
gcloud config set project PROJECT_ID

# 2. Build and push
docker build -t us-central1-docker.pkg.dev/PROJECT_ID/pf-rates/app:manual .
docker push us-central1-docker.pkg.dev/PROJECT_ID/pf-rates/app:manual

# 3. Deploy
gcloud run deploy pf-rates \
  --image=us-central1-docker.pkg.dev/PROJECT_ID/pf-rates/app:manual \
  --region=us-central1 \
  --platform=managed \
  --set-secrets=PF_DATABASE_URL=pf-db-url:latest,PF_RATES_API_KEY=pf-rates-api-key:latest \
  --min-instances=0 \
  --max-instances=2 \
  --memory=512Mi \
  --cpu=1 \
  --port=8080 \
  --service-account=pf-rates@PROJECT_ID.iam.gserviceaccount.com \
  --allow-unauthenticated
```

## Rollback

Cloud Run keeps previous revisions. To rollback:

```bash
# List revisions
gcloud run revisions list --service=pf-rates --region=us-central1

# Rollback to a specific revision
gcloud run services update-traffic pf-rates \
  --region=us-central1 \
  --to-revisions=pf-rates-00042-abc=100
```

## Monitoring

### Logs

```bash
# Stream logs
gcloud run services logs tail pf-rates --region=us-central1

# View in Cloud Console
# https://console.cloud.google.com/run/detail/us-central1/pf-rates/logs
```

### Metrics

Cloud Run provides automatic metrics:
- Request count
- Request latency (p50, p95, p99)
- Container instance count
- CPU and memory utilization

Access via Cloud Console: Metrics tab in the pf-rates service page.

### Alerts

Configure alerts in Cloud Monitoring for:
- Error rate > 5%
- p99 latency > 2s
- Instance count (should scale to 0 when idle)

## Troubleshooting

### Deployment fails: "Image not found"

**Cause:** Image push to Artifact Registry failed or used wrong tag.

**Solution:**
```bash
# Verify image exists
gcloud artifacts docker images list us-central1-docker.pkg.dev/PROJECT_ID/pf-rates
```

### Deployment fails: "Service account does not have permission"

**Cause:** Cloud Run service account lacks `roles/secretmanager.secretAccessor`.

**Solution:**
```bash
gcloud projects add-iam-policy-binding PROJECT_ID \
  --member="serviceAccount:pf-rates@PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### Service returns 500: "Database connection failed"

**Cause:** `PF_DATABASE_URL` secret is incorrect or database is unreachable.

**Solution:**
1. Verify secret value in Secret Manager
2. If using Cloud SQL, ensure proxy sidecar is configured
3. Check pf-db is accepting connections

### Service returns 403: "Invalid API key"

**Cause:** `PF_RATES_API_KEY` mismatch or not set.

**Solution:**
1. Verify secret value in Secret Manager matches client key
2. Check Cloud Run environment has the secret injected
3. Test with `/health` endpoint (no auth required)

### Trivy scan blocks deployment

**Cause:** Critical or high-severity vulnerabilities detected.

**Solution:**
1. Update base image in Dockerfile (`python:3.12-slim` to newer version)
2. Update dependencies in `pyproject.toml`
3. Run `make reinstall` locally and retest
4. If vulnerability is in transitive dependency, check for newer versions

## Versioning

Deployments are tagged with **SemVer** based on commit history:

- **Major** (1.0.0 to 2.0.0): Breaking API changes
- **Minor** (1.0.0 to 1.1.0): New features, backward-compatible
- **Patch** (1.0.0 to 1.0.1): Bug fixes

Use **Conventional Commits** to trigger semantic versioning:
- `feat:` to minor bump
- `fix:` to patch bump
- `feat!:` or `BREAKING CHANGE:` to major bump

See [AGENTS.md](../AGENTS.md#versioning-and-operations) for commit conventions.
