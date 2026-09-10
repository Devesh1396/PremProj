#!/usr/bin/env python3
"""Every suite must degrade to a NAMED skip when an optional dependency is absent.

CLAUDE.md **V3**. This is the assertion that makes the rule a mechanism
rather than a habit, and it exists because the habit failed three times:

| | what was missing | what the suite did instead of skipping |
|---|---|---|
| `pg_trgm` | the extension | called `similarity()` and died |
| `ajv` | the node module | indexed `'valid'` on an error dict |
| `MODEL_EMBEDDING` | the env var | raised `BadVector` halfway through |

Each was fixed where it was found, and CI stayed green throughout, because
CI configures all three. A suite that only passes where an optional
dependency happens to be present is not testing the configuration it claims
to support — and the practitioner's VPS is exactly that configuration:
`MODEL_EMBEDDING` is unset there on purpose.

### How it works

For each optional env var in `preflight.OPTIONAL_ENV`, this finds the
suites that depend on it — the suite's own text, or any `scripts/` module
it imports, transitively — and runs each one TWICE: once normally, once
with the variable removed from the environment. Then:

* the degraded run must **exit 0**. An exception is the failure this exists
  to catch.
* every SKIP line the degraded run prints that the baseline did not must
  **name the removed dependency**. A suite that goes quiet for some other
  reason has stopped testing something without saying which thing, which is
  the same failure wearing a disguise.

The baseline half is what makes the second assertion mean anything: it is
the real suite's real output, not a list of skips written here (V2).

### What this does NOT cover, and says so

Optional **extensions** cannot be removed from a running database by an
env var — it takes rebuilding the schema without them. `testing/run_bare.sh`
does that, for `pgvector`, `pg_trgm`, `btree_gin` and `ajv`. This suite
reports that boundary rather than implying it covers everything.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "testing"))

import preflight

FAILS: list[str] = []
SUITES = sorted(p for p in (REPO / "testing").glob("test_*.py")
                if p.name != "test_optional_deps.py")
SCRIPTS = {p.stem: p.read_text(encoding="utf-8")
           for p in (REPO / "scripts").glob("*.py")}

IMPORT = re.compile(r"^\s*(?:from\s+([A-Za-z_][\w]*)\s+import|import\s+([A-Za-z_][\w]*))",
                    re.M)


def check(name: str, condition: bool, detail: str = "") -> None:
    if condition:
        print(f"  PASS  {name}")
    else:
        print(f"  FAIL  {name}  {detail}")
        FAILS.append(name)


def imports_of(text: str) -> set[str]:
    """Local `scripts/` modules a file imports. Third-party names are
    simply absent from SCRIPTS and fall away."""
    found = set()
    for a, b in IMPORT.findall(text):
        name = a or b
        if name in SCRIPTS:
            found.add(name)
    return found


def reachable(text: str) -> set[str]:
    """Every `scripts/` module reachable from a file, transitively.

    Walked rather than listed: a registry of "suites that use embeddings"
    goes stale the first time somebody adds one, which is precisely how
    this class of gap re-forms.
    """
    seen: set[str] = set()
    queue = list(imports_of(text))
    while queue:
        module = queue.pop()
        if module in seen:
            continue
        seen.add(module)
        queue.extend(imports_of(SCRIPTS[module]) - seen)
    return seen


def affected_by(token: str) -> list[Path]:
    """Suites whose own text, or whose imported modules, mention `token`."""
    out = []
    for suite in SUITES:
        text = suite.read_text(encoding="utf-8")
        if token in text or any(token in SCRIPTS[m] for m in reachable(text)):
            out.append(suite)
    return out


def run(suite: Path, env: dict) -> tuple[int, str]:
    proc = subprocess.run([sys.executable, str(suite)], env=env,
                          capture_output=True, text=True, timeout=1800)
    return proc.returncode, proc.stdout + proc.stderr


def skip_lines(output: str) -> set[str]:
    return {line.strip() for line in output.splitlines()
            if line.startswith(preflight.SKIP_MARK)}


def main() -> int:
    print("\nthe skip marker is one thing, shared")
    check("preflight defines the marker the floors grep for",
          preflight.SKIP_MARK.strip() == "SKIP", repr(preflight.SKIP_MARK))
    check("at least one optional env var is registered",
          bool(preflight.OPTIONAL_ENV), str(preflight.OPTIONAL_ENV))
    check("and every registered one explains what its absence costs",
          all(len(v) > 40 for v in preflight.OPTIONAL_ENV.values()))

    print("\npreflight is the only way a suite may skip")
    # Static, and deliberately so: the behavioural half below can only test
    # the dependencies that are REGISTERED, and a suite hand-rolling a skip
    # for an unregistered one would never be exercised. Grepping for the
    # literal catches it the moment it is written.
    offenders = []
    for suite in SUITES:
        for number, line in enumerate(
                suite.read_text(encoding="utf-8").splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith(("print(", 'print(f"')) and "SKIP" in stripped:
                offenders.append(f"{suite.name}:{number}")
    check("no suite hand-writes a SKIP line",
          not offenders,
          ", ".join(offenders[:6]) + " -- use preflight.skip()")

    for name in sorted(preflight.OPTIONAL_ENV):
        print(f"\n{name} removed")

        if not preflight.env(name):
            preflight.skip(
                name,
                "it is already unset in this environment, so the degraded "
                "run and the baseline would be the same run and the "
                "comparison would prove nothing (V2). Set it and re-run.")
            continue

        suites = affected_by(name)
        check(f"{name} is traced to the suites that depend on it",
              bool(suites), "no suite reaches it")
        print(f"        {', '.join(s.stem for s in suites)}")

        degraded_env = {k: v for k, v in os.environ.items() if k != name}
        for suite in suites:
            base_rc, base_out = run(suite, dict(os.environ))
            if base_rc != 0:
                # The baseline is broken for an unrelated reason. Saying so
                # is the honest outcome; asserting anything about the
                # degraded run would be measuring the breakage.
                preflight.skip(
                    f"{suite.stem} (baseline)",
                    "it does not pass with the dependency present, so its "
                    "degraded behaviour cannot be attributed to the removal.")
                continue

            rc, out = run(suite, degraded_env)
            check(f"{suite.stem} exits 0 without {name}", rc == 0,
                  out.strip().splitlines()[-1] if out.strip() else "no output")

            new_skips = skip_lines(out) - skip_lines(base_out)
            unnamed = [line for line in new_skips if name not in line]
            check(f"{suite.stem}'s new skips name {name}",
                  not unnamed, "; ".join(sorted(unnamed))[:200])

    print("\nthe boundary this suite does not cross")
    print(f"{preflight.SKIP_MARK}optional EXTENSIONS "
          f"({', '.join(sorted(preflight.OPTIONAL_CAPABILITY))}) and the node "
          "module ajv cannot be removed by an environment variable.")
    print("        testing/run_bare.sh rebuilds the schema without them and "
          "asserts the same property there.")

    print()
    if FAILS:
        print(f"FAILED: {len(FAILS)}")
        for f in FAILS:
            print(f"  - {f}")
        return 1
    print("test_optional_deps: all checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
