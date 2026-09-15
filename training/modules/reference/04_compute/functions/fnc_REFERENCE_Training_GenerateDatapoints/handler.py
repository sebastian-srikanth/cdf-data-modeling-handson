"""Generate 720 hourly datapoints per training timeseries with a degradation signature."""

from __future__ import annotations

import math
import os
import random
from datetime import datetime, timedelta, timezone

from cognite.client.data_classes.data_modeling import NodeId


SERIES = [
    "21-PT-2001",
    "21-TT-2001",
    "21-LT-2001",
    "21-FT-2002",
    "21-VT-2002",
    "21-PT-2003",
]


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
        base = 320.0 + 8.0 * noise
        return base - degrade * (320.0 - 268.0)
    if tag == "21-VT-2002":
        base = 2.1 + 0.2 * noise
        return base + degrade * (7.4 - 2.1)
    if tag == "21-PT-2003":
        base = 38.0 + 0.6 * noise
        return base - degrade * (38.0 - 33.5)
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
        "series": len(SERIES),
        "points_per_series": 720,
        "total": len(SERIES) * 720,
        "window": [start.isoformat(), end.isoformat()],
        "space": space,
    }
