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

# Runtime: installed package only.
# Migrations are managed by pf-db — this image ships no migration tooling.
COPY --from=builder /opt/venv /opt/venv

# The base image's SYSTEM Python ships an old setuptools/msgpack with known
# HIGH severity CVEs (CVE-2025-47273, GHSA-6v7p-g79w-8964). Nothing at
# runtime uses the system Python — everything runs from /opt/venv via PATH
# below — so the safest fix is to remove this unused, vulnerable cruft
# rather than try to patch code we never execute.
# Belt-and-suspenders: use the system pip by absolute path (PATH below
# already favors /opt/venv's pip) AND a filesystem sweep, in case the
# packages live somewhere other than the expected site-packages dir.
RUN /usr/local/bin/pip uninstall -y setuptools msgpack 2>/dev/null; \
    find /usr -xdev -depth \
      \( -iname 'setuptools*' -o -iname 'msgpack*' \
         -o -iname '_distutils_hack' -o -iname 'pkg_resources' \) \
      -print -exec rm -rf {} + ; \
    true

RUN useradd --no-create-home --shell /bin/false appuser
USER appuser

# Cloud Run injects PORT at runtime; default to 8080 for local runs.
# Uses shell form (via sh -c) to allow ${PORT:-8080} variable expansion
# while properly forwarding OS signals via exec.
ENTRYPOINT ["sh", "-c"]
CMD ["exec uvicorn financial_data.interfaces.api.app:app --host 0.0.0.0 --port ${PORT:-8080}"]
