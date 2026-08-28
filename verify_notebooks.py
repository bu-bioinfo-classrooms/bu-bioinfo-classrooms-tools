#!/usr/bin/env python3
"""Execute every authored set's notebook twice -- release-checklist item 1.

Once with the reference implementation pasted into the empty student cell, so every
scenario passes. Once with an arbitrarily BROKEN implementation, so the PROVIDED
scenarios fail. **A provided scenario that cannot fail is not a test**, and that is
discovered only by breaking the code under it -- not by reading.

**broken.py is NOT the planted defect.** plant-uncertainty says to prefer defects that
survive the obvious check -- the PTC dominance bug passes both boundary scenarios and an
invariant, which is exactly why it teaches. Feed that here and this check reports a
failure that is really the design working. broken.py is obviously wrong (a stub returning
a constant will do); its only job is to prove the provided scenarios are live wiring.
The planted defect is a third thing and lives in impl_ours.py, which IS released.

Both implementations live beside the notebook and are never published:

    assignments/psNN/.verify/reference.py
    assignments/psNN/.verify/broken.py

That is strictly better than the rulebook's older "keep it in the instructor notes",
which is prose and unparseable: it makes a sidecar's [verified] numbers reproducible
rather than historical. A set with no .verify/ directory is skipped with a warning --
the notebook still gets a lock check elsewhere, but its numbers are unverified.

Usage:
  verify_notebooks.py --config .classroom.yaml [--set N]
"""
import argparse
import json
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


def student_cell(nb):
    """The one student code cell holding the %%writefile impl -- where code goes."""
    for cell in nb["cells"]:
        if "student" in (cell["metadata"].get("tags") or []) and \
                "%%writefile impl.py" in "".join(cell["source"]):
            return cell
    return None


def execute(nb_path, impl_path, workdir):
    """Run the notebook with impl_path pasted into the student cell. Returns pytest output."""
    import nbformat
    from nbclient import NotebookClient

    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    cell = student_cell(nb)
    if cell is None:
        fail(f"{nb_path}: no student cell containing `%%writefile impl.py`")
    body = impl_path.read_text(encoding="utf-8")
    cell["source"] = ("%%writefile impl.py\n" + body).splitlines(keepends=True)

    run_path = workdir / nb_path.name
    run_path.write_text(json.dumps(nb), encoding="utf-8")
    doc = nbformat.read(str(run_path), as_version=4)
    NotebookClient(doc, timeout=600, kernel_name="python3",
                   resources={"metadata": {"path": str(workdir)}}).execute()
    return "\n".join(
        (o.get("text") or "")
        for c in doc.cells for o in c.get("outputs", [])
    )


ANSI = re.compile(r"\x1b\[[0-9;]*m")


def summary(out):
    """pytest's own tally line, not whatever the last cell happened to print."""
    for line in reversed(ANSI.sub("", out).splitlines()):
        if re.search(r"\d+ (passed|failed|error)", line):
            return line.strip("= ").strip()
    return "(no pytest summary found)"


def verify_one(nb_path, verify_dir):
    reference, broken = verify_dir / "reference.py", verify_dir / "broken.py"
    for p in (reference, broken):
        if not p.is_file():
            fail(f"{p} is missing -- both implementations are required")

    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp) / "pass"
        work.mkdir()
        out = execute(nb_path, reference, work)
        if "failed" in out or " passed" not in out:
            fail(f"{nb_path}: the reference implementation does not pass every scenario\n{out}")
        print(f"  reference  -> {summary(out)}")

    with tempfile.TemporaryDirectory() as tmp:
        work = pathlib.Path(tmp) / "fail"
        work.mkdir()
        out = execute(nb_path, broken, work)
        if "failed" not in out:
            fail(f"{nb_path}: the broken implementation passed every scenario. "
                 f"A provided scenario that cannot fail is not a test.\n{out}")
        print(f"  broken     -> {summary(out)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=".classroom.yaml")
    ap.add_argument("--set", dest="set_number", type=int)
    args = ap.parse_args()
    cfg = yaml.safe_load(pathlib.Path(args.config).read_text(encoding="utf-8"))

    numbers = [args.set_number] if args.set_number else range(1, 13)
    checked = 0
    for n in numbers:
        nn = f"{n:02d}"
        source_dir = pathlib.Path(cfg["source_dir"].replace("{NN}", nn))
        nb_path = source_dir / f"ps{nn}.ipynb"
        if not nb_path.is_file():
            continue
        verify_dir = source_dir / ".verify"
        if not verify_dir.is_dir():
            print(f"::warning::{source_dir} has no .verify/ -- numbers unverified, skipping")
            continue
        print(f"set {n}: {nb_path}")
        verify_one(nb_path, verify_dir)
        checked += 1
    print(f"\n{checked} notebook(s) verified")


if __name__ == "__main__":
    main()
