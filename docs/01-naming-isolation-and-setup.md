# Chapter 01 — Naming, Isolation & Your Module

**Goal:** understand the one rule that lets 15+ people build the *same* data model in
the *same* CDF project with zero collisions, then create your own config and empty
module skeleton.

This is the most conceptually important chapter in the course. Everything from
Chapter 03 onward is an application of the rule below.

---

## 1.1 [INFO] Your module belongs to you alone

Every file you deploy in this course lives in exactly one place:
`participants/<YOURNAME>/`, and exactly one config points at it:
`config.<YOURNAME>-training.yaml`. You type every value into every file yourself —
nothing is pre-filled. That's not a limitation you're
working around; it's the point. Understanding *why* each value is what it is only
happens if you're the one who wrote it.

This has one direct consequence worth internalizing now: because your config selects
only your own folder, and no other config or module selects it, **nothing you do here
can collide with anyone else's work** — not through generation, not through shared
state, not through file overwrites. Isolation comes entirely from the folder
boundary (§1.3) plus the space boundary (§1.2) below.

⚠️ `[COMMON MISTAKE]` Editing anything outside your own `participants/<YOURNAME>/`
folder and your own config file — including anything else you might notice elsewhere
in this repository. If it's not one of those two paths, it isn't yours to touch.

---

## 1.2 [INFO] The (space, externalId) identity rule

This is the core insight of the entire course.

> **A DMS instance, container, or view is identified by the *pair* `(space,
> externalId)` — not by `externalId` alone.**

The same `externalId` can exist in two different spaces without any collision,
because the *space* is part of the identity. This is what makes multi-participant
training possible without every person inventing a unique tag name.

**Worked proof** — two participants, same equipment tag, zero collision:

```
SEBASTIAN → (isp_SEBASTIAN_TRN, ehp_21-PA-2001A)
ALICE     → (isp_ALICE_TRN,     ehp_21-PA-2001A)
```

Both nodes have the *identical* `externalId` — `ehp_21-PA-2001A` — but they live in
different spaces, so CDF sees them as two entirely distinct nodes. Neither participant
can see or overwrite the other's data, and neither had to invent a scoped tag name to
achieve that.

### Where `YOURNAME` goes — and where it must never go

| Goes in `YOURNAME` | Stays literal, never `YOURNAME`-scoped |
|---|---|
| Space names: `isp_YOURNAME_TRN`, `ssp_YOURNAME_TrainingCore_edm`, `ssp_YOURNAME_MaintenanceInsight_sdm` | Container external IDs: `con_SAP_edm`, `con_TRAINING_sdm` |
| Functions: `fnc_YOURNAME_Training_ParseDatasheet` | View external IDs: `viw_WorkOrder_edm`, `viw_EquipmentHealthProfile_sdm` |
| Transformations: `tra_YOURNAME_Training_TRN_Load_Assets` | Data model external IDs: `dam_TrainingCore_edm`, `dam_MaintenanceInsight_sdm` |
| Workflows: `wkf_YOURNAME_Training_TRN` | Node/instance external IDs: `21-PA-2001A`, `EQ-1002`, `ehp_21-PA-2001A`, `WO-1001` |
| Data sets: `dts_YOURNAME_Training_TRN` | |
| RAW databases: `rwd_YOURNAME_Training_TRN` | |
| Location filters: `loc_YOURNAME_TRN` | |
| 3D model names: `trd_YOURNAME_TRN_CAD` | |
| Files: `file_YOURNAME_TRN_PID_21_SEP` *(see note below)* | |

⚠️ `[COMMON MISTAKE]` Writing `ehp_ALICE_21-PA-2001A` "just to be safe." **Forbidden.**
Two reasons:

1. **It's redundant.** The space already guarantees isolation — `(isp_ALICE_TRN,
   ehp_21-PA-2001A)` cannot collide with anyone else's identical node in their own
   space.
2. **It breaks the identical-file benefit.** If everyone's container/view/data-model
   YAML is byte-for-byte identical except for the space they live in, everyone can
   follow the exact same worked examples, exact same screenshots, exact same
   troubleshooting steps in this course. The moment you scope an instance externalId,
   your files silently diverge from everyone else's for no isolation benefit at all.

💡 `[GOOD TO KNOW]` — why **Files** are in the left column even though `CogniteFile`
is a DMS-backed node type like `CogniteAsset`. Classic CDF Files predate the Data
Modeling Service and still carry a project-scoped identity underneath their DMS
instance wrapper; several 3D and file-processing code paths in this lab key off that
external ID directly (see [Chapter 04](04-data-sets-raw-and-files.md) and
[Chapter 09](09-3d.md)). Treat Files as belonging to the "globally-namespaced, scope
it" bucket alongside Functions/Transformations/Workflows — not the "keep it literal"
bucket where Asset/Equipment/WorkOrder/EHP nodes live.

📚 `[DOCS]` https://docs.cognite.com/cdf/dm/ (spaces, containers, views, instances)

---

## 1.3 [INFO] The approved folder structure (confirmed, not redesigned)

```
docs/                                      # this course — read-only for you
training/
├── config.<YOURNAME>-training.yaml        # you create this (§1.5)
└── modules/
    ├── reference/                         # the finished answer key — don't peek yet
    └── participants/<YOURNAME>/           # ← the ONLY path you create/edit
        ├── data_sets/
        ├── raw/
        ├── files/
        ├── data_modeling/
        ├── transformations/
        ├── functions/
        ├── workflows/
        ├── locations/
        ├── NOTES.md                       # your running notes — fill in as you go (§1.4)
        └── FEEDBACK.md                    # your course feedback — fill in at the end (§1.4)
```

ℹ️ `[INFO]` **One path rule for the whole course:** every command you run and every
`[WRITE]` path you see is relative to the **repo root** — the folder you landed in after
`git clone` in [Chapter 00](00-bootstrap.md) §0.2. The course never asks you to `cd`
anywhere else. If a command fails with "no such file or directory," check that first.

🔀 `[PR]` Your pull request will touch exactly:

```
training/config.<YOURNAME>-training.yaml
training/modules/participants/<YOURNAME>/**
```

Never edit `docs/`, `modules/reference/`, or another participant's folder. If it is
not one of your own two paths, it is not yours to touch. Full PR checklist in [Chapter 14](14-pr-and-merge.md).

---

## 1.4 [ACTION] Create your empty module skeleton

Pick your `YOURNAME` now (UPPERCASE, letters/digits only, e.g. `ALICE`). You will type
it dozens of times over the next few hours — get it right once.

```bash
mkdir -p training/modules/participants/<YOURNAME>/{data_sets,raw,files,data_modeling,transformations,functions,workflows,locations}

# Your two write-ups, seeded from the blank templates
cp docs/templates/NOTES.md    training/modules/participants/<YOURNAME>/NOTES.md
cp docs/templates/FEEDBACK.md training/modules/participants/<YOURNAME>/FEEDBACK.md
```

✅ `[VERIFY]`

```bash
find training/modules/participants/<YOURNAME> -type d
ls training/modules/participants/<YOURNAME>/*.md
```

You should see all eight subfolders, all empty, plus `NOTES.md` and `FEEDBACK.md`.
That's expected — you fill the folders in starting Chapter 03.

### `NOTES.md` — fill it in **as you go**

Open it now and keep it open. Each chapter ends with a `## Gate` that reminds you to add
two or three lines while the chapter is still fresh.

This is not busywork, and it is not graded. Two things make it worth your time:

- **For you:** the "what I'd have to look up again" line is the one you will actually reread
  in three weeks when you build something like this for real.
- **For the next cohort:** "I got stuck here, and *this* is what unblocked me" is the single
  most valuable sentence anyone writes all day. It is how the course gets fixed.

⚠️ `[COMMON MISTAKE]` Leaving `NOTES.md` untouched until 5pm and writing it from memory.
You will produce a summary of the *documentation*, not of your own experience — and the
friction you hit at 11am, the thing actually worth capturing, will be gone.

Write `n/a` under any heading you genuinely have nothing to say about. Leave nothing blank,
so "nothing to add" is distinguishable from "ran out of time".

📋 `FEEDBACK.md` you complete **once, at the end**, in Chapter 14. Leave it alone until then.

---

## 1.5 [WRITE] `training/config.<YOURNAME>-training.yaml`

📝 `[WRITE]` at the repo root:

```yaml
environment:
  name: <YOURNAME>-training
  project: <your-cdf-project>
  validation-type: dev
  selected:
    - modules/participants/<YOURNAME>
```

🔧 `[CHANGE]` — every `<YOURNAME>` above to your own uppercase name (keep it identical
in all three places).

| Key | Meaning |
|---|---|
| `environment.name` | A label for this environment instance — by convention, matches your config filename minus `config.` and `.yaml` |
| `environment.project` | The CDF project this config deploys to. **Intentionally hardcoded** — every config in this repo targets exactly one CDF project, by convention |
| `environment.validation-type` | `dev` — tells the Toolkit this is a development-tier config (affects which validation checks run) |
| `environment.selected` | The **only** module path this config will build/deploy — your own folder, and nothing else |

💡 `[GOOD TO KNOW]` — why there's no `variables:` block here. A `variables.modules...`
section exists to resolve `{{ placeholder }}` tokens inside shared YAML — useful when
*many* configs point at the *same* module with different values — that is exactly how
`modules/reference/` is built, so one module can be deployed under any participant name.
Your module, by contrast, belongs to exactly one config and one person: you. Writing `isp_<YOURNAME>_TRN` directly into
your own space YAML is simpler to read, simpler to search for in the Fusion UI, and
has zero indirection to debug when something doesn't resolve. Templating would be
solving a reuse problem you don't have.

⚠️ `[COMMON MISTAKE]` Setting `selected:` to `modules/reference` instead of your own
`participants/<YOURNAME>` path. If you do this, `cdf build` will try to build a much
larger, differently-structured module tree against a config that doesn't supply the
variables it expects — you'll get `{{ participant }}` literally showing up in your
build output, or a build error. If you ever see the literal string `CHANGEME` or `{{`
in build output, your `selected:` path is wrong.

---

## 1.6 [ACTION] Prove the config resolves — first build of your own module

```bash
uv run cdf build --config-yaml training/config.<YOURNAME>-training.yaml
```

✅ `[VERIFY]` Expected: the build succeeds and reports **zero resources** (your
folders are still empty). That's correct — you're proving the config → module path
wiring works *before* you add real content, so that when you do add content in
Chapter 03 onward, any error you see is about the content, not about the plumbing.

```bash
find build -type f 2>/dev/null | wc -l   # expect 0 right now
```

---

## Gate

**Do not proceed to Chapter 02 until:**

- You can state the (space, externalId) rule from memory, including which resource
  types get `YOURNAME` and which stay literal
- `participants/<YOURNAME>/` exists with all eight empty subfolders
- `training/config.<YOURNAME>-training.yaml` exists, selects **only** your own
  folder, and builds cleanly with zero resources
- You understand why your config has no `variables:` block
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 02 — Auth & Security](02-auth-and-security.md)
