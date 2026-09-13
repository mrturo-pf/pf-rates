# GitHub Actions Workflows

This directory contains CI/CD workflows for pf-rates. All three workflows are thin
callers into the **reusable workflows** centralized in
[`pf-common/.github/workflows/`](https://github.com/mrturo-pf/pf-common/tree/main/.github/workflows) —
that's the single source of truth for job definitions. This file only documents what
gets triggered from this repo and how to configure it.

## Workflows

### `deploy.yml` — CI / Deploy to Cloud Run

**Trigger:** push to `main`, pull requests targeting `main`.

**Calls:** `pf-common/.github/workflows/deploy-reusable.yml` with `repo_name: pf-rates`.

A 7-job pipeline (jobs 3–7 only run on push to `main`, not on PRs):

| # | Job | What it does |
|---|---|---|
| 1 | **Test & Lint** | ruff (lint + format check), vulture (dead code), mypy, jscpd (duplicate code), `make test-cov` (pytest, 100% coverage), Trivy filesystem scan |
| 2 | **Build & Scan** | Builds the Docker image, runs Trivy container scan (SARIF uploaded to GitHub Security), packages the release image as an artifact (push to `main` only) |
| 3 | **Approval Gate** | Manual approval via the `production` GitHub environment (required reviewers). Two mutually-exclusive gate jobs handle the approve/bypass paths depending on `require_approval` |
| 4 | **Deploy to Cloud Run** | Verifies Secret Manager secrets exist, verifies Artifact Registry vulnerability scanning is disabled (cost control), pushes the image, runs `gcloud run deploy` |
| 5 | **Smoke Test (Health Check)** | Curls the real, public `/health` endpoint and validates: `status == "ok"`, `service` matches this repo (catches a deploy-to-wrong-service mixup), and `uptime_seconds` is low (proves we're hitting the container that was *just* deployed, not a stale one) |
| 6 | **Notify — Failure** | Emails on failure of Test & Lint / Build & Scan / Deploy / Smoke Test (push to `main` only) |
| 7 | **Notify — Success** | Emails only after Deploy **and** Smoke Test both succeed (push to `main` only) |

Migrations are **not** run by this pipeline — `pf-db` owns and applies them via its own
Cloud Run Job before this service receives traffic.

### `gcp-setup.yml` — GCP Setup (one-time, manual)

**Trigger:** `workflow_dispatch` only — run manually from the Actions tab.

**Calls:** `pf-common/.github/workflows/gcp-setup-reusable.yml`.

Creates the Artifact Registry repository and placeholder Secret Manager secrets
(`PF_DATABASE_URL`, `PF_RATES_API_KEY`). Run this once before the very first deploy;
see the full manual setup checklist in the header comment of `deploy.yml`.

### `debug.yml` — Debug CI (manual)

**Trigger:** `workflow_dispatch` only.

**Calls:** `pf-common/.github/workflows/debug-reusable.yml`. Use this to poke at
runner environment/connectivity issues without going through the full pipeline.

## Required GitHub Secrets

Configured once at the repo (or org) level — see `deploy.yml`'s header comment for the
full one-time `gcloud` setup script.

| Secret | Purpose |
|---|---|
| `GCP_SA_KEY` | Service account JSON key used to authenticate to GCP |
| `GCP_PROJECT_ID` | GCP project ID |
| `GCP_CLOUD_SQL_INSTANCE` | (optional) Cloud SQL instance for the proxy sidecar |
| `GH_PAT` | (optional) GitHub PAT, only needed if `pf-common`/`pf-db` become private |
| `MAIL_SERVER`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_FROM`, `MAIL_TO` | SMTP config for the Notify jobs |

Secret Manager secrets (`PF_DATABASE_URL`, `PF_RATES_API_KEY`) are injected
automatically by the reusable deploy workflow — they are not GitHub secrets.

## Manual Approval Setup (one-time, GitHub UI)

1. Settings → Environments → New environment → name it `production`.
2. Enable "Required reviewers" and add yourself or your team.
3. The **Approval Gate (Manual)** job pauses there; deploy only runs after approval.

## Troubleshooting

- **Workflow not triggering:** confirm the push/PR targets `main` and the workflow
  file is enabled under Actions.
- **`pf-common not found` / composite action errors:** verify
  `github.com/mrturo-pf/pf-common` is reachable; if it ever goes private, set the
  `GH_PAT` secret.
- **`make check`-equivalent steps failing:** reproduce locally first with
  `make lint && make dead-code && make typecheck && make duplicate-code && make test-cov`.
- **Deploy job blocked on "Artifact Registry scanning is enabled":** run
  `gcloud artifacts repositories update pf-rates --location=us-central1 --disable-vulnerability-scanning`
  (kept disabled deliberately to avoid ~$5/month in scan fees; Trivy already covers this).

## See Also

- [`pf-common/.github/workflows/deploy-reusable.yml`](https://github.com/mrturo-pf/pf-common/blob/main/.github/workflows/deploy-reusable.yml) — the real pipeline definition
- [`../../docs/deployment.md`](../../docs/deployment.md) — full deployment guide for this service
- [`../../Makefile`](../../Makefile) — local equivalents of the CI quality gates
