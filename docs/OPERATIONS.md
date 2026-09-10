# OPERATIONS

Deployment, security, backup and restore.

**Environment:** Hostinger VPS, India. 2 vCPU, 8 GB RAM, 100 GB disk.
n8n already running in Docker. PostgreSQL added alongside it.

This document describes the **deployment**. For a throwaway local database
to develop and run the test suites against, see `docs/LOCAL_DEV.md`; it
uses a separate compose file and changes nothing here.

---

## Deployment

PostgreSQL runs in a container on the same Docker network as n8n, with
**no published port**. n8n reaches it by hostname `phi-postgres`. Nothing
on the public internet can reach it, and neither can other host processes
unless they join the network.

```bash
# 1. Find the network n8n is already on
docker ps --format '{{.Names}}'
docker inspect <n8n-container> -f '{{json .NetworkSettings.Networks}}' | python3 -m json.tool

# 2. Configure
cp .env.example .env
openssl rand -hex 32      # for each password
nano .env                 # set N8N_NETWORK and the three role passwords

# 3. Start
docker compose up -d
docker compose ps         # wait for healthy

# 4. Migrate (admin role, from inside the container)
docker compose exec postgres bash -c \
  'psql -U phi_admin -d phi -f /database/migrations/000_extensions.sql'
# or run scripts/migrate.py with DATABASE_URL pointed at the container

# 5. Set runtime role passwords (roles are created by migration 005)
docker compose exec postgres psql -U phi_admin -d phi -c \
  "ALTER ROLE phi_runtime WITH PASSWORD 'from-your-env';"
docker compose exec postgres psql -U phi_admin -d phi -c \
  "ALTER ROLE phi_practitioner WITH PASSWORD 'from-your-env';"

# 6. LOAD THE ENGINE PROMPTS. Not optional, and not part of migrating.
#    Since D23 the prompts are ROWS: prompts/*.md is the authored form and
#    engine_prompts is what RUN_ENGINE reads, which is the only reason n8n
#    can run an engine without a copy of the repository.
#
#    A database that has been migrated and not loaded is perfectly valid
#    and completely unusable: engine_prompts is empty, and RUN_ENGINE
#    raises PromptMissing on the first call of every engine. That is
#    correct behaviour (hard rule 7 -- never substitute a stub) and a
#    miserable thing to diagnose at 2am, so do this now.
DATABASE_URL=postgresql://phi_admin:...@host:port/phi \
  python3 scripts/load_prompts.py

# 6b. LOAD THE ORCHESTRATION CONTRACT. Same reason, same class of failure.
#     Since migration 012 the control contract is a row too, and it is what
#     RUN_ENGINE validates every control block against -- the typed fields
#     n8n routes on (hard rule 5). An unloaded registry raises
#     ContractMissing rather than validating against nothing.
DATABASE_URL=postgresql://phi_admin:...@host:port/phi \
  python3 scripts/load_contracts.py

# 6c. LOAD THE HANDOFF REGISTRY. Which substantive block each engine owes,
#     per mode (D24). Without it RUN_ENGINE raises HandoffMissing rather
#     than accepting a control block as evidence that an engine reasoned.
DATABASE_URL=postgresql://phi_admin:...@host:port/phi \
  python3 scripts/load_handoffs.py

# 7. Verify, and do not skip the second half.
docker compose exec postgres psql -U phi_admin -d phi -c \
  "SELECT capability, enabled FROM system_capabilities;"

#    n8n is NOT ready until this exits 0. It asserts all seven engines have
#    an active prompt AND that each active hash matches the authored file,
#    and prints the hash of each so it can be compared against the hash
#    recorded in engine_runs later.
DATABASE_URL=postgresql://phi_admin:...@host:port/phi \
  python3 scripts/load_prompts.py --check
#    exit 0  -> READY: all 7 engine prompts active and matching prompts/
#    exit 1  -> NOT READY: names the engines with no active row, or the
#               prompts that differ from the authored files
#    exit 2  -> a file in prompts/ is missing or empty

DATABASE_URL=postgresql://phi_admin:...@host:port/phi \
  python3 scripts/load_contracts.py --check
#    exit 0  -> READY, and prints the property and required counts, which
#               are worth reading: a contract that suddenly has three
#               properties would validate almost anything
#    exit 1  -> NOT READY, or the document differs from the authored file
#    exit 2  -> the schema file is missing, unparseable, or constrains
#               nothing

DATABASE_URL=postgresql://phi_admin:...@host:port/phi \
  python3 scripts/load_handoffs.py --check
#    exit 0  -> READY, and prints what each engine owes per mode
#    exit 1  -> an engine/mode has no registered handoff
#    exit 2  -> a registered tag is not defined in its prompt, which means
#               a specification was renamed and the registry was not
```

**Whenever `prompts/*.md` or `schemas/orchestration/*.json` changes, the
matching loaders must be re-run — `load_handoffs.py` included, since it
verifies its tags against the prompts** — deploying a prompt or contract edit is a
load, not a restart. The registry is
append-only: loading changed content inserts a new version and deactivates
the old one, so the superseded text stays readable for any `engine_runs`
row that cites its hash. Reverting reactivates the stored version rather
than creating a third.

Connect from the host for admin work:
```bash
docker compose exec postgres psql -U phi_admin -d phi
```

---

## Resource allocation

2 vCPU is the binding constraint, not memory. Most work here is
API-wait rather than compute, so this matters mainly for concurrency.

| Component | Allocation |
|---|---|
| Postgres `shared_buffers` | 2 GB |
| `effective_cache_size` | 4 GB |
| `work_mem` | 16 MB |
| `maintenance_work_mem` | 512 MB |
| `max_connections` | 60 |
| Container memory limit | 4 GB |
| n8n (existing) | ~1.5 GB |

**Keep `KNOWLEDGE_MAX_CONCURRENCY` at 2–3.** Wave-1 foundation runs are
the only thing that will contend for CPU with n8n. If n8n becomes sluggish
during a foundation batch, lower it before touching anything else.

Disk is not a concern: a 1536-dim vector is ~6 KB, so 50,000 embedded
chunks is roughly 300 MB. Watch `knowledge/inbox` if large book PDFs
accumulate.

---

## Database roles

Three roles, deliberately separated. See `docs/DECISIONS.md` D-RLS.

| Role | Purpose | Runtime use |
|---|---|---|
| `phi_admin` | Owns schema, runs migrations | No |
| `phi_runtime` | n8n workflows and engines | Yes — RLS enforced, default deny |
| `phi_practitioner` | Review surface | Read-only, cross-client |

`phi_runtime` is `NOSUPERUSER NOBYPASSRLS`. Every client-scoped table is
`FORCE ROW LEVEL SECURITY`, so even the table owner is subject. **n8n must
connect as `phi_runtime`, never as `phi_admin`** — connecting as the owner
would make RLS cosmetic.

### Setting client scope

Client scope is **transaction-local**, so a pooled connection cannot carry
Client A's context into a later Client B query.

```sql
BEGIN;
SELECT set_client_scope('<client-uuid>');
-- every query in this transaction sees only that client
COMMIT;
```

With no scope set, client-scoped tables return **zero rows**, not all rows.
A query that forgets its `client_id` filter fails safe.

Verify after any change to roles or policies:
```bash
python3 testing/test_case_events.py     # 34 checks, isolation included
```

---

## Data residency

Database and VPS are in India. **Model inference is not.**

RLS and VPS location protect data at rest. They do not cover what leaves in
a prompt. Engine calls send clinical content to the model provider's
infrastructure outside India.

Mitigations, in order of value:

1. **Strip identity from engine payloads.** Engines need clinical facts and
   `client_id`; they do not need names. The schema already separates
   `clients.display_name` from clinical data. `STRIP_IDENTITY_FROM_ENGINE_PAYLOADS=true`
   is the default and should stay on.
2. **Review the provider's data processing terms** before production use,
   particularly retention and training-use settings.
3. **Record the decision.** Under India's DPDP Act this is a deliberate
   processing choice, not a default. Whatever is decided, write it down.

Knowledge-library content is not client data and carries no such
constraint.

---

## Backups

**A VPS has no backups by default.** This is the single most likely way to
lose the entire project.

`scripts/backup.sh` runs a nightly encrypted dump. Add to root's crontab:

```
30 2 * * * /opt/phi/scripts/backup.sh >> /var/log/phi-backup.log 2>&1
```

What it does:
- `pg_dumpall --roles-only --no-role-passwords` — **the roles**
- `pg_dump -Fc` (custom format, compressed, restorable selectively)
- GPG-encrypts both to `BACKUP_GPG_RECIPIENT`
- Copies off the VPS to `BACKUP_REMOTE_TARGET`
- Prunes local copies past `BACKUP_RETENTION_DAYS`
- **Exits non-zero on failure** so cron mail surfaces it

**Two files, and they travel together.** `pg_dump` dumps one database;
roles are cluster-wide and are *not* in it. A database dump on its own
restores the data and none of the access controls — measured on the
2026-09-10 drill: 298 errors, every one of the 52 RLS policies among them.
Keep the `.roles.sql` beside its `.dump`.

The roles file carries **no passwords** by design, so a leaked backup is
client data to protect rather than client data plus the keys to it.
Passwords come from `.env` at restore time, exactly as at first install.

A backup that stays on the same VPS is not a backup. If the VPS is lost,
so is the dump.

---

## Restore — test this once, before you need it

An untested backup is not a backup. Run this drill after the first
successful nightly dump, and again after any schema change that matters.

```bash
# 1. Decrypt BOTH files
gpg --decrypt backups/phi-2026-09-09.dump.gpg      > /tmp/restore.dump
gpg --decrypt backups/phi-2026-09-09.roles.sql.gpg > /tmp/restore.roles.sql

# 2. Restore into a SCRATCH database, never over the live one.
#    ENCODING MUST MATCH. A database created with default initdb settings
#    can come up SQL_ASCII, and then psycopg returns text columns as BYTES:
#    migrate.py decides applied migrations are pending and dies on a
#    duplicate key, and set_role_passwords.py raises a TypeError. The data
#    is intact underneath, but every tool that touches it misbehaves.
#    scripts/migrate.py now refuses to run on a non-UTF8 database.
docker compose exec postgres psql -U phi_admin -d postgres -c \
  "CREATE DATABASE phi_restore_test OWNER phi_admin \
     ENCODING 'UTF8' LC_COLLATE 'C' LC_CTYPE 'C' TEMPLATE template0;"

# 2a. ROLES FIRST, on a machine that does not already have them.
#     Skipped on the live VPS where they exist; REQUIRED on a rebuild.
#     Without this every GRANT and every CREATE POLICY fails and you get a
#     database with all the data and none of the access controls.
docker compose exec -T postgres psql -U phi_admin -d postgres < /tmp/restore.roles.sql

docker compose exec -T postgres pg_restore -U phi_admin -d phi_restore_test < /tmp/restore.dump
# pg_restore must exit 0 and print NOTHING. Errors here are not cosmetic.

# 3. Verify it is actually usable, not merely present
docker compose exec postgres psql -U phi_admin -d phi_restore_test -c "
  SELECT count(*) AS migrations FROM schema_migrations;
  SELECT count(*) AS clients FROM clients;
  SELECT count(*) AS strategies FROM strategies;
  SELECT count(*) AS policies FROM pg_policies WHERE schemaname='public';
"

# 4. Confirm RLS survived the restore
docker compose exec postgres psql -U phi_admin -d phi_restore_test -c "
  SELECT relname, relrowsecurity, relforcerowsecurity
    FROM pg_class WHERE relname IN ('client_labs','case_events');
"

# 5. Set the role passwords from .env, as at first install
DATABASE_URL=... python3 scripts/set_role_passwords.py

# 5b. The prompt registry comes back WITH the dump -- engine_prompts is an
#     ordinary table, so pg_dump carried its rows and their hashes. Verify
#     that rather than assuming it, because a restore from a backup taken
#     before migration 010 will have no such table at all, and a restore
#     from a machine whose prompts/ had drifted will disagree with this
#     checkout.
DATABASE_URL=...phi_restore_test python3 scripts/load_prompts.py --check
DATABASE_URL=...phi_restore_test python3 scripts/load_contracts.py --check
DATABASE_URL=...phi_restore_test python3 scripts/load_handoffs.py --check
#     exit 0 -> the restored registry matches prompts/ in this checkout
#     exit 1 -> it does not. Read the output before loading over it: the
#               restored rows are what produced every engine_runs.prompt_hash
#               in this database, and superseding them is a deliberate act.

# 6. THE REAL TEST: is it usable, or merely present?
#    Counts prove nothing about whether triggers, constraints and policies
#    survived. Run the suite against the restored database.
DATABASE_URL=postgresql://phi_admin:...@host:port/phi_restore_test \
  bash testing/run_all.sh
# EVERY suite must pass, and migrations must report "Up to date"
# rather than trying to re-apply. run_all.sh exits non-zero if any suite
# fails; read the exit code, do not read the last line and hope.

# 7. Clean up
docker compose exec postgres dropdb -U phi_admin phi_restore_test
rm /tmp/restore.dump /tmp/restore.roles.sql
```

Record the date of the last successful restore drill in `PROGRESS.md`.

### Rehearsing a full rebuild

The drill above restores onto a machine that still has its roles. The
disaster it is insuring against does not. To rehearse that, restore onto a
cluster where `phi_runtime` and `phi_practitioner` do **not** exist and
follow step 2a. If `pg_restore` reports errors mentioning a role that does
not exist, the roles file was not applied first — the data will land and
the access controls will not.

### Rebuilding from the repository, with no backup

The other disaster: the database is gone and there is nothing to restore.
The repository can rebuild an empty one, and the sequence is longer than
`migrate.py` by exactly one step that is easy to forget:

```bash
python3 scripts/migrate.py             # schema
python3 scripts/set_role_passwords.py  # roles
python3 scripts/load_prompts.py        # THE ENGINE SPECIFICATIONS (D23)
python3 scripts/load_contracts.py      # THE ORCHESTRATION CONTRACT (D23)
python3 scripts/load_handoffs.py       # WHICH HANDOFF EACH ENGINE OWES (D24)
python3 scripts/seed_ontology.py       # K1 concept dictionary, if wanted
python3 scripts/load_prompts.py --check   # all three must exit 0
python3 scripts/load_contracts.py --check #   before n8n is
python3 scripts/load_handoffs.py --check  #   considered ready
bash testing/run_all.sh                # prove it, do not assume it
```

Client data is **not** recoverable this way and never was; this rebuilds
the machine, not the record. What it does mean is that a lost prompt
registry is not a crisis: `prompts/*.md` is the authored form and is in
version control, so the registry can always be rebuilt from it. Rows for
superseded versions that no longer exist in the checkout cannot, which is
why the dump is still the primary path.

---

## Monitoring

```sql
-- Cost by operation. Watch MERGE_DECISION: if cost per new card climbs
-- with library size, deterministic dedup is not filtering enough before
-- the LLM call.
SELECT * FROM v_cost_by_operation WHERE day > current_date - 7;

-- Engine health
SELECT * FROM v_engine_run_health;

-- Failures never lost silently
SELECT job_type, count(*) FROM dead_letter_jobs WHERE NOT resolved GROUP BY 1;

-- Wave-1 progress
SELECT * FROM v_knowledge_floors;
SELECT * FROM v_domain_readiness WHERE is_core_domain;

-- Practitioner queue depth
SELECT count(*) FROM v_review_queue;

-- Concept escalations (capped by CONCEPT_ESCALATION_WEEKLY_CAP)
SELECT count(*) FROM v_concept_escalation_queue;
```

Disk and container health:
```bash
df -h
docker stats --no-stream
docker compose logs --tail=50 postgres
```

---

## Log hygiene

`log_statement=none` and `log_min_duration_statement=2000` are set in
compose: slow queries are logged, statement text is not. Engine payloads
and client data must never reach ordinary logs.

On the n8n side, disable success-execution payload retention for these
workflows. Error retention is fine and useful.

---

## Upgrades

Postgres major upgrades need a dump-and-restore, not an image bump. Do a
full restore drill into a scratch database on the new version before
switching. `pgvector/pgvector:pg16` is pinned deliberately — do not move to
`latest`.
