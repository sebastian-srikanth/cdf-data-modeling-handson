# Working on this course

The course is code, so it changes like code: on a branch, through a pull request, with
the checks doing the arguing.

## The three gates

| Check | Runs | Needs credentials | Answers |
|---|---|---|---|
| **checks** | every push and PR | no | *Does the course still parse, and does it still tell the truth?* Links, cross-references, YAML, Python, notebooks, diagrams, the `[WRITE]` blocks against the reference module, the advertised counts, the documented Function return fields, and every code fragment quoted in a walkthrough table |
| **unit tests** | every push and PR | no | *Is the handler logic right?* The cascade's rungs, the confidence bands, human vetoes, retraction, and whether the quality gate can actually fail |
| **course evaluation** | every PR touching `docs/`, `tools/` or `training/` | yes | *Does the course still **work**?* Deploys the whole thing to CDF, runs it, self-checks every chapter, scores it, tears down |

The first two take seconds. The third takes up to an hour, mostly waiting for Cognite
Functions to build — that is normal, not a hang.

```bash
uv run python tools/check_docs.py
uv run --group dev python -m pytest tests/ -q
```

The division is deliberate. The unit tests never talk to CDF, so they can reach the
cases a live run reaches only by contrivance — the middle confidence band, a deleted
rule, a gate racing the write it checks. The live run is what proves CDF actually
behaves the way the chapters say it does. Neither substitutes for the other, and a
change to a handler usually needs both.

## Change a few chapters at a time

Open a pull request every two or three chapters rather than one enormous branch at the
end. The evaluation deploys the *whole* course on every PR, so a small PR still proves
the whole thing still works — and when something breaks, you know which few chapters did
it.

```bash
git switch -c fix/chapter-05-and-06
# edit
uv run python tools/check_docs.py      # seconds; run it before you push
git push -u origin HEAD
gh pr create
```

Then read the comment the evaluation leaves on the PR. Every chapter should be ✅ and the
score **100 / 100** — the reference module *is* the completed course, so anything less is
a regression you just introduced.

## Before you push

```bash
uv run python tools/check_docs.py     # the offline gate, ~1 second
uv run python tools/check_mermaid.py  # if you touched a diagram
```

`check_docs.py` is the one that matters. It compares every YAML block a chapter tells a
learner to write against the module in `training/modules/reference/`, so a chapter can
never quietly teach something different from what it ships.

## If you change the reference module

Two things embed it, and both go stale silently.

**The chapters.** Re-sync rather than hand-editing both:

```bash
uv run python tools/check_docs.py         # tells you which blocks drifted
uv run python tools/sync_write_blocks.py --write   # YAML blocks
uv run python tools/sync_handlers.py --write       # Function handlers
```

**Your deployed participant module.** `training/modules/participants/<NAME>/` is
*generated* from the reference and is gitignored. Editing the reference and running
`cdf build` does **nothing** — the build reads the generated copy, the Toolkit sees no
change, the deploy reports success, and your Function keeps running the old code with no
error anywhere. Re-materialise first:

```bash
uv run python -c "import sys; sys.path.insert(0,'tools'); \
  from live_e2e import materialise; materialise('<NAME>')"
```

`tools/live_e2e.py` and `tools/cohort.py provision` both do this for you; a hand-run
`cdf build` does not.

## If you add a chapter

1. It needs a `## Gate` and a `→ [Chapter NN]` link — `check_docs.py` enforces both.
2. Renumbering is the dangerous part. Do it in **one** pass, not sequentially: renaming
   16→17 and then 17→18 turns the first into 18. There is a check for the README tables
   drifting out of step, because that has happened on every renumber so far.
3. Add a self-check in `tools/selfcheck.py` if the chapter deploys anything.
4. Update the counts in `README.md`. There is a check for those too.

## Running it for a cohort

See [docs/FACILITATOR.md](docs/FACILITATOR.md) and [tools/README.md](tools/README.md).
