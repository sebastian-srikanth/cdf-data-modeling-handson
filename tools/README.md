# tools/

Two audiences.

## If you are taking the course

```bash
uv run python tools/selfcheck.py 03      # one chapter
uv run python tools/selfcheck.py all     # everything you have reached so far
```

`selfcheck.py` asks **CDF** whether you finished a chapter, instead of asking you. Every
check maps to a `[VERIFY]` line or a Gate bullet in that chapter, and it reads only — it
never writes to your project.

It needs `PARTICIPANT` set, in your `.env` or your shell:

```bash
PARTICIPANT=ALICE uv run python tools/selfcheck.py 03
```

A failure tells you what CDF actually contains versus what the chapter expects:

```
  [PASS] space isp_ALICE_TRN                          got=True want=True
  [FAIL] views deployed                               got=['EquipmentHealthProfile', 'WorkOrder'] want=['Asset', 'EquipmentHealthProfile', 'WorkOrder']

  Chapter 03: 9/10 checks passed
  Not ready for the next chapter — fix the FAILs above.
```

Chapters covered: **03, 04, 05, 06, 07, 08, 09, 10, 11, 12, 13, 15, 19.**

Two behave differently and are worth knowing about:

- **19 (teardown)** asserts the *opposite* of every other chapter — it passes when nothing
  of yours is left. `selfcheck.py all` therefore skips it; ask for it by name once you have
  torn down: `uv run python tools/selfcheck.py 19`.
- **15 (Atlas AI)** treats a missing agent as a **note, not a failure** — deleting it is the
  documented end state of section 15.7, and the API is alpha.

Chapters 00, 01, 02, 14, 17 and 18 have no self-check: they are toolchain setup, auth,
querying you verify by reading output, discussion, and git process. There is nothing
durable in CDF to assert.

## If you are being assessed

```bash
uv run python tools/assess.py --tasks              # the Part B tasks, up front
PARTICIPANT=<YOURNAME> uv run python tools/assess.py
```

Part A (60 pts) is the chapter self-checks. Part B (40 pts) is four tasks that are in no
chapter — you have to understand the model well enough to extend it. Both are graded from
CDF state. 75 passes, 90 is a distinction.

## If you are running a cohort

```bash
uv run python tools/cohort.py preflight roster.txt   # will the project take them?
uv run python tools/cohort.py board     roster.txt   # who is where, right now
uv run python tools/cohort.py provision roster.txt   # write every participant module
uv run python tools/cohort.py sweep     roster.txt   # what is left behind afterwards
```

`board` is the one to keep open. See also [docs/FACILITATOR.md](../docs/FACILITATOR.md).

## If you are maintaining the course

```bash
uv run python tools/check_docs.py        # no credentials, no network, ~1 second
uv run python tools/check_mermaid.py     # renders every diagram; needs Node
uv run python tools/live_e2e.py CI       # full deploy → run → verify → teardown
```

`check_docs.py` is the gate that stops a chapter drifting from the module it teaches:

| check | catches |
|---|---|
| relative links, in markdown **and notebook cells** | a chapter renamed without updating what points at it |
| `section N.M` cross-references | a section renumbered, or one that never existed |
| YAML and Python fenced blocks parse | a broken snippet a learner would paste |
| notebook cells parse | the same, in the notebooks |
| `[WRITE]` blocks vs `training/modules/reference/` | **the chapter teaching different YAML than the reference ships** |
| notebook undefined names | a cell using a variable no earlier cell defines |
| chapter shape | a chapter missing its Gate or its next-chapter link |

Both run in CI on every push and pull request (`.github/workflows/checks.yml`).

`live_e2e.py` deploys the whole course under a throwaway participant name, runs every
transformation and function, runs `selfcheck.py all`, and tears down — in
`.github/workflows/live-e2e.yml`, manually or weekly. It deliberately never calls
`cdf clean --drop-data` (destroys the whole project) or `cdf data purge space` (requires a
human to type the project name). Point it at a scratch project.

## `acceptance.py` — the eight-property production contract

```bash
uv run python tools/acceptance.py <PARTICIPANT>                  # every capability
uv run python tools/acceptance.py <PARTICIPANT> contextualization
```

Asks one live capability the eight questions that decide whether it is production-shaped:
correct first result, unchanged re-run is a no-op, a changed input moves only what it
should, a removed input retires its stale output, bad input becomes visible review data,
human decisions survive, evidence stays queryable, work is bounded.

**It writes to CDF and puts things back.** Point it at a scratch participant, never at a
cohort member's. Every property reports `PASS`, `FAIL` or `--`, and `--` raises unless it
carries a reason — a skipped check that prints like a pass is exactly how this repo
shipped a broken `check_unit_references` for several commits.

Teaching text: [Chapter 17](../docs/17-cross-cutting-mastery.md) section 17.2c.

## `check_build_insights.py` — read what the build printed

```bash
CI=true uv run cdf build --config-yaml training/config.REFERENCE-training.yaml
uv run python tools/check_build_insights.py
```

The offline build exits **0** while printing *"Do not proceed to deploy"* — it cannot
resolve `cdf_cdm` without credentials. Both halves are defensible and together they are a
trap: a real modelling error prints among fourteen expected ones, under a banner everyone
has learned to ignore, with a passing exit code.

This classifies every insight against a stated reason and fails on anything left over.
Adding a new expected class means adding the reason, in `EXPECTED` — it is a claim that
has been checked, not a mute button.
