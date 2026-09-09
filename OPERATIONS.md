# OPERATIONS

Deployment, security, backup and restore.

**Environment:** Hostinger VPS, India. 2 vCPU, 8 GB RAM, 100 GB disk.
n8n already running in Docker. PostgreSQL added alongside it.

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

# 6. Verify
docker compose exec postgres psql -U phi_admin -d phi -c \
  "SELECT capability, enabled FROM system_capabilities;"
```

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
- `pg_dump -Fc` (custom format, compressed, restorable selectively)
- GPG-encrypts to `BACKUP_GPG_RECIPIENT`
- Copies off the VPS to `BACKUP_REMOTE_TARGET`
- Prunes local copies past `BACKUP_RETENTION_DAYS`
- **Exits non-zero on failure** so cron mail surfaces it

A backup that stays on the same VPS is not a backup. If the VPS is lost,
so is the dump.

---

## Restore — test this once, before you need it

An untested backup is not a backup. Run this drill after the first
successful nightly dump, and again after any schema change that matters.

```bash
# 1. Decrypt
gpg --decrypt backups/phi-2026-09-09.dump.gpg > /tmp/restore.dump

# 2. Restore into a SCRATCH database, never over the live one
docker compose exec postgres createdb -U phi_admin phi_restore_test
docker compose exec -T postgres pg_restore -U phi_admin -d phi_restore_test < /tmp/restore.dump

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

# 5. Clean up
docker compose exec postgres dropdb -U phi_admin phi_restore_test
rm /tmp/restore.dump
```

Record the date of the last successful restore drill in `PROGRESS.md`.

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
