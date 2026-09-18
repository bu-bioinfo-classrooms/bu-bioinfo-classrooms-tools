#!/usr/bin/env python3
"""Register or update one assignment in <org>/classroom50/<classroom>/assignments.json.

Wraps `gh teacher assignment add` rather than writing the JSON directly. Classroom50's
contract is versioned and mirrored across Go, Python, and TypeScript -- its source is
full of "keep byte-identical" warnings -- so hand-writing its files reimplements a
contract that will drift. The CLI is the supported interface and validates as it goes.

`assignment add` replaces a same-slug entry in place, so this is idempotent.

**Registration is the seal.** `--available-from` is listing-only, not access control:
a student who guesses a slug can accept an assignment that exists. So an assignment is
registered at publish time and not before -- one that does not exist cannot be accepted,
which makes the week-long seal a property of the release process rather than a policy
students are trusted with.

Usage:
  update_classroom.py --config .classroom.yaml --set 4 [--due 2026-10-05T23:59:00-04:00] [--dry-run]
"""
import argparse
import pathlib
import random
import subprocess
import sys
import time

import yaml


def fail(msg):
    print(f"::error::{msg}", file=sys.stderr)
    sys.exit(1)


def expand(value, *, nn, n):
    return str(value).replace("{NN}", nn).replace("{N}", str(n))


def build_args(cfg, nn, n, due):
    a = cfg.get("assignment", {})
    source_dir = pathlib.Path(expand(cfg["source_dir"], nn=nn, n=n))
    argv = [
        "gh", "teacher", "assignment", "add",
        # The slug is the template repo's name (course-prefixed, e.g. bf550-ps02): the org
        # holds several courses' sets in one flat namespace, so a bare psNN collides, and a
        # re-add under a different slug creates a second entry instead of replacing the live one.
        cfg["org"], cfg["classroom"], f"{cfg['templates']}{nn}",
        "--name", expand(a.get("name", "Problem Set {N}"), nn=nn, n=n),
        "--template", f"{cfg['org']}/{cfg['templates']}{nn}",
    ]
    if a.get("description"):
        argv += ["--description", expand(a["description"], nn=nn, n=n)]
    if a.get("submission_mode"):
        argv += ["--submission-mode", a["submission_mode"]]
    if a.get("repo_visibility"):
        argv += ["--repo-visibility", a["repo_visibility"]]
    argv += ["--feedback-pr" if a.get("feedback_pr", True) else "--feedback-pr=false"]
    for pattern in a.get("allowed_files", []):
        argv += ["--allowed-files", pattern]
    for name, flag in (("tests", "--tests"), ("runtime", "--runtime")):
        rel = a.get(name)
        if not rel:
            continue
        path = source_dir / expand(rel, nn=nn, n=n)
        if not path.is_file():
            fail(f"assignment.{name} points at a missing file: {path}")
        argv += [flag, str(path)]
    if due:
        argv += ["--due", due]
    return argv


def run_with_retry(argv, attempts=4):
    """Retry on a concurrent write to the one shared classroom50 repository.

    Every course in the org writes to the same repo -- different directories, so the
    content merges, but two publishes racing on the same ref can still collide. The CLI
    does a read-modify-write against a remote ref; a bounded retry with jitter is the
    cheap correct answer, and a `concurrency:` group is not, because the callers are
    different repositories.
    """
    for attempt in range(attempts):
        r = subprocess.run(argv, capture_output=True, text=True)
        if r.returncode == 0:
            print(r.stdout.strip())
            return
        transient = any(s in (r.stderr + r.stdout).lower() for s in
                        ("is at", "non-fast-forward", "conflict", "stale", "reference update", "409"))
        if not (transient and attempt < attempts - 1):
            fail(f"gh teacher assignment add failed: {r.stderr.strip() or r.stdout.strip()}")
        delay = 2 ** attempt + random.random()
        print(f"concurrent write to classroom50, retrying in {delay:.1f}s "
              f"(attempt {attempt + 2}/{attempts})")
        time.sleep(delay)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=".classroom.yaml")
    ap.add_argument("--set", dest="set_number", type=int, required=True)
    ap.add_argument("--due")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    n = args.set_number
    nn = f"{n:02d}"
    cfg = yaml.safe_load(pathlib.Path(args.config).read_text(encoding="utf-8"))
    argv = build_args(cfg, nn, n, args.due)

    printable = " ".join(f'"{x}"' if " " in x else x for x in argv)
    print(f"would run:\n  {printable}")
    if args.dry_run:
        print("\n--dry-run: classroom50 not touched")
        return
    run_with_retry(argv)
    print(f"\nregistered {cfg['templates']}{nn} in {cfg['org']}/classroom50/{cfg['classroom']}")


if __name__ == "__main__":
    main()
