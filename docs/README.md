# CDF Data Modeling — From Scratch

**A from-zero, hand-authored path through Cognite Data Fusion, the Cognite Toolkit, and
one deliberately real industrial data model.**

> **Audience:** you have Python, git, and a browser, on either **macOS or Windows**.
> You do **not** yet have the Cognite Toolkit, `cdf.toml`, the Cognite SDK, this
> repository, or a ready-made config — every one of those gets installed, cloned, or
> created from zero in [Chapter 00](00-bootstrap.md). Every chapter cites the official
> docs and ends with something you can verify with your own eyes in the CDF UI.
> Commands are given for both macOS and Windows wherever they differ.

> **Last validated:** July 2026 — cognite-toolkit 0.8.125, Python 3.11 Function runtime.
> The **Document Parser API** ([Chapter 10](10-datasheet-parsing.md)) is a Cognite
> **public-preview / Early-Adopter** capability and may change — check the current
> Cognite documentation before relying on it.

---

## Why this course exists

Most CDF training either (a) hands you a finished module and asks you to click
"deploy," or (b) is a slide deck. Neither teaches you to *think* like a CDF
practitioner.

Here you will **create every file yourself** — including your own
`config.<YOURNAME>-training.yaml` — inside your own folder, understand *why* each
resource exists and is shaped the way it is, run real jobs against a real CDF project
(`<your-cdf-project>`), watch a real industrial story unfold (a pump quietly
failing), and open a real pull request scoped so tightly that a dozen of them could be
merged the same afternoon with zero collisions.

By the end you will have:

- Bootstrapped the Toolkit and SDK from an empty machine
- Authored a full CDF Toolkit module by hand: spaces, containers, views, a data model,
  a data set, RAW tables, files, transformations, five Cognite Functions (each
  preceded by a Jupyter notebook), a workflow, and a location filter
- Learned the **(space, externalId) identity rule** that makes 15 participants able to
  build the *same* model without a single collision
- Learned **why** the data model is shaped the way it is — not just its YAML
- Compared three ways to contextualize documents to assets (manual, regex, and the
  Entity Matching API) and two ways to parse a datasheet (regex, and the agentic
  Document Parser API — a Cognite public-preview capability)
- Opened a PR that touches only your own files

You type every file yourself, so you understand it and you own it.

---

## How to read this course

Every block is labeled so a tired human deep in a hands-on lab never confuses
"read this" with "do this." The labels are consistent across every chapter:

| Label | Meaning |
|---|---|
| 🟢 `[ACTION]` | **Do this now** — run a command, open a PR, click something |
| 📝 `[WRITE]` | **Create/edit this exact file** — full content is given, copy it |
| 🔧 `[CHANGE]` | Only these `YOURNAME` placeholders in the block above need personalizing |
| ✅ `[VERIFY]` | How to prove the last step actually worked — UI path, CLI output, SDK snippet |
| ℹ️ `[INFO]` | Context and architecture — read, don't act |
| 💡 `[GOOD TO KNOW]` | Deeper expertise, optional enrichment |
| 📚 `[DOCS]` | Official Cognite documentation to read |
| 🚧 `[LIMITS]` | Hard platform limits, quotas, timeouts — plan around these |
| ⚡ `[OPTIMIZE]` | Performance, cost, search, modeling, Spark SQL, Function, or prompt-engineering best practice |
| ⚠️ `[COMMON MISTAKE]` | What juniors (and seniors, once) get wrong here |
| 🔀 `[PR]` | Git / folder / pull-request rules that keep everyone's merge clean |

A chapter is "done" when every `[ACTION]` has been run and every `[VERIFY]` in it has
passed. If a `[VERIFY]` fails, stop — the gate at the end of the chapter exists so you
don't carry a broken foundation into the next one.

---

## The shape of every chapter

```
[WRITE] the files  →  [ACTION] cdf build  →  [VERIFY] locally
   →  [ACTION] dry-run / targeted deploy  →  [VERIFY] in CDF
   →  Gate: "Do not proceed until …"
```

Chapters that introduce a **Cognite Function** follow one extra rule: you always meet
the capability in a **Jupyter notebook** first — running the raw SDK calls cell by
cell — before you ever see it packaged into a `handler.py`. See
[Chapter 07](07-entity-matching.md) for the first example of this pattern.

---

## Agenda

Work through the chapters in order — each builds on the last. Go at your own pace.

| Chapter | You leave with |
|---|---|
| [00 — Bootstrap](00-bootstrap.md) | Toolkit + SDK installed, `cdf.toml` written, first empty `cdf build` |
| [01 — Naming, isolation & your module](01-naming-isolation-and-setup.md) | Your `config.<YOURNAME>-training.yaml`, empty `participants/<YOURNAME>/` skeleton |
| [02 — Auth & security](02-auth-and-security.md) | The two-identity trap, memorized |
| [03 — Data modeling](03-data-modeling.md) | Your spaces, containers, views, two data models deployed |
| [04 — Data sets, RAW & files](04-data-sets-raw-and-files.md) | Data set, RAW DB + 4 tables, 3 files deployed |
| [05 — Transformations](05-transformations.md) | 8 assets / 5 equipment / 6 time series / 3 work orders loaded |
| [06 — Location filters](06-location-filters.md) | Your own scoped view of the graph |
| [07 — Entity matching](07-entity-matching.md) | 3 contextualization techniques compared; `MatchDocuments` deployed |
| [08 — Diagram annotation](08-diagram-annotation.md) | `DetectDiagramTags` deployed and run once |
| [09 — 3D](09-3d.md) | `Load3DRevision` deployed; CAD nodes mapped to assets |
| [10 — Datasheet parsing](10-datasheet-parsing.md) | Both techniques upserting the same EHP node; `ParseDatasheet` deployed |
| [11 — Datapoints](11-datapoints.md) | 4,320 datapoints written; the degradation story is now visible |
| [12 — Workflows](12-workflows.md) | The whole pipeline running as one DAG |
| [13 — Cross-cutting mastery](13-cross-cutting-mastery.md) | Idempotency, observability, cost, the end-state graph, teardown |
| [14 — PR & merge](14-pr-and-merge.md) | PR opened |
| [15 — Teardown](15-teardown.md) | Your resources removed cleanly (SDK notebook + `cdf` spaces/location filter) |

---

## The approved folder structure (do not deviate)

```
docs/                                      # this course (you read, don't edit)
├── README.md                              #   you are here
├── 00-…md … 15-…md                        #   chapters, in order (15 = teardown)
├── notebooks/                             #   Jupyter templates you run locally
├── assets/                                #   PID PDF, datasheet PDF, 3D OBJ to copy
└── templates/                             #   NOTES.md / FEEDBACK.md to seed (Ch 01)

training/
├── config.<YOURNAME>-training.yaml        # one per participant; selects your folder
└── modules/
    ├── reference/                         # the finished answer key — don't peek yet
    └── participants/<YOURNAME>/           # ← the ONLY path you add/edit
        ├── NOTES.md                       # running notes, filled in as you go
        ├── FEEDBACK.md                    # course feedback, filled in at the end
        ├── data_sets/
        ├── raw/
        ├── files/
        ├── data_modeling/
        ├── transformations/
        ├── functions/
        ├── workflows/
        └── locations/
```

Your `config.<YOURNAME>-training.yaml` `selected:` list points at exactly one path:

```yaml
selected:
  - modules/participants/<YOURNAME>
```

Your pull request touches exactly two things:

```
training/config.<YOURNAME>-training.yaml
training/modules/participants/<YOURNAME>/**
```

Nothing else. See [Chapter 14](14-pr-and-merge.md) for the full PR checklist.

---

## The one naming rule that matters most

Your identity in this course is `YOURNAME` — an **UPPERCASE** placeholder
(e.g. `SEBASTIAN`, `ALICE`). It is never the literal word `TOKEN`. You'll see it
spelled out fully in [Chapter 01](01-naming-isolation-and-setup.md), but the headline
is:

> `YOURNAME` goes **only** in space names and globally-namespaced resources
> (functions, transformations, workflows, data sets, RAW databases, location filters,
> files, 3D model names). Container, view, data-model, and node/instance external IDs
> stay **literal** — never scoped to your name.

Get this one rule right and the rest of the course clicks into place.

---

Ready? Start with [Chapter 00 — Bootstrap](00-bootstrap.md).

---

Questions, corrections, or improvements to this course — please open an issue or a
pull request in this repository.
