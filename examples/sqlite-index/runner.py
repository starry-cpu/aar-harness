#!/usr/bin/env python3
"""runner.py -- executes one method against one workload.

A method is a directory containing tune.py that defines
    propose(schema_ddl: str, sample_queries: list[dict], budget: dict) -> list[str]
returning DDL statements (CREATE INDEX ...).  The runner builds the bench database,
calls propose with a SAMPLE of the workload, applies what it returns, then measures
the EVALUATION workload the tuner never saw.

Printed contract: exactly one JSON object on the last stdout line.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import world  # noqa: E402

ALLOWED = re.compile(r"^(create\s+(unique\s+)?index|analyze)\b", re.IGNORECASE)
FORBIDDEN = re.compile(r"\b(drop|alter|insert|update|delete|pragma|attach|vacuum)\b", re.IGNORECASE)


def load_tuner(method_dir):
    path = Path(method_dir) / "tune.py"
    if not path.exists():
        raise FileNotFoundError("no tune.py in " + str(method_dir))
    spec = importlib.util.spec_from_file_location("study_tuner", str(path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "propose"):
        raise AttributeError("tune.py must define propose(schema_ddl, sample_queries, budget)")
    return module.propose


def validate(statements, max_indexes):
    if statements is None:
        return []
    if not isinstance(statements, (list, tuple)):
        raise ValueError("propose() must return a list of DDL strings")
    out = []
    names = set()
    for raw in statements:
        if not isinstance(raw, str):
            raise ValueError("propose() returned a non-string entry")
        stmt = raw.strip().rstrip(";")
        if not stmt:
            continue
        if FORBIDDEN.search(stmt):
            raise ValueError("forbidden statement in proposal: " + stmt[:80])
        if not ALLOWED.match(stmt):
            raise ValueError("only CREATE INDEX and ANALYZE are allowed, got: " + stmt[:80])
        if stmt.upper().startswith("CREATE"):
            m = re.search(r"index\s+(?:if\s+not\s+exists\s+)?([\w\"]+)", stmt, re.IGNORECASE)
            name = (m.group(1).strip(chr(34)) if m else "").lower()
            if name in names:
                raise ValueError("duplicate index name: " + name)
            names.add(name)
        out.append(stmt)
    indexes = len([s for s in out if s.upper().startswith("CREATE")])
    if indexes > max_indexes:
        raise ValueError("proposed " + str(indexes) + " indexes, budget is " + str(max_indexes))
    return out


def run_one(method_dir, bench, seed, baselines):
    base = baselines[bench]
    conn = world.make_db(bench, seed, with_defaults=True)
    detail = {"indexes": [], "tuner_seconds": 0.0, "defaults": world.default_indexes(bench)}
    if method_dir != "baseline":
        propose = load_tuner(method_dir)
        budget = {"max_indexes": world.MAX_INDEXES, "max_seconds": 10}
        t0 = time.time()
        statements = propose(world.schema_of(bench), world.sample_queries(bench, seed + 1), budget)
        detail["tuner_seconds"] = round(time.time() - t0, 3)
        if detail["tuner_seconds"] > budget["max_seconds"]:
            raise ValueError("tuner exceeded its budget: " + str(detail["tuner_seconds"]) + "s")
        statements = validate(statements, world.MAX_INDEXES)
        for stmt in statements:
            conn.execute(stmt)
        conn.commit()
        detail["indexes"] = statements
    m = world.measure(bench, conn, seed)
    score = 1.0 - (m["eval_cost"] / float(base["eval_cost"]))
    per = max(1, len(m["eval_windows"]) )
    base_w = base["eval_windows"]
    windows = [1.0 - (m["eval_windows"][i] / float(base_w[i])) if base_w[i] else 0.0 for i in range(min(len(m["eval_windows"]), len(base_w)))]
    return {"bench": bench, "score": score, "eval_cost": m["eval_cost"], "baseline_eval_cost": base["eval_cost"],
            "write_cost": m["write_cost"], "windows": windows, "gate_windows": m["write_windows"], "detail": detail}


def main(argv=None):
    p = argparse.ArgumentParser(prog="runner.py")
    p.add_argument("--method", required=True)
    p.add_argument("--bench", required=True)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--baselines", default=str(HERE / "baselines.json"))
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        baselines = json.loads(Path(args.baselines).read_text(encoding="utf-8"))
        res = run_one(args.method, args.bench, args.seed, baselines)
    except Exception as exc:
        print(json.dumps({"bench": args.bench, "error": type(exc).__name__ + ": " + str(exc)}))
        return 1
    print(json.dumps(res))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
