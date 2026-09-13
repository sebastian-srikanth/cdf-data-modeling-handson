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
Section 4.3.

⚠️ `[COMMON MISTAKE]` — **Do NOT add a `queryFile:` key** (some older guides still show
one). On Toolkit
0.8.202 deploy resolves `queryFile` *literally* relative to `build/transformations/` —
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
  (section 4.2). Without the guard, `node_reference('...', '')` would try to build a relation
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
— identical shape to section 5.2 (unscoped filename, no `queryFile`), with:

```yaml
externalId: tra_<YOURNAME>_Training_TRN_Load_Equipment
name: tra_<YOURNAME>_Training_TRN_Load_Equipment
dataSetExternalId: dts_<YOURNAME>_Training_TRN
ignoreNullFields: true
conflictMode: upsert
isPublic: true
destination:
  type: nodes
  view:
    space: cdf_cdm
    externalId: CogniteEquipment
    version: v1
  instanceSpace: isp_<YOURNAME>_TRN
authentication:
  clientId: ${TRAINING_CDF_CLIENT_ID}
  clientSecret: ${TRAINING_CDF_CLIENT_SECRET}
  tokenUri: ${IDP_TOKEN_URL}
  cdfProjectName: ${CDF_PROJECT}
  scopes: ${IDP_SCOPES}
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
has a `tagExternalId` (section 4.2 shows no blanks), so no null-guard is needed. Compare to
Section 5.2: guard optional relations, don't guard required ones you've verified are always
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
— same shape (unscoped filename, no `queryFile`), `destination.view` → your own `WorkOrder`:

```yaml
externalId: tra_<YOURNAME>_Training_TRN_Load_WorkOrders
name: tra_<YOURNAME>_Training_TRN_Load_WorkOrders
dataSetExternalId: dts_<YOURNAME>_Training_TRN
ignoreNullFields: true
conflictMode: upsert
isPublic: true
destination:
  type: nodes
  view:
    space: ssp_<YOURNAME>_TrainingCore_edm
    externalId: WorkOrder
    version: v1.0.0
  instanceSpace: isp_<YOURNAME>_TRN
authentication:
  clientId: ${TRAINING_CDF_CLIENT_ID}
  clientSecret: ${TRAINING_CDF_CLIENT_SECRET}
  tokenUri: ${IDP_TOKEN_URL}
  cdfProjectName: ${CDF_PROJECT}
  scopes: ${IDP_SCOPES}
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
view — every property you defined on `WorkOrder` (section 3.11) plus the CDM-inherited
`name`, `description`, `assets`, `scheduledStartTime`, `scheduledEndTime` from
`CogniteActivity` (section 3.5), all in one `select`.

- `externalId` is set to `workOrderNumber` itself — the business key doubles as the
  node identity here, which is why `WorkOrder` also enforces a uniqueness
  constraint on `workOrderNumber` (section 3.7): two mechanisms protecting the same
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

## 5.6 [WRITE] Transform 5 — Work-order operations, and four ways SQL lies to you

The four transformations above each read one RAW table. Real pipelines join, and the
moment you join, a new class of bug appears: the kind that reports **success** and
quietly gives you the wrong number of rows.

This transformation loads **work-order operations** — the individual jobs that make up
one work order — from `rwt_Training_TRN_WorkOrderOperations`, joined to the work orders
you loaded in section 5.5. Eight source rows go in. Six nodes come out. That is correct, and
by the end of this section you will be able to say exactly why.

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/raw/rwt_Training_TRN_WorkOrderOperations.Table.yaml`

```yaml
dbName: rwd_<YOURNAME>_Training_TRN
tableName: rwt_Training_TRN_WorkOrderOperations
```

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/raw/rwt_Training_TRN_WorkOrderOperations.Table.csv`

```csv
key,operationNumber,workOrderNumber,tagExternalId,description,durationHours,craft
OP-1001-0010,0010,WO-1001,21-PA-2001A,Isolate and drain export pump A,4,MECH
OP-1001-0020,0020,WO-1001,21-PA-2001A,Replace mechanical seal cartridge,8,MECH
OP-1001-0020-REV,0020,WO-1001,21-PA-2001A,Replace mechanical seal cartridge (revised scope),10,MECH
OP-1001-0030,0030,WO-1001,21-XX-9999,Replace outboard bearing,5,MECH
OP-1002-0010,0010,WO-1002,21-VG-2001,Calibrate transmitter loop,3,INST
OP-1003-0010,0010,WO-1003,21-VG-2001,Open manway and inspect internals,12,MECH
OP-1003-BLANK,,WO-1003,21-VG-2001,Close manway and pressure test,6,MECH
OP-9999-0010,0010,WO-9999,21-PA-2001A,Operation left behind by a deleted work order,2,MECH
```

ℹ️ `[INFO]` Four of those eight rows are deliberately damaged, in four different ways.
This is what a real SAP extract looks like on a Tuesday.

### 5.6.1 The INNER JOIN that deletes your data

The obvious query joins operations to their work order to pick up the title:

```sql
from      `rwd_<YOURNAME>_Training_TRN`.`rwt_Training_TRN_WorkOrderOperations` o
inner join `rwd_<YOURNAME>_Training_TRN`.`rwt_Training_TRN_WorkOrders`         w
        on o.`workOrderNumber` = w.`workOrderNumber`
```

`OP-9999-0010` belongs to `WO-9999`, which does not exist. An `INNER JOIN` drops it —
**no error, no warning, one fewer row than you expected.**

⚠️ `[COMMON MISTAKE]` Reaching for `INNER JOIN` by reflex. Use `LEFT JOIN` while you are
developing, precisely so unmatched rows stay visible, then decide deliberately whether
to keep or exclude them. The choice should be yours, not the join's.

### 5.6.2 The duplicate external ID that fails the whole batch

`OP-1001-0020` and `OP-1001-0020-REV` are an operation and its revision. Both derive the
same external ID `WO-1001-0020`, and CDF rejects the entire request:

```
Duplicate node externalIds for space 'isp_<YOURNAME>_TRN' present in request: WO-1001-0020
```

⚠️ `[COMMON MISTAKE]` Reaching for `DISTINCT`. It cannot help — the rows genuinely
differ, that is the point. You must *choose* a winner:

```sql
row_number() over (partition by opExternalId order by sourceKey desc) as rn
...
where rn = 1
```

`ORDER BY` inside the window is where you encode the business rule: newest wins, highest
revision wins, most complete wins. Make it explicit; a future reader cannot guess it.

### 5.6.3 The NULL that eats your external ID

`OP-1003-BLANK` has no `operationNumber`. In Spark, `concat()` returns **NULL** if any
argument is NULL — so the external ID for that row is not `"WO-1003-"`, it is nothing at
all, and the row fails to ingest.

```sql
concat(
  nullif(trim(cast(o.`workOrderNumber`  as STRING)), ''),
  '-',
  nullif(trim(cast(o.`operationNumber` as STRING)), '')
) as opExternalId
...
where opExternalId is not null
```

`nullif(trim(x), '')` turns the blank cells RAW hands you into real NULLs, so the guard
can catch them. Without it, an empty string sails through and you create a node with a
malformed ID that nothing will ever match.

💡 `[GOOD TO KNOW]` Filtering the row out is the *right* behaviour — but log it. A
silently discarded record and a correctly excluded record look identical from the
outside. [Chapter 14](14-debugging-broken-links.md) section 14.5 shows you how to find them.

### 5.6.4 The reference that points at nothing

`OP-1001-0030` names asset `21-XX-9999`, which does not exist.

```sql
array(node_reference('isp_<YOURNAME>_TRN', tagExternalId)) as assets
```

`node_reference()` builds a reference out of a string. It does **not** check that the
string names anything — and what happens next surprises most people:

> `auto_create_direct_relations` defaults to **True**. CDF does not reject the bad
> reference and does not leave it dangling. It **creates** `21-XX-9999` as a bare node
> with no properties at all.

So after this runs you have a brand-new asset in your graph that nobody designed, which
is invisible through `CogniteAsset` (it has no data in any container that view maps) but
perfectly real in the registry. Your asset count stays at 8; your node count goes up.

### The production setting this chapter deliberately does not use

The default is not the only option. A Transformation destination can refuse to invent
targets:

```yaml
destination:
  type: nodes
  view:
    space: cdf_cdm
    externalId: CogniteActivity
    version: v1
  instanceSpace: isp_<YOURNAME>_TRN
  autoCreate:
    directRelations: false     # a reference to a node that does not exist now FAILS
```

⚡ `[OPTIMIZE]` **In production this is usually what you want**, and the reasoning is the
whole trade-off in one line: with `true`, a typo becomes a silent phantom you find months
later ([Chapter 14](14-debugging-broken-links.md)); with `false`, a typo becomes a failed
job you find in ten minutes.

The cost is real, though, and it is the reason the default exists: **`false` makes load
order mandatory.** If operations load before the assets they reference, the job fails —
correctly, but at 03:00. You then need the dependency ordering of
[Chapter 12](12-workflows.md) to be right, not merely tidy.

ℹ️ `[INFO]` This course leaves it at the default **on purpose**, so that
[Chapter 14](14-debugging-broken-links.md) has a real phantom to hunt. That is a teaching
decision, not a recommendation. When you build the real thing, decide this consciously
and write down which way you went and why.

⚠️ `[COMMON MISTAKE]` Assuming a typo'd reference will fail loudly, or at least leave a
detectably broken link. It does neither. This is the single most silent failure in the
whole course, and hunting it is the first thing you do in
[Chapter 14](14-debugging-broken-links.md) section 14.3.

You cannot fix this one in SQL: nothing about the row is malformed. The data is simply
wrong, and it has to be fixed at the source.

### 5.6.5 The leading zeros RAW silently ate

One more, and it is the kind that survives review because the output *looks* fine.

SAP operation numbers are `0010`, `0020`, `0030`. Your CSV says exactly that. But RAW
**infers types on upload**, sees a column of digits, and stores it as an **integer** —
so `0010` comes back as `10`, and `cast(... as STRING)` gives you `"10"`.

Your external IDs become `WO-1001-10` instead of `WO-1001-0010`: still unique, still
functional, and no longer matching the source system anybody will cross-reference them
against.

```sql
lpad(nullif(trim(cast(o.`operationNumber` as STRING)), ''), 4, '0')
```

✅ `[VERIFY]` Read the RAW row back and look at the Python type, not the rendering:

```python
row = client.raw.rows.retrieve(db_name=f"rwd_{YOURNAME}_Training_TRN",
                               table_name="rwt_Training_TRN_WorkOrderOperations",
                               key="OP-1001-0010")
print(repr(row.columns["operationNumber"]), type(row.columns["operationNumber"]))
```

You will see `10 <class 'int'>`, not `'0010'`.

💡 `[GOOD TO KNOW]` This applies to anything zero-padded: cost centres, well numbers,
ISO codes, phone numbers. If a leading zero carries meaning, either pad it back
explicitly as above, or make sure the source writes a value RAW cannot read as a number.

### 5.6.6 The finished transformation

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/transformations/tra_<YOURNAME>_Training_TRN_Load_WorkOrderOperations.Transformation.yaml`

```yaml
externalId: tra_<YOURNAME>_Training_TRN_Load_WorkOrderOperations
name: tra_<YOURNAME>_Training_TRN_Load_WorkOrderOperations
dataSetExternalId: dts_<YOURNAME>_Training_TRN
ignoreNullFields: true
conflictMode: upsert
isPublic: true
destination:
  type: nodes
  view:
    space: cdf_cdm
    externalId: CogniteActivity
    version: v1
  instanceSpace: isp_<YOURNAME>_TRN
authentication:
  clientId: ${TRAINING_CDF_CLIENT_ID}
  clientSecret: ${TRAINING_CDF_CLIENT_SECRET}
  tokenUri: ${IDP_TOKEN_URL}
  cdfProjectName: ${CDF_PROJECT}
  scopes: ${IDP_SCOPES}
```

📝 `[WRITE]` `.../transformations/tra_Training_TRN_Load_WorkOrderOperations.sql` — the
full query is in the reference module at
`training/modules/reference/transformations/`, with every clause commented against the
subsection it came from. Type it yourself; the comments are the lesson.

✅ `[VERIFY]` After running it:

| Check | Expected |
|---|---|
| Source rows | 8 |
| Nodes created | 6 |
| Dropped for NULL external ID | 1 (`OP-1003-BLANK`) |
| Dropped by deduplication | 1 (`OP-1001-0020-REV`) |
| Kept but orphaned | 1 (`WO-9999-0010`) |
| Kept, pointing at an autocreated phantom | 1 (`WO-1001-0030` → `21-XX-9999`) |
| Activities in your space afterwards | 9 — 6 operations **plus** your 3 work orders |

If you get 8 nodes, your NULL guard or your dedup is missing. If you get 5, you used an
`INNER JOIN`. If the run fails outright, you have the duplicate ID.

---

## 5.7 [LIMITS] and [OPTIMIZE]

🚧 `[LIMITS]`

- Transformations run on a shared Spark cluster with per-project scheduling and
  concurrency limits — a runaway wide join can starve other transformations in the
  same project. Keep joins narrow and filtered.
- `authentication:` credentials are evaluated at **run time**, not deploy time — this
  is exactly why the two-identity trap from [Chapter 02](02-auth-and-security.md)
  doesn't surface until the transformation actually runs.

⚡ `[OPTIMIZE]`

- **Idempotent loads**: `conflictMode: upsert` + `ignoreNullFields: true` means
  re-running any of these five transforms any number of times converges to the same
  state — it never duplicates nodes and never wipes a property to null just because
  this run's `select` didn't include it. This is not an accident; it's why you can
  safely re-run the whole pipeline in [Chapter 12](12-workflows.md) without fear.
- **Staging discipline**: RAW → Transformation → model, never source system →
  Transformation → model directly. If a transform ever fails, you still have the
  RAW rows to re-run against; you haven't lost provenance.
- Avoid wide scans: the first four transforms read exactly one RAW table each. The
  fifth (section 5.6) joins two — and when you join, filter each side down **before** the
  join, not after, or you pay for rows you are about to discard.

📚 `[DOCS]` https://docs.cognite.com/cdf/integration/guides/transformation/write_sql_queries ·
https://docs.cognite.com/cdf/integration/guides/transformation/troubleshooting

---

## 5.7b [OPTIMIZE] Three things these five transformations do not do

Your five transformations are correct for eight assets and wrong for eight million, in
three specific ways. None of them is a bug here. All three are the first questions a
reviewer will ask about the real thing.

### 1. They re-read the whole table, every run

Every `select` above scans its RAW table end to end. At this scale that is free. At
production scale it is the difference between a nightly job that finishes and one that
does not.

CDF Transformations give you a watermark for this — `is_new()`:

```sql
select
  cast(`workOrderNumber` as STRING) as externalId,
  ...
from `rwd_<YOURNAME>_Training_TRN`.`rwt_Training_TRN_WorkOrders`
where is_new('workorders_watermark', lastUpdatedTime)
```

The first argument is a **name you choose** for the watermark; the second is the column
it advances on. On each successful run CDF records the high-water mark under that name,
and the next run sees only rows past it.

✅ `[VERIFY]` Four things about that watermark, measured against a live project rather
than assumed — build a two-row table, a transformation, and watch it:

| Claim | Measured |
|---|---|
| The first run under a fresh watermark name processes everything | ✅ both rows written |
| An immediate re-run, nothing changed, processes nothing | ✅ zero rows written |
| A row whose watermark column **advances** is picked up | ✅ only that row |
| A row edited **without** advancing the column is picked up | ❌ **never** — the edit is invisible |

⚠️ `[COMMON MISTAKE]` That last row is the one that costs you. Advancing on a column the
source system does not actually update means an edit to an existing row is invisible to
`is_new()` **forever** — not late, not eventually: never. If `lastUpdatedTime` is set when
the row is created and never touched again, you have built a pipeline that can only ever
see inserts. Check what the column *means* in the source, not what it is called.

💡 `[GOOD TO KNOW]` The watermark is scoped to the **transformation**, not to the name
alone. Two transformations using the same watermark name were measured not to interfere:
the second still processed every row on its first run, because it had its own watermark.
Convenient, and worth knowing before you spend an afternoon assuming the opposite — but
still name them distinctly, because the name is what you will read in six months when you
are trying to work out which job is stuck.

🚧 `[LIMITS]` A watermark is state that lives in CDF, not in your repository. It survives
`cdf deploy`, so re-deploying a transformation does **not** replay history — and after a
teardown that removed your instances but left the transformation, a re-run loads
*nothing* and the tables look mysteriously empty. That is the single most confusing
consequence of incremental loading, and it is why this course loads in full: a learner
who re-runs Chapter 05 must get their data back.

### 2. They have nowhere to put a bad row

Section 5.6 taught you to *filter out* rows that would break the load — a null external
ID, a duplicate, a reference to nothing. Filtering makes the job succeed. It also makes
the bad rows **disappear**, and nobody is counting them.

```sql
-- the load: only rows that are safe to write
where `operationId` is not null and `workOrderNumber` is not null

-- the quarantine: a second transformation, same source, opposite predicate
where `operationId` is null or `workOrderNumber` is null
```

Point the second one at a RAW table — `rwt_Training_TRN_WorkOrderOperations_rejected` —
and you have turned silent data loss into a queue somebody can work. The pattern is the
same one [Chapter 17](17-cross-cutting-mastery.md) section 17.1c applies to
contextualization: *"we looked at this and could not use it"* is information, and
discarding it is how a backlog becomes invisible.

⚡ `[OPTIMIZE]` The two predicates must be exact complements. Write them as one
`case` expression feeding both jobs if you can, because the day they drift is the day
rows fall between them and are in neither place.

### 3. They cannot express a deletion

`conflictMode: upsert` writes and updates. Nothing in these five transformations can
say *"this work order no longer exists"*. Delete a row from RAW and re-run: the node
stays, forever, with no indication it is orphaned.

This is the same problem the contextualization spine solves with `superseded`
([Chapter 17](17-cross-cutting-mastery.md) section 17.1c) — **silence is not agreement** —
and it has the same two honest answers:

| Approach | How | When |
|---|---|---|
| **Tombstones** | The source emits a row marked deleted; the transformation writes a status property rather than removing the node | When downstream consumers need to know it *was* deleted — almost always, in maintenance data |
| **Reconcile and remove** | A separate job lists what the model holds, diffs it against what the source now contains, and deletes the difference | When the source genuinely cannot emit deletions |

⚠️ `[COMMON MISTAKE]` Reaching for `conflictMode: delete` to solve this. It is not a
reconciliation mode — it deletes the rows your `select` **returns**, which is the exact
opposite of the rows you want gone.

💡 `[GOOD TO KNOW]` Tombstones interact badly with `is_new()` if you are not careful: a
deletion row must update the watermark column, or the incremental load will never see
it. A model where deletions are invisible to the very mechanism that reads changes is
a common and expensive combination of two individually sensible decisions.

---

## 5.8 [ACTION] Build, deploy, run

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
import os
from cognite.client import CogniteClient
from cognite.client.config import ClientConfig
from cognite.client.credentials import OAuthClientCredentials, OAuthInteractive

def cdf_client(client_name: str = "dm-handson") -> CogniteClient:
    """Same helper as Chapter 07 section 7.3. CogniteClient() with no arguments does NOT
    read .env -- the SDK dropped implicit construction in v8."""
    base   = os.environ.get("CDF_URL") or f"https://{os.environ['CDF_CLUSTER']}.cognitedata.com"
    scopes = [s for s in os.environ.get("IDP_SCOPES", f"{base}/.default").split(",") if s]
    if os.environ.get("LOGIN_FLOW", "interactive").lower() == "interactive":
        creds = OAuthInteractive(authority_url=os.environ["IDP_AUTHORITY_URL"],
                                 client_id=os.environ["IDP_CLIENT_ID"], scopes=scopes)
    else:
        creds = OAuthClientCredentials(token_url=os.environ["IDP_TOKEN_URL"],
                                       client_id=os.environ["IDP_CLIENT_ID"],
                                       client_secret=os.environ["IDP_CLIENT_SECRET"],
                                       scopes=scopes)
    return CogniteClient(ClientConfig(client_name=client_name,
                                      project=os.environ["CDF_PROJECT"],
                                      base_url=base, credentials=creds))

from cognite.client.data_classes.data_modeling import ViewId

client = cdf_client()   # see Chapter 07 section 7.3
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
