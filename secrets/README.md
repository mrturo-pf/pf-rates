# secrets/ (pf-rates, local-only)

Module-scoped, machine-local secrets for one-off `pf-rates` scripts.
Everything placed in this folder — including new subfolders — is gitignored
by default (see `.gitignore` right here): only this `README.md` and the
`.gitignore` itself can ever be committed.

## This is a different folder than the ecosystem-level `secrets/pf-rates/`

The credential `pf-rates` actually needs for the Google Drive OAuth manual
recovery procedure (`gdrive-oauth-client-secret.json`) does **not** live
here — it lives at the **ecosystem root**,
`../../../secrets/pf-rates/gdrive-oauth-client-secret.json`. See
[`../../../secrets/README.md`](../../../secrets/README.md) and
[`../docs/google-drive-credentials-setup.md`](../docs/google-drive-credentials-setup.md)
for the full story. That's the one file needed for that rare/manual flow;
routine `POST /exports/financial-data` uses Application Default Credentials
and needs no file at all.

This local folder is for anything narrower and disposable: a target URL, a
one-off API key, or a throwaway credential a script under `scripts/` needs
only on your machine — not worth documenting in the shared ecosystem folder.
Empty today; nothing here yet.

## Rules

- Never hardcode a path to a file in here inside committed code — read it
  from an environment variable, same convention as the rest of this repo.
- If a script needs a template value checked in for teammates to copy (the
  way `pf-db` does with `secrets/neon.env.example`), name it `*.env.example`
  and add a matching `!*.env.example` allow-line to this folder's
  `.gitignore`.
