# pf-rates

Microservice for Chilean financial reference data: exchange rates, economic indices, and income tax brackets.

## Overview

This repository implements a dedicated microservice for Chilean financial reference data with:

- exchange rates (USD, EUR) sourced from Mindicador and Banco Central de Chile (BCCH)
- economic indices (UF, UTM, IPC) from official Chilean sources
- income tax brackets for payroll tax calculation
- FastAPI API
- PostgreSQL persistence (schema and migrations managed by **pf-db**)

## Contribution workflow

Create a dedicated branch, run the documented quality checks, and open a pull
request targeting `main`. The protected `main` branch blocks direct pushes,
force-pushes, and deletion. Merging to `main` is the release input for the
Cloud Run deployment workflow.


See [`docs/getting-started.md`](docs/getting-started.md) for installation, setup, and first run.

## Documentation

| Document | Purpose |
| --- | --- |
| [`docs/getting-started.md`](docs/getting-started.md) | Installation, setup, basic validation |
| [`docs/development.md`](docs/development.md) | Development commands, testing, git hooks, adding features |
| [`docs/deployment.md`](docs/deployment.md) | CI/CD pipeline, Cloud Run deployment, production config |
| [`docs/database.md`](docs/database.md) | Database connection, schema ownership, local setup |
| [`docs/api.md`](docs/api.md) | Complete API reference with examples |
| [`AGENTS.md`](AGENTS.md) | AI agent reference: architecture, code style, design principles |