#!/usr/bin/env python3
"""Set the runtime role passwords, then prove the roles are constrained.

docs/OPERATIONS.md step 5. Migration 005 creates phi_runtime and
phi_practitioner with NO password; something has to set one afterwards, and
that step is identical on the VPS, on a laptop and in CI. It lives here
rather than being written three times in two shell dialects.

Two things it does that an inline `psql -c` cannot do safely:

  * quotes the password as a SQL literal instead of interpolating it
    through a shell. A password from `openssl rand -hex 32` is safe by
    luck; one a human chose containing a quote is not, and the failure is
    either a syntax error or a role whose password is not what anyone
    thinks it is.
  * verifies afterwards. phi_runtime being NOSUPERUSER NOBYPASSRLS is what
    makes RLS real rather than cosmetic, so it is checked here and exits
    non-zero rather than being assumed from the migration.

Reads DATABASE_URL (admin) plus POSTGRES_RUNTIME_USER / _PASSWORD and
POSTGRES_PRACTITIONER_USER / _PASSWORD.
"""

from __future__ import annotations

import os
import sys

import psycopg
from psycopg import sql

ROLES = [
    ("POSTGRES_RUNTIME_USER", "phi_runtime", "POSTGRES_RUNTIME_PASSWORD"),
    ("POSTGRES_PRACTITIONER_USER", "phi_practitioner", "POSTGRES_PRACTITIONER_PASSWORD"),
]


def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL is not set. See docs/LOCAL_DEV.md or docs/OPERATIONS.md.")
        return 2

    conn = psycopg.connect(dsn, autocommit=True)

    for user_var, default_role, password_var in ROLES:
        role = os.environ.get(user_var) or default_role
        password = os.environ.get(password_var, "")
        if not password:
            print(f"  skip  {role}: {password_var} is empty")
            continue
        conn.execute(
            sql.SQL("ALTER ROLE {} WITH PASSWORD {}").format(
                sql.Identifier(role), sql.Literal(password)))
        print(f"  set   {role}")

    print()
    rows = conn.execute(
        """select rolname, rolcanlogin, rolsuper, rolbypassrls,
                  rolcreatedb, rolcreaterole
             from pg_roles
            where rolname in ('phi_admin','phi_runtime','phi_practitioner')
            order by rolname"""
    ).fetchall()
    print(f"  {'role':<18}{'login':<8}{'super':<8}{'bypassrls':<12}"
          f"{'createdb':<11}createrole")
    for name, login, super_, bypass, createdb, createrole in rows:
        print(f"  {name:<18}{str(login):<8}{str(super_):<8}{str(bypass):<12}"
              f"{str(createdb):<11}{createrole}")

    # The property the whole security model rests on. A runtime role that
    # can bypass RLS makes every policy in migration 005 decorative.
    runtime = conn.execute(
        "select rolsuper, rolbypassrls from pg_roles where rolname='phi_runtime'"
    ).fetchone()
    if runtime is None:
        print("\nFAIL: phi_runtime does not exist. Run the migrations first.")
        return 1
    if runtime[0] or runtime[1]:
        print(f"\nFAIL: phi_runtime is superuser={runtime[0]} "
              f"bypassrls={runtime[1]}. It must be NOSUPERUSER NOBYPASSRLS.")
        return 1
    print("\nok: phi_runtime is NOSUPERUSER NOBYPASSRLS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
