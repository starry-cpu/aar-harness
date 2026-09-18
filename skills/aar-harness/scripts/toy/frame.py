#!/usr/bin/env python3
"""frame.py -- materialises a toy run: run_config, construct, held-out store, suite items.

This is the toy stand-in for step 01-frame.  It also demonstrates the held-out
contract: the sealed items live OUTSIDE the run directory, and the research side
only ever sees a manifest without item contents.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS / "lib"))
sys.path.insert(0, str(HERE))
import aar_lib as A  # noqa: E402
import world  # noqa: E402


def build(workspace, run_dir):
    workspace = Path(workspace).resolve()
    run_dir = Path(run_dir).resolve()
    store = A.heldout_store(workspace)
    A.ensure_dir(store / "items")
    A.ensure_dir(store / "gold")
    A.ensure_dir(store / "scorer")

    baselines = {name: world.baseline_for(name) for name in world.WORKLOADS}

    heldout_spec = world.spec_for(world.HELDOUT_BENCH)
    heldout_items = [{"id": "heldout-1", "text": world.item_text(world.HELDOUT_BENCH), "spec": heldout_spec}]
    A.atomic_write_json(store / "items" / "items.json", heldout_items)
    items_hash = A.sha256_text(A.canonical_json(heldout_items))
    A.write_manifest(store, {
        "version": "v1",
        "sealed": True,
        "owner": "evaluator",
        "generalization": "scenario: a non-stationary popularity workload whose skew shifts halfway through, a different arrival process from every scored workload",
        "license": "synthetic, generated locally, no third-party data",
        "n_items": len(heldout_items),
        "items_hash": items_hash,
        "public_name": None,
        "visibility": {"items": "sealed", "identity": "sealed", "descriptor": "open"},
        "items_file": "items/items.json",
    })

    suite_items = [{"id": name, "text": world.item_text(name), "spec": world.spec_for(name)} for name in world.SUITE_BENCHES]
    suite_items_path = HERE / "items_suite.json"
    A.atomic_write_json(suite_items_path, suite_items)

    gate = baselines[world.GATE_BENCH]
    suite = []
    for name in world.SUITE_BENCHES:
        suite.append({"name": name, "metric": "hit_rate", "baseline": round(baselines[name]["hit_rate"], 6), "optimum": 1.0, "source": "toy cache simulator"})

    config = {
        "tier": "toy",
        "question": "Which cache-eviction policy generalises across workload shapes without hurting latency-sensitive traffic?",
        "construct": "eviction policy quality under a fixed capacity, measured as hit rate",
        "target_system": "fixed-capacity cache simulator (capacity " + str(world.CAPACITY) + ")",
        "method_contract": {"interface": "policy.py defining class Policy(capacity) with on_access(key, hit) and choose_victim(resident)", "budget_seconds": 10, "artifact": "methods/<method_id>/"},
        "suite": suite,
        "held_out": {"store": str(store), "manifest": str(store / "manifest.json"), "generalization": "scenario", "selector": True, "items_file": str(store / "items" / "items.json")},
        "gates": [{"name": "cap_short_latency", "direction": "higher_better", "stat": "mean_ci", "baseline_values": gate["windows"], "note": "collapse detector only: it rules out a large regression, it does not certify no harm"}],
        "runner": {"cmd": "python " + str(HERE / "runner.py") + " --method {method_dir} --bench {bench} --json", "baseline_dir": "baseline", "gate_bench": world.GATE_BENCH, "timeout_seconds": 60},
        "stop": {"wall_clock_hours": 0.1, "plateau_window": 10, "min_gain": 0.005},
        "forum": {"enabled": True},
        "retrieval": {"tier": "offline", "note": "toy domain needs no literature retrieval"},
        "researchers": 2,
        "seeds": {"runner": 0},
    }
    A.init_run(run_dir, config)
    construct = {
        "question": config["question"],
        "construct": config["construct"],
        "method_space": "any eviction policy expressible against the Policy interface: recency, frequency, size-aware, adaptive, segmented, learning-based or hybrid",
        "scored_benchmarks": [b["name"] for b in suite],
        "held_out_note": "a separate held-out workload, never shown to a researcher, re-tests generalisation",
        "method_families_seed": ["recency (LRU/LFU hybrids)", "frequency counting", "segmented/probationary (SLRU, ARC-like)", "adaptive/self-tuning", "sampling-based (CLOCK, random)", "cost or size aware"],
    }
    A.write_construct(run_dir, construct)
    A.freeze_run_config(run_dir, force=True)
    return {"run_dir": str(run_dir), "store": str(store), "baselines": {k: round(v["hit_rate"], 4) for k, v in baselines.items()}, "items_hash": items_hash}


def main(argv=None):
    p = argparse.ArgumentParser(prog="frame.py")
    p.add_argument("--workspace", default=str(SCRIPTS.parent.parent.parent.parent))
    p.add_argument("--run", required=True)
    args = p.parse_args(argv)
    print(json.dumps(build(args.workspace, args.run), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
