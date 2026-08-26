# Chapter 05 — Transformations (Spark SQL)

**Goal:** load your four RAW tables into your data model, statement by statement,
understanding every cast, join, and null-guard — then deploy and run them for real.

📚 `[DOCS]` https://docs.cognite.com/cdf/integration/concepts/transformation/overview ·
https://docs.cognite.com/cdf/integration/guides/transformation/transformations ·
https://docs.cognite.com/cdf/integration/guides/transformation/sql_patterns ·
https://docs.cognite.com/cdf/integration/guides/transformation/operations_and_performance

---

## 5.1 [INFO] Why a Transformation here, not RAW-as-is or a Function

RAW → model is a **clean, deterministic key mapping**: every RAW row has an obvious
destination property. That's exactly the case for Spark SQL, not Python:

> **Rule:** clean deterministic key → Spark SQL Transformation. Fuzzy/ML/NLP/job-based
> work → Python Function.

You'll see this rule justify itself by contrast once you reach entity matching
([Chapter 07](07-entity-matching.md)), where "which file matches which asset" has no
clean key — that's exactly where a Transformation stops being the right tool.

---

## 5.2 [WRITE] Transform 1 — Load Assets (with the null-parent trap)

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/transformations/tra_Training_TRN_Load_Assets.Transformation.yaml`
(unscoped filename — the scoped identity lives in `externalId:`, see the `[COMMON MISTAKE]` below)

```yaml
externalId: tra_<YOURNAME>_Training_TRN_Load_Assets
name: tra_<YOURNAME>_Training_TRN_Load_Assets
dataSetExternalId: dts_<YOURNAME>_Training_TRN
ignoreNullFields: true
conflictMode: upsert
isPublic: true
destination:
  type: nodes
  view:
    space: cdf_cdm
    externalId: CogniteAsset
    version: v1
  instanceSpace: isp_<YOURNAME>_TRN
authentication:
  clientId: ${TRAINING_CDF_CLIENT_ID}
  clientSecret: ${TRAINING_CDF_CLIENT_SECRET}
  tokenUri: ${IDP_TOKEN_URL}
  cdfProjectName: ${CDF_PROJECT}
  scopes: ${IDP_SCOPES}
```

💡 `[GOOD TO KNOW]` — **how the SQL pairs to the transformation (and why there is no
`queryFile:` key).** Give the `.sql` file the **same basename** as its
`.Transformation.yaml` (`tra_Training_TRN_Load_Assets.Transformation.yaml` ↔
`tra_Training_TRN_Load_Assets.sql`). `cdf build` finds the adjacent SQL by that shared
stem, inlines its content, and stages it beside the built YAML; at deploy the Toolkit
re-finds it the same way. The scoped identity lives **inside** the file
(`externalId: tra_<YOURNAME>_…`), never in the filename — same rule as the RAW tables in
§4.3.

🛑 `[COMMON MISTAKE]` — **Do NOT add a `queryFile:` key** (some older guides still show
one). On Toolkit
0.8.125 deploy resolves `queryFile` *literally* relative to `build/transformations/` —
but build stages the SQL under the built YAML's prefixed stem, so
`queryFile: tra_Training_TRN_Load_Assets.sql` points at a file that isn't there and
deploy dies with `ToolkitFileNotFoundError: Query file
build/transformations/tra_Training_TRN_Load_Assets.sql not found`. Omit `queryFile` and
let the basename pairing above resolve it.

📝 `[WRITE]` sibling **with the identical basename**, `tra_Training_TRN_Load_Assets.sql`:

```sql
select
  cast(`assetExternalId` as STRING)                     as externalId,
  cast(`name`            as STRING)                     as name,
  cast(`description`     as STRING)                     as description,
  case
    when `parentExternalId` is null or trim(`parentExternalId`) = '' then null
    else node_reference('isp_<YOURNAME>_TRN', `parentExternalId`)
  end                                                   as parent,
  array(cast(`assetClass` as STRING))                   as tags
from `rwd_<YOURNAME>_Training_TRN`.`rwt_Training_TRN_Assets`
```

**Line by line:**

- `cast(... as STRING)` — RAW columns are untyped; every destination property needs an
  explicit type. Never rely on implicit coercion in Spark SQL — it fails silently in
  ways that are hard to trace back to a source row.
- `node_reference('isp_<YOURNAME>_TRN', ...)` — builds a **direct relation** (a
  `(space, externalId)` pair) from a plain string column. This is how a flat RAW
  column becomes a real graph edge to another node.
- The `case ... when null or empty ... else node_reference(...)` guard — **this is the
  null-parent trap, and it's the single most important SQL pattern in this course.**
  `TRN-FPSO` (the hierarchy root) has an empty `parentExternalId` in RAW, by design
  (§4.2). Without the guard, `node_reference('...', '')` would try to build a relation
  to a node with an **empty string** externalId — not "no parent," but a reference to
  a garbage node that doesn't exist. The guard is what correctly expresses "this asset
  has no parent" as SQL `null`, not as a broken reference.
- `array(cast(...))` — `tags` on `CogniteAsset` is a list property; even a single
  value must be wrapped in `array(...)`.

⚠️ `[COMMON MISTAKE]` Deleting the null-guard because "the data should just have a
parent." **Don't fix the data — teach the guard.** Real extractor output has missing
parents (a site root, an unmapped asset) far more often than clean training data
suggests, and `case when ... is null` is the idiom you'll reuse for every optional
relation you ever write.

⚡ `[OPTIMIZE]` This is a single small `select` with no joins — nothing to tune here.
The pattern matters more at scale: prefer filtering/casting early in the `select` list
so Spark's predicate pushdown has narrow, typed columns to work with, rather than
wide, stringly-typed scans joined late.

---

## 5.3 [WRITE] Transform 2 — Load Equipment

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/transformations/tra_Training_TRN_Load_Equipment.Transformation.yaml`
— identical shape to §5.2 (unscoped filename, no `queryFile`), with:

```yaml
externalId: tra_<YOURNAME>_Training_TRN_Load_Equipment
name: tra_<YOURNAME>_Training_TRN_Load_Equipment
destination:
  type: nodes
  view: { space: cdf_cdm, externalId: CogniteEquipment, version: v1 }
  instanceSpace: isp_<YOURNAME>_TRN
```

(`dataSetExternalId`, `ignoreNullFields`, `conflictMode`, `isPublic`, and
`authentication` are the same in every transformation this chapter — write them once,
keep them consistent.)

📝 `[WRITE]` sibling `tra_Training_TRN_Load_Equipment.sql`:

```sql
select
  cast(`equipmentExternalId` as STRING)                   as externalId,
  cast(`name`                as STRING)                   as name,
  cast(`description`         as STRING)                   as description,
  cast(`manufacturer`        as STRING)                   as manufacturer,
  cast(`serialNumber`        as STRING)                   as serialNumber,
  node_reference('isp_<YOURNAME>_TRN', `tagExternalId`)   as asset
from `rwd_<YOURNAME>_Training_TRN`.`rwt_Training_TRN_Equipment`
```

`asset` is a **required** direct relation here — every row in the Equipment RAW table
has a `tagExternalId` (§4.2 shows no blanks), so no null-guard is needed. Compare to
§5.2: guard optional relations, don't guard required ones you've verified are always
populated — an unnecessary `case when` just hides a real data problem if one ever
appears.

---

## 5.4 [WRITE] Transform 3 — Load TimeSeries

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/transformations/tra_Training_TRN_Load_TimeSeries.Transformation.yaml`
— same shape (unscoped filename, no `queryFile`), `destination.view` → `{ space: cdf_cdm, externalId: CogniteTimeSeries, version: v1 }`.

📝 `[WRITE]` `tra_Training_TRN_Load_TimeSeries.sql`:

```sql
select
  cast(`tsExternalId`  as STRING)                                as externalId,
  cast(`name`          as STRING)                                as name,
  cast(`description`   as STRING)                                as description,
  'numeric'                                                      as type,
  cast(`isStep`        as BOOLEAN)                               as isStep,
  cast(`sourceUnit`    as STRING)                                as sourceUnit,
  array(node_reference('isp_<YOURNAME>_TRN', `tagExternalId`))   as assets
from `rwd_<YOURNAME>_Training_TRN`.`rwt_Training_TRN_TimeSeries`
```

- `'numeric' as type` — a **literal**, not a RAW column. Every series in this lab is a
  numeric sensor reading; hardcoding it is correct because it's a fact about the
  *destination schema*, not something to derive from source data.
- `assets` is a **list** of direct relations (`CogniteTimeSeries.assets: [Asset]`) —
  note the `array(node_reference(...))` wrapping, matching the list cardinality.
- This transform only creates the time series **nodes** (metadata) — no numeric
  readings yet. [Chapter 11](11-datapoints.md)'s Function writes the actual datapoints.

---

## 5.5 [WRITE] Transform 4 — Load Work Orders

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/transformations/tra_Training_TRN_Load_WorkOrders.Transformation.yaml`
— same shape (unscoped filename, no `queryFile`), `destination.view` → your own `viw_WorkOrder_edm`:

```yaml
destination:
  type: nodes
  view:
    space: ssp_<YOURNAME>_TrainingCore_edm
    externalId: viw_WorkOrder_edm
    version: v1.0.0
  instanceSpace: isp_<YOURNAME>_TRN
```

📝 `[WRITE]` `tra_Training_TRN_Load_WorkOrders.sql`:

```sql
select
  cast(`workOrderNumber` as STRING)                              as externalId,
  cast(`workOrderNumber` as STRING)                              as workOrderNumber,
  cast(`title`           as STRING)                              as name,
  cast(`description`     as STRING)                              as description,
  upper(trim(cast(`status` as STRING)))                          as status,
  cast(`orderType`       as STRING)                              as orderType,
  cast(`priority`        as INT)                                 as priority,
  cast(`actualCost`      as DOUBLE)                              as actualCost,
  nullif(trim(cast(`currency` as STRING)), '')                   as currency,
  'SAP-PM-TRAINING'                                              as sourceSystem,
  to_timestamp(`plannedStart`)                                   as scheduledStartTime,
  to_timestamp(`plannedEnd`)                                     as scheduledEndTime,
  array(node_reference('isp_<YOURNAME>_TRN', `tagExternalId`))   as assets
from `rwd_<YOURNAME>_Training_TRN`.`rwt_Training_TRN_WorkOrders`
```

This is your first transform writing into a **custom** view instead of a bare CDM
view — every property you defined on `con_SAP_edm` (§3.10) plus the CDM-inherited
`name`, `description`, `assets`, `scheduledStartTime`, `scheduledEndTime` from
`CogniteActivity` (§3.5), all in one `select`.

- `externalId` is set to `workOrderNumber` itself — the business key doubles as the
  node identity here, which is why `con_SAP_edm` also enforces a uniqueness
  constraint on `workOrderNumber` (§3.7): two mechanisms protecting the same
  invariant.
- `upper(trim(...))` on `status` — defensive normalization against source-system
  case/whitespace inconsistency, so it reliably matches the container's `enum` values
  (`OPEN` / `IN_PROGRESS` / `CLOSED`). If this didn't run, a source value of `"open "`
  would fail the enum constraint instead of loading as `OPEN`.
- `nullif(trim(cast(... as STRING)), '')` on `currency` — **this is `WO-1002`'s empty
  `actualCost` neighbor's twin trap.** `actualCost` itself is cast straight to
  `DOUBLE` — an empty string casts to SQL `NULL` automatically for numeric types, so
  no guard is needed there. `currency`, however, is a `STRING` destination — an empty
  string would load as `""`, a non-null empty value, not the `NULL` you actually want.
  `nullif(..., '')` converts empty string to true `NULL`.
- `'SAP-PM-TRAINING' as sourceSystem` — another literal fact about provenance, not
  derived from a column.

⚠️ `[COMMON MISTAKE]` Assuming every "empty-looking" source value becomes `NULL`
automatically. **It depends on the destination type.** Numeric casts of `''` → `NULL`;
string casts of `''` → `""`. Know which one you're writing and guard accordingly —
this is exactly the bug the `currency` guard above prevents, and it's invisible until
someone queries `where currency is null` and gets zero rows they expected.

---

## 5.6 [LIMITS] and [OPTIMIZE]

🚧 `[LIMITS]`

- Transformations run on a shared Spark cluster with per-project scheduling and
  concurrency limits — a runaway wide join can starve other transformations in the
  same project. Keep joins narrow and filtered.
- `authentication:` credentials are evaluated at **run time**, not deploy time — this
  is exactly why the two-identity trap from [Chapter 02](02-auth-and-security.md)
  doesn't surface until the transformation actually runs.

⚡ `[OPTIMIZE]`

- **Idempotent loads**: `conflictMode: upsert` + `ignoreNullFields: true` means
  re-running any of these four transforms any number of times converges to the same
  state — it never duplicates nodes and never wipes a property to null just because
  this run's `select` didn't include it. This is not an accident; it's why you can
  safely re-run the whole pipeline in [Chapter 12](12-workflows.md) without fear.
- **Staging discipline**: RAW → Transformation → model, never source system →
  Transformation → model directly. If a transform ever fails, you still have the
  RAW rows to re-run against; you haven't lost provenance.
- Avoid wide scans: every `select` above reads exactly one RAW table with no joins.
  The moment you *do* need a join (you won't, in this lab), filter each side down
  before joining, not after.

📚 `[DOCS]` https://docs.cognite.com/cdf/integration/guides/transformation/write_sql_queries ·
https://docs.cognite.com/cdf/integration/guides/transformation/troubleshooting

---

## 5.7 [ACTION] Build, deploy, run

```bash
uv run cdf build --config-yaml training/config.<YOURNAME>-training.yaml
uv run cdf deploy --cdf-project <your-cdf-project> --dry-run --include transformations
uv run cdf deploy --cdf-project <your-cdf-project> --include transformations
```

🟢 `[ACTION]` Run each transformation once from the Fusion UI (Transformations →
select → Run) or via the SDK. Run them in dependency order: **Assets → Equipment →
TimeSeries and WorkOrders** (both depend on Equipment/Assets existing first for their
relations to resolve, though CDF will still accept out-of-order writes and resolve
relations once the target exists).

✅ `[VERIFY]`

```python
from cognite.client import CogniteClient
from cognite.client.data_classes.data_modeling import ViewId

client = CogniteClient()
space = "isp_<YOURNAME>_TRN"

for view_id, expected in [
    (ViewId("cdf_cdm", "CogniteAsset", "v1"), 8),
    (ViewId("cdf_cdm", "CogniteEquipment", "v1"), 5),
    (ViewId("cdf_cdm", "CogniteTimeSeries", "v1"), 6),
]:
    n = len(client.data_modeling.instances.list(
        instance_type="node", sources=[view_id], space=space, limit=-1))
    print(view_id.external_id, n, "expected", expected)
```

Also confirm `TRN-FPSO`'s `parent` is genuinely absent (not a broken reference) —
open it in Fusion and check it has no parent link at all.

---

## Gate

**Do not proceed to Chapter 06 until:**

- 8 assets / 5 equipment / 6 time series / 3 work orders exist in `isp_<YOURNAME>_TRN`
- `TRN-FPSO` has no parent (and you can explain why the guard was needed)
- `WO-1002`'s `currency` is `EUR` and its `actualCost` is genuinely `null` (not `0` or
  `""`)
- You can state the Transformation-vs-Function rule from memory
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 06 — Location Filters](06-location-filters.md)
