# Chapter 15 — Teardown (the CLI half)

**Goal:** remove the two resource classes the Python SDK can't — your **spaces** and your
**location filter** — using `cdf` commands driven by your own
`config.<YOURNAME>-training.yaml`.

Teardown happens in **two halves**, and you need both:

1. **[`notebooks/06_teardown.ipynb`](notebooks/06_teardown.ipynb)** — pure Python SDK.
   Deletes your global resources: functions, transformations, workflow, RAW database, the
   classic OBJ file and 3D model, and *archives* the data set. Run that first.
2. **This chapter** — the two things the public SDK cannot delete, via `cdf`.

> ⚠️ **Destructive & irreversible.** Only ever purge spaces / filters that carry **your**
> `YOURNAME` (UPPERCASE, e.g. `SEBASTIAN`). Never touch another participant's.

---

## 15.1 [ACTION] Purge your three spaces

🟢 `[ACTION]` Run these in a **real interactive terminal** — not a notebook `!` cell, not
piped. `cdf data purge space` **requires** you to type the project name to confirm, and
the `--yes`/`-y` flag is **deprecated** (it does nothing now). **Order matters: instance
space first**, then the schema spaces — purging a schema space first can orphan instances
the purge then can't see.

```bash
# 1) instance space — nodes, edges, both PDF CogniteFiles + content, time-series datapoints,
#    diagram-annotation edges, the Equipment Health Profile node
uv run cdf data purge space isp_<YOURNAME>_TRN \
  --include-space --delete-datapoints --delete-file-content

# 2) enterprise schema space
uv run cdf data purge space ssp_<YOURNAME>_TrainingCore_edm --include-space

# 3) solution schema space
uv run cdf data purge space ssp_<YOURNAME>_MaintenanceInsight_sdm --include-space
```

When Toolkit asks you to confirm, type the project name **exactly** (not `y`):

```text
<your-cdf-project>
```

⚠️ `[COMMON MISTAKE]` Typing `y` instead of the project name, or piping the confirmation
(`printf … | cdf …`). Both break the confirm flow — run it interactively and type the
project name. This is the reason the SDK teardown notebook can't do the space purge for
you: a notebook `!` cell isn't a TTY.

🚧 `[LIMITS]` `cdf data purge space` builds its delete plan from **space statistics**,
which can lag and report `0` right after heavy writes — the purge then no-ops and
`--include-space` fails with *"contain nodes or edges"*. Wait ~1–2 minutes and re-run it
interactively; if it persists, delete the space from the CDF UI rather than looping.

---

## 15.2 [ACTION] Remove your location filter

The location filter `loc_<YOURNAME>_TRN` lives under the CDF **apps** API, and the public
Cognite SDK exposes **no delete** for it — which is exactly why the notebook leaves it to
`cdf`. Clean it against your own config:

```bash
uv run cdf build --config-yaml training/config.<YOURNAME>-training.yaml
uv run cdf clean --cdf-project <your-cdf-project> --include locations
```

(If a confirmation prompt appears, type `<your-cdf-project>` again.)

---

## 15.3 [VERIFY] Nothing of yours is left

- **Fusion → Data management → Spaces**: `isp_<YOURNAME>_TRN`,
  `ssp_<YOURNAME>_TrainingCore_edm`, `ssp_<YOURNAME>_MaintenanceInsight_sdm` are **gone**.
- Re-run the **verify cell** in [`06_teardown.ipynb`](notebooks/06_teardown.ipynb): your
  functions / transformations / 3D model lists are empty, and the data set reports
  **archived** (data sets can never be hard-deleted — archived is the clean end state).
- **Keep** `config.<YOURNAME>-training.yaml` — do **not** delete it.

That's a clean exit. 🎉

← [Chapter 14 — PR & Merge](14-pr-and-merge.md)
