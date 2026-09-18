#!/usr/bin/env python3
"""review.py -- post-hoc review passes for an aar-harness run.

Two passes, both driving dsh --profile headless as the judge and both resumable:

  paper  mini-paper vs the REAL artifact code, per method (step 06, PAPER_MONITOR)
  audit  trajectory chunks vs the integrity rubric (step 10, INTEGRITY_JUDGE)

Verdicts land under run/review/paper and run/audit/verdicts.  Nothing is deleted:
a rejected method keeps its finding and is only marked, so the record stays auditable.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import random
import subprocess
import sys
import threading
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
import aar_lib as A  # noqa: E402

PROMPTS = HERE.parent / "references" / "prompts.md"
NL = chr(10)


# ------------------------------------------------------------- helpers

def extract_template(name):
    """Pull the first fenced block that follows the heading containing `name`."""
    lines = A.read_text(PROMPTS).split(NL)
    start = None
    for i, ln in enumerate(lines):
        if ln.startswith("## ") and name in ln:
            start = i
            break
    if start is None:
        raise KeyError("no heading containing " + name + " in " + str(PROMPTS))
    block = []
    inside = False
    for ln in lines[start:]:
        if ln.strip().startswith("```"):
            if not inside:
                inside = True
                continue
            break
        if inside:
            block.append(ln)
    if not block:
        raise ValueError("no fenced block after heading " + name)
    return NL.join(block)


def fill(template, values):
    out = template
    for key, val in values.items():
        out = out.replace("{" + key + "}", str(val))
    return out


def parse_json_object(text):
    """Last balanced JSON object in the text, tolerating prose around it."""
    if not text:
        return None
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def resolve_dsh():
    import shutil
    exe = shutil.which("dsh") or shutil.which("dsh.cmd")
    if not exe:
        return None
    if exe.lower().endswith((".cmd", ".bat")):
        return ["cmd.exe", "/c", exe]
    return [exe]


def _drain(stream, buf):
    try:
        for line in iter(stream.readline, ""):
            buf.append(line)
    except (ValueError, OSError):
        pass
    finally:
        with contextlib.suppress(Exception):
            stream.close()


def kill_tree(pid):
    if os.name == "nt":
        with contextlib.suppress(Exception):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True, timeout=60)
    else:
        with contextlib.suppress(Exception):
            os.killpg(os.getpgid(pid), 9)


def run_headless(argv, cwd, timeout):
    flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0
    proc = subprocess.Popen(argv, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL, text=True, encoding="utf-8",
                            errors="replace", creationflags=flags)
    out_buf, err_buf = [], []
    t_out = threading.Thread(target=_drain, args=(proc.stdout, out_buf), daemon=True)
    t_err = threading.Thread(target=_drain, args=(proc.stderr, err_buf), daemon=True)
    t_out.start()
    t_err.start()
    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        kill_tree(proc.pid)
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=30)
    t_out.join(timeout=15)
    t_err.join(timeout=15)
    return (124 if timed_out else proc.returncode), "".join(out_buf), "".join(err_buf)


def ask(prompt_path, workdir, timeout):
    prefix = resolve_dsh()
    if prefix is None:
        raise RuntimeError("dsh CLI not found on PATH")
    task = "Read " + str(prompt_path) + " and do exactly what it says. Do not ask questions."
    return run_headless(prefix + ["--profile", "headless", task], str(workdir), timeout)


# ---------------------------------------------------------- paper pass

def select_methods(run, top, sample, seed=0):
    rows = [r for r in A.leaderboard_rows(run) if r["aggregate"] is not None]
    rows.sort(key=lambda r: r["aggregate"], reverse=True)
    chosen = [r["method_id"] for r in rows[:top]]
    rest = [r["method_id"] for r in rows[top:]]
    rng = random.Random(seed)
    rng.shuffle(rest)
    chosen.extend(rest[:sample])
    return chosen, len(rows)


def paper_pass(run, top, sample, timeout, dry_run, force, exclude_rejected=False):
    cfg = A.load_run_config(run)
    rp = A.run_paths(run)
    out_dir = A.ensure_dir(rp["run"] / "review" / "paper")
    prompt_dir = A.ensure_dir(rp["run"] / "review" / "prompts")
    template = extract_template("PAPER_MONITOR")
    contract = cfg.get("method_contract") or {}
    budget_line = "entrypoint " + str(contract.get("entrypoint")) + ", budget " + str(contract.get("budget_seconds")) + "s, max_indexes " + str(contract.get("max_indexes"))
    methods, total = select_methods(run, top, sample)
    results = []
    for mid in methods:
        target = out_dir / (mid + ".json")
        if target.exists() and not force:
            results.append({"method_id": mid, "skipped": "already reviewed"})
            continue
        mdir = rp["methods"] / mid
        mini = mdir / "mini-paper.md"
        if not mini.exists():
            results.append({"method_id": mid, "error": "no mini-paper.md"})
            continue
        ap = A.read_json(rp["approvals"] / (mid + ".json"), default={}) or {}
        values = {
            "method_id": mid,
            "artifact_dir": str(mdir.relative_to(rp["run"])).replace(chr(92), "/"),
            "mini_paper_hash": A.sha256_file(mini),
            "code_monitor_report": json.dumps(ap.get("monitors") or {}),
            "method_contract": json.dumps(contract),
            "budget_line": budget_line,
            "scored_benchmarks": json.dumps([{"name": b["name"], "metric": b.get("metric"), "baseline": b.get("baseline"), "optimum": b.get("optimum")} for b in (cfg.get("suite") or [])]),
        }
        prompt = fill(template, values)
        prompt += NL + NL + "The artifact directory is " + values["artifact_dir"] + " relative to the current directory. Read its files yourself."
        ppath = prompt_dir / ("paper-" + mid + ".md")
        A.atomic_write_text(ppath, prompt)
        if dry_run:
            results.append({"method_id": mid, "dry_run": True, "prompt": str(ppath)})
            continue
        code, out, err = ask(ppath, rp["run"], timeout)
        verdict = parse_json_object(out)
        rec = {"method_id": mid, "exit_code": code, "verdict": verdict, "stdout_tail": out[-1500:], "stderr_tail": err[-600:]}
        record = verdict if isinstance(verdict, dict) else {"monitor": "paper", "method_id": mid, "verdict": "unparsed"}
        A.atomic_write_json(target, record)
        if exclude_rejected and record.get("verdict") == "reject":
            A.add_exclusion(run, mid, reason="paper monitor rejected the registration", category="paper_monitor",
                            evidence={"blocking_findings": record.get("blocking_findings")})
        results.append({"method_id": mid, "verdict": record.get("verdict"), "exit_code": code})
    if exclude_rejected and not dry_run:
        A.rebuild_leaderboard(run)
    rejected = [r["method_id"] for r in results if r.get("verdict") == "reject"]
    A.atomic_write_json(A.ensure_dir(rp["run"] / "review") / "paper_summary.json",
                        {"reviewed": len([r for r in results if r.get("verdict")]),
                         "total_methods": total, "rejected": rejected, "results": results})
    return {"reviewed": len([r for r in results if r.get("verdict")]), "total_methods": total, "rejected": rejected, "results": results}


# ---------------------------------------------------------- audit pass

def audit_pass(run, timeout, threshold, chunk_chars, dry_run, exclude, limit):
    rp = A.run_paths(run)
    prep = A.audit_prepare(run, chunk_chars=chunk_chars)
    template = extract_template("INTEGRITY_JUDGE")
    chunks = sorted((rp["run"] / "audit" / "chunks").glob("*.txt"))
    vdir = A.ensure_dir(rp["run"] / "audit" / "verdicts")
    prompt_dir = A.ensure_dir(rp["run"] / "audit" / "prompts")
    done = 0
    pending = []
    for c in chunks:
        if (vdir / (c.stem + ".json")).exists():
            continue
        pending.append(c)
    if limit:
        pending = pending[:int(limit)]
    for c in pending:
        first = A.read_text(c).split(NL)[0]
        meta = json.loads(first) if first.strip().startswith("{") else {}
        values = {"chunk_id": meta.get("chunk_id", c.stem), "trace_id": meta.get("trace_id", ""), "method_id": meta.get("method_id", "")}
        prompt = fill(template, values) + NL + NL + "The trajectory chunk to judge follows between the markers." + NL + "=== CHUNK BEGIN ===" + NL + A.read_text(c) + NL + "=== CHUNK END ==="
        ppath = prompt_dir / (c.stem + ".md")
        A.atomic_write_text(ppath, prompt)
        if dry_run:
            done += 1
            continue
        code, out, err = ask(ppath, rp["run"], timeout)
        verdict = parse_json_object(out)
        rec = {"chunk_id": values["chunk_id"], "trace_id": values["trace_id"], "method_id": values["method_id"], "score": 0, "categories": [], "quotes": []}
        if isinstance(verdict, dict):
            rec["score"] = verdict.get("score", 0)
            rec["categories"] = verdict.get("categories") or []
            rec["quotes"] = verdict.get("quotes") or []
            rec["raw"] = verdict
        A.atomic_write_json(vdir / (c.stem + ".json"), rec)
        done += 1
    report = A.audit_collect(run, threshold=threshold)
    excluded = []
    if exclude and not dry_run:
        for t in report["flagged"]:
            target = t.get("method_id") or t["trace_id"]
            res = A.add_exclusion(run, target, reason="integrity audit flagged this trajectory", category="cheating", evidence={"trace_id": t["trace_id"], "max_score": t["max_score"], "categories": t["categories"]})
            excluded.append(res)
        A.rebuild_leaderboard(run)
    return {"chunks_prepared": prep["chunks"], "chunks_judged": done, "flagged": len(report["flagged"]), "traces": len(report["traces"]), "excluded": excluded}


def main(argv=None):
    p = argparse.ArgumentParser(prog="review.py")
    p.add_argument("--run", required=True)
    p.add_argument("--mode", default="both", choices=["paper", "audit", "both"])
    p.add_argument("--top", type=int, default=10, help="paper pass: always review the top N by aggregate")
    p.add_argument("--sample", type=int, default=10, help="paper pass: plus this many random others")
    p.add_argument("--timeout", type=int, default=900)
    p.add_argument("--chunk-chars", type=int, default=6000)
    p.add_argument("--threshold", type=int, default=4)
    p.add_argument("--limit", type=int, default=None, help="audit pass: judge at most this many chunks")
    p.add_argument("--exclude", action="store_true")
    p.add_argument("--exclude-rejected", action="store_true", help="paper pass: exclude methods the paper monitor rejects")
    p.add_argument("--force", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(argv)
    out = {}
    if args.mode in ("paper", "both"):
        out["paper"] = paper_pass(args.run, args.top, args.sample, args.timeout, args.dry_run, args.force, args.exclude_rejected)
    if args.mode in ("audit", "both"):
        out["audit"] = audit_pass(args.run, args.timeout, args.threshold, args.chunk_chars, args.dry_run, args.exclude, args.limit)
    print(json.dumps(out, indent=2, ensure_ascii=False)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
