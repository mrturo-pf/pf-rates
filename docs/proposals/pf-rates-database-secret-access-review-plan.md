# Plan: pf-rates database secret access review

Date: 2026-10-11
Status: released
Level: M
Scope: Verify `pf-rates` database secret dependency and remove unnecessary shared Secret Manager access.
Related artifacts: [brief](pf-rates-database-secret-access-review-brief.md) · [recommendation](pf-rates-database-secret-access-review-recommendation.md) · [investigation](../investigations/pf-rates-database-secret-access-review.md)
Approved: 2026-10-12 by a0a11b7 (explicit authorization)
Superseded-by: none

## 1. Gates

- [x] Current source/runtime dependency identified.
- [x] Service-specific deployment input identified.
- [x] Reference audit completed across source, workflows, setup, rollback, and docs.
- [x] Read-only Cloud Run configuration and health validation completed.
- [x] Brief/recommendation approved.
- [x] Sanitized Secret Manager policy inventory obtained from an allowed context.
- [x] A controlled validation procedure is prepared to test health and an authenticated database-backed read without persisting secret values or response bodies.
- [x] Controlled authenticated database/export validation passed.
- [x] Explicit authorization for scoped `pf-rates` binding removal.
- [x] Shared-secret binding mutation completed and verified.
- [x] Post-mutation service and consumer validation passed.
- [x] Closure evidence recorded.

## 2. Slices

### Slice 1 — Reference audit

Classify every `PF_DATABASE_URL`, `PF_RATES_DATABASE_URL`, and related reference as
runtime, setup, migration, rollback, or stale documentation. Do not read values.

### Slice 2 — Controlled validation

Confirm the deployed rates service uses `PF_RATES_DATABASE_URL`, starts correctly,
and performs representative database-backed operations.

### Slice 3 — Binding reduction

After representative database-backed validation and explicit authorization, remove
only the `pf-rates` principal from the shared `PF_DATABASE_URL` Secret Manager
policy. Keep the secret and the `pf-payroll` member unchanged. Capture the
before/after policy metadata and retain the reversible rollback command.

### Slice 4 — Close

Record before/after policy metadata, service validation, rollback evidence, and
update the register/index.

## 3. Validation checklist

- [x] No unclassified runtime/setup/rollback reference remains;
- [x] service-specific secret exists and is accessible;
- [x] rates health/database/export checks pass;
- [x] shared-secret binding reduction is scoped to `pf-rates`;
- [x] no secret values appear in output;
- [x] rollback procedure is documented;

## 4. Change log

| Date | Status | Change | Evidence |
| --- | --- | --- | --- |
| 2026-10-11 | investigating | IMP-004 promoted to formal artifacts; no Secret Manager mutation performed. | Source and workflow inspection |
| 2026-10-12 | investigating | Allowed-context policy evidence confirms `pf-rates` and `pf-payroll` access to shared `PF_DATABASE_URL`, while `PF_RATES_DATABASE_URL` is scoped to `pf-rates`; Cloud Run uses only the service-specific secret. | Sanitized Secret Manager IAM and Cloud Run metadata |
| 2026-10-12 | investigating | Authenticated validation passed on revision `pf-rates-00060-krl`: health and `/monetary-units` returned HTTP 200; secret and response body were not persisted. | Sanitized Cloud Shell validation summary |
| 2026-10-12 | released | Post-mutation health and authenticated `/monetary-units` validation remained HTTP 200; no rollback required. | User-confirmed post-mutation endpoint validation |

## 5. Release record

- Commits: pending documentation commit
- Workflow runs: pending documentation push
- Owner approval: complete
- Secret policy mutation: completed and verified
- Closure evidence: complete
