#!/usr/bin/env python3
"""runner.py -- executes one method artifact against one workload.

A method is a directory containing policy.py that defines class Policy(capacity)
with on_access(key, hit) and choose_victim(resident).  The runner is the only
component that touches the scored workloads, and it prints aggregate numbers.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import world  # noqa: E402


def load_policy(method_dir):
    path = Path(method_dir) / "policy.py"
    if not path.exists():
        raise FileNotFoundError("no policy.py in " + str(method_dir))
    spec = importlib.util.spec_from_file_location("aar_toy_policy", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "Policy"):
        raise AttributeError("policy.py must define class Policy")
    return module.Policy


def run_one(method_dir, bench, capacity):
    trace = world.gen_trace(world.spec_for(bench))
    if method_dir == "baseline":
        policy = world.LRUPolicy(capacity)
    else:
        policy = load_policy(method_dir)(capacity)
    result = world.simulate(policy, trace, capacity)
    result["bench"] = bench
    result["method_dir"] = str(method_dir)
    return result


def main(argv=None):
    p = argparse.ArgumentParser(prog="runner.py")
    p.add_argument("--method", required=True)
    p.add_argument("--bench", required=True)
    p.add_argument("--capacity", type=int, default=world.CAPACITY)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        res = run_one(args.method, args.bench, args.capacity)
    except Exception as exc:
        print(json.dumps({"error": type(exc).__name__ + ": " + str(exc), "bench": args.bench}))
        return 1
    if args.json:
        print(json.dumps(res))
    else:
        print(res["bench"], "hit_rate=%.4f" % res["hit_rate"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
