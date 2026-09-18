#!/usr/bin/env python3
"""frame.py -- step 01-frame for the SQLite index-selection study.

Measures the un-indexed baselines, seals the held-out workload outside the run
directory, writes construct.json then the frozen run_config.json.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# <repo>/examples/sqlite-index/frame.py -> <repo>/skills/aar-harness/scripts
SCRIPTS = HERE.parent.parent / "skills" / "aar-harness" / "scripts"
sys.path.insert(0, str(SCRIPTS / "lib"))
sys.path.insert(0, str(HERE))
import aar_lib as A  # noqa: E402
import world  # noqa: E402

SEED = 7
WRITE_TOLERANCE = 1.75
NL = chr(10)


def baselines():
    out = {}
    for bench in list(world.SCORED) + [world.HELDOUT]:
        conn = world.make_db(bench, SEED)
        out[bench] = world.measure(bench, conn, SEED)
    return out


def bench_text(bench):
    spec = world.BENCHES[bench]
    return ("workload " + bench + " over schema " + spec["schema"] + ": " + spec["describes"] +
            " (" + str(sum(n for _, n in spec["eval"])) + " evaluation queries)")


def build(study_dir, run_dir):
    study_dir = Path(study_dir).resolve()
    run_dir = Path(run_dir).resolve()
    store = A.heldout_store(study_dir)
    A.ensure_dir(store / "items")
    A.ensure_dir(store / "gold")
    A.ensure_dir(store / "scorer")

    base = baselines()
    A.atomic_write_json(study_dir / "baselines.json", base)

    held_text = ("held-out workload sensors over a different schema: " + world.SENSOR_SCHEMA +
                 " evaluation queries are device time-series lookups and per-site aggregation, a " +
                 "different schema and query shape from every scored workload")
    items = [{"id": "heldout-sensors", "spec": world.HELDOUT, "text": held_text}]
    A.atomic_write_json(store / "items" / "items.json", items)
    A.write_manifest(store, {"version": "v1", "sealed": True, "owner": "evaluator",
                             "generalization": "domain: a different schema (devices/readings) and different query shapes, same mechanism (index selection from a workload sample)",
                             "license": "synthetic, generated locally, no third-party data",
                             "n_items": len(items),
                             "items_hash": A.sha256_text(A.canonical_json(items)),
                             "public_name": None,
                             "visibility": {"items": "sealed", "identity": "sealed", "descriptor": "open"},
                             "items_file": "items/items.json"})

    suite_items = [{"id": b, "text": bench_text(b)} for b in world.SCORED]
    A.atomic_write_json(HERE / "items_suite.json", suite_items)

    write_line = int(round(base[world.GATE_BENCH]["write_windows"][0] * WRITE_TOLERANCE))
    suite = [{"name": b, "metric": "score", "baseline": 0.0, "optimum": 1.0,
              "source": "sqlite in-memory, opcode cost via progress handler",
              "items_file": str(HERE / "items_suite.json"),
              "describes": world.BENCHES[b]["describes"]} for b in world.SCORED]

    config = {
        "tier": "light",
        "title": "SQLite 索引选择研究",
        "question": "Which index-selection strategy is most useful across heterogeneous SQLite query workloads?",
        "construct": "index selection from a bounded workload sample, scored as the fraction of query work removed against an un-indexed baseline",
        "target_system": "in-memory SQLite database rebuilt deterministically from a seeded generator; schema, data and evaluation queries are fixed",
        "method_contract": {
            "interface": "tune.py defining propose(schema_ddl: str, sample_queries: list[dict], budget: dict) -> list[str] of CREATE INDEX / ANALYZE statements",
            "artifact": "methods/<method_id>/",
            "entrypoint": "tune.py",
            "required_symbol": "propose",
            "budget_seconds": 10,
            "max_indexes": world.MAX_INDEXES,
            "notes": "only CREATE INDEX and ANALYZE are accepted; evaluation queries are never passed to propose()",
        },
        "suite": suite,
        "held_out": {"store": str(store), "manifest": str(store / "manifest.json"), "generalization": "domain",
                     "selector": True, "items_file": str(store / "items" / "items.json")},
        "gates": [{"name": "write_budget", "direction": "lower_better", "stat": "mean_ci", "bench": world.GATE_BENCH,
                   "baseline_values": [write_line] * world.WINDOWS,
                   "line": write_line,
                   "note": "a fixed line, not a baseline distribution: per-window write cost must stay under " + str(write_line) + " opcodes (" + str(WRITE_TOLERANCE) + "x the untuned cost). Follows the paper over-refusal gate, which is also compared against a line. It catches an index set that wrecks the write path; it does not certify that writes are unharmed."}],
        "runner": {"cmd": "python " + str(HERE / "runner.py") + " --method {method_dir} --bench {bench} --seed " + str(SEED) + " --json",
                   "gate_bench": world.GATE_BENCH, "timeout_seconds": 180, "baselines": str(study_dir / "baselines.json")},
        "stop": {"wall_clock_hours": 8, "plateau_window": 40, "min_gain": 0.005},
        "forum": {"enabled": True},
        "monitors": {"static": True, "code": False, "paper": False,
                     "note": "this run left the two LLM monitors to the post-hoc pass; --code-monitor / --paper-monitor force them on in-loop"},
        "retrieval": {"tier": "basic", "note": "index-selection literature is reachable through arXiv/OpenAlex/Crossref; HuggingFace is blocked by this machine proxy"},
        "researchers": 4,
        "max_methods": 120,
        "seeds": {"runner": SEED},
    }
    A.init_run(run_dir, config)

    construct = {
        "question": config["question"],
        "construct": config["construct"],
        "method_space": "any procedure that reads the schema and a bounded sample of the workload and returns at most 6 index definitions: full-candidate, selectivity-driven, frequency-weighted, composite column order, covering indexes, partial or expression indexes, or hybrids",
        "scored_benchmarks": [b["name"] for b in suite],
        "held_out_note": "a separate held-out workload over a different schema, never shown to a researcher, re-tests generalisation",
        "method_families_seed": ["one index per predicate column", "selectivity-proportional (cardinality ordered, top-k)", "workload-frequency weighted", "composite index with searched column order", "covering index widening", "partial or expression index", "greedy marginal-gain search over candidate indexes"],
    }
    A.write_construct(run_dir, construct)
    A.freeze_run_config(run_dir, force=True)
    return {"run_dir": str(run_dir), "store": str(store),
            "baseline_eval_cost": {k: v["eval_cost"] for k, v in base.items()},
            "gate_baseline_write_cost": base[world.GATE_BENCH]["write_cost"],
            "write_line": write_line}


def main(argv=None):
    p = argparse.ArgumentParser(prog="frame.py")
    p.add_argument("--study", default=str(HERE))
    p.add_argument("--run", default=str(HERE / "run"))
    args = p.parse_args(argv)
    print(json.dumps(build(args.study, args.run), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
