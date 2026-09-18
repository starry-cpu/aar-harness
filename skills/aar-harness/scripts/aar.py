#!/usr/bin/env python3
"""aar.py -- single-step CLI for aar-harness.

Every mechanical part of the harness lives here so the step procedures never
hand-roll scoring, hashing, publish or verification logic.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
import aar_lib as A  # noqa: E402
import sources as S  # noqa: E402


def emit(obj, code=0):
    print(json.dumps(obj, indent=2, ensure_ascii=False))
    return code


def load_arg(value):
    """Accept inline JSON or @path/to/file.json."""
    if value is None:
        return None
    text = value
    if value.startswith("@"):
        text = Path(value[1:]).read_text(encoding="utf-8")
    return json.loads(text)


# ------------------------------------------------------------- commands

def cmd_new_run(args):
    cfg = load_arg(args.config) if args.config else {}
    if cfg is None:
        cfg = {}
    if args.tier:
        cfg["tier"] = args.tier
    cfg = A.init_run(args.dir, cfg)
    if args.construct:
        A.write_construct(args.dir, load_arg(args.construct))
    return emit({"run_dir": str(Path(args.dir).resolve()), "tier": cfg.get("tier"), "created_at": cfg.get("created_at")})


def cmd_status(args):
    run = args.run
    cfg = A.load_run_config(run)
    rows = A.leaderboard_rows(run)
    passing = [r for r in rows if r["gates_pass"]]
    plat = A.plateau_decision(rows, window=int(cfg.get("stop", {}).get("plateau_window", 40)), min_gain=float(cfg.get("stop", {}).get("min_gain", 0.005)))
    return emit({"tier": cfg.get("tier"), "frozen_at": cfg.get("frozen_at"), "findings": len(rows), "gate_passing": len(passing), "best": passing[0] if passing else None, "exclusions": len(A.load_exclusions(run)), "survey_entries": len(A.list_survey_entries(run)), "plateau": plat})


def cmd_hash(args):
    return emit({"path": str(Path(args.path).resolve()), "hash": A.hash_dir(args.path)})


def cmd_approve(args):
    monitors = {}
    for item in (args.monitor or []):
        if "=" in item:
            k, v = item.split("=", 1)
            monitors[k] = v
    path = A.approve_method(args.run, args.method, verdict=args.verdict, monitors=monitors, notes=args.notes)
    rec = A.read_json(path)
    return emit({"approved": str(path), "code_hash": rec["code_hash"], "verdict": rec["verdict"]})


def cmd_verify_approval(args):
    res = A.verify_approval(args.run, args.method)
    return emit(res, 0 if res["ok"] else 2)


def cmd_score(args):
    cfg = A.load_run_config(args.run)
    suite = cfg.get("suite") or []
    if not suite:
        return emit({"error": "run_config has no suite"}, 2)
    raw = load_arg(args.raw)
    if isinstance(raw, dict) and "raw" in raw and isinstance(raw["raw"], dict):
        raw = raw["raw"]
    scored = A.score_finding(suite, raw)
    meta = {"runner_cmd": args.runner_cmd, "started_at": args.started_at, "ended_at": args.ended_at, "duration_s": args.duration_s, "seed": args.seed}
    payload = {"schema": A.SCHEMA_VERSION, "method_id": args.method, "raw": raw, "meta": meta, "scored": scored}
    out_dir = A.ensure_dir(A.run_paths(args.run)["eval"] / args.method)
    A.atomic_write_json(out_dir / "scores.json", payload)
    return emit({"wrote": str(out_dir / "scores.json"), "aggregate": scored["aggregate"], "closed": {k: v["closed"] for k, v in scored["scores"].items()}})


def cmd_gate(args):
    verdict = A.gate_verdict(args.name, load_arg(args.method_values), load_arg(args.baseline_values), direction=args.direction, stat=args.stat, iters=args.iters, seed=args.seed)
    out_dir = A.ensure_dir(A.run_paths(args.run)["eval"] / args.method)
    path = out_dir / "gates.json"
    gates = A.read_json(path, default=[]) or []
    gates = [g for g in gates if g.get("name") != args.name] + [verdict]
    A.atomic_write_json(path, gates)
    return emit({"wrote": str(path), "gate": verdict})


def cmd_publish(args):
    run = args.run
    rp = A.run_paths(run)
    mid = args.method
    va = A.verify_approval(run, mid)
    if not va["ok"]:
        return emit({"error": "approval check failed -- refusing to publish", "detail": va}, 2)
    scored_rec = A.read_json(rp["eval"] / mid / "scores.json", default=None)
    if scored_rec is None:
        return emit({"error": "no eval/" + mid + "/scores.json; run `score` first"}, 2)
    gates = A.read_json(rp["eval"] / mid / "gates.json", default=[]) or []
    sub = A.read_json(rp["submissions"] / (mid + ".json"), default={}) or {}
    cfg = A.load_run_config(run)
    scored = A.score_finding(cfg.get("suite") or [], scored_rec["raw"])
    mini = rp["methods"] / mid / "mini-paper.md"
    claims = args.claim or sub.get("claims") or []
    finding = {"method_id": mid, "artifact_hash": va["approved_hash"], "mini_paper": {"id": "mp-" + mid, "hash": (A.sha256_file(mini) if mini.exists() else None), "path": str(mini.relative_to(rp["run"])) if mini.exists() else None}, "author": {"researcher_id": args.researcher or sub.get("researcher_id") or "unknown", "session_id": args.session or sub.get("session_id")}, "status": "scored", "family": args.family or sub.get("family"), "scores": scored["scores"], "aggregate": scored["aggregate"], "gates": gates, "evidence": {"score_file": "eval/" + mid + "/scores.json", "score_file_hash": A.sha256_file(rp["eval"] / mid / "scores.json"), "runner_cmd": (scored_rec.get("meta") or {}).get("runner_cmd"), "started_at": (scored_rec.get("meta") or {}).get("started_at"), "ended_at": (scored_rec.get("meta") or {}).get("ended_at")}, "claims": claims, "reuse_hint": args.reuse_hint or sub.get("reuse_hint"), "tags": args.tag or sub.get("tags") or [], "supersedes": args.supersedes}
    if gates and not A.all_gates_pass(gates):
        finding["status"] = "gate_failed"
    mismatch = A.check_claim_mismatch(finding)
    if mismatch:
        finding["status"] = "claim_mismatch"
        finding["claim_mismatch"] = mismatch
    path = A.publish_finding(run, finding)
    board = A.rebuild_leaderboard(run)
    survey_results = []
    for entry in (sub.get("survey_additions") or []):
        if args.no_survey:
            break
        try:
            survey_results.append(A.add_survey_entry(run, entry))
        except ValueError as exc:
            survey_results.append({"added": False, "error": str(exc)})
    return emit({"published": str(path), "status": finding["status"], "aggregate": finding["aggregate"]["value"], "leaderboard_best": (board.get("best") or {}).get("method_id"), "survey_additions": survey_results})


def cmd_forum(args):
    if args.action == "list":
        rows = [{k: r.get(k) for k in ("finding_id", "method_id", "status", "family", "artifact_hash", "aggregate")} for r in A.list_findings(args.run)]
        if args.include_failed is False:
            rows = [r for r in rows if r["status"] == "scored"]
        return emit({"count": len(rows), "findings": rows})
    if args.action == "digest":
        text = A.forum_digest(args.run, top=args.top, recent=args.recent, per_family=args.per_family)
        print(text)
        return 0
    if args.action == "verify":
        problems = A.verify_forum(args.run)
        return emit({"ok": not problems, "problems": problems}, 0 if not problems else 2)
    return emit({"error": "unknown forum action"}, 2)


def cmd_leaderboard(args):
    board = A.rebuild_leaderboard(args.run)
    if args.full:
        return emit(board)
    return emit({"count": board["count"], "passing": board["passing"], "best": board["best"], "top": board["rows"][:10]})


def cmd_survey(args):
    if args.action == "add":
        entry = load_arg(args.entry)
        res = A.add_survey_entry(args.run, entry)
        return emit(res, 0 if res.get("added") else 0)
    if args.action == "index":
        return emit(A.rebuild_survey_index(args.run))
    if args.action == "verify":
        problems = A.verify_survey(args.run)
        return emit({"ok": not problems, "problems": problems}, 0 if not problems else 2)
    if args.action == "queries":
        return emit({"count": len(A.read_jsonl(A.run_paths(args.run)["survey_queries"])), "queries": A.read_jsonl(A.run_paths(args.run)["survey_queries"])})
    if args.action == "log-query":
        A.log_query(args.run, load_arg(args.entry))
        return emit({"logged": True})
    return emit({"error": "unknown survey action"}, 2)


def cmd_heldout(args):
    if args.action == "manifest":
        if args.manifest:
            A.write_manifest(args.store, load_arg(args.manifest))
        man = A.read_manifest(args.store)
        safe = {"version": man.get("version"), "items_hash": man.get("items_hash"), "n_items": man.get("n_items"), "generalization": man.get("generalization"), "license": man.get("license"), "sealed": man.get("sealed", True)}
        return emit(safe, 0 if man else 2)
    if args.action == "verify":
        cfg = {}
        try:
            cfg = A.load_run_config(args.run)
        except FileNotFoundError:
            cfg = {}
        suite_files = args.suite_items or [b.get("items_file") for b in (cfg.get("suite") or []) if b.get("items_file")]
        res = A.verify_heldout(args.store, args.run, suite_item_files=suite_files, threshold=args.threshold)
        return emit(res, 0 if res["ok"] else 2)
    return emit({"error": "unknown heldout action"}, 2)


def cmd_plateau(args):
    cfg = A.load_run_config(args.run)
    rows = A.leaderboard_rows(args.run)
    window = args.window or int((cfg.get("stop") or {}).get("plateau_window", 40))
    min_gain = args.min_gain if args.min_gain is not None else float((cfg.get("stop") or {}).get("min_gain", 0.005))
    return emit(A.plateau_decision(rows, window=window, min_gain=min_gain))


def cmd_audit(args):
    if args.action == "prepare":
        return emit(A.audit_prepare(args.run, chunk_chars=args.chunk_chars))
    if args.action == "collect":
        report = A.audit_collect(args.run, threshold=args.threshold)
        excluded = []
        if args.exclude:
            for t in report["flagged"]:
                target = t.get("method_id") or t["trace_id"]
                res = A.add_exclusion(args.run, target, reason="integrity audit flagged this trajectory", category="cheating", evidence={"trace_id": t["trace_id"], "max_score": t["max_score"], "categories": t["categories"]})
                excluded.append(res)
            A.rebuild_leaderboard(args.run)
        return emit({"flagged": len(report["flagged"]), "traces": len(report["traces"]), "excluded": excluded})
    if args.action == "exclusions":
        return emit({"exclusions": A.load_exclusions(args.run)})
    return emit({"error": "unknown audit action"}, 2)


def cmd_sources(args):
    if args.action == "probe":
        return emit(S.probe_sources())
    errors = []
    papers = S.multi_search(args.query, per_source=args.limit, sources=tuple(args.source), errors=errors)
    return emit({"query": args.query, "count": len(papers), "errors": errors, "papers": papers}, 0 if papers else 2)


def cmd_snapshot(args):
    """Freeze a hash-only record of an artifact or the whole run."""
    if args.method:
        return emit({"method_id": args.method, "hash": A.hash_dir(A.run_paths(args.run)["methods"] / args.method)})
    return emit({"run_dir": str(Path(args.run).resolve()), "forum": A.verify_forum(args.run)})


def build_parser():
    p = argparse.ArgumentParser(prog="aar.py", description="aar-harness step CLI")
    sub = p.add_subparsers(dest="cmd", required=True)

    q = sub.add_parser("new-run"); q.add_argument("--dir", required=True); q.add_argument("--config"); q.add_argument("--construct"); q.add_argument("--tier"); q.set_defaults(func=cmd_new_run)
    q = sub.add_parser("status"); q.add_argument("--run", required=True); q.set_defaults(func=cmd_status)
    q = sub.add_parser("hash"); q.add_argument("--path", required=True); q.set_defaults(func=cmd_hash)
    q = sub.add_parser("approve"); q.add_argument("--run", required=True); q.add_argument("--method", required=True); q.add_argument("--verdict", default="approved"); q.add_argument("--monitor", action="append"); q.add_argument("--notes"); q.set_defaults(func=cmd_approve)
    q = sub.add_parser("verify-approval"); q.add_argument("--run", required=True); q.add_argument("--method", required=True); q.set_defaults(func=cmd_verify_approval)
    q = sub.add_parser("score"); q.add_argument("--run", required=True); q.add_argument("--method", required=True); q.add_argument("--raw", required=True); q.add_argument("--runner-cmd"); q.add_argument("--started-at"); q.add_argument("--ended-at"); q.add_argument("--duration-s", type=float); q.add_argument("--seed", type=int); q.set_defaults(func=cmd_score)
    q = sub.add_parser("gate"); q.add_argument("--run", required=True); q.add_argument("--method", required=True); q.add_argument("--name", required=True); q.add_argument("--direction", default="higher_better", choices=["higher_better", "lower_better"]); q.add_argument("--method-values", required=True); q.add_argument("--baseline-values", required=True); q.add_argument("--stat", default="mean_ci", choices=["mean_ci", "wilson", "bootstrap"]); q.add_argument("--iters", type=int, default=2000); q.add_argument("--seed", type=int, default=0); q.set_defaults(func=cmd_gate)
    q = sub.add_parser("publish"); q.add_argument("--run", required=True); q.add_argument("--method", required=True); q.add_argument("--researcher"); q.add_argument("--session"); q.add_argument("--family"); q.add_argument("--claim", action="append"); q.add_argument("--reuse-hint"); q.add_argument("--tag", action="append"); q.add_argument("--supersedes"); q.add_argument("--no-survey", action="store_true"); q.set_defaults(func=cmd_publish)
    q = sub.add_parser("forum"); q.add_argument("action", choices=["list", "digest", "verify"]); q.add_argument("--run", required=True); q.add_argument("--top", type=int, default=8); q.add_argument("--recent", type=int, default=8); q.add_argument("--per-family", type=int, default=1); q.add_argument("--include-failed", action="store_true", default=True); q.set_defaults(func=cmd_forum)
    q = sub.add_parser("leaderboard"); q.add_argument("--run", required=True); q.add_argument("--full", action="store_true"); q.set_defaults(func=cmd_leaderboard)
    q = sub.add_parser("survey"); q.add_argument("action", choices=["add", "index", "verify", "queries", "log-query"]); q.add_argument("--run", required=True); q.add_argument("--entry"); q.set_defaults(func=cmd_survey)
    q = sub.add_parser("heldout"); q.add_argument("action", choices=["manifest", "verify"]); q.add_argument("--store", required=True); q.add_argument("--run"); q.add_argument("--manifest"); q.add_argument("--suite-items", action="append"); q.add_argument("--threshold", type=float, default=0.5); q.set_defaults(func=cmd_heldout)
    q = sub.add_parser("plateau"); q.add_argument("--run", required=True); q.add_argument("--window", type=int); q.add_argument("--min-gain", type=float); q.set_defaults(func=cmd_plateau)
    q = sub.add_parser("audit"); q.add_argument("action", choices=["prepare", "collect", "exclusions"]); q.add_argument("--run", required=True); q.add_argument("--chunk-chars", type=int, default=6000); q.add_argument("--threshold", type=int, default=4); q.add_argument("--exclude", action="store_true"); q.set_defaults(func=cmd_audit)
    q = sub.add_parser("sources"); q.add_argument("action", choices=["probe", "search"]); q.add_argument("--query", default="agent memory"); q.add_argument("--source", action="append", default=[]); q.add_argument("--limit", type=int, default=5); q.set_defaults(func=cmd_sources)
    q = sub.add_parser("snapshot"); q.add_argument("--run", required=True); q.add_argument("--method"); q.set_defaults(func=cmd_snapshot)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.cmd == "sources" and args.action == "search" and not args.source:
        args.source = ["arxiv", "openalex", "crossref"]
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
