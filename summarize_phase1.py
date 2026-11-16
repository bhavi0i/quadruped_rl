"""Combine the per-seed damage evaluations from Phase 1 into one table.

python summarize_phase1.py results/phase1_sac_seed*_damage_eval.json
"""
import json
import sys
from collections import defaultdict

import numpy as np

rows = defaultdict(lambda: defaultdict(list))
for path in sys.argv[1:]:
    for name, r in json.load(open(path))["results"].items():
        if name == "summary":
            continue
        for k in ("return_mean", "distance_mean", "speed_mean", "fall_rate", "distance_drop_pct"):
            rows[name][k].append(r[k])

print(f"{len(sys.argv) - 1} seeds\n")
print(f"{'scenario':<30}{'return':>16}{'x distance':>16}{'speed':>8}{'falls':>7}{'drop%':>8}")
for name, r in rows.items():
    m = {k: np.mean(v) for k, v in r.items()}
    s = {k: np.std(v) for k, v in r.items()}
    print(f"{name:<30}{m['return_mean']:>9.0f}±{s['return_mean']:<6.0f}{m['distance_mean']:>9.1f}±"
          f"{s['distance_mean']:<6.1f}{m['speed_mean']:>8.2f}{m['fall_rate']:>7.2f}{m['distance_drop_pct']:>8.1f}")
