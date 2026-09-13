# ── builder stage ────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

RUN pip install --upgrade pip --no-cache-dir

# Install runtime dependencies only (no [dev] extras).
# Regular (non-editable) install places the package in venv/site-packages,
# so the final stage does not need to carry the src/ tree.
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

# ── final stage ──────────────────────────────────────────────────────────────
FROM python:3.12-slim AS final

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app

# Pull the latest Debian security patches for OS packages baked into the base
# image (gzip, libpcre2, libsqlite3, perl-base, etc.). python:3.12-slim is a
# floating tag; Trivy's vuln DB updates daily and will flag whatever CVEs were
# published against the image's OS packages since it was last rebuilt, even
# when our own dependencies haven't changed at all.
RUN apt-get update \
    && apt-get upgrade -y \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Runtime: installed package only.
# Migrations are managed by pf-db — this image ships no migration tooling.
COPY --from=builder /opt/venv /opt/venv

# The base image's system pip AND our venv's pip both vendor an old
# msgpack/setuptools that trip Trivy with known HIGH severity CVEs
# (CVE-2025-47273, GHSA-6v7p-g79w-8964) via pip's internal vendor
# manifest. Confirmed by elimination: removing only the system pip had
# zero effect, so the venv's own pip (copied in above) is the real
# culprit. Nothing at runtime uses pip in either location — the app
# runs via uvicorn from /opt/venv — so delete pip from both.
RUN rm -rf /opt/venv/lib/python3.12/site-packages/pip* \
           /opt/venv/bin/pip* \
           /usr/local/lib/python3.12/site-packages/pip* \
           /usr/local/bin/pip*

RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

# Cloud Run injects PORT at runtime; default to 8001 for local runs.
# Uses shell form (via sh -c) to allow ${PORT:-8001} variable expansion
# while properly forwarding OS signals via exec.
ENTRYPOINT ["sh", "-c"]
CMD ["exec uvicorn rates.interfaces.api.main:app --host 0.0.0.0 --port ${PORT:-8001}"]
