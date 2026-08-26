# Chapter 11 — Datapoints

**Goal:** write the actual sensor readings onto your six time series — the step that
turns "a pump with metadata" into "a pump that is visibly degrading."

---

## 11.1 [INFO] Why a Function, not a Transformation or a static CSV

[Chapter 05](05-transformations.md) created the six `CogniteTimeSeries` **nodes** —
metadata only, zero readings. You could, in principle, load a `*.Datapoints.csv`
through the Toolkit — but that keys off classic external IDs and freezes every
timestamp at authoring time: the moment the lab runs a day later than you wrote the
CSV, your "last 5 days" story is stale. A Function computes timestamps **relative to
`now()`** every time it runs, so the trend always ends "recently" no matter when you
call it — which is also why this is a Function and not a Transformation: writing
computed, time-relative numeric data isn't a clean deterministic RAW-to-model key
mapping (§5.1's rule).

---

## 11.2 [INFO] The story, encoded as math

Recall the hero story: vibration (`21-VT-2002`) ramps **2.1 → 7.4 mm/s** while flow
(`21-FT-2002`) falls **320 → 268 m³/h**, over the last 120 of 720 hourly points (the
last 5 days of a 30-day window) — explaining `WO-1001` ("replace mechanical seal").
The other four series get gentle sinusoidal noise with no trend — normal operation,
so the two degrading series stand out by contrast, not because everything is dramatic.

---

## 11.3 [WRITE] + [ACTION] Notebook: `05_generate_datapoints.ipynb`

📝 `[WRITE]` Recreate `docs/notebooks/05_generate_datapoints.ipynb`. Cell
order: auth → compute the 720-hour timestamp window → generate values per series
(normal noise for four, a degradation ramp for two) → write via
`client.time_series.data.insert(..., instance_id=NodeId(space, tag))` → inspect the
last few points of `21-VT-2002` to confirm the ramp is really there.

🟢 `[ACTION]` Run it, then plot (even a crude `print` of the last 10 values is
enough to see the ramp) `21-VT-2002` and `21-FT-2002` before moving on.

✅ `[VERIFY]` notebook results in CDF: open `21-VT-2002` in Fusion's time series
viewer over the last 5 days — you should see a visible upward ramp, not noise.

---

## 11.4 [WRITE] The Function: `GenerateDatapoints`

### What this Function does

[Chapter 05](05-transformations.md) created six `CogniteTimeSeries` **nodes** — metadata
shells with zero readings. This fills them: 720 hourly points × 6 tags = **4,320 readings**
across 30 days.

### The design in one sentence

Every reading is **baseline + gentle sine wave + random noise**, and three of the six tags
additionally get a **`degrade` term that is zero for 600 points and then ramps to full over
the final 120** — which is what makes vibration climb and flow fall in the last 5 days,
explaining work order `WO-1001` ("replace mechanical seal").

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/functions/fnc_<YOURNAME>_Training_GenerateDatapoints/handler.py`

```python
"""Generate 720 hourly datapoints per training timeseries with a degradation signature."""

from __future__ import annotations

import math
import os
import random
from datetime import datetime, timedelta, timezone

from cognite.client.data_classes.data_modeling import NodeId

SERIES = ["21-PT-2001", "21-TT-2001", "21-LT-2001", "21-FT-2002", "21-VT-2002", "21-PT-2003"]


def _value(tag: str, i: int, n: int) -> float:
    """i=0 is oldest; last 120 hours carry the degradation signature on pump A."""
    t = i / max(n - 1, 1)
    noise = random.uniform(-1, 1)
    degrade = max(0.0, (i - (n - 120)) / 119.0) if i >= n - 120 else 0.0

    if tag == "21-PT-2001":
        return 12.0 + 0.4 * math.sin(2 * math.pi * t * 4) + 0.1 * noise
    if tag == "21-TT-2001":
        return 68.0 + 2.0 * math.sin(2 * math.pi * t * 3) + 0.3 * noise
    if tag == "21-LT-2001":
        return 52.0 + 6.0 * math.sin(2 * math.pi * t * 2) + 0.8 * noise
    if tag == "21-FT-2002":
        return 320.0 + 8.0 * noise - degrade * (320.0 - 268.0)
    if tag == "21-VT-2002":
        return 2.1 + 0.2 * noise + degrade * (7.4 - 2.1)
    if tag == "21-PT-2003":
        return 38.0 + 0.6 * noise - degrade * (38.0 - 33.5)
    return 0.0


def handle(client, data=None, secrets=None, function_call_info=None) -> dict:
    space = os.environ["INSTANCE_SPACE"]
    random.seed(20260724)

    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=719)
    timestamps = [start + timedelta(hours=i) for i in range(720)]

    for tag in SERIES:
        values = [_value(tag, i, 720) for i in range(720)]
        points = [{"timestamp": ts, "value": val} for ts, val in zip(timestamps, values)]
        client.time_series.data.insert(points, instance_id=NodeId(space, tag))

    return {
        "series": len(SERIES), "points_per_series": 720, "total": len(SERIES) * 720,
        "window": [start.isoformat(), end.isoformat()], "space": space,
    }
```

### Line-by-line walkthrough

| Code | What it does | Why it is written this way |
|---|---|---|
| `from ...data_modeling import NodeId` | Addresses a node by `(space, externalId)` | These time series are **DMS nodes**, not classic assets. The Chapter 01 §1.2 identity rule in code form. [Data modeling](https://docs.cognite.com/cdf/dm/) |
| `SERIES = [...]` | The six tags, in fixed order | Order must be stable or the seeded noise below stops being reproducible |
| `t = i / max(n - 1, 1)` | Normalises position to `0.0 → 1.0` | Used only as sine **phase**, so each tag completes a fixed number of cycles across the whole 30 days regardless of point count |
| `noise = random.uniform(-1, 1)` | One draw per point | Scaled per tag below — a pressure sensor wobbles by tenths of a bar, a flow meter by several m³/h |
| `degrade = max(0.0, (i - (n - 120)) / 119.0) if ...` | `0.0` for 600 points, then `0.0 → 1.0` across the last 120 | Multiply by a delta to walk a tag from healthy to failed. **Note:** `max(0.0, …)` already clamps before the window opens, so the `if` is belt-and-braces — kept because it states the intent louder than the arithmetic does |
| `12.0 + 0.4*sin(...*4) + 0.1*noise` | Suction pressure, ~4 cycles / 30 d | One of four **healthy** tags — no `degrade` term at all |
| `320.0 + 8.0*noise - degrade*(320-268)` | Flow falls 320 → 268 m³/h | Hero tag #1 |
| `2.1 + 0.2*noise + degrade*(7.4-2.1)` | Vibration climbs 2.1 → 7.4 mm/s | Hero tag #2 — the one you look at in Fusion |
| `38.0 + 0.6*noise - degrade*(38-33.5)` | Discharge pressure falls 38 → 33.5 bar | Quiet corroboration: a failing seal loses discharge pressure too |
| `def handle(client, data=None, ...)` | The entry point | Cognite Functions calls it **by name** — it must be `handle`. [Functions](https://docs.cognite.com/cdf/functions/) |
| the `client` parameter | Pre-authenticated SDK client | Arrives already authenticated as the Function's service principal. **Never** build a `CogniteClient` or read a secret inside a Function — the most common mistake when moving notebook code into one |
| `os.environ["INSTANCE_SPACE"]` | Reads your space | Injected by `envVars` in the `.Function.yaml` below. This is *why* 15 people can deploy byte-identical code without colliding |
| `random.seed(20260724)` | Fixed seed | Two participants comparing screenshots see the same curve **shape**. For synthetic teaching data, reproducibility beats entropy |
| `end = ...replace(minute=0, ...)` / `hours=719` | Window anchored to the current hour | `719`, not `720`, because `start` is itself the first of 720 points |
| `insert(points, instance_id=NodeId(space, tag))` | Writes to the DMS node | Passing `external_id=` instead would address a **classic** time series — a different object that does not exist here, and the call would fail |
| `return {...}` | Counts, window, space | This is what `result.get_response()` prints in §11.5. A Function returning `None` is untestable |

### Why the other four tags are boring on purpose

The two degrading tags stand out by **contrast**. If all six were dramatic, none would be.
A deliberate teaching choice, not laziness in the data generator.

📚 `[DOCS]` [Cognite Functions](https://docs.cognite.com/cdf/functions/) ·
[Python SDK](https://docs.cognite.com/dev/sdks/python/) ·
[Data modeling](https://docs.cognite.com/cdf/dm/)

📝 `[WRITE]` `requirements.txt`: `cognite-sdk==8.10.0`

📝 `[WRITE]` `training/modules/participants/<YOURNAME>/functions/GenerateDatapoints.Function.yaml`

```yaml
externalId: fnc_<YOURNAME>_Training_GenerateDatapoints
name: fnc_<YOURNAME>_Training_GenerateDatapoints
owner: Training
description: Write 30 days of hourly datapoints to the six training timeseries.
functionPath: handler.py
runtime: py311
dataSetExternalId: dts_<YOURNAME>_Training_TRN
envVars:
  PARTICIPANT: "<YOURNAME>"
  INSTANCE_SPACE: "isp_<YOURNAME>_TRN"
  SCHEMA_SPACE_EDM: "ssp_<YOURNAME>_TrainingCore_edm"
  SCHEMA_SPACE_SDM: "ssp_<YOURNAME>_MaintenanceInsight_sdm"
  DATASET: "dts_<YOURNAME>_Training_TRN"
  MODEL_VERSION: "v1.0.0"
```

⚡ `[OPTIMIZE]` `random.seed(20260724)` is fixed on purpose — every participant's
"random" noise is reproducible, so if two people compare screenshots the *shape* of
the curves matches even though the exact values differ slightly by run time. Fixed
seeds for synthetic training/test data are good practice generally: reproducibility
beats novelty when the point is teaching a pattern, not generating realistic entropy.

⚠️ `[COMMON MISTAKE]` Calling this Function repeatedly "to get more data." Each call
recomputes the **same** 720-hour trailing window relative to `now()` and re-inserts —
idempotent by design (a datapoint insert at an existing timestamp overwrites, it
doesn't duplicate), so repeated calls are harmless, but they also don't accumulate
history. If you want the appearance of a longer history, that's a deliberate change
to `timedelta(hours=719)`, not a reason to spam calls.

---

## 11.5 [ACTION] Build, deploy, run

```bash
uv run cdf build --config-yaml training/config.<YOURNAME>-training.yaml
uv run cdf deploy --cdf-project <your-cdf-project> --include functions
```

```python
result = client.functions.call(external_id="fnc_<YOURNAME>_Training_GenerateDatapoints")
print(result.get_response())
```

✅ `[VERIFY]` Response shows `series: 6`, `total: 4320`. In Fusion, open
`21-VT-2002`'s chart over the last 5 days — the ramp from ~2.1 to ~7.4 mm/s should be
visually obvious, not something you have to squint at.

---

## Gate

**Do not proceed to Chapter 12 until:**

- All six time series have 720 datapoints each (4,320 total)
- `21-VT-2002` visibly ramps up and `21-FT-2002` visibly falls over the trailing 5
  days in the Fusion chart view
- You can explain why this had to be a Function and not a static Toolkit
  `*.Datapoints.csv`
- 📓 You have added your two or three lines for this chapter to `participants/<YOURNAME>/NOTES.md` — **now**, not tonight

→ [Chapter 12 — Workflows](12-workflows.md)
