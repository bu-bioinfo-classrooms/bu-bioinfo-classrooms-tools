# bu-bioinfo-classrooms-tools

Publishing tooling for BU Bioinformatics courses that distribute assignments through
[Classroom50](https://github.com/foundation50/classroom50).

Each course keeps its materials in its own **private instructor repository**. This repo holds the
shared machinery that moves one problem set from there to a Classroom50 template repo and registers
it as an assignment. Course materials never live here.

> [!IMPORTANT]
> **This repository is public and holds tooling only.** No assignment content, no solutions, no
> rosters, no scores, no student data. It is public because a private repository's reusable
> workflows cannot be called across organizations, and the instructor repos live in a different org
> from `bu-bioinfo-classrooms`. Nothing here is sensitive; keep it that way.

## What is here

| File | Does |
|---|---|
| `publish_set.py` | Assembles one set's whitelisted files and replaces the template repo's tree |
| `update_classroom.py` | Registers the assignment via `gh teacher assignment add`, with retry |
| `verify_notebooks.py` | Executes each notebook twice — reference passes, broken fails |
| `workflows/verify.yml` | Copy into a course repo: verifies on every PR, never publishes |
| `workflows/publish.yml` | Copy into a course repo: `workflow_dispatch` only, one set at a time |
| `classroom.example.yaml` | The single per-course config, annotated |

## Using it in a course

1. Copy `classroom.example.yaml` to `.classroom.yaml` in the instructor repo and fill it in.
2. Copy both workflows into `.github/workflows/`.
3. Add a `CLASSROOM_TOKEN` secret — a fine-grained PAT with `contents: write` on the org's template
   repos and on `classroom50`.
4. Create a `publish` environment with a required reviewer.

Then publishing a set is one dispatch, and verification happens on every pull request.

## Three properties worth knowing

**Templates are outputs, never edited in place.** `publish_set.py` replaces the template's tree with
exactly the whitelisted payload and commits on top of the previous publish, so a file dropped from
the whitelist disappears. History is the record of how a set evolved across offerings.

**Republishing does not fix a released notebook.** `gh student accept` copies the template at accept
time, and `gh student submit` re-fetches only `.gitignore` and `.github/`. Anyone who already
accepted keeps their copy. Publishing governs future accepts.

**Registration is the seal.** Classroom50's `--available-from` is listing-only, not access control —
an assignment that exists can be accepted by anyone who guesses the slug. Registering only at
release time means next week's materials do not exist yet, which turns a week-long seal from a
policy students are trusted with into a property of the release process.

## Never in a template

`.github/workflows/autograde.yaml`. The autograde shim is written by `gh student accept` and never
changes after; a template copy is clobbered by submit's `.github/` re-fetch and will double-grade or
break grading. Autograding logic lives in the `classroom50` repository. `publish_set.py` refuses a
whitelist entry ending in `autograde.yaml`.
