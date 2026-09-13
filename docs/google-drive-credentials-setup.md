# Google Drive OAuth Setup

> One-time, manual setup done by the Drive account owner (you) in a
> browser. After this, the export flow authenticates unattended forever --
> no repeated browser logins, which is required since this is meant to be
> triggered by an endpoint and, eventually, a cronjob (no human present to
> click through a consent screen at 3am).

This is a prerequisite for
[`csv-export-plan.md`](csv-export-plan.md) -- the exchange-rates CSV export
flow needs this to authenticate against the Google Drive API.

## Why OAuth as yourself, not a Service Account

An earlier version of this doc recommended a Service Account. That works
right up until the first time the export needs to *create* a new file --
at which point Drive rejects it with:

```
Service Accounts do not have storage quota. Leverage shared drives...
```

Google Service Accounts have **no personal storage quota** in a regular
(non-Workspace) Google Drive. They can update a file's content if it
already exists, but cannot create a new one -- creating requires quota,
and a Service Account has none of its own. The only real workarounds are:

- **Shared Drives** -- pooled storage, but a **Google Workspace-only**
  feature. Not available on personal `@gmail.com` accounts.
- **Domain-wide delegation** -- also Workspace-admin-only.
- **Authenticate as the actual account owner (this doc)** -- uses your own
  quota, so create/update/delete all work normally, and the export can
  self-heal (recreate the file) if it's ever deleted by accident.

We also considered plain interactive OAuth ("Testing" publishing status)
early on and rejected it, because Google **expires that refresh token
after 7 days** -- fine for a script you run by hand, useless for a
cronjob. The fix isn't to avoid OAuth; it's to **publish the OAuth consent
screen as "In production"** instead of leaving it in "Testing". That one
setting removes the 7-day expiry entirely, while still using your own
Drive quota. That's the approach below.

## 1. Create (or pick) a Google Cloud project

1. Go to **[console.cloud.google.com](https://console.cloud.google.com/)**
   and sign in with the Google account that owns the target Drive folder.
2. Top-left project selector -> **"New Project"**.
3. Suggested name: `pf-rates-exports`. Create it.

## 2. Enable the Google Drive API

1. With the project selected, go to **"APIs & Services" -> "Library"**.
2. Search for **"Google Drive API"** -> click it -> **"Enable"**.

## 3. Configure the OAuth consent screen

1. Go to **"APIs & Services" -> "OAuth consent screen"**.
2. User type: **"External"** (personal accounts can't use "Internal",
   that's Workspace-only) -- fill in the required fields (app name,
   support email, developer contact).
3. Scopes: add `.../auth/drive` (full Drive access -- see
   [`csv-export-plan.md`](csv-export-plan.md) for why the narrower
   `drive.file` scope isn't enough for this adapter).
4. Test users: add your own Google account here while iterating.
5. **Publish the app**: go back to the consent screen summary and click
   **"Publish App"** to move it from "Testing" to **"In production"**.
   You'll see a warning that Google hasn't verified it -- that's fine and
   expected for a personal single-user tool; verification is only
   required for public-facing apps requesting access to *other people's*
   data. This step is what removes the 7-day refresh-token expiry.

## 4. Create the OAuth Client ID

1. Go to **"APIs & Services" -> "Credentials"**.
2. **"Create Credentials" -> "OAuth client ID"**.
3. Application type: **"Desktop app"** (not "Web application" -- Desktop
   apps are designed for exactly this local, redirect-to-localhost flow).
4. Name: e.g. `pf-rates-csv-export-desktop`.
5. Download the resulting JSON. This is the **client secret** file --
   treat it like a password, but note it is *not* by itself enough to
   access your Drive; it just identifies the app to Google. The actual
   access grant happens in the next step.

## 5. Run the one-time authorization script

```bash
cd pf-rates
uv sync --extra dev   # ensures google-auth-oauthlib (dev-only dep) is installed
.venv/bin/python scripts/gdrive_oauth_setup.py \
    --client-secret /path/to/downloaded/client-secret.json \
    --output ../secrets/pf-rates/gdrive-oauth-token.json
```

This opens your browser. Log in as the account that owns the target Drive
folder, click **"Allow"**. You'll see an **"unverified app"** warning
first (expected, see step 3.5) -- click **"Advanced" -> "Go to
pf-rates-csv-export (unsafe)"**. Once you approve, the script saves the
resulting token (containing a long-lived refresh token) to `--output`,
with file permissions locked to `600`.

That token file goes inside this ecosystem's shared `secrets/` folder at
the `pf` repo root (**not** anywhere outside the repo tree) -- see
[`secrets/README.md`](../../secrets/README.md) for the `.gitignore`
guarantee that keeps it out of version control regardless of subfolder.

## 6. Wire it into pf-rates

```bash
# pf-rates/.env
PF_RATES_GDRIVE_OAUTH_TOKEN_JSON_PATH=/absolute/path/to/pf/secrets/pf-rates/gdrive-oauth-token.json
PF_RATES_GDRIVE_EXPORT_FOLDER_ID=<the target Drive folder id>
```

Use an **absolute** path -- `.env` values aren't resolved relative to the
repo root, and pf-rates may be launched from different working directories
(`make run` vs a container).

The folder id is the segment after `/folders/` in the Drive folder's URL:

```
https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz1234
                                        └──────── this is the id ────────┘
```

You do **not** need to manually create or share anything inside that
folder -- authenticating as yourself means the export can create the
destination file itself on first run, and update it in place afterwards.

## 7. Production (Secret Manager, not GitHub Actions secrets)

In production, `PF_RATES_GDRIVE_OAUTH_TOKEN_JSON` (the raw token content,
not a path) is injected the same way `PF_DATABASE_URL` and
`PF_RATES_API_KEY` already are -- see [`deployment.md`](deployment.md) for
the exact `gcloud secrets create` / `--set-secrets` commands. GitHub
Actions itself never needs to see this token's value; it only needs
`GCP_SA_KEY` to authenticate `gcloud`, and the deploy step references the
Secret Manager secret by name.

## Security notes

- The token file **is** a long-lived credential with full access to your
  Drive -- protect it like a password. Never commit it, never paste it
  into chat/logs.
- If it ever leaks: go to
  **[myaccount.google.com/permissions](https://myaccount.google.com/permissions)**,
  find the app, and revoke access. Then re-run step 5 to issue a new one.
- Cloud Run's `min-instances: 0` means the container cold-starts
  frequently and re-reads the token from Secret Manager each time. If
  Google ever rotates the refresh token server-side (rare for installed
  apps, but not impossible), the stored copy in Secret Manager would go
  stale until someone re-runs step 5 and updates the secret. Watch for
  `invalid_grant` errors from the export endpoint as the symptom.

