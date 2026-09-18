"""world.py -- deterministic toy target system for aar-harness end-to-end tests.

The "target system" is a fixed-capacity cache.  A "method" is an eviction policy
(a policy.py exposing class Policy).  Three scored workloads, one held-out
workload from a different distribution, and one latency-sensitive regression
gate.  No GPU, no network, one method runs in well under a second.
"""

from __future__ import annotations

import json
import random

CAPACITY = 64

WORKLOADS = {
    "uniform": {"dist": "uniform", "keys": 512, "nreq": 4000, "seed": 11},
    "zipf": {"dist": "zipf", "keys": 256, "nreq": 4000, "alpha": 1.2, "seed": 22},
    "scan": {"dist": "scanmix", "keys": 2048, "hot": 64, "hot_p": 0.4, "nreq": 8000, "seed": 33},
    "shiftzipf": {"dist": "shiftzipf", "keys": 512, "nreq": 6000, "alpha_a": 0.6, "alpha_b": 1.8, "seed": 44},
    "short_latency": {"dist": "locality", "hot": 16, "cold": 4096, "hot_p": 0.85, "nreq": 1200, "seed": 55},
}

SUITE_BENCHES = ("uniform", "zipf", "scan")
HELDOUT_BENCH = "shiftzipf"
GATE_BENCH = "short_latency"
WINDOWS = 10


def zipf_choice(rng, n, alpha):
    """Small exact Zipf sampler (rejection-free, cumulative table)."""
    table = [1.0 / ((i + 1) ** alpha) for i in range(n)]
    total = sum(table)
    r = rng.random() * total
    acc = 0.0
    for i, w in enumerate(table):
        acc += w
        if r <= acc:
            return i
    return n - 1


def gen_trace(spec):
    dist = spec["dist"]
    rng = random.Random(spec["seed"])
    if dist == "uniform":
        return [rng.randrange(spec["keys"]) for _ in range(spec["nreq"])]
    if dist == "zipf":
        return [zipf_choice(rng, spec["keys"], spec.get("alpha", 1.0)) for _ in range(spec["nreq"])]
    if dist == "scanmix":
        trace = []
        cursor = 0
        for _ in range(spec["nreq"]):
            if rng.random() < spec["hot_p"]:
                trace.append(rng.randrange(spec["hot"]))
            else:
                trace.append(cursor % spec["keys"])
                cursor += 1
        return trace
    if dist == "shiftzipf":
        trace = []
        half = spec["nreq"] // 2
        for i in range(spec["nreq"]):
            alpha = spec["alpha_a"] if i < half else spec["alpha_b"]
            trace.append(zipf_choice(rng, spec["keys"], alpha))
        return trace
    if dist == "locality":
        return [(rng.randrange(spec["hot"]) if rng.random() < spec["hot_p"] else rng.randrange(spec["keyspace"] if "keyspace" in spec else spec["cold"])) for _ in range(spec["nreq"])]
    raise ValueError("unknown distribution " + str(dist))


def spec_for(name):
    if name not in WORKLOADS:
        raise KeyError("unknown workload " + str(name))
    return dict(WORKLOADS[name])


def simulate(policy, trace, capacity=CAPACITY, windows=WINDOWS):
    """Return overall hit rate plus per-window hit rates for confidence intervals."""
    resident = set()
    hits = 0
    win_size = max(1, len(trace) // windows)
    win = []
    win_hits = 0
    win_n = 0
    for key in trace:
        hit = key in resident
        if hit:
            hits += 1
            win_hits += 1
        policy.on_access(key, hit)
        if not hit:
            if len(resident) >= capacity:
                victim = policy.choose_victim(list(resident))
                if victim not in resident:
                    victim = next(iter(resident))
                resident.discard(victim)
            resident.add(key)
        win_n += 1
        if win_n >= win_size:
            win.append(win_hits / win_n)
            win_hits = 0
            win_n = 0
    if win_n:
        win.append(win_hits / win_n)
    return {"hit_rate": hits / len(trace), "n_requests": len(trace), "windows": win}


class LRUPolicy:
    """Reference baseline: least recently used."""

    def __init__(self, capacity):
        self.capacity = capacity
        self.order = []

    def on_access(self, key, hit):
        if key in self.order:
            self.order.remove(key)
        self.order.append(key)

    def choose_victim(self, resident):
        for k in self.order:
            if k in resident:
                return k
        return sorted(resident)[0]


def baseline_for(name, capacity=CAPACITY):
    return simulate(LRUPolicy(capacity), gen_trace(spec_for(name)), capacity)


def item_text(name):
    """The textual item used for leak and overlap checks (a distinctive spec line)."""
    return "workload-spec " + json.dumps(spec_for(name), sort_keys=True)


def main():
    import sys
    names = sys.argv[1:] or list(WORKLOADS)
    for n in names:
        r = baseline_for(n)
        print(n, "lru_hit_rate=%.4f" % r["hit_rate"], "n=%d" % r["n_requests"])


if __name__ == "__main__":
    main()
