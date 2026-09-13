#!/usr/bin/env python3
"""One-time interactive OAuth setup for the Google Drive CSV export.

Run this ONCE, manually, from a terminal on a machine with a browser:

    cd pf-rates
    .venv/bin/python scripts/gdrive_oauth_setup.py \
        --client-secret ../secrets/pf-rates/gdrive-oauth-client-secret.json \
        --output ../secrets/pf-rates/gdrive-oauth-token.json

It opens your browser, you log in as the Google account that owns the
target Drive folder and click "Allow" (you'll see an "unverified app"
warning first -- click "Advanced" -> "Go to <app name> (unsafe)"; this is
expected and safe for a personal-use app you created yourself). The
resulting token (with a long-lived refresh token) is saved to --output.

Prerequisite: an OAuth Client ID of type "Desktop app" created in Google
Cloud Console (APIs & Services -> Credentials -> Create Credentials ->
OAuth client ID), downloaded as JSON. That downloaded file is the
--client-secret input here; it is NOT the same thing as the --output
token file this script produces.

This script is a one-time developer tool, not part of the running
service -- that's why google-auth-oauthlib is a dev-only dependency
(see pyproject.toml) and this file lives outside src/.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

_SCOPES = ["https://www.googleapis.com/auth/drive"]


def _parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--client-secret",
        required=True,
        type=Path,
        help="Path to the OAuth Client ID JSON downloaded from Google Cloud Console.",
    )
    parser.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Path to write the resulting authorized-user token JSON to.",
    )
    return parser.parse_args()


def main() -> int:
    """Run the interactive consent flow and save the resulting token."""
    args = _parse_args()

    if not args.client_secret.is_file():
        print(f"Client secret file not found: {args.client_secret}", file=sys.stderr)
        return 1

    if args.output.exists():
        answer = (
            input(f"{args.output} already exists. Overwrite it? [y/N] ").strip().lower()
        )
        if answer != "y":
            print("Aborted, nothing was overwritten.")
            return 1

    flow = InstalledAppFlow.from_client_secrets_file(
        str(args.client_secret), scopes=_SCOPES
    )
    credentials = flow.run_local_server(port=0)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(credentials.to_json())
    args.output.chmod(0o600)

    print(f"\nToken saved to {args.output} (permissions set to 600).")
    print(
        "Next steps: point PF_RATES_GDRIVE_OAUTH_TOKEN_JSON_PATH at this file "
        "locally, or `gcloud secrets create PF_RATES_GDRIVE_OAUTH_TOKEN_JSON "
        "--data-file=...` for production."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
