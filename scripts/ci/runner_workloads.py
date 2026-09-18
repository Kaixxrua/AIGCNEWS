"""Task-aware estimates, not memory reservations or OOM guarantees."""
from __future__ import annotations

import json
import math
from pathlib import Path

GIB = 1024**3
FLOORS = {'admission': .25, 'control': .25, 'mcp': .75,
          'database': 2, 'backend': 2, 'frontend': 2, 'smoke': 2, 'unknown': 3}


def category(job):
    name = job.get('name', '').lower()
    workflow = job.get('workflow_name', '').lower()
    if name == 'verify current pr base': return 'admission'
    if workflow in {'session pr', 'delivery sweeper', 'auto merge validated session pr'}: return 'control'
    if name == 'mcp go build and tests': return 'mcp'
    if 'postgresql' in name: return 'database'
    if name == 'backend tests': return 'backend'
    if name == 'frontend build': return 'frontend'
    if name == 'compose and image smoke': return 'smoke'
    return 'unknown'


class History:
    def __init__(self, path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text()) if self.path.exists() else {'peaks': {}, 'oom': {}}
        if set(self.data) != {'peaks', 'oom'}:
            raise ValueError('invalid workload history schema')
        for values in self.data['peaks'].values():
            if any(not math.isfinite(v) or v < 0 for v in values):
                raise ValueError('invalid workload history')

    def predict(self, kind):
        # Conservative high-water, with 25% margin; bounded retention avoids
        # unbounded state. Cold categories use explicit bootstrap floors.
        peaks = self.data['peaks'].get(kind, [])
        return max(int(FLOORS[kind] * GIB), math.ceil(max(peaks, default=0) * 1.25))

    def observe(self, identity, kind, peak):
        if not math.isfinite(peak) or peak < 0:
            raise ValueError('invalid measured memory peak')
        # One bounded record per task instance; repeated polling updates its peak.
        key = kind
        entries = self.data['peaks'].setdefault(key, [])
        if not entries or peak > max(entries):
            entries.append(peak)
            self.data['peaks'][key] = entries[-32:]

    def oom(self, identity, count):
        if count:
            self.data['oom'][identity] = count

    def save(self):
        from runner_pool_receipts import atomic_json
        atomic_json(self.path, self.data)
