#!/usr/bin/env python3
"""Publish one problem set from a course's instructor repo to its Classroom50 template repo.

The instructor repo is the source; the template repo is an output, like a compiled
artifact. Nothing is ever hand-edited on the far side, so this script is the only
way material reaches students.

Four gates, in order, and any one of them refuses the publish:

  1. the course's own gates (notebook locks, tool invariants) -- declared in
     .classroom.yaml because they belong to the course, not to this tooling
  2. the whitelist -- only files named in `publish:` are copied, so a new file in
     the source directory is private by default
  3. the deny-markers -- a scan of the assembled payload for instructor vocabulary,
     so a mis-edited whitelist still cannot leak a sidecar
  4. --dry-run -- prints exactly what would be pushed and stops

Usage:
  publish_set.py --config .classroom.yaml --set 4 [--dry-run]
"""
import argparse
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

import yaml


def fail(msg):
    print(f"::error::{msg}", file=sys.stderr)
    sys.exit(1)


def expand(value, *, nn, n=None, source_dir=None):
    out = value.replace("{NN}", nn)
    if n is not None:
        out = out.replace("{N}", str(n))
    if source_dir is not None:
        out = out.replace("{source_dir}", str(source_dir))
    return out


def git(args, cwd, check=True, quiet=False):
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode != 0:
        fail(f"git {' '.join(args)} failed: {r.stderr.strip()}")
    if not quiet and r.stdout.strip():
        print(r.stdout.strip())
    return r


def run_gates(gates, *, nn, n, source_dir):
    for raw in gates:
        cmd = expand(raw, nn=nn, n=n, source_dir=source_dir)
        print(f"gate: {cmd}")
        if subprocess.run(cmd, shell=True).returncode != 0:
            fail(f"gate failed, refusing to publish: {cmd}")


def assemble(cfg, nn, n, staging):
    """Copy exactly the whitelisted files. Never a glob, never a directory walk."""
    source_dir = pathlib.Path(expand(cfg["source_dir"], nn=nn, n=n))
    if not source_dir.is_dir():
        fail(f"source_dir does not exist: {source_dir}")
    copied = []
    for pattern in cfg["publish"]:
        name = expand(pattern, nn=nn, n=n, source_dir=source_dir)
        if name.endswith("autograde.yaml"):
            fail("the autograde shim is written by `gh student accept`; a template "
                 "copy is clobbered by submit's .github/ re-fetch and breaks grading")
        src = source_dir / name
        if not src.is_file():
            fail(f"whitelisted file is missing: {src}")
        dest = staging / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        copied.append(name)
    return source_dir, copied


def scan_deny(staging, markers):
    """Refuse on instructor vocabulary anywhere in the payload, notebook JSON included."""
    hits = []
    for path in sorted(staging.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for marker in markers:
            if re.search(re.escape(marker), text, re.I):
                hits.append(f"{path.relative_to(staging)}: {marker!r}")
    if hits:
        fail("deny-marker found in the publish payload:\n  " + "\n  ".join(hits))


def ensure_template_repo(target, visibility):
    """Create the template repo if absent, and make sure is_template is set.

    Without the flag, `gh student accept` fails with a cross-org visibility message
    that never names the real cause.
    """
    r = subprocess.run(["gh", "repo", "view", target, "--json", "isTemplate"],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print(f"creating {target}")
        subprocess.run(
            ["gh", "repo", "create", target, f"--{visibility}", "--description",
             "Classroom50 assignment template - generated from the instructor repo, do not edit"],
            check=True)
    if r.returncode != 0 or not json.loads(r.stdout or "{}").get("isTemplate"):
        subprocess.run(["gh", "api", "-X", "PATCH", f"repos/{target}", "-F", "is_template=true"],
                       check=True, stdout=subprocess.DEVNULL)
        print(f"{target}: is_template set")


def push(staging, target, branch, set_number, visibility):
    """Replace the template's tree with exactly the payload, preserving history.

    The template is an output, not an accumulation. History survives because each
    publish commits on top of the last: `reset --soft` re-parents without restoring
    the old tree, so a file dropped from the whitelist disappears from the template.

    Only future accepts see it. `gh student accept` copies at accept time, and submit
    re-fetches only .gitignore and .github/ -- a released notebook cannot be fixed
    by republishing.
    """
    ensure_template_repo(target, visibility)
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        fail("GH_TOKEN or GITHUB_TOKEN must be set to push")

    work = staging.parent / "work"
    shutil.copytree(staging, work)
    git(["init", "-q", "-b", branch], work)
    git(["remote", "add", "origin",
         f"https://x-access-token:{token}@github.com/{target}.git"], work)
    git(["config", "user.name", "classroom50-publisher"], work)
    git(["config", "user.email", "noreply@github.com"], work)

    if git(["fetch", "-q", "--depth", "1", "origin", branch],
           work, check=False, quiet=True).returncode == 0:
        git(["reset", "-q", "--soft", "FETCH_HEAD"], work)

    git(["add", "-A"], work)
    if git(["diff", "--cached", "--quiet"], work, check=False, quiet=True).returncode == 0:
        print("no change since the last publish")
        return git(["rev-parse", "HEAD"], work, quiet=True).stdout.strip()

    git(["commit", "-q", "-m", f"Publish set {set_number} from the instructor repo"], work)
    git(["push", "-q", "origin", f"HEAD:{branch}"], work)
    return git(["rev-parse", "HEAD"], work, quiet=True).stdout.strip()


def record_published(cfg, nn, n, target, sha):
    """Write `published: <target>@<sha>` into the set's sidecar frontmatter.

    The version pinning a submodule would have given, without a second copy of the
    notebook in the tree.
    """
    rel = cfg.get("sidecar")
    if not rel:
        return
    path = pathlib.Path(expand(rel, nn=nn, n=n))
    if not path.is_file():
        print(f"no sidecar at {path} - skipping the published: record")
        return
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        fail(f"{path} has no frontmatter to record into")
    head, body = text[3:].split("---", 1)
    kept = [l for l in head.strip("\n").splitlines() if not l.startswith("published:")]
    line = f"published: {target}@{sha}"
    path.write_text("---\n" + "\n".join(kept + [line]) + "\n---" + body, encoding="utf-8")
    print(f"recorded {line} in {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=".classroom.yaml")
    ap.add_argument("--set", dest="set_number", type=int, required=True)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not 1 <= args.set_number <= 99:
        fail(f"--set out of range: {args.set_number}")
    n = args.set_number
    nn = f"{n:02d}"
    cfg = yaml.safe_load(pathlib.Path(args.config).read_text(encoding="utf-8"))

    target = f"{cfg['org']}/{cfg['templates']}{nn}"
    branch = cfg.get("branch", "main")
    visibility = cfg.get("assignment", {}).get("repo_visibility", "private")
    source_dir = pathlib.Path(expand(cfg["source_dir"], nn=nn, n=n))

    run_gates(cfg.get("gates", []), nn=nn, n=n, source_dir=source_dir)

    with tempfile.TemporaryDirectory() as tmp:
        staging = pathlib.Path(tmp) / "payload"
        staging.mkdir()
        source_dir, copied = assemble(cfg, nn, n, staging)
        scan_deny(staging, cfg.get("deny_markers", []))

        print(f"\nwould publish to {target}:")
        for name in copied:
            print(f"  {name}  ({(staging / name).stat().st_size} bytes)")
        if args.dry_run:
            print("\n--dry-run: nothing pushed")
            return

        sha = push(staging, target, branch, n, visibility)
        print(f"\npublished {target}@{sha}")
        record_published(cfg, nn, n, target, sha)


if __name__ == "__main__":
    main()
