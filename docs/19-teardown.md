# Chapter 19 — Teardown (the CLI half)

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

## 19.0 [INFO] Before you delete anything — two rules

**You have 72 hours.** Deleting an instance does not destroy it. CDF soft-deletes: the
instance is stamped with a `deletedTime`, vanishes from every normal query, and is
permanently collected roughly three days later. Inside that window it is still visible
through `/sync`, and re-running the transformation that created it restores it — the
source row never moved. [Chapter 14](14-debugging-broken-links.md) section 14.8 walks through
exactly that recovery.

Two caveats worth carrying:

- Soft-deleted instances **still count** against your project's instance limits until
  they are collected. Deleting is not the same as freeing.
- A space cannot be deleted while it still holds anything. That is why the order below
  is instances first, spaces last.

**Delete edges before nodes.** Deleting a node cascades to every edge attached to it,
and restoring the node does **not** restore the edges. You would get your instance back
with all of its connections gone — usually worse than the original mistake. It also
avoids a long cascade on a well-connected node.

That matters directly here: the `CogniteDiagramAnnotation` edges you created in
[Chapter 08](08-diagram-annotation.md) are edges. They go first.

---

## 19.1 [ACTION] Purge your three spaces

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

## 19.2 [ACTION] Remove your location filter

The location filter `loc_<YOURNAME>_TRN` lives under the CDF **apps** API, and the public
Cognite SDK exposes **no delete** for it — which is exactly why the notebook leaves it to
`cdf`. Clean it against your own config:

```bash
uv run cdf build --config-yaml training/config.<YOURNAME>-training.yaml
uv run cdf clean --cdf-project <your-cdf-project> --include locations
```

(If a confirmation prompt appears, type `<your-cdf-project>` again.)

---

## 19.2b [ACTION] The leftovers nothing warns you about

Two things survive a tidy teardown and will not show up unless you go looking.

**Function zips.** Deploying a Cognite Function uploads its code as a **classic file**.
Deleting the function does **not** delete that file — you are left with one orphaned
zip per function, named after the function's external ID.

🟢 `[ACTION]`

```python
leftovers = [f.external_id for f in client.files.list(limit=1000)
             if (f.external_id or "").startswith(f"fnc_{YOURNAME}_")
             or (f.external_id or "").startswith(f"file_{YOURNAME}_")]
print(leftovers)
client.files.delete(external_id=leftovers)
```

✅ `[VERIFY]` Re-run the list — it comes back empty. Five function zips plus the classic
OBJ from [Chapter 09](09-3d.md).

**Your data set.** Data sets **cannot be deleted in CDF, ever.** Archiving is the clean
end state, which the teardown notebook already does for you — but know that it is a
platform limit, not a step you forgot.

---

## 19.3 [VERIFY] Nothing of yours is left

- **Fusion → Data management → Spaces**: `isp_<YOURNAME>_TRN`,
  `ssp_<YOURNAME>_TrainingCore_edm`, `ssp_<YOURNAME>_MaintenanceInsight_sdm` are **gone**.
- Re-run the **verify cell** in [`06_teardown.ipynb`](notebooks/06_teardown.ipynb): your
  functions / transformations / 3D model lists are empty, and the data set reports
  **archived** (data sets can never be hard-deleted — archived is the clean end state).
- **Keep** `config.<YOURNAME>-training.yaml` — do **not** delete it.

That's a clean exit. 🎉

---

## Gate

This is the last chapter, so this gate closes the course rather than opening the next one.
**You are done when:**

- All three of your spaces are gone from Fusion, verified by looking rather than by
  trusting the notebook's output
- Your functions, transformations and 3D model lists come back empty
- Your data set reports **archived** — the clean end state, because a data set can never
  be hard-deleted
- Nobody else's resources changed. Re-run `tools/selfcheck.py` for a colleague still
  working and confirm it still passes
- You kept `config.<YOURNAME>-training.yaml`

💡 `[GOOD TO KNOW]` That fourth one is the real test of everything
[Chapter 01](01-naming-isolation-and-setup.md) taught you. A teardown that takes a
neighbour's work with it means the isolation was never real — you just never stressed it.

---

← [Chapter 18 — PR & Merge](18-pr-and-merge.md)
