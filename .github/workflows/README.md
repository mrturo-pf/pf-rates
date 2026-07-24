# GitHub Actions Workflows

This directory contains CI/CD workflows for pf-rates.

## Workflows

### test.yml - Quality Checks

**Trigger:** Push to main, Pull Requests

**What it does:**
1. Clones pf-rates into subdirectory
2. Clones pf-common (shared infrastructure) alongside
3. Runs `make check` (all quality gates)

**Steps:**
- Lint (ruff)
- Dead code detection (vulture)
- Type checking (mypy)
- Duplicate code detection (jscpd)
- Tests (pytest)
- Coverage (100% required)
- Security scan (trivy)

## Directory Structure in CI

```
/home/runner/work/pf-rates/pf-rates/
├── pf-common/          <- Cloned from github.com/mrturo/pf-common
└── pf-rates/           <- This repository
    └── Makefile        <- include ../pf-common/make/common.mk
```

This recreates the same structure as local development.

## Requirements

- **pf-common repository** must exist at `github.com/mrturo/pf-common`
- If pf-common is private, configure `PF_COMMON_TOKEN` secret

## Configuration

### For Public pf-common

No additional configuration needed.

### For Private pf-common

1. Create Personal Access Token with `repo` scope
2. Add as repository secret: `Settings > Secrets > Actions > New secret`
   - Name: `PF_COMMON_TOKEN`
   - Value: `<your-PAT>`

3. Uncomment in test.yml:
```yaml
- name: Checkout pf-common
  uses: actions/checkout@v4
  with:
    repository: your-org/pf-common
    path: pf-common
    token: ${{ secrets.PF_COMMON_TOKEN }}  # <- Uncomment this line
```

## Local Testing

You can test the workflow locally using [act](https://github.com/nektos/act):

```bash
# Install act
brew install act  # macOS
# or: curl https://raw.githubusercontent.com/nektos/act/master/install.sh | sudo bash

# Run workflow
act -j test
```

## Troubleshooting

### Workflow not running

- Check file is at `.github/workflows/test.yml` (note the dot)
- Verify workflow is enabled: Actions tab > Enable workflows

### pf-common not found

- Verify repository URL in test.yml
- If private, ensure PF_COMMON_TOKEN secret is configured

### make check fails

- Run `make check` locally first
- Check logs in Actions tab for specific error

## See Also

- [pf-common](https://github.com/mrturo/pf-common) - Shared infrastructure
- [Makefile](../Makefile) - Build targets
- [Contributing Guide](../docs/CONTRIBUTING.md) - Development workflow
