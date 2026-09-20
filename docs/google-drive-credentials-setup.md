# Google Drive export: credentials setup and the create-vs-update trade-off

`POST /exports/financial-data` uploads a CSV into a single Google Drive
folder. This doc explains how authentication is configured, and — the part
worth reading carefully — a deliberate limitation we accepted rather than
engineered around, because engineering around it wasn't worth the cost.

## How it authenticates today

The service authenticates via **Application Default Credentials (ADC)**,
resolved by the `google-auth` library with zero configuration from us:

- **In production (Cloud Run):** ADC automatically resolves to the
  identity Cloud Run attaches to the service —
  `pf-rates@<PROJECT>.iam.gserviceaccount.com`. Nothing to configure, no
  token to store, nothing to rotate.
- **Locally:** run `gcloud auth application-default login` once; ADC picks
  up the resulting local credentials file automatically.

The only setting that still exists is `PF_RATES_GDRIVE_EXPORT_FOLDER_ID`
(see `.env.example` / `docs/deployment.md`) — which Drive folder to write
into. There is no OAuth token setting anymore.

### Why this replaced the previous OAuth-based setup

Until 2026-09-20, this service authenticated as a real human Google
account (`arturo.amb89@gmail.com`) via a long-lived OAuth refresh token,
produced once with `scripts/gdrive_oauth_setup.py` and stored in Secret
Manager. That worked, but came with a recurring, self-inflicted problem:
the OAuth consent screen for that Client ID is in Google's **"Testing"**
publishing status (not verified), and Google **forces refresh tokens for
apps in that status to expire after exactly 7 days** — no exceptions. This
bit us in production twice, each time needing a human to re-run the
interactive OAuth flow and re-upload the secret.

Moving to ADC + the service's own identity eliminates that failure mode
completely: nothing expires on a schedule, nothing needs periodic human
intervention.

## The trade-off we accepted: service accounts can't `create()`, only `update()`

This is the part to actually remember.

**Google service accounts have no storage quota of their own in a
personal (non-Workspace) Google Drive.** Concretely, against the Drive
API:

- `files().update(fileId=..., ...)` on a file that **already exists** and
  has been shared with the service account (as Editor/Writer) — **works
  fine**. Updating content doesn't consume the service account's own
  storage quota; it writes against the file's existing owner allocation.
- `files().create(...)` to make a **brand-new** file — **fails** for a
  bare service account with a `storageQuotaExceeded` error, because
  creating a file would need quota the service account doesn't have.

Our adapter (`GoogleDriveFileExport`) already looks up the file by name
before uploading and prefers `update()` whenever a match exists
(`_find_existing_file_id`). Since `financial-data.csv` **already exists**
in the target folder — created back when this service still used human
OAuth — every normal, everyday export run is a pure `update()`. The
service account limitation above never actually gets hit in practice.

### What we did *not* build, and why

We could have engineered around this — e.g. domain-wide delegation on a
Google Workspace domain, or keeping the old human-OAuth path alive
specifically for the create-a-new-file case, wired up alongside ADC. We
deliberately didn't:

- This is a single-user, personal-Drive setup, not a Workspace org — domain-
  wide delegation doesn't even apply here.
- Keeping two authentication code paths alive (ADC for the common case,
  OAuth for the rare case) is exactly the kind of complexity YAGNI warns
  against: the "rare case" is "someone manually deletes the export file
  from Drive," which has never happened and is easy to recover from by
  hand when (if) it ever does.
- Every extra authentication path is extra attack surface, extra secrets
  to rotate, and extra code to keep correct. Not worth it for a scenario
  that's rare, detectable (the next export run would 500 or error clearly
  instead of silently succeeding), and cheap to fix manually when it
  happens.

### The accepted consequence

**If the destination file is ever deleted from Drive, the automated export
will fail** (`storageQuotaExceeded`, wrapped as
`FinancialDataDependencyError` → HTTP 502) until someone manually recreates
it. That recreation is a rare, one-off, human-in-the-loop procedure:

1. Run the existing one-time OAuth helper as a real Google account that
   owns (or has Editor+ access to) the target folder:
   ```bash
   cd pf-rates
   .venv/bin/python scripts/gdrive_oauth_setup.py \
       --client-secret ../secrets/pf-rates/gdrive-oauth-client-secret.json \
       --output /tmp/recovery-token.json
   ```
2. Use that token to create the file once (a short one-off Python snippet
   using `googleapiclient`, or simply drag-and-drop the file into the
   folder via the Drive web UI with the same filename the service expects,
   e.g. `financial-data.csv`).
3. Confirm the folder (or the file specifically) is still shared with
   `pf-rates@<PROJECT>.iam.gserviceaccount.com` as Editor. If the whole
   folder was shared already (the normal setup), a new file created inside
   it inherits that sharing automatically — no extra step needed.
4. From that point on, the automated `update()` path takes over again with
   zero further manual intervention, exactly as it did before the file was
   deleted.

Note step 1's token is **not** stored anywhere persistent and is **not**
wired into any service setting — it's a throwaway, local, one-time-use
credential for this one manual recovery action. Delete it afterwards.

## One-time setup checklist (for a fresh environment / new folder)

1. Create (or pick) the destination Google Drive folder.
2. Share the folder with `pf-rates@<PROJECT>.iam.gserviceaccount.com` as
   **Editor**. (Already done for the current production folder — see the
   permission granted 2026-09-20.)
3. Set `PF_RATES_GDRIVE_EXPORT_FOLDER_ID` to that folder's id (the string
   in the folder's Drive URL after `/folders/`).
4. Make sure the destination filename (`financial-data.csv`) already
   exists in that folder — either because a prior run created it, or
   because you seeded it manually via the recovery procedure above.
5. Locally, run `gcloud auth application-default login` once. In
   production, no action needed — Cloud Run's attached service account
   identity is used automatically.

No OAuth client, no refresh token, no 7-day expiry to babysit.
