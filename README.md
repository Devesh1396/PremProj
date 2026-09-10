# Prem Health Intelligence

Internal AI-assisted nutrition / functional-health operating system for a
single Certified Functional Nutritionist.

The practitioner remains the professional decision-maker. The software
removes repetitive cognitive labour: analysis, research, memory,
comparison, implementation design, documentation, follow-up reasoning and
knowledge retrieval.

## Stack

- **n8n** — orchestration
- **PostgreSQL** (+ pgvector, optional) — persistent client state and knowledge
- **OpenAI-compatible LLM API** — reasoning, extraction, research
- **Engines 1–7** — specialist reasoning specifications in `/prompts`

Claude Code builds this. It is not part of the runtime.

## Quick start

```bash
cp .env.example .env        # fill in secrets
openssl rand -hex 32        # for N8N_ENCRYPTION_KEY

docker compose up -d
docker compose ps           # wait for postgres healthy

pip install 'psycopg[binary]'
export $(grep -v '^#' .env | xargs)
export POSTGRES_HOST=localhost

python scripts/migrate.py --status
python scripts/migrate.py
python scripts/load_prompts.py     # engine specifications into the DB (D23)
python scripts/load_contracts.py   # orchestration contract into the DB (D23)
bash testing/run_all.sh
```

`load_prompts.py` is not optional and is not part of migrating. Since D23
the seven engine specifications are **rows**: `prompts/*.md` is the
authored form and `engine_prompts` is what `RUN_ENGINE` reads, which is
what lets n8n run an engine without a copy of this repository. A migrated
database with an empty registry is valid and unusable — every engine
raises `PromptMissing` on its first call. `load_prompts.py --check` exits
0 only when all seven are active and match the files. `load_contracts.py`
does the same for the control contract, which `RUN_ENGINE` validates every
control block against and n8n routes on.

n8n at http://localhost:5678

## Layout

```
database/migrations/   ordered SQL, applied once, checksum-guarded
prompts/               engine specifications (Markdown, versioned)
schemas/orchestration/ strict JSON Schema for control-flow fields
schemas/engine_outputs/ engine output contracts
n8n/workflows/         exported workflows
knowledge/inbox/       drop books and documents here for ingestion
knowledge/seed/        recovered reference material (E7 foundation curriculum)
testing/               functional tests
docs/                  ARCHITECTURE, DATABASE, WORKFLOWS, KNOWLEDGE_FACTORY,
                       OPERATIONS, RESTORE, TESTING
```

## Migrations

Applied once, in filename order, each in its own transaction, recorded with
a checksum. **Editing an applied migration is a hard error.** Add a new one.

`norm_phrase()` backs STORED generated columns. Changing it requires a
migration that also rewrites those columns and rebuilds their indexes.

## Optional extensions

pgvector, pg_trgm and btree_gin are all optional. Each is attempted at
migration time and recorded in `system_capabilities`. Without pgvector,
retrieval runs on metadata filters + full-text + trigram; enable it later
without database redesign.

```sql
SELECT * FROM system_capabilities;
```

## Security

Personal health information. Secrets via environment only, never committed.
Ports bound to loopback. n8n success-execution payloads not retained.
Knowledge data kept logically separate from identifiable client data.
Practice-derived knowledge uses de-identified aggregates.
