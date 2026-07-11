"""Root conftest — sets required environment variables before any package import.

Settings() is evaluated eagerly at import time, so env vars that have no default
must be present before the first ``import financial_data`` statement anywhere in
the test suite.  This root-level conftest runs before tests/conftest.py, making
the setup order deterministic without requiring noqa overrides.
"""

import os

# Force a known test value regardless of the developer's shell environment.
# setdefault would silently keep a real key, causing verify_api_key to reject
# the hardcoded "test-key" header used in every test fixture.
os.environ["PF_RATES_API_KEY"] = "test-key"
