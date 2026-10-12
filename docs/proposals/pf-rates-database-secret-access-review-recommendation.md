# Recommendation: pf-rates database secret access review

Date: 2026-10-11
Status: designed
Level: M
Scope: Verify `pf-rates` database secret dependency and remove unnecessary shared Secret Manager access.
Related artifacts: [brief](pf-rates-database-secret-access-review-brief.md) · [investigation](../investigations/pf-rates-database-secret-access-review.md) · [register](../../../docs/proposals/ecosystem-improvement-register.md)
Approved: Pending explicit owner approval
Superseded-by: none

## 1. Recommendation

Use `PF_RATES_DATABASE_URL` as the only production database secret referenced by
`pf-rates`. Keep its runtime accessor binding. Remove `pf-rates` access to the
legacy shared `PF_DATABASE_URL` only after a reference audit and controlled health
validation prove that no rollback/setup path requires it.

Do not delete the shared secret as part of this improvement; other services may
still consume it. Limit this work to the `pf-rates` principal's access policy.

## 2. Evidence and placement

`pf-rates` reads the database URL from `PF_DATABASE_URL`, while the reusable deploy
workflow maps `PF_RATES_DATABASE_URL` into that environment variable. The database
engine is initialized at application startup and repositories perform real database
operations. Therefore access is necessary, but shared-secret access is not the
intended steady-state path.

## 3. Rollout and rollback

1. Audit source, workflows, setup scripts, and environment configuration.
2. Confirm `PF_RATES_DATABASE_URL` exists and is readable by the runtime identity.
3. Validate service startup, health, representative reads/writes, and export paths.
4. Remove only the `pf-rates` member from the shared `PF_DATABASE_URL` policy.
5. Revalidate the service and inspect logs for configuration failures.
6. Roll back the policy binding only if an approved compatibility path is found.

No secret value is read or recorded. The mutation is an IAM policy change, not a
secret rotation or database schema change.

## 4. Validation matrix

| Area | Validation | Acceptance |
| --- | --- | --- |
| References | Source/workflow/setup audit | Every reference classified |
| Runtime | Cloud Run revision and health check | Starts with service-specific secret |
| Database | Representative rates/reference/export operations | No connection failure |
| Secret policy | Before/after IAM binding | `pf-rates` removed only from shared secret |
| Consumers | Payroll/rates integration checks | No unrelated outage |
| Rollback | Reversible binding procedure | Recovery path documented |

## 5. Cost and decision gate

No infrastructure cost is expected. The operational benefit is smaller secret blast
radius and clearer ownership. Implementation requires explicit approval of the
reference audit, validation window, and Secret Manager binding mutation.
