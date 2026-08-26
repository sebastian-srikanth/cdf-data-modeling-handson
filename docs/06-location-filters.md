# Chapter 06 — Location Filters

**Goal:** scope Fusion's Search/Explore experience to *only* your own graph, and
understand why the filter points at the solution model, not the enterprise model.

---

## 6.1 [INFO] Why location filters exist

A CDF project can host many data models and many participants' data side by side.
Without a location filter, opening Search/Explore shows *everything* the model
allows — every participant's `TRN-FPSO`, all at once, indistinguishable from each
other except by inspecting the space of every node. A **location filter** gives end
users (and you, in [Chapter 13](13-cross-cutting-mastery.md)'s aha-moment walkthrough)
a named, scoped entry point: "show me only this instance space, through this data
model."

This is a **UI/consumption-time** filter, not a security boundary — it does not
replace access-control groups. Think of it as "which curated view does a user land
on," not "what can a user access."

---

## 6.2 [INFO] Why it points at the *solution* model

Recall §3.4: `dam_MaintenanceInsight_sdm` is the narrow, curated surface for one use
case; `dam_TrainingCore_edm` is the broad enterprise surface. A location filter is a
**product decision** about what an end user should land on — and the answer is
almost always the narrow, purpose-built surface, not the broad enterprise one.
Pointing it at the enterprise model here would hand every viewer the full 10-view
surface (including 3D CAD views this use case doesn't need) instead of the 8-view
"Rotating-Equipment Maintenance Insight" product you actually built for.

⚠️ `[COMMON MISTAKE]` Pointing your location filter at `dam_TrainingCore_edm` because
"it has more stuff." More views is not more useful to the end user you're building
for — it's noise relative to the one use case the solution model was designed around.

---

## 6.3 [WRITE] Your location filter

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/locations/loc_<YOURNAME>_TRN.LocationFilter.yaml`

```yaml
externalId: loc_<YOURNAME>_TRN
name: TRN FPSO - <YOURNAME>
description: Hands-on training location for <YOURNAME>.
dataModelingType: DATA_MODELING_ONLY
instanceSpaces:
  - isp_<YOURNAME>_TRN
dataModels:
  - space: ssp_<YOURNAME>_MaintenanceInsight_sdm
    externalId: dam_MaintenanceInsight_sdm
    version: v1.0.0
```

🔧 `[CHANGE]` Every `<YOURNAME>` — `externalId`, `name`, `description`,
`instanceSpaces`, and the `dataModels` space reference. `dataModelingType`,
`dataModels[].externalId`, and `dataModels[].version` stay literal.

| Key | Meaning |
|---|---|
| `dataModelingType: DATA_MODELING_ONLY` | This location is scoped purely to the Data Modeling Service — no classic assets/events fallback. Correct for this lab since everything lives in the model |
| `instanceSpaces` | Which instance space(s) this location shows — yours, and only yours |
| `dataModels` | Which data model(s) define the view surface a user sees inside this location — your solution model, per §6.2 |

---

## 6.4 [ACTION] Build, deploy, verify

```bash
uv run cdf build --config-yaml training/config.<YOURNAME>-training.yaml
uv run cdf deploy --cdf-project <your-cdf-project> --dry-run --include locations
uv run cdf deploy --cdf-project <your-cdf-project> --include locations
```

✅ `[VERIFY]` In Fusion, open Search/Explore → switch location to **"TRN FPSO -
`<YOURNAME>`"**. You should see exactly your own 8 assets and nothing from any other
participant. If you see other people's data, or none of your own, your
`instanceSpaces` value is wrong — re-check it matches `isp_<YOURNAME>_TRN` exactly.

📚 `[DOCS]` https://docs.cognite.com/cdf/dm/ (search "location filter" — this is a
newer Toolkit resource type; confirm the current field names against
https://docs.cognite.com/llms.txt if this section of the docs has moved by the time
you read this).

⚠️ `[COMMON MISTAKE]` Building the location filter *before* Chapter 03's data model
is deployed. The Toolkit will complain it can't resolve `dam_MaintenanceInsight_sdm`
— location filters are a downstream, scoping resource, never the first thing you
deploy.

---

## Gate

**Do not proceed to Chapter 07 until:**

- Your location filter deploys and appears in Fusion's location switcher
- Selecting it shows exactly your 8 assets, no more, no less
- You can explain, in one sentence, why it points at the solution model and not the
  enterprise model
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 07 — Entity Matching](07-entity-matching.md)
