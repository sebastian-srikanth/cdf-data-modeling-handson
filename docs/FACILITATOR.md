# Facilitator guide

For whoever runs this with a cohort. Participants do not need this file.

> **Two kinds of number here.** The *machine* timings are **measured**, on `bluefield` with
> Toolkit 0.8.202. The *chapter* timings are **derived**, not observed — from each
> chapter's word count, its `[ACTION]` and `[WRITE]` counts, the measured machine waits, and
> a friction allowance for the chapters that always run long. They are a defensible first
> pass, not gospel. **Correct them after your first cohort** — that is the one thing in this
> file only you can supply.

## Machine time you cannot compress

These are the waits that wreck a schedule if you don't plan around them.

| What | Measured | Plan for |
|---|---|---|
| **Cognite Functions first deploy (5 functions)** | **6–12 min** | Do this *before the break*, not after. Nothing downstream works until they are `Ready` |
| Diagram detect job | ~30–60 s | fine inline |
| 3D revision processing | ~2–4 min | start it, then teach something else |
| Entity-matching fit + predict | ~60 s | fine inline |
| Five transformations | ~60 s total | fine inline |
| Whole workflow, ten tasks | **47 s** | a satisfying live demo — run it on the projector |
| `cdf deploy` (data modeling only) | ~10 s | fine inline |

⚠️ **The function build is the single biggest scheduling risk.** Have everyone run
`cdf deploy --include functions` at the *start* of the Chapter 07 session and let it build
while you teach entity-matching theory.

## How long it actually takes

Derived per chapter — reading at 180 wpm, 2.5 min per `[WRITE]`, 2.5 min per `[ACTION]`,
plus measured machine waits and a friction allowance where noted.

| Ch | Topic | Est. | Where the time goes |
|---|---|---:|---|
| 00 | Bootstrap | 45 m | +15 friction: toolchain installs never go cleanly for everyone |
| 01 | Naming and isolation | 30 m | |
| 02 | Auth and security | 45 m | +20 friction: **the single most over-running chapter.** Redirect URIs, tenants, consent |
| 03 | Data modeling | **100 m** | 14 `[WRITE]` files. The longest chapter, and worth every minute |
| 04 | Data sets, RAW, files | 45 m | 9 `[WRITE]` |
| 05 | Transformations | **70 m** | 17 `[WRITE]` — the most files in the course |
| 06 | Location filters | 15 m | The shortest. Good recovery slot |
| 07 | Entity matching | 65 m | +8 machine: **deploy the Functions at the start of this block** |
| 08 | Diagram annotation | 55 m | |
| 09 | 3D | 50 m | +4 machine: start the revision, teach while it converts |
| 10 | Datasheet parsing | 60 m | |
| 11 | Datapoints | 35 m | |
| 12 | Workflows | 25 m | Mostly reading; the run itself is 47 s |
| 13 | Querying the graph | **75 m** | 19 `[ACTION]` — the most interactive chapter in the course |
| 14 | Debugging broken links | 55 m | 13 `[ACTION]` |
| 15 | Atlas AI agent | 45 m | |
| 16 | Cross-cutting mastery | 15 m | Discussion, not typing |
| 17 | PR and merge | 40 m | +10 friction: git goes wrong for somebody |
| 18 | Teardown | 20 m | |

**Total ≈ 14.8 hours of contact time.**

⚠️ That does **not** fit two days. A realistic day is 6–6.5 working hours once you remove
breaks, lunch and restarts. Pick one:

- **Three half-days** (~5 h each) — the comfortable shape, and the one to quote by default.
- **Two full days** — workable only if you cut. Cut in this order: 16 (discussion),
  09 (3D), 11 (datapoints). Never cut 03 or 13.
- **Two days plus pre-work** — have participants complete 00–02 *before* day one against a
  checklist. That removes 2 hours and, more importantly, moves the auth pain out of the room.

### A three-half-day shape

| Session | Chapters | Est. |
|---|---|---:|
| 1 | 00–03 | 3 h 40 m |
| 2 | 04–08 | 4 h 30 m |
| 3 | 09–12 | 2 h 50 m |
| 4 | 13–18 | 4 h 10 m |

Sessions 2 and 4 are the long ones. **Start the Function deploy at the top of session 2**
and it builds while you teach Chapter 07's theory.

## Before the cohort — a week ahead

1. **Run the whole course yourself against a scratch project**, or trigger the
   `live-e2e` workflow. It deploys, runs, verifies and tears down unattended.
2. **Check the Functions quota.** Five functions per participant. A project capped at 100
   functions supports 20 participants, and the cap is silent until you hit it.
3. **Confirm Atlas AI is enabled** and the identity can create agents (Chapter 15).
4. **Pre-create participant identities** and verify one end to end. Auth is where day one
   is lost.
5. `PARTICIPANT=<you> uv run python tools/selfcheck.py all` — should be green before
   anyone else arrives.

## During — the checks that save you

Every chapter's Gate is executable. When someone says "I think I'm done":

```bash
PARTICIPANT=THEIRNAME uv run python tools/selfcheck.py 03
```

It prints PASS/FAIL per Gate item against what CDF actually contains. Use it instead of
reading over shoulders — it scales to a room, and it tells them *what* is missing.

## The five things that actually go wrong

1. **`.env` and the redirect URI.** `localhost:53000` must be registered on the app
   registration or interactive login fails with no useful message. Chapter 02.
2. **Someone deploys into someone else's space.** The `<YOURNAME>` substitution is the
   whole isolation model. Chapter 01 §1.2.
3. **The empty view.** A node exists but the view returns nothing, because only one of two
   containers was populated. Chapter 03 §3.8b. Budget time for this — everybody hits it.
4. **`ConsistencyError` panic at Chapter 03.** Without `.env` a build reports 13 errors and
   "Do not proceed to deploy." They are all `cdf_cdm` references a build cannot verify
   offline. Chapter 03 §3.14 explains it; say it out loud anyway.
5. **Functions still `Deploying`.** See above. It is never broken, it is just slow.

## Teardown

Chapter 18, and it matters — a project full of abandoned participant resources makes the
next cohort worse. Two things survive on purpose:

- **Data sets** cannot be deleted in CDF, ever. Archived is the clean end state.
- **Location filters** need `cdf clean --include locations`; no SDK delete exists.

Check afterwards with `tools/live_e2e.py <NAME> --teardown-only`, which is idempotent.
