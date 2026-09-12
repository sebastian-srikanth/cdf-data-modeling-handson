# Facilitator guide

For whoever runs this with a cohort. Participants do not need this file.

> **Human timings below are estimates and marked 🔶. They need calibrating against a real
> cohort — replace them after the first run.** The ⏱ machine timings are *measured*, on
> `bluefield` with Toolkit 0.8.202, and are the ones that will surprise you.

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

## Suggested shape — two days

| Session | Chapters | 🔶 Estimate | Notes |
|---|---|---|---|
| Day 1 AM | 00–02 | 🔶 2 h | Setup and auth. Expect the long tail here: `.env`, tenant, redirect URI |
| Day 1 AM | 03 | 🔶 2 h | The longest chapter, and the one worth the time. Do not rush §3.9 |
| Day 1 PM | 04–06 | 🔶 2 h | Mechanical. Good recovery slot if the morning ran over |
| Day 1 PM | 07–08 | 🔶 1.5 h | **Deploy functions at the start of this block** |
| Day 2 AM | 09–12 | 🔶 2.5 h | 3D and datasheet parsing. Start the 3D revision early |
| Day 2 AM | 13–14 | 🔶 1.5 h | Querying and debugging. The most interactive chapters — 19 and 13 `[ACTION]`s |
| Day 2 PM | 15 | 🔶 1 h | The payoff. Agents API is **alpha** — check it still behaves the week before |
| Day 2 PM | 16–18 | 🔶 1 h | Recap, PR, teardown |

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
