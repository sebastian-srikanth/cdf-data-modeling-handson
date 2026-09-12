# Chapter 14 — Debugging broken links

**Goal:** find out why your graph is quietly wrong, using the query tools from
[Chapter 13](13-querying-the-graph.md) — and learn the one habit that separates
engineers who fix data from engineers who guess at it.

Here is the number this whole chapter hangs on. `rwt_Training_TRN_WorkOrderOperations`
has **8 rows**. Your graph has **6 operation nodes**. The transformation reported
success.

> Two rows went missing and nobody told you. Two more arrived broken.
> None of that produced an error.

That is what makes data bugs different from code bugs. Code fails loudly. Data fails
silently, and the first person to notice is usually a reliability engineer six weeks
later asking why a pump has no maintenance history.

📝 `[WRITE]` `docs/notebooks/08_debug_broken_links.ipynb` — run this chapter in a
notebook, reusing the client setup from Chapter 13 section 13.2.

---

## 14.1 [INFO] Three ways a link breaks

Before hunting, know what you are hunting. Every broken link in a knowledge graph is
one of these:

| Class | What it looks like | Your example |
|---|---|---|
| **Phantom target** | The reference points at a node that exists but holds no data — so it is invisible through every view | `WO-1001-0030` points at `21-XX-9999` |
| **Orphaned** | The node exists, but the parent it belongs to was never created | `WO-9999-0010` belongs to work order `WO-9999` |
| **Absent** | The row never became a node at all | `OP-1003-BLANK` and `OP-1001-0020-REV` |

⚠️ `[COMMON MISTAKE]` Expecting a bad reference to *dangle*. It does not.
`auto_create_direct_relations` defaults to **True**, so when a transformation writes
`node_reference(space, '21-XX-9999')` and that asset does not exist, CDF **creates it**
— as a bare node with no properties in any container. Your reference resolves perfectly.
You simply have a new, empty asset in your graph that nobody meant to create.

That is why the check below compares against the **view**, not against existence.

The first two you find by querying the graph. The third you can only find by comparing
the graph **back against the source** — which is why "count your rows" is the first
step of every investigation.

⚠️ `[COMMON MISTAKE]` Only ever looking at what is in the graph. An absent record is
invisible from inside: there is nothing to query. If you never compare counts, you will
never know it is gone.

---

## 14.2 [ACTION] Count first — 8 in, 6 out

🟢 `[ACTION]`

```python
from cognite.client.data_classes.data_modeling import ViewId
from cognite.client.data_classes.aggregations import Count
from cognite.client.data_classes import filters as flt

ACTIVITY = ViewId("cdf_cdm", "CogniteActivity", "v1")

# What the graph holds
WORKORDER = ViewId(EDM_SPACE, "WorkOrder", MODEL_VERSION)

# What the graph holds. WorkOrder implements CogniteActivity, so subtract the
# work orders to get operations alone.
acts   = client.data_modeling.instances.list(
    sources=ACTIVITY, space=INSTANCE_SPACE, limit=-1)
wo_ids = {n.external_id for n in client.data_modeling.instances.list(
    sources=WORKORDER, space=INSTANCE_SPACE, limit=-1)}
ops    = [a for a in acts if a.external_id not in wo_ids]

# What the source holds
rows = client.raw.rows.list(
    db_name=f"rwd_{YOURNAME}_Training_TRN",
    table_name="rwt_Training_TRN_WorkOrderOperations",
    limit=-1,
)
print("source rows :", len(rows))       # 8
print("activities  :", len(acts))       # 9  <- operations AND work orders
print("operations  :", len(ops))        # 6
```

✅ `[VERIFY]` 8 source rows, **9 activities**, 6 operations.

The 9 catches people out. `WorkOrder` implements `CogniteActivity`, so your three work
orders *are* activities too — querying the parent view returns both concepts. Subtract
them to count operations alone, as the snippet does. 8 rows in, 6 operations out:
**now you have a question worth answering**, and you got it from cheap calls rather
than a hunch.

💡 `[GOOD TO KNOW]` This is the whole discipline in one move. A count mismatch turns
"something feels off" into "two records are missing" — which is falsifiable, and which
tells you when you are done.

---

## 14.3 [ACTION] Find the phantom target

`node_reference()` builds a reference out of a string and never checks that the string
names a real asset. Worse, autocreate then **materialises** the missing target as an
empty node — so "does it exist?" is the wrong question. The right question is
**"is it a real asset?"**, and the way to ask that is to compare against the view.

🟢 `[ACTION]` Get every asset an operation points at, then ask which of those are
actually visible as `CogniteAsset`:

```python
ASSET = ViewId("cdf_cdm", "CogniteAsset", "v1")

referenced = {}
for n in ops:
    for ref in (n.properties[ACTIVITY].get("assets") or []):
        referenced.setdefault((ref["space"], ref["externalId"]), []).append(n.external_id)

real_assets = {
    (n.space, n.external_id)
    for n in client.data_modeling.instances.list(
        sources=ASSET, space=INSTANCE_SPACE, limit=-1)
}

phantom = {k: v for k, v in referenced.items() if k not in real_assets}
for (space, xid), holders in phantom.items():
    print(f"  PHANTOM {xid}  <- referenced by {holders}")

# and prove it really is there, just empty:
print("exists as a node:",
      len(client.data_modeling.instances.retrieve(nodes=(INSTANCE_SPACE, "21-XX-9999")).nodes))
```

✅ `[VERIFY]` `PHANTOM 21-XX-9999 <- referenced by ['WO-1001-0030']`, and
`exists as a node: 1`.

Read those two lines together, because they are the whole lesson. The node **exists**.
It is **not** a `CogniteAsset`. Your asset count is still 8, not 9 — the view filters it
out because it has no data in any of the containers `CogniteAsset` maps. Autocreate gave
you a reference that resolves to nothing useful, and nothing anywhere reported an error.

ℹ️ `[INFO]` What you just wrote is an **anti-join**: everything referenced, minus
everything real. It is the single most useful query shape in graph debugging, and it
works the same way whatever the relation. The subtlety is choosing what "real" means —
here, *visible through the view*, not *present in the registry*.

⚡ `[OPTIMIZE]` `retrieve()` takes the whole list in one call. Do not loop and call it
per reference — that is a round trip per row, and it is how a five-second check becomes
a five-minute one.

---

## 14.4 [ACTION] Find the orphan

`WO-9999-0010` exists and its asset reference is fine. What is missing is its
**parent**: the work order it was booked against.

🟢 `[ACTION]`

```python
WORKORDER = ViewId(EDM_SPACE, "WorkOrder", MODEL_VERSION)

orders = {
    n.properties[WORKORDER]["workOrderNumber"]
    for n in client.data_modeling.instances.list(
        sources=WORKORDER, space=INSTANCE_SPACE, limit=-1)
}

for n in ops:
    parent = n.external_id.rsplit("-", 1)[0]      # "WO-1001-0020" -> "WO-1001"
    if parent not in orders:
        print(f"  ORPHAN {n.external_id}  (no work order {parent})")
```

✅ `[VERIFY]` One orphan: `WO-9999-0010`.

💡 `[GOOD TO KNOW]` This one survived *because* the transformation uses a `LEFT JOIN`.
Had it been an `INNER JOIN`, this row would have been silently dropped instead —
class **absent** rather than class **orphaned**. Neither is "correct" in the abstract;
what matters is that you chose, rather than the join choosing for you.

---

## 14.5 [ACTION] Find the absent — and trace them to source

Two rows never became nodes. The graph cannot tell you which. Compare the derived IDs.

🟢 `[ACTION]`

```python
from collections import Counter

# Map every source row to the external ID it would produce.
derived = {}
for r in rows:
    wo = (r.columns.get("workOrderNumber") or "").strip()
    op = (r.columns.get("operationNumber") or "").strip()
    derived[r.key] = f"{wo}-{op}" if (wo and op) else None

counts = Counter(x for x in derived.values() if x)
actual = {n.external_id for n in ops}

print("rows that produced no external ID at all:")
for k, xid in derived.items():
    if xid is None:
        print(f"   {k}  — blank operationNumber, so concat() returned NULL")

print("rows whose ID collided, so all but one lost deduplication:")
for k, xid in derived.items():
    if xid and counts[xid] > 1:
        print(f"   {k}  ->  {xid}   ({counts[xid]} rows compete for this one ID)")

print("IDs expected but genuinely missing:", sorted(
    {x for x in derived.values() if x} - actual))
```

✅ `[VERIFY]` Two rows are named, and the third line prints an **empty list**:

1. **`OP-1003-BLANK`** — `operationNumber` is blank, so `concat()` returned NULL and the
   `where opExternalId is not null` guard dropped the row. The guard is correct; the
   **source data** is wrong. Escalate it.
2. **`OP-1001-0020`** and **`OP-1001-0020-REV`** — two rows competing for the ID
   `WO-1001-0020`. One won the `ROW_NUMBER()` tiebreak, the other did not. Nothing is
   broken: that is deduplication doing its job.

⚠️ Read the third line carefully. *"IDs expected but genuinely missing"* is **empty** —
`WO-1001-0020` does exist, because one of the two competing rows created it. The naive
check "which expected IDs are absent?" would have reported nothing wrong at all and sent
you away happy. You have to count **rows**, not IDs, to see a collision.

⚠️ `[COMMON MISTAKE]` Treating both as bugs and "fixing" the dedup. One is a data
defect to escalate upstream; the other is your own logic behaving correctly. Telling
them apart is the job.

---

## 14.6 [INFO] Work upstream — the checklist

When something is missing, resist the urge to edit SQL. Walk the lineage instead, in
this order, and stop at the first step that fails:

| Step | Question | If it fails |
|---|---|---|
| 1 | Is the record in the **source** (RAW, or the classic resource)? | Not your bug — escalate to ingestion |
| 2 | Does the **join** keep it? Swap `INNER` for `LEFT` temporarily | Fix the join or the join key |
| 3 | Does a **`WHERE`** clause exclude it? Relax them one at a time | Fix the filter |
| 4 | Do the **required fields** survive? `externalId`, `space` non-null after every `concat` | Add `COALESCE` / `nullif` guards |
| 5 | Does it **ingest**? Preview the transformation before running it | Read the error; it is usually duplicate IDs |

Three rules make this fast:

- **Change one thing at a time.** Two changes and a different result tells you nothing.
- **Never experiment on the live transformation.** Duplicate it, point the copy at a
  scratch RAW table, break that instead.
- **Write down the root cause** when you find it. The next person — probably you in
  three months — starts from your note instead of from zero.

---

## 14.7 [ACTION] Fix it at the source

`21-XX-9999` is a typo in the source system. You could patch the graph, and it would be
correct until the next transformation run overwrites it. Fix the row instead.

🟢 `[ACTION]`

```python
from cognite.client.data_classes.raw import RowWrite

client.raw.rows.insert(
    db_name=f"rwd_{YOURNAME}_Training_TRN",
    table_name="rwt_Training_TRN_WorkOrderOperations",
    row=RowWrite(key="OP-1001-0030", columns={
        "operationNumber": "0030",
        "workOrderNumber": "WO-1001",
        "tagExternalId":   "21-PA-2001A",     # was 21-XX-9999
        "description":     "Replace outboard bearing",
        "durationHours":   "5",
        "craft":           "MECH",
    }),
)
```

⚠️ `[COMMON MISTAKE]` Writing `Row(...)` instead of `RowWrite(...)`. cognite-sdk 8.x
splits read and write classes: `Row` is what you *get back* (it carries
`lastUpdatedTime`), `RowWrite` is what you *send*. Using the read class raises
`TypeError: Row.__init__() missing 1 required positional argument: 'last_updated_time'`.
The same split shows up across the SDK — `DatabaseWrite`, `TableWrite`, `NodeApply`.

🟢 `[ACTION]` Re-run the transformation, then re-run section 14.3.

```bash
uv run cdf run transformation tra_<YOURNAME>_Training_TRN_Load_WorkOrderOperations
```

✅ `[VERIFY]` The dangling-reference check now prints nothing. The orphan in section 14.4 is
still there — you did not touch it, and that is correct: a missing work order is a
different problem with a different owner.

💡 `[GOOD TO KNOW]` Because the transformation is `conflictMode: upsert` and the
external ID did not change, this **updated** the existing node rather than creating a
second one. Had you fixed the typo by changing the operation number instead, you would
now own two nodes: the corrected one and the original, still dangling. External IDs
are identity — changing one is not an edit, it is a new object.

---

## 14.8 [INFO] The safety net — you have 72 hours

Delete an instance and it is not immediately gone. CDF **soft-deletes**: the instance
is flagged with a `deletedTime`, disappears from every normal query, and is permanently
removed by a garbage collector about **72 hours** later.

Inside that window it is recoverable through `/sync`.

🟢 `[ACTION]` Delete something on purpose, then watch `/sync` surface it.

**The order of these steps is the whole lesson.** `/sync` reports *changes since a
cursor*. If you ask it for changes without holding a cursor from **before** the delete,
it simply hands you current state — and a deleted instance is not in current state.

```python
from cognite.client.data_classes.data_modeling import NodeId
from cognite.client.data_classes.data_modeling.query import (
    QuerySync, NodeResultSetExpression, Select, SourceSelector)

victim = NodeId(INSTANCE_SPACE, "WO-1002-0010")

def ops_query():
    return QuerySync(
        with_={"ops": NodeResultSetExpression(
            filter=flt.SpaceFilter(INSTANCE_SPACE, "node"), limit=1000)},
        select={"ops": Select([SourceSelector(ACTIVITY, ["name"])])})

# 1. Take a cursor FIRST. This is the step people skip.
baseline = client.data_modeling.instances.sync(ops_query())
cursor   = baseline.cursors
print("baseline:", len(baseline["ops"]), "instances")

# 2. Now delete.
client.data_modeling.instances.delete(nodes=victim)
print("after delete, retrieve finds:",
      len(client.data_modeling.instances.retrieve(nodes=victim).nodes))

# 3. Sync FROM THAT CURSOR — the deletion shows up, stamped with deletedTime.
sq = ops_query(); sq.cursors = cursor
changes = client.data_modeling.instances.sync(sq)
for n in changes["ops"]:
    print("  changed:", n.external_id, "| deletedTime:", n.deleted_time)
```

✅ `[VERIFY]`

```
baseline: 46 instances
after delete, retrieve finds: 0
  changed: WO-1002-0010 | deletedTime: 1789199338184
```

⚠️ `[COMMON MISTAKE]` Calling `sync` fresh, with no cursor, and expecting deletions.
You get the current 45 instances and **zero** `deletedTime` values — the delete is
invisible, and it looks like the recovery story is a myth. It is not; you just asked
the wrong question. A cursorless sync means *"give me everything as it is now"*.

💡 `[GOOD TO KNOW]` This is exactly why a downstream copy — a dashboard, a search index,
a cache — has to persist its cursor between runs. Lose the cursor and you lose the
ability to learn about deletions at all; you can only ever re-read the survivors and
guess what went missing.

🟢 `[ACTION]` Restore it by re-running the transformation — the source row never went
anywhere, so the upsert recreates the node with the same identity.

✅ `[VERIFY]` `retrieve` finds `WO-1002-0010` again.

🚧 `[LIMITS]` Two things people get wrong about the grace period:

- Soft-deleted instances **still count** against your project's instance limits until
  they are collected. Deleting is not immediately freeing.
- `/sync` results are ordered by transaction, **not** by `lastUpdatedTime`, and cannot
  be sorted. Do not build recovery logic that assumes an order.

---

## 14.9 [INFO] Delete edges before nodes

Deleting a node **cascades** to every edge attached to it. Restoring the node does
**not** bring those edges back — you get your instance returned to you with all of its
connections gone, which is often worse than the original mistake.

So, when you delete deliberately:

1. Query the edges attached to the node first, and keep the list.
2. Delete the edges.
3. Delete the node.

That ordering also avoids a long-running cascade on a well-connected node. It matters
directly in [Chapter 19](19-teardown.md), where you remove the diagram annotations you
created in [Chapter 08](08-diagram-annotation.md) — those are edges, and they go first.

---

## 14.10 ✅ Gate

- [ ] You can explain 8 rows / 9 activities / 6 operations, and all four discrepancies
- [ ] The anti-join in section 14.3 found the phantom `21-XX-9999`, and you can explain why `retrieve` finds it but the view does not
- [ ] You found the orphan `WO-9999-0010` and can say why it is *not* the same bug
- [ ] You can explain why `OP-1001-0020-REV` being absent is correct behaviour
- [ ] You deleted a node, saw it in `/sync` with a `deletedTime`, and restored it
- [ ] You can recite the five-step lineage checklist without looking

You can now find what is wrong, prove it, fix it at the right layer, and undo yourself
if you are wrong. That is the last engineering skill this course owes you.

---

→ [Chapter 15 — Atlas AI agent](15-atlas-ai-agent.md)
