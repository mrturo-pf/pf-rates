# AGENTS.md — pf-rates

Dedicated microservice for Chilean financial reference data: exchange rates, economic indices, and income tax brackets.

## Scope

This file governs implementation, testing, documentation, and operations inside
`pf-rates`. Ecosystem ownership boundaries and cross-repository coordination are defined
in the root [`AGENTS.md`](../../AGENTS.md). This file owns the service-specific details.

## Architecture

Four layers; dependency flows inward only (interfaces → application → domain; infrastructure → application).

```
interfaces/      # FastAPI (adapter in)
application/     # Use cases, ports (Protocols), DTOs, services
domain/          # Value objects, quantizers, domain helpers — no I/O
infrastructure/  # SQLAlchemy, rate providers (adapters out)
shared/          # Cross-cutting constants
```

- `domain/` has zero external dependencies — pure Python only
- Ports (`application/ports/`) are `typing.Protocol` classes — never import concrete infrastructure types in the application layer
- Use cases are classes with `__init__` accepting port protocols; injected via `interfaces/api/dependencies.py`
- DTOs (`application/dto.py`) are the only data crossing layer boundaries

## Financial precision

- Always use `Decimal`, never `float` for monetary/rate values
- PostgreSQL columns use `NUMERIC`, never `FLOAT`
- Quantization helpers: `quantize_clp()` and `quantize_utm()` in `domain/quantizers.py`

## Language policy

- All code, identifiers, comments, docstrings, and files: English
- Exception: preserve official Chilean regulatory terms/source literals/seed values in original language only when translation alters meaning

## Code style

- ruff: `extend-select = ["D", "E", "W", "UP"]`, `pep257` convention
- Docstrings required for all modules, classes, and functions only
- PEPs: 484 (mypy), 544 (Protocols), 585 (`list[X]`), 604 (`X | None`), 498 (f-strings), 492 (async/await), 621 (pyproject.toml), 654 (exception groups)
- Domain dataclasses: `@dataclass(slots=True)`; frozen value objects add `frozen=True`
- Async throughout; structlog only (`infrastructure/logging/logger.py`) — never `print` or stdlib `logging`

## Design principles

- Apply DRY, SOLID, Clean Code, DDD — avoid god objects; prefer small, focused classes
- Extract constants/mappings/literals to `shared/`; zero duplication in `src/` or `tests/`
- Orchestration logic belongs in use cases, not routes
- Never `assert` for production validation; raise from `application/errors.py`
- No silent fallbacks
- **Cloud cost is always the priority in cloud decisions**: cheapest viable option first
  (scale-to-zero, free tooling over paid add-ons, no over-provisioning). See
  [`docs/deployment.md`](docs/deployment.md#pipeline-invariants) for the concrete rules
  this drives (`--min-instances=0`, Trivy instead of paid AR scanning, external DB option).

## Test-driven development

Use TDD for all behavioral changes. For new HTTP or application features, use Outside-In TDD: start with an observable API or application behavior test, drive the implementation through ports and use cases, then add focused domain and adapter tests.

Use ATDD for functional requirements and API contracts. Use BDD Given/When/Then scenarios when they clarify business behavior; BDD is complementary to TDD, not a required format for every unit test.

Keep unit tests isolated with typed hand-written stubs and use integration tests for real PostgreSQL and adapter boundaries. Tests must verify meaningful outputs, state, errors, and contracts. Documentation-only, formatting-only, and mechanical refactor changes are exempt from adding tests but must run applicable validation.

## Documentation and Postman collection must track reality

- [`docs/api.md`](docs/api.md) must describe every HTTP endpoint this service actually
  exposes. This file documents only the FastAPI surface owned by `pf-rates`.
  Adding, removing, or changing an endpoint (path, request/response shape, auth, error
  codes) requires updating `docs/api.md` in the **same change**, not "later" — letting
  it drift is an incomplete change. If ever unsure whether it's stale, check it
  against the live `GET /openapi.json`/route definitions before assuming it's correct.

- This service's endpoints are also mirrored in the shared Postman collection at the
  ecosystem root: `pf-base/postman/pf-ecosystem.postman_collection.json`, plus the
  `pf-rates-url`/`pf-rates-api-key` variables in
  `pf-base/postman/pf-ecosystem.postman_environment.{local,gcp}.json`. Update those too
  in the same change when practical — see `pf-base/postman/README.md` for the sync
  mechanics and `pf-base/AGENTS.md` for the ecosystem-wide version of this rule.

## Development commands

See [`docs/development.md`](docs/development.md) for the complete development workflow:
- `make` commands (install, local-up, check, test, lint, etc.)
- Git hooks (pre-commit, pre-push)
- Testing conventions (stubs, coverage, async)
- Adding a new use case (step-by-step guide)

Quick reference:

```bash
make install               # create .venv, install deps, configure git hooks
make local-up              # start API (requires pf-db running)
make check                 # lint → dead-code → typecheck → dup-check → test → test-cov
```

## CLI policy

Do not implement, add, restore, or expand any product-facing CLI command in `pf-rates`. Existing development, deployment, and automation commands such as `make` and repository scripts may still be used unless explicitly prohibited. Use the supported HTTP API and existing automation instead. Any exception requires explicit user approval first.


Before any interaction with GitHub using `gh`, including read-only commands, execute
`unset-proxies` first:

```bash
unset-proxies
```

The alias is defined in `~/.zshrc` as:

```bash
alias unset-proxies="source $HOME/Documents/scripts/unset_proxies.sh"
```

If aliases are unavailable in the current shell, run:

```bash
source "$HOME/Documents/scripts/unset_proxies.sh"
```

Only then run `gh`. This applies to every `gh` command in this repository.


See [`docs/deployment.md`](docs/deployment.md) for the complete deployment guide:
- Pipeline jobs (test, build, gate, deploy, notify)
- Pipeline invariants (migrations before traffic, secrets, scaling, etc.)
- GitHub Secrets configuration
- Cloud Run configuration
- Manual deployment and rollback procedures

Quick reference:

- **Trigger:** Push to `main` (after manual approval via `production` environment)
- **Security:** Trivy scan blocks on CRITICAL/HIGH vulnerabilities
- **Database:** Shared instance managed by [pf-db](../pf-db); migrations applied before deployment
- **Scaling:** min 0 / max 2 instances (scale-to-zero enabled)

## Versioning and operations

- SemVer; Conventional Commits (English)
- Never autonomously commit, push branches, create issues, or open PRs — requires explicit user command
- **Post-push monitoring:** before pushing, inspect the target workflow and cancel older superseded runs for the same repository, branch, and workflow. Cancel only active runs (`queued`, `pending`, `in_progress`, or `waiting`) using the actual status field; never cancel completed runs or runs from another branch/workflow. Verify each cancellation before pushing, then monitor the new run by exact SHA/run ID with `gh run watch`. Manual deployment approval requires explicit user authorization.
- **Network resilience:** if `gh`/GitHub is unreachable while monitoring (VPN/proxy
  hiccups happen), retry a couple of times with a short wait, then stop — never loop
  indefinitely, and never assume a push/cancel/approval-check succeeded just because
  an earlier command in the same sequence did. Report the blocker to the user
  explicitly and wait for them to fix connectivity or ask for a retry.

## Database

See [`docs/database.md`](docs/database.md) for the complete database guide:
- Connection configuration (`PF_DATABASE_URL`)
- Local database setup (pf-db workflow)
- Table ownership (currencies, exchange_rates, economic_indices, income_tax_brackets)
- ORM models and repositories
- Schema changes (coordination with pf-db)
- SQL test fixtures (integration tests)
- Database inspection tools (psql, Adminer)

Quick reference:

- **Schema owner:** [pf-db](../pf-db) (separate repository)
- **Connection:** `postgresql+asyncpg://pf_db:pf_db@localhost:5432/pf_db` (local)
- **Session management:** Always use `async with SessionLocal() as session`
- **Schema changes:** Coordinate with pf-db maintainers; never edit ORM models without a corresponding migration