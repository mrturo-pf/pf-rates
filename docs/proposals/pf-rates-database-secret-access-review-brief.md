# Brief: pf-rates database secret access review

Date: 2026-10-11
Status: released
Level: M
Scope: Verify `pf-rates` database secret dependency and remove unnecessary shared Secret Manager access.
Related artifacts: [investigation](../investigations/pf-rates-database-secret-access-review.md) · [register](../../../docs/proposals/ecosystem-improvement-register.md) · [index](../../../docs/proposals/index.md)
Approved: 2026-10-12 by a0a11b7 (explicit authorization)
Superseded-by: none

## Objective

Confirm that `pf-rates` uses only its service-specific database secret and reduce
unnecessary access to the legacy shared database secret without breaking deploy,
rollback, local setup, or runtime startup.

## Non-objectives

- Changing database schema or runtime role grants;
- rotating secret values without an approved consumer plan;
- changing the public API;
- deleting a shared secret still required by another approved consumer;
- changing the WIF deployment identity.

## Required outcomes

- Actual runtime and deployment references are inventoried.
- `PF_RATES_DATABASE_URL` is confirmed as the sole `pf-rates` database secret path.
- Representative service health/database operations pass after access reduction.
- Shared-secret access is removed only when no legitimate `pf-rates` path remains.
- Rollback and secret-policy evidence are recorded.

## Acceptance criteria

1. Source/workflow/deployment references are classified as runtime, setup, migration,
   rollback, or stale.
2. A controlled service validation passes using only the service-specific secret.
3. Secret Manager policy contains no unnecessary `pf-rates` access to shared
   `PF_DATABASE_URL`.
4. Other consumers of `PF_DATABASE_URL` remain unaffected.
5. No secret values enter artifacts or logs.
