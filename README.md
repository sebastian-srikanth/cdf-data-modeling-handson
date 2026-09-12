# CDF Data Modeling — Hands-On

**A from-zero, hand-authored path through Cognite Data Fusion, the Cognite Toolkit,
and one deliberately real industrial data model.**

You start with Python, git, and a browser. You finish having built — by hand, file by
file — a complete CDF module: spaces, containers, views, two data models, a data set,
RAW tables, files, four transformations, five Cognite Functions, a workflow, and a
location filter. Along the way a pump quietly fails, and you make that visible in the
data.

Nothing is pre-filled. You type every file yourself, so you understand it and you own it.

---

## Start here

1. **[PREREQUISITES.md](PREREQUISITES.md)** — what you need before Chapter 00. Read
   this first; "I have a CDF login" is not sufficient on its own.
2. **[The course →](docs/README.md)** — 16 chapters, in order.

```bash
git clone https://github.com/sebastian-srikanth/cdf-data-modeling-handson.git
cd cdf-data-modeling-handson
cp .env.example .env    # then fill in every <angle-bracket> value
uv sync
uv run cdf auth verify --dry-run
```

---

## The chapters

| Chapter | You leave with |
|---|---|
| [00 — Bootstrap](docs/00-bootstrap.md) | Toolkit + SDK installed, first empty `cdf build` |
| [01 — Naming & isolation](docs/01-naming-isolation-and-setup.md) | Your own config and module skeleton |
| [02 — Auth & security](docs/02-auth-and-security.md) | The two-identity trap, memorized |
| [03 — Data modeling](docs/03-data-modeling.md) | Spaces, containers, views, two data models deployed |
| [04 — Data sets, RAW & files](docs/04-data-sets-raw-and-files.md) | Data set, RAW DB + 4 tables, 3 files deployed |
| [05 — Transformations](docs/05-transformations.md) | Assets, equipment, time series, work orders loaded |
| [06 — Location filters](docs/06-location-filters.md) | Your own scoped view of the graph |
| [07 — Entity matching](docs/07-entity-matching.md) | 3 contextualization techniques compared |
| [08 — Diagram annotation](docs/08-diagram-annotation.md) | Tags detected on a P&ID, annotations written |
| [09 — 3D](docs/09-3d.md) | CAD nodes mapped to assets |
| [10 — Datasheet parsing](docs/10-datasheet-parsing.md) | Regex vs. the agentic Document Parser API |
| [11 — Datapoints](docs/11-datapoints.md) | 4,320 datapoints — the degradation story becomes visible |
| [12 — Workflows](docs/12-workflows.md) | The whole pipeline running as one DAG |
| [13 — Querying the graph](docs/13-querying-the-graph.md) | Ask the graph real questions — traversal, filters, aggregates, sync |
| [14 — Debugging broken links](docs/14-debugging-broken-links.md) | Find what is quietly wrong, trace it to source, and undo a bad delete |
| [15 — Atlas AI agent](docs/15-atlas-ai-agent.md) | Point an agent at your model and see every Chapter 03 decision pay off |
| [16 — Cross-cutting mastery](docs/16-cross-cutting-mastery.md) | Idempotency, observability, cost |
| [17 — PR & merge](docs/17-pr-and-merge.md) | A PR scoped so tightly a dozen could merge at once |
| [18 — Teardown](docs/18-teardown.md) | Your resources removed cleanly |

Chapters that introduce a Cognite Function always meet the capability in a **Jupyter
notebook** first — raw SDK calls, cell by cell — before it is packaged into a
`handler.py`.

---

## Check your own work

```bash
PARTICIPANT=<YOURNAME> uv run python tools/selfcheck.py 03
```

Every chapter's Gate is executable. `selfcheck.py` asks CDF what you actually deployed and
prints PASS/FAIL per item, so you never have to guess whether you are ready to move on.
See [tools/README.md](tools/README.md).

## Running this alone vs. running it for a team

The course was built for a cohort — every participant works in
`training/modules/participants/<YOURNAME>/`, and the `(space, externalId)` identity rule
(Chapter 01) lets a dozen people build the *same* model in the *same* CDF project
without a single collision.

**Alone**, that still works — you are simply a cohort of one. Chapter 17 has you open
the PR against your own fork or branch and merge it yourself.

**For a team**, the isolation model is the point: one CDF project, one repo, N
participants, zero collisions. Everyone clones this repo, picks a unique `YOURNAME`,
and works through the same chapters — Chapter 01 explains why that does not collide,
and Chapter 17 explains why the pull requests don't either.

---

## Repository layout

```
README.md            You are here
PREREQUISITES.md     Access and tooling you need before Chapter 00
.env.example         Copy to .env and fill in — Chapter 00 walks you through it
cdf.toml             Toolkit config — organization dir is training/
pyproject.toml       Pins cognite-toolkit 0.8.202

docs/                THE COURSE
├── README.md          Start here
├── 00-…md … 18-…md    19 chapters, in order
├── notebooks/         9 Jupyter notebooks (chapters 07–11, 13–15, 18)
├── assets/            The P&ID, datasheet and 3D model you load
└── templates/         NOTES.md / FEEDBACK.md, seeded in Chapter 01

training/            The Cognite Toolkit organization directory
├── config.REFERENCE-training.yaml   Deploys the finished reference module
└── modules/
    ├── reference/                   The completed implementation — the answer key
    └── participants/<YOURNAME>/     The only path you create and edit
```

> **`modules/reference/` is the answer key.** Deploy it with
> `config.REFERENCE-training.yaml` if you want to see the finished thing run, or diff
> your work against it afterwards. Try not to read it before you have written your own.

---

## Teardown

Every resource this course creates can be removed — see
[Chapter 18](docs/18-teardown.md), which walks through it with an SDK notebook and
`cdf` commands. Entity-matching models are global to a project: if you create one, you
must delete it.

---

*Last validated September 2026 against cognite-toolkit 0.8.202, cognite-sdk 8.14 and the
Python 3.11 Function runtime.
The Document Parser API used in Chapter 10 is a Cognite public-preview capability and
may change — check the current Cognite documentation before relying on it.*
