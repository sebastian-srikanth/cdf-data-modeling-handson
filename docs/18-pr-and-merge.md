# Chapter 18 — PR & Merge

**Goal:** open a pull request that could be merged alongside a dozen other people's
PRs the same afternoon, with **zero collisions** and no review surprises. This is where
all the naming discipline from Chapter 01 pays off — or doesn't.

ℹ️ `[INFO]` **Working through this alone?** Open the PR against your own fork or a
branch of your own clone and merge it yourself. Do the chapter anyway — the isolation
model it verifies is exactly what lets this course be run for a whole team later, and
the pre-flight checks in section 18.5 catch real mistakes in your module regardless of who
reviews them.

---

## 18.1 [INFO] The isolation architecture — why this merges cleanly

Everything about how you've named and placed files exists to make this moment safe.
The design isolates every participant on **two independent axes at once**:

| Axis | Mechanism | Prevents |
|---|---|---|
| **Folder isolation** | Each person owns exactly one path: `participants/<YOURNAME>/**` + their own `config.<YOURNAME>-training.yaml` | *Git* collisions — two PRs never touch the same file, so `main` merges without conflicts |
| **Space isolation** | `YOURNAME` lives in your **space names** (`isp_<YOURNAME>_TRN`, `ssp_<YOURNAME>_*`) | *CDF* collisions — your `ehp_21-PA-2001A` and Alice's are different nodes because `(space, externalId)` differs, even though the externalId is byte-identical |

The picture for a cohort:

```
config.SEBASTIAN-training.yaml ─► participants/SEBASTIAN/** ─► space isp_SEBASTIAN_TRN ┐
config.ALICE-training.yaml     ─► participants/ALICE/**     ─► space isp_ALICE_TRN     ├─ all write
config.BOB-training.yaml       ─► participants/BOB/**       ─► space isp_BOB_TRN       ┘  node
                                                                                          ehp_21-PA-2001A
        ▲ different files (clean git)          ▲ different spaces (no CDF clash)          (same externalId,
                                                                                           zero collision)
```

The literal externalIds (`WorkOrder`, `WorkOrder`, `21-PA-2001A`,
`ehp_21-PA-2001A`) being **identical** across everyone is a *feature*, not a risk: it's
what lets a reviewer diff your work against the reference in seconds, and it's safe
precisely because your space namespaces it. If you'd scoped externalIds with your name
(`ehp_ALICE_...`), you'd have broken that benefit for zero isolation gain — the space
already did the isolating. (Full derivation: [Chapter 01](01-naming-isolation-and-setup.md) section 1.2.)

---

## 18.2 [PR] Exactly what you may touch — and what you must never touch

✅ **You may add/edit only these two paths:**

```
training/config.<YOURNAME>-training.yaml
training/modules/participants/<YOURNAME>/**
```

That second path includes your `NOTES.md` and `FEEDBACK.md` (section 1.4) — they live inside your
own folder, so they are already covered by the rule and need no exception.

🚫 **You must never touch anything else**, including:

- `docs/**` — this course's materials
- Any *other* participant's `participants/<other-name>/**`
- `cdf.toml`, `pyproject.toml`, or any other shared config
- Any file under `training/modules/` that lives **outside** your own `participants/<YOURNAME>/`
  folder

If your `git diff` shows anything outside your two paths, **stop and find out why before
you push.** The most common cause is an editor auto-formatting a file you merely opened,
or a stray `.env` / `.ipynb` checkpoint. The second most common is copying a worked
example and accidentally saving it into `modules/reference/` instead of your own folder.

✅ `[VERIFY]` before you commit anything:

```bash
git status
git diff --stat
```

Every changed/new path must match one of the two allowed patterns. No exceptions.

⚠️ `[COMMON MISTAKE]` **Committing your `.env` or notebook outputs.** `.env` holds the
one secret in this lab (Chapter 02 section 2.6) and must stay git-ignored. Notebooks under
`docs/notebooks/` are *curriculum* — you run them locally for learning; you
do **not** PR them. Confirm: `git check-ignore .env` prints `.env`, and no `*.ipynb`
appears in your `git status`.

---

## 18.3 [PR] Naming contract recap — the identity rule, proven

| Rule | Correct | Wrong |
|---|---|---|
| `YOURNAME` in **space names** + globally-namespaced resources | `isp_<YOURNAME>_TRN`, `fnc_<YOURNAME>_Training_ParseDatasheet`, `tra_<YOURNAME>_Training_...`, `wkf_<YOURNAME>_Training_TRN` | omitting your name → collides with everyone else's function/transformation |
| Container / view / data-model **externalIds** stay literal | `WorkOrder`, `WorkOrder`, `MaintenanceInsight` | `viw_ALICE_WorkOrder_edm` → breaks the identical-file benefit for no gain |
| **Instance** externalIds stay literal | `21-PA-2001A`, `ehp_21-PA-2001A`, `EQ-1002` | `ehp_ALICE_21-PA-2001A` → noise; the space already isolates it |
| `config.<YOURNAME>-training.yaml` `selected:` points at **exactly one** path | `modules/participants/<YOURNAME>` | more than one entry, or pointing at someone else's folder |

**The proof, one line:** `(isp_SEBASTIAN_TRN, ehp_21-PA-2001A)` and
`(isp_ALICE_TRN, ehp_21-PA-2001A)` are *two distinct nodes* — same externalId, different
space, zero collision. Never `YOURNAME`-scope an externalId, and never use the word
`TOKEN` anywhere. Full derivation: [Chapter 01](01-naming-isolation-and-setup.md) section 1.2.

---

## 18.4 [PR] Conflict-avoidance & git hygiene

- **Your `YOURNAME` must be unique among everyone using the same CDF project.** Two
  people picking `ALEX` collide on both folder *and* space. Settle your name before you
  start, not after you've authored 40 files.
- **Branch from a fresh `main`, don't drift.** Start clean and keep current:
  ```bash
  git checkout main && git pull
  git checkout -b training/<YOURNAME>
  ```
  If `main` moves while you work, `git pull --rebase origin main` onto your branch.
  Because you only touch your own two paths, a rebase should apply with **no
  conflicts** — if it doesn't, you've edited a shared file (see section 18.2).
- **Never edit a shared/global file to "make the build work."** If a build error tempts
  you to change `cdf.toml`, `default.config.yaml`, or the curriculum, the real fix is
  almost always in *your* folder. Anything shared is shared for a reason.
- **Don't rename or restructure the approved folder layout.** The subfolders under
  `participants/<YOURNAME>/` are fixed ([Chapter 01](01-naming-isolation-and-setup.md)
  Section 1.3). If a resource type isn't used, leave the folder empty — don't reorganize.
- **Two participants' diffs must never touch the same line of the same file.** If they
  could, something is mis-scoped — re-read Chapter 01 before pushing.

---

## 18.4b [WRITE] Finish your two write-ups

Before the pre-flight gate, close out the two files you created in
[Chapter 01](01-naming-isolation-and-setup.md) section 1.4. Both are part of the deliverable, and
CI checks for them.

📓 **`participants/<YOURNAME>/NOTES.md`** — you have been adding to this at every chapter
Gate. Read it through once now: fill any heading still empty with `n/a`, and complete the
final *"The one thing I'll actually use next week"* line.

📝 **`participants/<YOURNAME>/FEEDBACK.md`** — complete it now, in one sitting, while the
day is fresh.

- Keep the **YAML block at the top valid** — it is read across the whole cohort to find
  which chapters cost people the most time. A broken block drops you out of that analysis.
  Fill in every `difficulty`, `minutes` and `got_stuck`; rough numbers are fine, `0` is not.
- Then the free text. **Be blunt.** "section 7.4 confused me and here is the sentence that did it"
  is worth more than "great course". If something was wrong or out of date, say which
  chapter and line.

This is not graded and it does not affect any assessment of you. It exists so the next
cohort hits fewer of the walls you hit.

⚠️ `[COMMON MISTAKE]` Writing both files in the last ten minutes. `NOTES.md` written from
memory becomes a summary of the *documentation* rather than of your own experience — which
is exactly the thing nobody else can reconstruct later.

---

## 18.5 [ACTION] Pre-flight gate — run this locally before you push

🟢 `[ACTION]` The same checks a reviewer (and CI) will run — catch problems on your
laptop, not in the PR:

```bash
# 1. Formatting, trailing whitespace, YAML syntax, secret scanning
uv run pre-commit run --all-files

# 2. Your module builds cleanly and its config resolves
uv run cdf build --config-yaml training/config.<YOURNAME>-training.yaml

# 3. Confirm your diff is scoped to your two paths ONLY
git status && git diff --stat

# 4. The one secret is still ignored
git check-ignore .env   # must print: .env
```

Also complete the **self-verification checklist** in
[Chapter 17](17-cross-cutting-mastery.md) section 17.6 and confirm it prints `PASS` — that's
what proves your *deployed* resources actually exist in CDF, which a code diff can't
show.

✅ `[VERIFY]` What a reviewer checks (mirror it before you push):

- [ ] Diff touches only the two paths in section 18.2 — nothing shared, no other participant
- [ ] `config.<YOURNAME>-training.yaml` `selected:` has exactly one entry, your folder
- [ ] No `{{ }}` template syntax anywhere in your files (you write literals — section 1.5)
- [ ] No other participant's name appears anywhere in your files
- [ ] Container/view/data-model/instance externalIds are byte-identical to the worked
  examples in [Chapter 03](03-data-modeling.md) — no scoped tags, no `TOKEN`
- [ ] `handler.py` files match the worked Function chapters — identical Python is the
  point; it lets a reviewer diff yours against the reference in seconds
- [ ] `pre-commit run --all-files` passes
- [ ] No `.env`, no `*.ipynb`, no editor cruft in the diff
- [ ] `NOTES.md` is complete — every chapter heading filled in or explicitly `n/a` (section 18.4b)
- [ ] `FEEDBACK.md` is complete and its **YAML block still parses** (section 18.4b)

---

## 18.6 [WRITE] Your PR description — copy-paste template

🔀 `[PR]` Paste this into the **GitHub PR description** (do **not** commit it as a file —
a repo-level template would be a shared file you're not allowed to touch, section 18.2).
Personalize the `[CHANGE]` bits:

```markdown
## Participant module — <YOURNAME>

**Participant:** <YOURNAME>
**Space:** isp_<YOURNAME>_TRN
**Config:** training/config.<YOURNAME>-training.yaml

### Self-verification (Ch 17 section 17.6)
- [ ] Ran the self-verification checklist — it printed `PASS`
- [ ] `pre-commit run --all-files` passes
- [ ] `cdf build --config-yaml training/config.<YOURNAME>-training.yaml` clean
- [ ] `git diff --stat` touches ONLY my config + training/modules/participants/<YOURNAME>/**

### What I built (confirmed in CDF)
- [ ] Spaces, containers, views, 2 data models
- [ ] Data set + RAW tables + files (PID, datasheet, 3D)
- [ ] 5 transformations (SP auth block, not interactive client)
- [ ] 6 Functions (five that do work, one quality gate)
- [ ] Workflow + location filter
- [ ] Contextualization: manual / regex / entity-matching; datasheet regex + Doc Parser

### Notes & feedback
- [ ] `NOTES.md` complete — filled in chapter by chapter as I went
- [ ] `FEEDBACK.md` complete, YAML block valid

### Anything NOT fully verified (be honest)
> e.g. "3D revision still `Processing` at PR time" — state it; don't ship an
> unverified claim silently.

### Teardown
- [ ] I understand my entity-matching model is GLOBAL and must be deleted (Ch 17 section 17.7)
```

⚠️ `[COMMON MISTAKE]` Leaving the "NOT fully verified" section blank when something
genuinely didn't finish (a slow 3D conversion, a doc-parser job still `Running`). Say so
explicitly — an honest "still processing" is a green flag to a reviewer; a silent gap
that turns out to be broken is not.

---

## 18.7 [ACTION] Open the PR

🟢 `[ACTION]`

```bash
git add training/config.<YOURNAME>-training.yaml
git add training/modules/participants/<YOURNAME>/
git status   # double-check the staged set matches section 18.2 EXACTLY
git commit -m "Add <YOURNAME> training module"
git push -u origin training/<YOURNAME>
```

Then open the PR against `main` and paste the section 18.6 template as the description.

- **If CI flags something**, fix it in your folder and push again to the same branch —
  the PR updates automatically. Don't open a second PR.
- **If `main` moved**, `git pull --rebase origin main` and push. Your scoped diff should
  rebase without conflicts (section 18.4).
- **Don't force-push over a reviewer mid-review** unless you're only amending your own
  latest commit — coordinate if in doubt.

---

## 18.8 [INFO] What merging your PR does — and doesn't

Your PR does **not**, by itself, deploy your module anywhere beyond the training project
you already deployed to during the lab (`<your-cdf-project>`). These training
modules are **not** part of any production promotion pipeline. Merging simply
consolidates everyone's module into `main` as a durable record of the cohort's work —
and because every PR is scoped to its own two paths, many can be merged in a row without
conflicts.

---

## You're done

You bootstrapped the Toolkit from zero, hand-authored a full CDF module — spaces,
containers, views, two data models, a data set, RAW tables, files, five transformations,
six Cognite Functions (each preceded by a notebook), a workflow, and a location filter
— watched a real pump degrade in real data, contextualized documents three different
ways, parsed a datasheet two different ways including a genuinely agentic API call, and
opened a clean PR that could be merged next to a dozen others without a single
collision.

That's the craft. Well done.

---

## Gate

**Do not proceed to Chapter 19 until:**

- Your pull request is open, and its title and body say what you built rather than
  what you touched
- Every check on it is green — including the course evaluation, which deploys your
  work to CDF and scores it
- `uv run python tools/assess.py` gave you a score you are willing to have read out
- You reviewed your own diff, file by file, before asking anyone else to
- You can name one thing in it you would do differently, and say why you did not
- 📓 Your `participants/<YOURNAME>/NOTES.md` has a line for every chapter — **now**,
  not tonight

⚠️ `[COMMON MISTAKE]` Tearing down before the PR is merged. Chapter 19 removes the
resources your evaluation deploys against; run it too early and the check that was
green goes red with nothing left to inspect.

---

When you're finished with the lab and want to remove your CDF resources, see
→ [Chapter 19 — Teardown](19-teardown.md).
