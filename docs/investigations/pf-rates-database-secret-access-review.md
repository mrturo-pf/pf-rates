# Investigation: pf-rates database secret access review

Date: 2026-10-11
Status: investigating
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

No source code fallback to a second production secret was found. The remaining
shared-secret references are local-development or stale production setup guidance,
not runtime reads of a second environment variable.


- deployed revision configuration confirms only `PF_RATES_DATABASE_URL` is referenced;
- service starts and performs representative database reads/writes with the
  service-specific secret;
- no workflow, setup script, or runtime configuration still requires shared
  `PF_DATABASE_URL` for `pf-rates`;
- Secret Manager policy after cleanup contains only the intended runtime identity;
- rollback and failure behavior are documented.

Never read or record secret values, connection strings, tokens, or business rows.

## 4. Risks and open decisions

- Removing shared-secret access before validating every deployment path can cause
  a cold-start or rollback failure.
- The `gcp-setup` workflow and historical documentation may still mention shared
  `PF_DATABASE_URL`; classify each occurrence as runtime, migration, setup, or stale
  documentation before changing it.
- Decide whether the shared secret is still needed by another consumer before
  deleting or changing its policy.

## 5. Conclusion

Proceed with a focused M-level access review. `pf-rates` genuinely needs a database
secret, but the service-specific `PF_RATES_DATABASE_URL` path is now the source of
truth. The next step is controlled validation and a consumer-wide reference audit,
not immediate secret deletion.
