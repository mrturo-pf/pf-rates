# Investigation: pf-rates database secret access review

Date: 2026-10-11
Status: closed
Level: M
Scope: Verify the actual `pf-rates` database dependency and reduce unnecessary Secret Manager access without breaking the service.
Owner: `pf-rates`
Related artifacts: [register](../../../docs/proposals/ecosystem-improvement-register.md) · [index](../../../docs/proposals/index.md) · [source investigation](../../pf-payroll/docs/investigations/pf-svc-income-renaming.md)
Superseded-by: none

## 1. Question

Does `pf-rates` require `PF_DATABASE_URL` at runtime, which database secret should
it use, and which Secret Manager access can be removed safely?

## 2. Evidence observed

- `pf-rates` settings reads `PF_DATABASE_URL` through the `pf_database_url`
  validation alias and creates a SQLAlchemy engine from it.
- The service has database-backed repositories for rates, reference data, and
  export jobs; database access is a real runtime dependency.
- The deployment caller now passes `PF_RATES_DATABASE_URL` as the database secret
  name to the shared deploy workflow, which injects it as `PF_DATABASE_URL`.
- The shared runtime identity has access to both the service-specific database
  secret and the legacy shared `PF_DATABASE_URL` according to IMP-005 evidence.
- The service-specific Secret Manager policy is the intended target; the shared
  secret is a cleanup candidate only after runtime validation confirms no fallback
  reads or alternate deployment path remain.

## 3.1 Reference audit (2026-10-11)

Classified references found in the repository:

| Location | Classification | Conclusion |
| --- | --- | --- |
| `src/rates/config.py` | runtime | Reads `PF_DATABASE_URL` via the settings alias; keep the environment variable name stable |
| `src/rates/infrastructure/db/session.py` | runtime | Creates the SQLAlchemy engine from settings; database access is required |
| `.github/workflows/deploy.yml` | production deployment | Uses `PF_RATES_DATABASE_URL` as the Secret Manager source injected into `PF_DATABASE_URL` |
| `.env.example`, `Makefile`, `scripts/local_stack.sh`, `scripts/write_env.sh` | local development | Shared `PF_DATABASE_URL` is appropriate for local shared development; not evidence of production shared-secret dependency |
| `docs/database.md`, `docs/deployment.md`, `.github/workflows/README.md`, `gcp-setup.yml` comments | documentation/setup | Still describe legacy `PF_DATABASE_URL`; update to distinguish local/shared setup from production service-specific secret |

## 3.2 Controlled validation (2026-10-12)

Read-only Cloud Run inspection confirmed:

- service `pf-rates` is serving revision `pf-rates-00060-krl` at 100% traffic;
- the runtime configuration maps application variable `PF_DATABASE_URL` to
  Secret Manager secret `PF_RATES_DATABASE_URL`, version `latest`;
- the runtime configuration contains no `PF_DATABASE_URL` secret reference;
- the unauthenticated health endpoint returned HTTP 200 with the expected service
  identity and no secret or payload data was recorded.

Secret Manager IAM policy reads from the local environment were initially denied by
VPC Service Controls. The sanitized policy inventory from an allowed context now
confirms the member relationship. No IAM mutation was attempted. The remaining
required evidence is a representative authenticated database-backed operation and
explicit authorization for the scoped binding removal.

The production documentation and workflow comments were corrected to distinguish
`PF_RATES_DATABASE_URL` production access from local-development `PF_DATABASE_URL`.

## 3.3 Secret Manager policy evidence (2026-10-12)

The sanitized Secret Manager policy inventory confirms:

- `PF_RATES_DATABASE_URL` grants `roles/secretmanager.secretAccessor` to the
  `pf-rates` runtime identity only;
- legacy shared `PF_DATABASE_URL` grants the same role to both `pf-rates` and
  `pf-payroll` runtime identities;
- Cloud Run `pf-rates` uses only `PF_RATES_DATABASE_URL` for its database
  environment variable;
- no source, workflow, or deployed configuration evidence requires `pf-rates` to
  read `PF_DATABASE_URL`.

The evidence supports removing only the `pf-rates` member from the
`PF_DATABASE_URL` policy. The shared secret itself and the `pf-payroll` binding
remain outside this mutation. No secret values were read and no IAM mutation was
performed.


## 3.4 Authenticated runtime validation (2026-10-12)

Using the service-specific API secret only in memory, the active Cloud Run revision
`pf-rates-00060-krl` passed:

- `GET /health`: HTTP 200;
- authenticated `GET /monetary-units`: HTTP 200;
- response bodies were not persisted;
- secret values were unset after the request;
- no IAM, Secret Manager, Cloud Run, or database mutation was performed.

This validates that the service-specific runtime path is operational without relying
on the shared `PF_DATABASE_URL` secret. Combined with the policy and Cloud Run
metadata, the evidence supports the scoped IAM binding removal.

## 3.5 Scoped IAM mutation (2026-10-12)

The approved policy mutation completed successfully:

- before: shared `PF_DATABASE_URL` granted access to `pf-rates` and `pf-payroll`;
- after: shared `PF_DATABASE_URL` grants access only to `pf-payroll`;
- `PF_RATES_DATABASE_URL` remains the service-specific production path;
- the removed `pf-rates` member was absent in the after-policy verification;
- the `pf-payroll` member remained present;
- secret values were not read;
- rollback is limited to re-adding the removed `pf-rates` member if post-mutation
  validation identifies an actual dependency.

## 3.6 Post-mutation runtime validation (2026-10-12)

After the shared-secret binding removal, the service endpoints continued to respond
successfully:

- `GET /health`: HTTP 200;
- authenticated `GET /monetary-units`: HTTP 200;
- no rollback was required.

The operational change is therefore validated: `pf-rates` runs through
`PF_RATES_DATABASE_URL` without access to the legacy shared `PF_DATABASE_URL`. The
investigation is closed; the rollback procedure remains available as a contingency.
