# LOCAL DEVELOPMENT

A throwaway PostgreSQL 16 + pgvector for development and testing on a
laptop. **Synthetic data only.**

`docs/OPERATIONS.md` is the deployment document and is unchanged by any of
this. Nothing here runs on the VPS.

---

## Why a separate compose file rather than an override

`docker-compose.yml` is VPS-targeted by design, and two of its properties
are exactly what a laptop cannot provide:

- it joins `${N8N_NETWORK}` as an **external** network — that network does
  not exist on a development machine, so the stack will not start;
- it publishes **no port** — deliberate, because the VPS reaches Postgres
  container-to-container. But the migration runner and all seven test
  suites run on the *host*, so locally there has to be a port.

An override file (`docker-compose.override.yml`) was rejected: Compose
applies it automatically and silently to every `docker compose` invocation
in the directory, including one intended for production, and an override
cannot remove the external network requirement. It would also share the
project name `phi`, meaning the same container name and the same volume —
so a local `down -v` and a VPS deployment would be aimed at the same
objects.

`docker-compose.local.yml` is therefore a **separate stack**:

| | production (`docker-compose.yml`) | local (`docker-compose.local.yml`) |
|---|---|---|
| project | `phi` | `phi-local` |
| container | `phi-postgres` | `phi-postgres-local` |
| volume | `phi_postgres_data` | `phi-local_postgres_data_local` |
| network | `${N8N_NETWORK}`, external | `phi-local_default`, own |
| port | none published | `127.0.0.1:55432` |
| `shared_buffers` | 2 GB | 256 MB |
| env file | `.env` | `.env.local` |

Nothing collides. A `docker compose -f docker-compose.local.yml down -v`
cannot touch a deployment, and neither can the reverse.

The env files are separate for the same reason: a laptop password can never
be picked up by a production `docker compose up`.

---

## Setup

```bash
cp .env.local.example .env.local        # edit if you want your own passwords
bash scripts/local_db_setup.sh          # up + migrate + role passwords + verify
```

Windows (PowerShell, from the repo root):

```powershell
Copy-Item .env.local.example .env.local
powershell -ExecutionPolicy Bypass -File scripts\local_db_setup.ps1
```

`--reset` / `-Reset` destroys the volume first and rebuilds from empty.

The script is the local mirror of `docs/OPERATIONS.md` steps 3–6, in the
same order and for the same reason:

1. `docker compose up -d`, wait for the healthcheck
2. `python3 scripts/migrate.py` as **`phi_admin`**
3. `ALTER ROLE` the two runtime passwords — migration 005 creates the roles
   with **no** password, so this cannot happen before the migration
4. assert `phi_runtime` is `NOSUPERUSER NOBYPASSRLS`, and print
   `system_capabilities`

`run_all.sh` runs `scripts/load_prompts.py` itself, right after migrating,
so the suites always start from a registry that matches `prompts/` — see
D23, and note that `test_run_engine.py` deliberately replaces the seven
specifications with stubs for the length of its run. A **deployment** has
no such safety net: `docs/OPERATIONS.md` step 6 loads them explicitly, and
step 7 refuses to call n8n ready until `load_prompts.py --check` exits 0.

---

## Running the suites

```bash
set -a; . ./.env.local; set +a
bash testing/run_all.sh
```

```powershell
powershell -ExecutionPolicy Bypass -File scripts\local_test.ps1
```

The suites connect as three different roles from one `DATABASE_URL`:
`phi_admin` for fixtures, and `phi_runtime` / `phi_practitioner` for the
isolation assertions, with each role's own password taken from
`POSTGRES_RUNTIME_PASSWORD` / `POSTGRES_PRACTITIONER_PASSWORD`. If those are
unset the DSN carries no password at all, which keeps a trust/peer setup
working; it never falls back to the admin password, because a connection
that is not the role under test proves nothing.

---

## The same path runs in CI

`.github/workflows/tests.yml` does what `local_db_setup.sh` does, against a
service container instead of this compose file: migrate, set the role
passwords through `scripts/set_role_passwords.py`, run the suites. That
script is shared rather than duplicated, so the step that decides whether
RLS is real is the same three places it happens — laptop, CI, VPS.

CI runs it three times over: on `pgvector/pgvector:pg16` (full
capability), on plain `postgres:16` (no pgvector), and on `postgres:16`
with the **contrib control files deleted from the server** — no pgvector,
no pg_trgm, no btree_gin. That third job exists because pg_trgm and
btree_gin ship in every PostgreSQL image, so no choice of image can test
their absence, and steps 12 and 13 duly shipped an ungated `similarity()`
call that killed the K1 seeder on a database without pg_trgm.

Reproduce that floor locally:

```bash
set -a; . ./.env.local; set +a
bash testing/run_bare.sh
```

It moves the extension control files aside, rebuilds the schema, asserts
every capability is recorded false, runs the suites, and puts the files
back — including on failure and on Ctrl-C. **Destructive**: it drops and
rebuilds `public`, so point it at the throwaway database only.

---

## What this is not

- **Not a backup target.** The volume is disposable by design.
- **Not for real client data.** It publishes a port and its password is a
  literal in a committed example file.
- **Not the deployment rehearsal.** The VPS stack has no published port,
  different tuning, and shares a network with n8n. Test deployment changes
  on the VPS, against `docs/OPERATIONS.md`.
