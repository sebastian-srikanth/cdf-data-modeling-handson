# Chapter 03 — Data Modeling

**Goal:** understand *why* this lab's data model is shaped the way it is — not just
copy YAML — then author every data-modeling resource for your own module.

This is the longest chapter in the course on purpose. Everything downstream
(transformations, functions, location filters) exists to populate or scope the model
you build here.

---

## 3.1 [INFO] Problem framing — what graph are we actually building?

An industrial question like *"why is pump* `21-PA-2001A` *degrading, and what should we
do about it?"* requires walking a graph, not querying a table:

```
Asset hierarchy (where is it?)
  → Equipment (what physical thing is installed there?)
    → TimeSeries (what are its sensors saying, over time?)
    → Files / Diagrams (what P&ID and datasheet describe it?)
    → WorkOrders (what maintenance has been done or is planned?)
    → 3D (where does it sit physically?)
    → EquipmentHealthProfile (the derived, human-readable rollup)
```

No single classic resource type (assets, time series, events) answers this alone —
you need a model that lets all of these *reference each other* through relations. That
is what data modeling in CDF is for: not storage, but **navigable structure**.

---



## 3.2 [INFO] Why spaces — instance vs schema

A **space** is a namespace for either data (*instance space*) or schema (*schema
space*). This lab uses three, and the split is deliberate:


| Space                                 | Kind           | Holds                                                                       |
| ------------------------------------- | -------------- | --------------------------------------------------------------------------- |
| `isp_YOURNAME_TRN`                    | Instance space | Your actual nodes/edges: assets, equipment, time series, files, work orders |
| `ssp_YOURNAME_TrainingCore_edm`       | Schema space   | Your enterprise container + view + data model definitions                   |
| `ssp_YOURNAME_MaintenanceInsight_sdm` | Schema space   | Your solution container + view + data model definitions                     |


**Why separate instance from schema at all?** Schema (containers/views/models) changes
rarely and needs careful versioning; instances (actual data) change constantly and
need none. Mixing them in one space means every data write and every schema change
compete for the same namespace's access rules and lifecycle. Separating them means you
can, for example, purge all your instance data (teardown, [Chapter 13](13-cross-cutting-mastery.md))
without touching your schema at all.

**Why three spaces and not one?** Because *isolation* in this course is achieved
**by space**, not by scoping every external ID (§1.2). If everyone shared one
instance space, `21-PA-2001A` would collide across all participants immediately. Each
person's own `isp_YOURNAME_TRN` is what makes 15 identical builds coexist.

⚠️ `[COMMON MISTAKE]` Putting instance data in a schema space "because it's already
there." CDF won't stop you, but it defeats separated lifecycle management and is not
how this course — or most production CDF deployments — are structured.

📚 `[DOCS]` [https://docs.cognite.com/cdf/dm/](https://docs.cognite.com/cdf/dm/) (spaces, containers, views, data models)

---



## 3.3 [INFO] Why `cdf_cdm` + EDM + SDM layering (not a fully custom model)

**Design decision log — read this before touching YAML:**


| Choice made                                                                                                                                                           | Alternative considered                              | Why rejected                                                                                                                                                                                                                                                                         |
| --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Extend `cdf_cdm` (Cognite's Core Data Model); author exactly **one** enterprise view (`viw_WorkOrder_edm`) + **one** solution view (`viw_EquipmentHealthProfile_sdm`) | Fully custom, green-field data model (no CDM reuse) | Too slow to build in a 4-hour lab, and it throws away CDM's built-in contextualization machinery (diagram annotations, 3D linking, entity matching all assume `CogniteAsset`/`CogniteEquipment`/`CogniteFile` shapes). You'd be re-inventing plumbing this course wants you to *use* |
| Two data models: broad **enterprise** (`dam_TrainingCore_edm`) vs narrow **solution** (`dam_MaintenanceInsight_sdm`) that reuses enterprise views by reference        | One data model for everything                       | A single model can't demonstrate the enterprise/solution contrast that's the actual teaching point — see §3.4                                                                                                                                                                        |
| Location filter points at the **solution** model, not the enterprise model                                                                                            | Point the location filter at the enterprise model   | Would expose the *entire* broad surface to end users instead of the one curated use case — see [Chapter 06](06-location-filters.md)                                                                                                                                                  |


**What "extending CDM" means concretely:** every view in this model either *is* a CDM
view unchanged (`CogniteAsset`, `CogniteEquipment`, `CogniteTimeSeries`, `CogniteFile`,
`Cognite3DObject`, …) or *implements* one, inheriting its properties and adding a few
of your own. You only author net-new schema where CDM genuinely has no equivalent:
SAP work-order fields, and the derived Equipment Health Profile rollup.

**When to fork CDM instead of extending it:** if your domain concept has *no*
reasonable CDM parent (rare — CDM's core types are intentionally broad) or you need
incompatible semantics on a property CDM already defines. Neither applies here.

📚 `[DOCS]` Core Data Model reference — fetch the current page from
[https://docs.cognite.com/llms.txt](https://docs.cognite.com/llms.txt) (search "Core Data Model") before relying on
property names from memory; the CDM evolves between Toolkit versions.

---



## 3.4 [INFO] Why two data models, not one — enterprise vs solution


|                                     | `dam_TrainingCore_edm` (**enterprise**)                  | `dam_MaintenanceInsight_sdm` (**solution**)                                             |
| ----------------------------------- | -------------------------------------------------------- | --------------------------------------------------------------------------------------- |
| Audience                            | Broad — every consumer of this domain's data             | One use case: "Rotating-Equipment Maintenance Insight"                                  |
| Views                               | 10 CDM views + `viw_WorkOrder_edm`                       | 6 CDM views + `viw_WorkOrder_edm` (**by reference**) + `viw_EquipmentHealthProfile_sdm` |
| Includes 3D CAD views?              | Yes (`Cognite3DObject`, `CogniteCADModel/Revision/Node`) | No — out of scope for this use case                                                     |
| Who points a Location Filter at it? | Nobody, in this lab                                      | Your Location Filter ([Chapter 06](06-location-filters.md))                             |


The solution model **reuses** the enterprise `viw_WorkOrder_edm` by reference rather
than redefining it — a view is identified by `(space, externalId, version)`, so a
solution model can simply list an enterprise view in its own `views:` array. This is
the actual mechanic behind "layering": solution models compose enterprise + CDM
views, they don't duplicate them.

**The contrast is the lesson.** In production, the enterprise model is the broad,
governed surface that many teams build on; solution models are narrow, opinionated
products built *from* enterprise views for one audience. Building both, even in a toy
lab, is what makes the difference legible instead of theoretical.

---



## 3.5 [INFO] Why containers vs views vs data models — three different jobs


| Layer          | Job                                                                                                                                       | Analogy                               |
| -------------- | ----------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------- |
| **Container**  | Storage contract: property types, nullability, constraints, indexes                                                                       | A database table's column definitions |
| **View**       | Read/query contract: which container properties are exposed, under what names, optionally inheriting from a parent view via `implements:` | A SQL view / API shape                |
| **Data model** | Published product surface: a named, versioned collection of views                                                                         | An API version you hand to consumers  |


Splitting these matters because they **change at different rates and for different
reasons**: you might add an index to a container without changing any view; you might
publish a new data-model version exposing an existing view differently without
touching the container at all. Versioning the *data model* (and view) independently
from the *container* is a change-management tool, not bureaucracy — it's what lets
you evolve a published product without breaking every consumer on day one.

**Why** `implements:` — `viw_WorkOrder_edm` implements `CogniteActivity`:

```yaml
implements:
  - space: cdf_cdm
    externalId: CogniteActivity
    version: v1
    type: view
```

This is inheritance for free: `name`, `description`, `assets` (the relation to the
equipment/asset it's performed on), and CDM's scheduling fields
(`scheduledStartTime`, etc.) all come from `CogniteActivity` without you redefining
them. You only add the properties CDM has no equivalent for: `workOrderNumber`,
`status`, `orderType`, `priority`, `actualCost`, `currency`, `sourceSystem`. This is
the concrete mechanism behind "extend, don't fork" from §3.3.

---



## 3.6 [INFO] Nodes, edges, and files as instances

- **Nodes** are the primary instance type: assets, equipment, time series metadata,
work orders, the Equipment Health Profile — anything with properties.
- **Edges** connect two nodes with their own properties. `CogniteDiagramAnnotation`
(Chapter 08) is an edge: it connects a file node to an asset node and carries the
bounding box and confidence score of *that specific match* — properties that belong
to neither node alone.
- **Files** are a hybrid: `CogniteFile` is a DMS node (has a space+externalId
identity, participates in views like any other node) *and* has binary content
attached via the classic Files API underneath. That dual nature is why file
external IDs get `YOURNAME`-scoped (§1.2) even though other node external IDs don't.

**Why relations/edges matter for this lesson specifically:** the entire "hero tag"
story (`21-PA-2001A` as the hub everything converges on) *is* a set of direct
relations and edges: `Equipment.asset → Asset`, `TimeSeries.assets → [Asset]`,
`WorkOrder.assets → [Asset]`, `DiagramAnnotation edge: File → Asset`,
`EquipmentHealthProfile.asset/equipment/datasheetFile → [Asset, Equipment, File]`.
Nothing here is a copy of data — it's all navigable references into the same handful
of nodes.

---



## 3.7 [OPTIMIZE] Search, indexing, and property choices

Two features you'll use in `con_SAP_edm`:

```yaml
constraints:
  uniqueWorkOrderNumber:
    constraintType: uniqueness
    properties: [workOrderNumber]
indexes:
  statusIndex:
    indexType: btree
    properties: [status]
```

- **Uniqueness constraints** prevent duplicate business keys from ever being written —
cheaper to catch at write time than to detect and dedupe later.
- **B-tree indexes** speed up equality/range filtering on that property (`status = 'OPEN'`) at query time — without one, that filter is a full scan of the container.

⚠️ `[COMMON MISTAKE]` Indexing every property "to be safe." Indexes cost write
throughput and storage; add them for properties you know you'll filter or sort on
(here: `status`, because dashboards and workflows will query "give me all `OPEN`
work orders"), not speculatively.

💡 `[GOOD TO KNOW]` Property **names and descriptions are not just for humans**. In
[Chapter 10](10-datasheet-parsing.md) you'll see the Document Parser API treat a
view's property descriptions as the literal extraction schema an AI model fills in —
the same "write it clearly" discipline that helps a human skim a view in Fusion also
steers an agent's output. Model your properties assuming both audiences read them.

---



## 3.8 [INFO] Modeling anti-patterns seen in this design (and the redesign)


| Anti-pattern                                   | Why it's tempting                | What this lab does instead                                                                                                       |
| ---------------------------------------------- | -------------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| Scope every instance externalId by participant | "Feels safer"                    | Scope the **space**, keep externalIds literal (§1.2) — simpler, and it's what makes identical files possible across participants |
| One data model for everything                  | Fewer files to write             | Split enterprise/solution — the contrast between them is the actual lesson (§3.4)                                                |
| Fork CDM instead of extending it               | Full control over every field    | Throws away built-in contextualization tooling for no benefit here (§3.3)                                                        |
| Index every property                           | "Just in case we query it later" | Index only what you know you'll filter/sort on (§3.7)                                                                            |


---



## 3.9 [WRITE] Your spaces

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/data_modeling/isp_<YOURNAME>_TRN.Space.yaml`

```yaml
space: isp_<YOURNAME>_TRN
name: <YOURNAME> TRN Training Instances
description: Instance (data) space for <YOURNAME> - CDF data modeling hands-on.
```

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/data_modeling/ssp_<YOURNAME>_TrainingCore_edm.Space.yaml`

```yaml
space: ssp_<YOURNAME>_TrainingCore_edm
name: <YOURNAME> Training Core EDM
description: Enterprise schema space for <YOURNAME> - Training Core EDM.
```

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/data_modeling/ssp_<YOURNAME>_MaintenanceInsight_sdm.Space.yaml`

```yaml
space: ssp_<YOURNAME>_MaintenanceInsight_sdm
name: <YOURNAME> Maintenance Insight SDM
description: Solution schema space for <YOURNAME> - Rotating-Equipment Maintenance Insight.
```

🔧 `[CHANGE]` Every `<YOURNAME>` above — nowhere else in these three files.

---



## 3.10 [WRITE] Your containers

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/data_modeling/con_SAP_edm.Container.yaml`

```yaml
space: ssp_<YOURNAME>_TrainingCore_edm
externalId: con_SAP_edm
name: SAP Work Order
description: Custom container for SAP PM work-order enrichment properties (training).
usedFor: node
properties:
  workOrderNumber:
    type:
      type: text
      list: false
      collation: ucs_basic
    nullable: false
  status:
    type:
      type: enum
      values:
        OPEN:
          name: Open
        IN_PROGRESS:
          name: In progress
        CLOSED:
          name: Closed
    nullable: true
  orderType:
    type:
      type: text
      list: false
      collation: ucs_basic
    nullable: true
  priority:
    type:
      type: int32
      list: false
    nullable: true
  actualCost:
    type:
      type: float64
      list: false
    nullable: true
  currency:
    type:
      type: text
      list: false
      collation: ucs_basic
    nullable: true
  sourceSystem:
    type:
      type: text
      list: false
      collation: ucs_basic
    nullable: true
constraints:
  uniqueWorkOrderNumber:
    constraintType: uniqueness
    properties:
      - workOrderNumber
indexes:
  statusIndex:
    indexType: btree
    properties:
      - status
```

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/data_modeling/con_TRAINING_sdm.Container.yaml`

```yaml
space: ssp_<YOURNAME>_MaintenanceInsight_sdm
externalId: con_TRAINING_sdm
name: Equipment Health Profile
description: Solution-only enrichment container for rotating-equipment health (training).
usedFor: node
properties:
  asset:
    type: { type: direct, list: false }
    nullable: true
  equipment:
    type: { type: direct, list: false }
    nullable: true
  datasheetFile:
    type: { type: direct, list: false }
    nullable: true
  ratedFlowM3h:
    type: { type: float64, list: false }
    nullable: true
  ratedHeadM:
    type: { type: float64, list: false }
    nullable: true
  ratedPowerKw:
    type: { type: float64, list: false }
    nullable: true
  designPressureBarg:
    type: { type: float64, list: false }
    nullable: true
  designTemperatureC:
    type: { type: float64, list: false }
    nullable: true
  dryWeightKg:
    type: { type: float64, list: false }
    nullable: true
  casingMaterial:
    type: { type: text, list: false, collation: ucs_basic }
    nullable: true
  sealType:
    type: { type: text, list: false, collation: ucs_basic }
    nullable: true
  openWorkOrderCount:
    type: { type: int32, list: false }
    nullable: true
  lastParsedTime:
    type: { type: timestamp, list: false }
    nullable: true
```

🔧 `[CHANGE]` Only the `space:` line in each file — every `externalId`, property name,
and constraint stays **literal**, identical to every other participant's copy (§1.2).

⚠️ `[COMMON MISTAKE]` This is the container that carries `openWorkOrderCount` and
`lastParsedTime` — both look like they *should* be computed automatically. They're
not: `ParseDatasheet` ([Chapter 10](10-datasheet-parsing.md)) computes and writes them
explicitly, every run. Nothing in CDF auto-derives a "count of open work orders" for
you.

---
