# Plan: pf-rates database secret access review

Date: 2026-10-11
Status: investigating
Level: M
Scope: Verify `pf-rates` database secret dependency and remove unnecessary shared Secret Manager access.
Related artifacts: [brief](pf-rates-database-secret-access-review-brief.md) · [recommendation](pf-rates-database-secret-access-review-recommendation.md) · [investigation](../investigations/pf-rates-database-secret-access-review.md)
Approved: Pending explicit owner approval
Superseded-by: none

## 1. Gates

- [x] Current source/runtime dependency identified.
- [x] Service-specific deployment input identified.
- [x] Reference audit completed across source, workflows, setup, rollback, and docs.
- [ ] Brief/recommendation approved.
- [ ] Controlled runtime/database validation passed.
- [ ] Shared-secret binding mutation approved.
- [ ] Post-mutation service and consumer validation passed.
- [ ] Closure evidence recorded.

## 2. Slices

### Slice 1 — Reference audit

Classify every `PF_DATABASE_URL`, `PF_RATES_DATABASE_URL`, and related reference as
runtime, setup, migration, rollback, or stale documentation. Do not read values.

### Slice 2 — Controlled validation

Confirm the deployed rates service uses `PF_RATES_DATABASE_URL`, starts correctly,
and performs representative database-backed operations.

### Slice 3 — Binding reduction

Remove only the `pf-rates` principal from the shared `PF_DATABASE_URL` Secret
Manager policy after approval. Keep the secret itself and other consumers unchanged.

### Slice 4 — Close

Record before/after policy metadata, service validation, rollback evidence, and
update the register/index.

## 3. Validation checklist

- [ ] No unclassified runtime/setup/rollback reference remains;
- [ ] service-specific secret exists and is accessible;
- [ ] rates health/database/export checks pass;
- [ ] shared-secret binding reduction is scoped to `pf-rates`;
- [ ] no secret values appear in output;
- [ ] rollback procedure is documented.

## 4. Change log

| Date | Status | Change | Evidence |
| --- | --- | --- | --- |
| 2026-10-11 | investigating | IMP-004 promoted to formal artifacts; no Secret Manager mutation performed. | Source and workflow inspection |
| 2026-10-11 | investigating | Completed reference audit. Production uses `PF_RATES_DATABASE_URL` injected as `PF_DATABASE_URL`; remaining shared references are local setup or stale documentation. | Repository-wide `git grep` audit |

## 5. Release record

- Commits: pending
- Workflow runs: pending
- Owner approval: pending
- Secret policy mutation: pending
- Closure evidence: pending
