#!/usr/bin/env python3
"""Apply SQL migrations in order, exactly once.

Each migration runs in its own transaction and is recorded with a checksum.
An already-applied file whose contents have changed is a hard error: edit
history in place and the database silently diverges from the repo.

Usage:
    python scripts/migrate.py                 # apply pending
    python scripts/migrate.py --status        # show state, apply nothing
    python scripts/migrate.py --dry-run       # list what would run
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

try:
    import psycopg
except ImportError:
    sys.exit("psycopg (v3) required:  pip install 'psycopg[binary]'")

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "database" / "migrations"

BOOTSTRAP = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    filename    text PRIMARY KEY,
    checksum    text        NOT NULL,
    applied_at  timestamptz NOT NULL DEFAULT now(),
    duration_ms integer
);
"""


def dsn() -> str:
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    return (
        f"host={os.environ.get('POSTGRES_HOST', 'localhost')} "
        f"port={os.environ.get('POSTGRES_PORT', '5432')} "
        f"dbname={os.environ.get('POSTGRES_DB', 'phi')} "
        f"user={os.environ.get('POSTGRES_USER', 'phi')} "
        f"password={os.environ.get('POSTGRES_PASSWORD', '')}"
    )


def checksum(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"), key=lambda p: p.name)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    files = migration_files()
    if not files:
        print(f"No migrations found in {MIGRATIONS_DIR}")
        return 1

    with psycopg.connect(dsn(), autocommit=True) as conn:
        conn.execute(BOOTSTRAP)
        applied = {
            row[0]: row[1]
            for row in conn.execute(
                "SELECT filename, checksum FROM schema_migrations"
            ).fetchall()
        }

        pending = []
        for path in files:
            sql = path.read_text()
            digest = checksum(sql)
            if path.name in applied:
                if applied[path.name] != digest:
                    print(
                        f"FAIL {path.name}: applied checksum {applied[path.name]} "
                        f"!= file checksum {digest}.\n"
                        "     An applied migration was edited. Add a new migration "
                        "instead of changing history."
                    )
                    return 2
                if args.status:
                    print(f"  ok      {path.name}")
            else:
                pending.append((path, sql, digest))
                if args.status or args.dry_run:
                    print(f"  PENDING {path.name}")

        if args.status or args.dry_run:
            print(f"\n{len(applied)} applied, {len(pending)} pending")
            return 0

        if not pending:
            print("Up to date.")
            return 0

        for path, sql, digest in pending:
            print(f"applying {path.name} ...", end=" ", flush=True)
            # Each migration is atomic on its own so a mid-run failure
            # leaves earlier migrations committed and this one absent.
            with psycopg.connect(dsn()) as run_conn:
                with run_conn.cursor() as cur:
                    start = run_conn.execute("SELECT clock_timestamp()").fetchone()[0]
                    try:
                        cur.execute(sql)
                    except Exception as exc:
                        run_conn.rollback()
                        print("FAILED")
                        print(f"  {type(exc).__name__}: {exc}")
                        return 3
                    end = run_conn.execute("SELECT clock_timestamp()").fetchone()[0]
                    ms = int((end - start).total_seconds() * 1000)
                    cur.execute(
                        "INSERT INTO schema_migrations (filename, checksum, duration_ms) "
                        "VALUES (%s, %s, %s)",
                        (path.name, digest, ms),
                    )
                run_conn.commit()
            print(f"ok ({ms} ms)")

        print(f"\n{len(pending)} migration(s) applied.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
