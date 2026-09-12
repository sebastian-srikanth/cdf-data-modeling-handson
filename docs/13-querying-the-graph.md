# Chapter 13 — Querying the graph

**Goal:** stop reading your data model in the Fusion UI and start asking it questions in
code. By the end you will have answered, with real queries against your own graph:
*which work orders touch the failing pump, what do they cost, and what is still open?*

You have spent twelve chapters building a knowledge graph. You have never once queried
it directly — every check so far has been "look at it in Fusion" or "the SDK helper
returned something." That is the gap this chapter closes. Everything an application,
a dashboard, or an Atlas AI agent does to your model, it does through these endpoints.

📝 `[WRITE]` `docs/notebooks/07_query_the_graph.ipynb` — this chapter runs entirely in a
notebook. Recreate it cell by cell as you read, the same way you did in
[Chapter 07](07-entity-matching.md).

---

## 13.1 [INFO] Five endpoints, and which one you actually want

Everything below sits on the Data Modeling instances API. Reaching for the wrong one is
the most common reason a "slow model" is actually a slow query.

| Endpoint | SDK call | Use it when |
|---|---|---|
| `/list` | `instances.list(...)` | You want instances of one view, optionally filtered. The simplest thing that works — start here |
| `/byids` | `instances.retrieve(...)` | You already know the exact `(space, externalId)` pairs |
| `/query` | `instances.query(...)` | You need to **traverse** — start at a pump, walk to its work orders, then to their operations, in one round trip |
| `/search` | `instances.search(...)` | A human typed a word and you want ranked text matches |
| `/aggregate` | `instances.aggregate(...)` | You want a **count or a statistic**, not the rows. Never fetch 10,000 nodes to count them |
| `/sync` | `instances.sync(...)` | You already hold a copy of the data and only want what changed |

⚠️ `[COMMON MISTAKE]` Using `/query` for everything because it is the most powerful. A
traversal query has a cost a flat `list` does not. If you are not following a
relationship, do not pay for one.

📚 `[DOCS]` https://docs.cognite.com/cdf/dm/dm_concepts/dm_querying

---

## 13.2 [ACTION] Connect, and count what you built

🟢 `[ACTION]` First cell — the same client bootstrap you used in Chapter 07:

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

from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path.cwd().parents[1] / ".env")   # repo-root .env
client = cdf_client()   # see Chapter 07 section 7.3

YOURNAME       = os.environ["PARTICIPANT"]          # e.g. "ALICE"
INSTANCE_SPACE = f"isp_{YOURNAME}_TRN"
EDM_SPACE      = f"ssp_{YOURNAME}_TrainingCore_edm"
SDM_SPACE      = f"ssp_{YOURNAME}_MaintenanceInsight_sdm"
MODEL_VERSION  = "v1.0.0"
print(client.config.project, INSTANCE_SPACE)
```

🔧 `[CHANGE]` `PARTICIPANT` must be set in your `.env`, or replace `os.environ[...]`
with your literal name.

Now the cheapest possible question: **how many assets did I create?**

🟢 `[ACTION]`

```python
from cognite.client.data_classes.data_modeling import ViewId
from cognite.client.data_classes.aggregations import Count
from cognite.client.data_classes import filters as flt

ASSET = ViewId("cdf_cdm", "CogniteAsset", "v1")

res = client.data_modeling.instances.aggregate(
    view=ASSET,
    aggregates=Count("externalId"),
    filter=flt.SpaceFilter(INSTANCE_SPACE, "node"),
)
print(res)
```

✅ `[VERIFY]` You should see a count of **8** — the eight rows of
`rwt_Training_TRN_Assets.Table.csv` from [Chapter 04](04-data-sets-raw-and-files.md).

⚡ `[OPTIMIZE]` Note what this did **not** do: it never transferred eight nodes to your
laptop. `/aggregate` computes server-side. At eight rows that is irrelevant; at eight
million it is the difference between a dashboard that loads and one that times out.

💡 `[GOOD TO KNOW]` `SpaceFilter` is doing real work here. Without it you would be
counting every `CogniteAsset` in the project — including all fifteen other
participants'. Your space is your scope.

---

## 13.3 [INFO] Why `/query` has three parts

`list` and `aggregate` take arguments. `/query` takes a small **program**, and the
shape of that program is the thing worth learning:

```
Query(
    with_  = { ... }   # 1. the result sets: WHAT to find, and how to walk between them
    select = { ... }   # 2. for each result set, WHICH properties to return
    parameters = {}    # 3. optional: values injected at run time
)
```

- **`with_`** is a named dictionary of *result set expressions*. Each one is either a
  set of nodes or a set of edges. Crucially, a result set can start **`from_`** another
  one — that chaining is how traversal works.
- **`select`** decides what comes back. A result set that appears in `with_` but not in
  `select` is still computed (it may be a stepping stone) but its properties are not
  transferred. Use that deliberately.
- **`parameters`** lets you write the query once and run it with different values.

ℹ️ `[INFO]` A result set that is neither selected nor chained from is dead weight — it
still costs a little to plan. Delete it rather than leaving it commented out.

---

## 13.4 [ACTION] Your first real query — find the failing pump

🟢 `[ACTION]`

```python
from cognite.client.data_classes.data_modeling.query import (
    Query, NodeResultSetExpression, Select, SourceSelector,
)

q = Query(
    with_={
        "pump": NodeResultSetExpression(
            filter=flt.And(
                flt.SpaceFilter(INSTANCE_SPACE, "node"),
                flt.Equals(["node", "externalId"], "21-PA-2001A"),
            ),
            limit=1,
        )
    },
    select={
        "pump": Select([SourceSelector(ASSET, ["name", "description", "tags"])])
    },
)

result = client.data_modeling.instances.query(q)
for node in result["pump"]:
    print(node.external_id, "|", node.properties[ASSET])
```

✅ `[VERIFY]` One node, external ID `21-PA-2001A`, description
`Crude oil export pump A`.

⚠️ `[COMMON MISTAKE]` Writing `ASSET.as_property_ref("externalId")` here. It looks
right and it fails:

```
Property identifier cannot be one of the reserved values:
[space, externalId, createdTime, lastUpdatedTime, deletedTime, ...]
```

`externalId` is not a *view property* — it belongs to the **node itself**, alongside
`space` and `createdTime`. Reference those with the literal two-element path
`["node", "externalId"]`. Use `as_property_ref(...)` only for properties your view
actually declares — `workOrderNumber`, `status`, `assets`.

---

## 13.5 [ACTION] Which work orders touch the failing pump?

This is the question the whole course has been building toward. Your work orders carry
`assets`, a direct relation pointing at the pump. You want the reverse: given the pump,
find everything pointing at it.

Your first instinct will be to traverse inwards. **Try it, so you meet the error:**

```python
WORKORDER = ViewId(EDM_SPACE, "WorkOrder", MODEL_VERSION)

q = Query(
    with_={
        "pump": NodeResultSetExpression(
            filter=flt.Equals(["node", "externalId"], "21-PA-2001A"), limit=1),
        "orders": NodeResultSetExpression(
            from_="pump",
            through=WORKORDER.as_property_ref("assets"),
            direction="inwards", limit=100),
    },
    select={"orders": Select([SourceSelector(WORKORDER, ["workOrderNumber"])])},
)
client.data_modeling.instances.query(q)
```

```
CogniteAPIError: Cannot traverse lists of direct relations inwards. | code: 400
```

🚧 `[LIMITS]` **You cannot walk a *list* of direct relations backwards.** `assets` is a
list — one activity can touch several assets — and DMS does not maintain a reverse index
for list membership. Traversing *outwards* (order → its assets) is fine. Inwards is not.

This is the single most important structural decision in the whole chapter, so it is
worth stating plainly:

| What you need | Model it as | Reverse traversal |
|---|---|---|
| A simple pointer, reverse lookups rare | Direct relation (single) | Works |
| One-to-many, and you mostly read forwards | **List** of direct relations | **Not traversable inwards** |
| Reverse navigation is a first-class operation | **Edge** | Works from both ends |
| Reverse navigation on a *single* direct relation | Direct relation + a **reverse direct relation** property on the target view | Works |

🟢 `[ACTION]` What actually works here is a **filter**, not a traversal — ask which work
orders contain the pump in their list:

```python
PUMP = {"space": INSTANCE_SPACE, "externalId": "21-PA-2001A"}

orders = client.data_modeling.instances.list(
    sources=WORKORDER,
    space=INSTANCE_SPACE,
    limit=-1,
    filter=flt.ContainsAny(WORKORDER.as_property_ref("assets"), [PUMP]),
)
for n in orders:
    p = n.properties[WORKORDER]
    print(f"   {p['workOrderNumber']:<9} {str(p['status']):<12} "
          f"{p.get('actualCost')} {p.get('currency')}")
```

✅ `[VERIFY]` Exactly one order: **WO-1001**, `IN_PROGRESS`, 18500 EUR — the seal
replacement on the failing pump. `WO-1002` and `WO-1003` point at the separator, so they
are correctly absent.

⚠️ `[COMMON MISTAKE]` Using `Equals` instead of `ContainsAny` on a list property. It
fails with *"Invalid value for list property"*. `Equals` compares the whole value;
`ContainsAny` asks whether the list contains one of your candidates.

⚡ `[OPTIMIZE]` This is why [Chapter 03](03-data-modeling.md) put a btree index on the
`asset` direct relation. Filtering an unindexed relation is a full scan.

### Walking a *single* direct relation backwards — the row that says "Works"

`WorkOrder.assets` is a **list**, so it is a dead end inwards. But
`EquipmentHealthProfile.asset` is a **single** direct relation, and that one reverses.
This is the fourth row of the table above, and the reason
[Chapter 03](03-data-modeling.md) section 3.12 had you declare `healthProfile` on your `Asset`
view.

🟢 `[ACTION]` Same query shape that just failed — one property, not a list:

```python
EHP = ViewId(SDM_SPACE, "EquipmentHealthProfile", MODEL_VERSION)

q = Query(
    with_={
        "pump": NodeResultSetExpression(
            filter=flt.Equals(["node", "externalId"], "21-PA-2001A"), limit=1),
        "profile": NodeResultSetExpression(
            from_="pump",
            through=EHP.as_property_ref("asset"),   # the FORWARD property
            direction="inwards", limit=10),
    },
    select={"profile": Select([SourceSelector(EHP, ["ratedPowerKw", "sealType"])])},
)
res = client.data_modeling.instances.query(q)
for n in res["profile"]:
    print(n.external_id, n.properties[EHP])
```

✅ `[VERIFY]` One node — `ehp_21-PA-2001A` — with its rated power and seal type. No
`Cannot traverse lists` error, because `asset` is singular.

💡 `[GOOD TO KNOW]` Notice what `through` names: the **forward** property on the view
that does the pointing (`EquipmentHealthProfile.asset`), *not* the `healthProfile`
property you declared on `Asset`. `/query` walks the underlying relation directly.

🚧 `[LIMITS]` So what did declaring the reverse direct relation in Chapter 03 actually
buy you, if `/query` works without it? Be precise about this, because it is widely
misunderstood:

| | Raw `/query` traversal | Declared reverse direct relation |
|---|---|---|
| Works at all | yes | yes |
| Shows up in GraphQL / the data model's schema | **no** | yes |
| Navigable in Fusion, Canvas, Search | **no** | yes |
| An Atlas AI agent can discover and follow it | **no** | yes |
| Costs storage | no | no |

The declaration does not enable the traversal — it **publishes** it. Anything that reads
your model rather than hand-writing queries against it (an application, a UI, an agent)
can only see connections the model declares. That is the whole argument for spending a
schema change on something that stores nothing.

---

## 13.6 [ACTION] The operations on that pump — and a surprise

[Chapter 05](05-transformations.md) section 5.6 loaded work-order **operations** as
`CogniteActivity` nodes. Same shape of question, same filter:

```python
ACTIVITY = ViewId("cdf_cdm", "CogniteActivity", "v1")

acts = client.data_modeling.instances.list(
    sources=ACTIVITY, space=INSTANCE_SPACE, limit=-1,
    filter=flt.ContainsAny(ACTIVITY.as_property_ref("assets"), [PUMP]))
for n in sorted(acts, key=lambda x: x.external_id):
    print(" ", n.external_id)
```

✅ `[VERIFY]` You get **four** nodes, and one of them is `WO-1001` — a *work order*, not
an operation.

ℹ️ `[INFO]` That is not a bug. Your `WorkOrder` view **implements** `CogniteActivity`, so
every work order *is* a Cognite activity. Querying the parent view returns both concepts.
Whenever you query a CDM view, you are querying everything that implements it.

🟢 `[ACTION]` To count operations alone, subtract the work orders:

```python
wo_ids = {n.external_id for n in client.data_modeling.instances.list(
    sources=WORKORDER, space=INSTANCE_SPACE, limit=-1)}

all_acts = client.data_modeling.instances.list(
    sources=ACTIVITY, space=INSTANCE_SPACE, limit=-1)
ops = [a for a in all_acts if a.external_id not in wo_ids]

print("activities:", len(all_acts), "| work orders:", len(wo_ids), "| operations:", len(ops))
```

✅ `[VERIFY]` `activities: 9 | work orders: 3 | operations: 6`. Hold on to that **6** —
[Chapter 14](14-debugging-broken-links.md) opens with it.

---

## 13.7 [INFO] `hasData`, and the filter you did not write

Deploy a view, populate nothing, and the view shows `0`. Everyone accepts that. The
confusing version is: deploy a view, populate it, and it **still** shows `0`.

> If no filter is specified, a default **`hasData`** filter is applied to the views
> being queried. There is an implicit **AND** between every container the view
> references — the node must have data in **all** of them.

Your `EquipmentHealthProfile` view is exactly the shape that triggers this. It
implements `CogniteDescribable`, so it references **two** containers: your own
`EquipmentHealthProfile`, and `cdf_cdm:CogniteDescribable`. A node with parsed
datasheet specs but no `name` has data in one container, not both — so it does not
match, and the view looks empty.

🟢 `[ACTION]` Prove it to yourself:

```python
from cognite.client.data_classes.data_modeling.instances import InvolvedContainers

EHP = ViewId(SDM_SPACE, "EquipmentHealthProfile", MODEL_VERSION)

print("through the view :", len(client.data_modeling.instances.list(
    sources=EHP, space=INSTANCE_SPACE, limit=-1)))

print("in the registry  :", client.data_modeling.instances.inspect(
    nodes=(INSTANCE_SPACE, "ehp_21-PA-2001A"),
    involved_containers=InvolvedContainers()))
```

⚠️ `[COMMON MISTAKE]` Calling `inspect()` with only `nodes=`. It raises
*"Must pass at least one of 'involved_views' or 'involved_containers'"* — you have to
tell it which of the two answers you want. `InvolvedContainers()` is the one that
settles a `hasData` argument, because containers are where data actually lives.

✅ `[VERIFY]` `inspect()` is the ground truth — it reports which containers the node
actually has data in, regardless of any view. If the node appears in `inspect` but not
in the view listing, you have met the `hasData` filter.

⚠️ `[COMMON MISTAKE]` "Fixing" this by putting a bare `hasData` filter on the view to
force the instances to appear. **Do not.** A standalone `hasData` filter is ignored by
the `/inspect` endpoint that Canvas and Search rely on, so you get instances that show
up in one application and vanish in another. The real fix is to populate the missing
container — which is why [Chapter 10](10-datasheet-parsing.md) writes `name` and
`description` alongside the specs.

📚 `[DOCS]` https://docs.cognite.com/cdf/dm/dm_concepts/dm_querying#hasdata-filter

---

## 13.8 [ACTION] Aggregate — the shape of the backlog

🟢 `[ACTION]` Count work orders by type:

```python
for bucket in client.data_modeling.instances.aggregate(
    view=WORKORDER,
    aggregates=Count("externalId"),
    group_by="orderType",
    filter=flt.SpaceFilter(INSTANCE_SPACE, "node"),
):
    print(bucket)
```

✅ `[VERIFY]` Two buckets — `PM01` with 2, `PM02` with 1.

⚠️ `[COMMON MISTAKE]` Grouping by `status`. It is the obvious thing to want, and it
fails:

```
Property 'status' of type enum cannot be used in group by.
Supported types are [text, text[], direct, direct[], int32, int64, float32, float64, numeric, boolean]
```

**`group_by` does not accept enum properties.** You modelled `status` as an enum in
[Chapter 03](03-data-modeling.md) — which is the right call for data quality, because it
constrains what can be written. The cost is that you cannot group on it. Either count
each value with a filter, or model the property as `text` if grouping matters more than
validation. Know which trade you are making.

🟢 `[ACTION]` Counting one enum value with a filter instead:

```python
open_wo = client.data_modeling.instances.list(
    sources=WORKORDER, space=INSTANCE_SPACE, limit=-1,
    filter=flt.Equals(WORKORDER.as_property_ref("status"), "OPEN"))
print("open:", [n.external_id for n in open_wo])
```

✅ `[VERIFY]` `['WO-1002']`.

🟢 `[ACTION]` And a statistic rather than a count:

```python
from cognite.client.data_classes.aggregations import Avg, Max
print(client.data_modeling.instances.aggregate(
    view=WORKORDER,
    aggregates=[Avg("actualCost"), Max("actualCost")],
    filter=flt.SpaceFilter(INSTANCE_SPACE, "node"),
))
```

✅ `[VERIFY]` Average 30250.0, max 42000.0 — computed from WO-1001 and WO-1003 only,
because `WO-1002` has no `actualCost`. **A null is not a zero**, and aggregates skip it
rather than dragging the mean down.

🚧 `[LIMITS]` `/aggregate` and `/search` are **eventually consistent** — a few seconds
can pass before a write shows up. If you write then immediately aggregate and the number
looks stale, wait and re-run before you start debugging.

---

## 13.9 [ACTION] Search — when a human typed the word

🟢 `[ACTION]`

```python
hits = client.data_modeling.instances.search(
    view=WORKORDER,
    query="seal",
    properties=["name", "description"],
    filter=flt.SpaceFilter(INSTANCE_SPACE, "node"),
    limit=10,
)
for h in hits:
    print(h.external_id, "|", h.properties[WORKORDER]["workOrderNumber"])
```

✅ `[VERIFY]` `WO-1001` — "Replace mechanical seal on 21-PA-2001A."

💡 `[GOOD TO KNOW]` `search` ranks by relevance; `list` with a `Prefix` filter matches
exactly. Search is for people, filters are for programs. Do not use `search` to build
a pipeline — the ranking is not a contract.

---

## 13.10 [ACTION] Sync — read once, then only the changes

A dashboard that re-reads your whole model every 30 seconds is how you turn a small
model into a support ticket. `/sync` hands you a cursor and then returns only what
changed since it.

🟢 `[ACTION]`

```python
from cognite.client.data_classes.data_modeling.query import QuerySync

sq = QuerySync(
    with_={"orders": NodeResultSetExpression(
        # SpaceFilter alone would sync EVERY node in the space -- assets, files,
        # operations, all of it. HasData narrows it to instances that actually
        # carry WorkOrder data. This is the explicit form of the implicit filter
        # from 13.7, used deliberately.
        filter=flt.And(
            flt.SpaceFilter(INSTANCE_SPACE, "node"),
            flt.HasData(views=[WORKORDER]),
        ),
        limit=100)},
    select={"orders": Select([SourceSelector(WORKORDER, ["workOrderNumber", "status"])])},
)

first = client.data_modeling.instances.sync(sq)
print("initial:", len(first["orders"]), "orders")

sq.cursors = first.cursors           # carry the cursor forward
again = client.data_modeling.instances.sync(sq)
print("since then:", len(again["orders"]), "changed")
```

✅ `[VERIFY]` The first call returns **3** orders; the second returns **0**, because
nothing has changed. Edit one work order in Fusion, run the second call again, and
exactly one comes back.

💡 `[GOOD TO KNOW]` `/sync` also returns instances that have been **deleted**, carrying
a non-null `deletedTime`. That is how you keep a downstream copy honest — and it is the
mechanism [Chapter 14](14-debugging-broken-links.md) uses to undo an accidental delete.

🚧 `[LIMITS]` Sync **one space at a time**. Broad filters across many spaces perform
badly, and the endpoint does not support arbitrary sorting — results come back in
transaction order, not by `lastUpdatedTime`.

---

## 13.11 [LIMITS] What will bite you at scale

| Limit | Number | What to do |
|---|---|---|
| Default result set size | 100 | Set `limit` explicitly; you rarely want the default |
| Maximum per result set | 10,000 | Page with cursors, or narrow the filter |
| Query timeout | `408 Request Timeout` | Reduce `max_distance`, add filters, split the query |
| Traversal execution | Nested-loop, breadth-first | Fine to a few hundred thousand paths; fully connected graphs and loops will not finish |
| Search / aggregate freshness | Eventually consistent | Wait a few seconds after a write |

⚡ `[OPTIMIZE]` `max_distance` is the single biggest lever on a traversal. If you know
the answer is one hop away, say `max_distance=1` — the planner stops instead of
exploring your whole graph breadth-first.

### The `space=` trap — a wrong answer with no error

⚠️ `[COMMON MISTAKE]` The schema list endpoints take **one** space, not a list:

```python
client.data_modeling.containers.list(space=...)   # space: str | None
client.data_modeling.views.list(space=...)        # space: str | None
client.data_modeling.data_models.list(space=...)  # space: str | None
```

Hand them a list and you get **no error and no warning** — just the results for one of
your spaces. Your model spans two:

```python
edm, sdm = f"ssp_{YOURNAME}_TrainingCore_edm", f"ssp_{YOURNAME}_MaintenanceInsight_sdm"

# WRONG — silently returns only one space's views
views = client.data_modeling.views.list(limit=-1, space=[edm, sdm], include_global=False)
print(sorted(v.external_id for v in views))    # ['WorkOrder']  -- where did the other two go?

# RIGHT — list once, filter in Python
views = [v for v in client.data_modeling.views.list(limit=-1, include_global=False)
         if v.space in {edm, sdm}]
print(sorted(v.external_id for v in views))    # ['Asset', 'EquipmentHealthProfile', 'WorkOrder']
```

💡 `[GOOD TO KNOW]` `instances.list` **does** accept a sequence of spaces — which is
exactly why this catches people. Two neighbouring APIs, two different contracts. When a
list-shaped argument gives you a suspiciously short answer, check the signature before you
believe it.

---

## 13.12 ✅ Gate

Do not proceed until all of these are true:

- [ ] `aggregate` returns 8 assets in your instance space
- [ ] section 13.5's inward traversal fails, and you can say why a *list* cannot be walked backwards
- [ ] The `ContainsAny` filter returns **exactly** `WO-1001`
- [ ] section 13.6 gives 9 activities / 3 work orders / 6 operations, and you can explain the 9
- [ ] `inspect()` in section 13.7 tells you which containers your EHP node has data in
- [ ] `group_by="status"` fails because it is an enum; `orderType` gives two buckets
- [ ] The second `sync` call returns 0 changes
- [ ] You can say, in one sentence each, when you would use `list`, `query` and `aggregate`

You can now ask your model anything. Next you will use exactly these tools to find what
is **wrong** with it.

---

→ [Chapter 14 — Debugging broken links](14-debugging-broken-links.md)
