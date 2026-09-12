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

Chapters covered: 03, 04, 05, 07, 08, 09, 10, 11, 12, 13.

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
| `§N.M` cross-references | a section renumbered, or one that never existed |
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
