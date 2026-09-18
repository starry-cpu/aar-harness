"""rundata.py -- read one run directory and build the dashboard DATA bundle.

The dashboard is a derived view: it is rebuildable at any time from the run directory and
it decides nothing.  Gate verdicts, exclusion membership, leaderboard order, the stop
verdict and the integrity report all come from aar_lib; this module reads files and
arranges what is already decided.  Missing data renders as a dash, never as a zero and
never as a pass.

One rule learned the hard way: a number in a design mock that has no source in the run
directory is a placeholder, not a requirement.  Leave the empty state visible instead of
finding a lookalike number somewhere else -- a real number under the wrong label (a
reference implementation's score printed as "the baseline") misleads more than a gap.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import aar_lib as A

# The eleven INTEGRITY_JUDGE categories, in rubric order (references/prompts.md).
# Used for the "N 类分类器" denominator and to order ties; a category a verdict file
# invents is still displayed, counted under 其余分类.
AUDIT_CATEGORIES = (
    "Held-out peek",
    "Benchmark-data use",
    "Self-authored data",
    "Larger-model distillation",
    "Scorer or harness tampering",
    "Degenerate metric-gaming",
    "Capability-filter tampering",
    "Finding forgery",
    "Judge injection",
    "Seed cherry-picking",
    "Other",
)

# PAPER_MONITOR blocking kinds that mean a deliberate rule break rather than an
# incomplete write-up.  Only used for the leaderboard flag column.
SEVERE_BLOCKING_KINDS = ("leaked_result", "forbidden_construct", "fabricated_result",
                         "scorer_tampering", "heldout_peek")

# The untuned baseline scores exactly 0.0 in this harness's closed-fraction convention
# (raw == baseline => (raw - baseline) / (optimum - baseline) == 0).  It is derived, not
# read: no run file carries a baseline score, and the panel must never present a
# reference implementation's number as the baseline.
BASELINE_SCORE_BY_CONSTRUCTION = 0.0


# ------------------------------------------------------------------ helpers

def utc_now():
    return datetime.now(timezone.utc)


def parse_utc(text):
    """Run timestamps are aar_lib.utcnow() output; anything else counts as absent."""
    if not text:
        return None
    try:
        return datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def display_time(text):
    """'2026-09-17T11:49:28Z' -> '2026-09-17 11:49 UTC'."""
    t = str(text or "")
    if len(t) >= 16 and t[10] == "T":
        return t[:16].replace("T", " ") + " UTC"
    return t or None


def format_elapsed(started, now):
    """Wall clock since the run started, in the prototype's 4h45m shape."""
    t0 = parse_utc(started)
    if t0 is None:
        return None
    secs = max(0, int((now - t0).total_seconds()))
    hours, rem = divmod(secs, 3600)
    minutes, seconds = divmod(rem, 60)
    if hours:
        return "%dh%02dm" % (hours, minutes)
    if minutes:
        return "%dm%02ds" % (minutes, seconds)
    return "%ds" % seconds


def is_running(run_dir, last_published):
    """A run is still going unless a final report exists that is newer than the last
    finding.  The orchestrator writes reports/final.json when the loop stops, so its
    mtime is the closest thing to a stop time we have."""
    final = Path(run_dir) / "reports" / "final.json"
    if not final.exists():
        return True
    if not last_published:
        return False
    last = parse_utc(last_published)
    if last is None:
        return False
    return datetime.fromtimestamp(final.stat().st_mtime, tz=timezone.utc) < last


def title_from(question, limit=60):
    q = " ".join(str(question or "").split())
    if not q:
        return None
    return q[:limit] + ("…" if len(q) > limit else "")


# ------------------------------------------------------- paper monitor reads

def load_paper_verdicts(run_dir):
    """{method_id: {verdict, confidence, blocking_kinds, flag}} from review/paper/*.json.

    A missing file is 'not_reviewed'; a file that cannot be parsed, or that review.py
    wrote as unparsed, is 'unparsed' -- undecided, never a rejection.
    """
    out = {}
    pdir = Path(run_dir) / "review" / "paper"
    if not pdir.is_dir():
        return out
    for f in sorted(pdir.glob("*.json")):
        try:
            rec = A.read_json(f)
        except (OSError, ValueError):
            rec = None
        if not isinstance(rec, dict):
            out[f.stem] = {"verdict": "unparsed", "confidence": None, "blocking_kinds": [], "flag": None}
            continue
        verdict = rec.get("verdict")
        verdict = str(verdict) if verdict else None
        kinds = [b.get("kind") for b in (rec.get("blocking_findings") or [])
                 if isinstance(b, dict) and b.get("kind")]
        conf = rec.get("confidence")
        out[f.stem] = {
            "verdict": verdict,
            "confidence": float(conf) if isinstance(conf, (int, float)) else None,
            "blocking_kinds": kinds,
            "flag": kinds[0] if kinds and kinds[0] in SEVERE_BLOCKING_KINDS else None,
        }
    return out


def paper_state(finding, paper):
    """The 审查 column: a monitor rejection is 'n/a', it never reached paper review."""
    if finding.get("status") == "rejected_by_monitor":
        return "n/a"
    return paper.get("verdict") or "not_reviewed"


def rejection_reason(finding):
    ev = finding.get("evidence") or {}
    problems = ev.get("problems") or []
    if problems:
        return str(problems[0])
    if ev.get("detail"):
        return str(ev["detail"])
    return finding.get("claim_mismatch") or None


# ------------------------------------------------------------- findings rows

def finding_rows(run_dir, papers, excluded_ids):
    """One row per published finding, ordered by seq.  Excluded methods stay in."""
    rows = []
    for rec in A.list_findings(run_dir):
        mid = rec.get("method_id")
        gates = rec.get("gates") or []
        paper = papers.get(mid) or {}
        row = {
            "seq": rec.get("seq"),
            "method_id": mid,
            "finding_id": rec.get("finding_id"),
            "aggregate": (rec.get("aggregate") or {}).get("value"),
            "gates_pass": A.all_gates_pass(gates) if gates else None,
            "status": rec.get("status"),
            "excluded": mid in excluded_ids,
            "paper": paper_state(rec, paper),
            "family": rec.get("family"),
            "researcher": (rec.get("author") or {}).get("researcher_id"),
        }
        if paper.get("confidence") is not None:
            row["confidence"] = paper["confidence"]
        if paper.get("flag"):
            row["flag"] = paper["flag"]
        if rec.get("status") == "rejected_by_monitor":
            row["reason"] = rejection_reason(rec)
        rows.append(row)
    rows.sort(key=lambda r: (r["seq"] is None, r["seq"]))
    return rows


# ------------------------------------------------------------- climb reading

def climb_narrative(rows, min_gain=0.005):
    """仍在上升 / 已见顶 / 无数据, using plateau_decision's own improvement rule.

    aar_lib.plateau_decision guards on len(vals) < window on purpose: a stop verdict
    must not fire on a short run.  This is the descriptive reading of the same series,
    so it drops the guard but keeps the +min_gain improvement test -- which is why a
    short run can read 已见顶 while the live stop verdict still reads 样本不足.
    """
    scored = [r for r in rows if r.get("aggregate") is not None]
    if not scored:
        return {"state": "empty", "label": "○ 无数据", "tone": "muted"}
    best, best_idx = -1.0, 0
    for i, r in enumerate(scored):
        v = float(r["aggregate"])
        if v > best + min_gain:
            best, best_idx = v, i
    since = len(scored) - 1 - best_idx
    if since <= 0:
        return {"state": "climbing", "label": "▲ 仍在上升", "tone": "pass"}
    return {"state": "peaked", "label": "⚠ 已见顶", "tone": "warn", "since_best": since}


def plateau_band(findings, winner):
    """The flat region of the curve: from the champion's finding to the last one."""
    if not winner or len(findings) < 2:
        return None
    start = winner.get("seq")
    if start is None:
        return None
    after = [f for f in findings if f.get("seq") is not None and f["seq"] > start]
    scored_after = len([f for f in after if f.get("aggregate") is not None])
    if not scored_after:
        return None
    excluded_after = len([f for f in after if f.get("excluded")])
    text = "从 #%s 起 %d 个已评分方法没有带来任何增益，其中 %d 个事后被排除。" % (start, scored_after, excluded_after)
    return {"from": start, "to": findings[-1]["seq"], "text": text,
            "scored_after": scored_after, "excluded_after": excluded_after}


def climb_note(climb, band):
    """The curve subtitle: the flat-region sentence, else a one-line state."""
    if band:
        return band["text"]
    if climb["state"] == "empty":
        return "尚无方法被评分"
    if climb["state"] == "climbing":
        return "仍在上升：最后一个已评分方法刷新了最好成绩。"
    return "已见顶：最后一个已评分方法之后没有新的增益。"


# ------------------------------------------------------------- winner detail

def winner_block(run_dir, cfg, rows, records):
    """First leaderboard row that passed its gates with a non-null aggregate.

    The ranking rule is aar_lib.leaderboard_rows; this only picks its head.
    """
    best = None
    for r in A.leaderboard_rows(run_dir):
        if r.get("gates_pass") and r.get("aggregate") is not None:
            best = r
            break
    if best is None:
        return None
    rec = records.get(best["method_id"]) or {}
    gates = rec.get("gates") or []
    gate = None
    if gates:
        g = gates[0]
        line = None
        for gc in (cfg.get("gates") or []):
            if gc.get("name") == g.get("name"):
                line = gc.get("line")
        mean = (g.get("method") or {}).get("mean")
        used_pct = None
        if mean is not None and line:
            used_pct = max(0.0, min(1.0, float(mean) / float(line))) * 100.0
        gate = {"name": g.get("name"), "direction": g.get("direction"), "line": line,
                "method_mean": mean, "baseline_mean": (g.get("baseline") or {}).get("mean"),
                "margin": g.get("margin"), "pass": bool(g.get("pass")), "used_pct": used_pct}
    per_bench = {k: (v or {}).get("closed") for k, v in (rec.get("scores") or {}).items()}
    return {
        "method_id": best["method_id"],
        "finding_id": best.get("finding_id"),
        "seq": rec.get("seq"),
        "family": rec.get("family") or best.get("family"),
        "researcher": best.get("researcher_id"),
        "per_bench": per_bench,
        "aggregate": best.get("aggregate"),
        "gate": gate,
        "hashes": {"mini_paper": (rec.get("mini_paper") or {}).get("hash"),
                   "artifact": rec.get("artifact_hash"),
                   "score_file": (rec.get("evidence") or {}).get("score_file_hash")},
        "claims": [str(c) for c in (rec.get("claims") or [])],
    }


def bottleneck_of(per_bench):
    """The benchmark the geometric mean is actually bound by, or None."""
    known = {k: v for k, v in (per_bench or {}).items() if v is not None}
    if not known:
        return None
    return min(known.items(), key=lambda kv: kv[1])[0]


# --------------------------------------------------------------- audit panel

def audit_block(run_dir):
    """Histogram and category hits folded from audit/verdicts/*.json."""
    adir = Path(run_dir) / "audit"
    vdir = adir / "verdicts"
    verdicts = []
    if vdir.is_dir():
        for f in sorted(vdir.glob("*.json")):
            rec = A.read_json(f, default=None)
            if isinstance(rec, dict):
                verdicts.append(rec)
    if not verdicts:
        return None
    manifest = A.read_json(adir / "chunks.json", default={}) or {}
    chunks_total = manifest.get("count")
    if chunks_total is None:
        cdir = adir / "chunks"
        chunks_total = len(list(cdir.glob("*.txt"))) if cdir.is_dir() else 0
    histogram = Counter()
    categories = Counter()
    for rec in verdicts:
        score = rec.get("score")
        if isinstance(score, (int, float)):
            histogram[str(int(score))] += 1
        for c in (rec.get("categories") or []):
            categories[str(c)] += 1
    report = A.read_json(adir / "report.json", default={}) or {}
    order = {name: i for i, name in enumerate(AUDIT_CATEGORIES)}
    ranked = sorted(categories.items(), key=lambda kv: (-kv[1], order.get(kv[0], len(AUDIT_CATEGORIES)), kv[0]))
    unmapped = sum(v for k, v in categories.items() if k not in order)
    judged = len(verdicts)
    coverage = round(judged / chunks_total, 2) if chunks_total else None
    # audit_collect writes threshold and flagged; a missing report leaves them unknown
    # rather than defaulted, because "flagged: none" would be a claim the run never made.
    return {
        "chunks_total": chunks_total,
        "chunks_judged": judged,
        "coverage": coverage,
        "traces": len(report.get("traces") or []) if report else None,
        "histogram": {k: histogram[k] for k in sorted(histogram, key=int)},
        "threshold": report.get("threshold"),
        "flagged": len(report["flagged"]) if isinstance(report.get("flagged"), list) else None,
        "categories": dict(ranked),
        "categories_total": len(AUDIT_CATEGORIES),
        "categories_unmapped": unmapped,
    }


# ---------------------------------------------------------------- integrity

def integrity_block(run_dir, cfg, with_integrity=True):
    """verify_forum problems, held-out leak scan, duplicate artifacts.

    Every verdict comes from aar_lib.  --no-integrity skips the slow tree scan, and
    each field then renders as 未检查 rather than as a pass.
    """
    if not with_integrity:
        return {"forum_verify": None, "forum_problems": None, "heldout_verify": None,
                "leaks": None, "duplicate_artifacts": None, "overlap_ratio": None}
    problems = A.verify_forum(run_dir)
    store = (cfg.get("held_out") or {}).get("store")
    suite_files = [b.get("items_file") for b in (cfg.get("suite") or []) if b.get("items_file")]
    held = A.verify_heldout(store, run_dir, suite_item_files=suite_files) if store else None
    overlap = ((held or {}).get("overlap") or {}).get("ratio")
    return {
        "forum_verify": "ok" if not problems else "problems",
        "forum_problems": len(problems),
        "heldout_verify": None if held is None else ("ok" if not held.get("leaks") else "leaks"),
        "leaks": None if held is None else len(held.get("leaks") or []),
        "duplicate_artifacts": len([p for p in problems if p.get("kind") == "duplicate_artifact_hash"]),
        "overlap_ratio": overlap,
    }


# ------------------------------------------------------------------ bundle

def load_reference(path):
    """--reference-file: {"name", "per_bench", "aggregate"} (+ optional held_out)."""
    if not path:
        return None
    rec = A.read_json(path)
    if not isinstance(rec, dict):
        raise ValueError("reference file must contain a JSON object: " + str(path))
    per_bench = rec.get("per_bench") or {}
    if not isinstance(per_bench, dict):
        raise ValueError("reference per_bench must be an object: " + str(path))
    aggregate = rec.get("aggregate")
    if aggregate is None and per_bench:
        vals = [float(v) for v in per_bench.values() if v is not None]
        if vals and all(v > 0 for v in vals):
            aggregate = A.aggregate_geomean(vals)[0]
    return {"name": rec.get("name") or Path(path).stem,
            "per_bench": {str(k): (None if v is None else float(v)) for k, v in per_bench.items()},
            "aggregate": None if aggregate is None else float(aggregate),
            "held_out": rec.get("held_out") if isinstance(rec.get("held_out"), dict) else None}


def held_out_block(cfg, reference, integrity, winner=None):
    """run_config.held_out + reports/final.json's verification + the reference's own run.

    There is no baseline score to read anywhere, and none is invented: the untuned
    baseline is the 0 point of this scoring convention
    (BASELINE_SCORE_BY_CONSTRUCTION).  What carries information is the champion's
    held-out cost against the untuned baseline cost.  A reference implementation's score
    on the same sealed workload is a different fact, and the page labels it 参考实现.
    """
    reports = A.run_paths(cfg["run_dir"])["reports"] if cfg.get("run_dir") else None
    final = (A.read_json(reports / "final.json", default={}) or {}) if reports else {}
    ver = final.get("verification") or {}
    if not ver:
        return None
    ref = reference or {}
    ref_held = ref.get("held_out") or {}
    selected = ver.get("selected")
    method_cost = ver.get("heldout_cost")
    baseline_cost = ver.get("heldout_baseline_cost")
    method_score = ver.get("heldout_score")
    removed = None
    if method_cost is not None and baseline_cost:
        removed = 1.0 - float(method_cost) / float(baseline_cost)
    elif method_score is not None:
        removed = float(method_score)
    champion = bool(selected and winner and selected == winner.get("method_id"))
    return {
        "bench": ver.get("heldout_bench"),
        "generalization": (cfg.get("held_out") or {}).get("generalization"),
        "subject": "冠军" if champion else "选中方法",
        "method_id": selected,
        "method_score": method_score,
        "method_cost": method_cost,
        "baseline_cost": baseline_cost,
        "baseline_score": BASELINE_SCORE_BY_CONSTRUCTION,
        "removed_fraction": removed,
        "generalizes": ver.get("generalizes"),
        "overlap_ratio": integrity.get("overlap_ratio"),
        "reference_name": ref.get("name"),
        "reference_score": ref_held.get("score"),
    }


def build_bundle(run_dir, title=None, reference=None, integrity=True, now=None, refresh=None):
    """The whole DATA object the dashboard consumes.  Read-only.

    Always carries every finding: the data file is the complete snapshot, and inlining
    fewer rows into the page is a rendering decision (dashboard.page_view), not an
    extraction one.
    """
    run = Path(run_dir)
    cfg = dict(A.load_run_config(run))
    cfg.setdefault("run_dir", str(run))
    now = now or utc_now()
    papers = load_paper_verdicts(run)
    excluded_ids = {e.get("method_id") for e in A.load_exclusions(run)}
    records = {r.get("method_id"): r for r in A.list_findings(run)}
    rows = finding_rows(run, papers, excluded_ids)
    winner = winner_block(run, cfg, rows, records)
    band = plateau_band(rows, winner)
    stop = cfg.get("stop") or {}
    window = stop.get("plateau_window", 15)   # keep in step with aar_lib.plateau_decision
    min_gain = stop.get("min_gain", 0.005)
    climb = climb_narrative(rows, min_gain)
    stop_verdict = A.plateau_decision(rows, window=window, min_gain=min_gain)
    climb["stop"] = stop_verdict.get("stop")
    climb["reason"] = stop_verdict.get("reason")
    climb["since_best_window"] = stop_verdict.get("since_best")
    climb["window"] = window
    climb["min_gain"] = min_gain
    climb["note"] = climb_note(climb, band)
    integ = integrity_block(run, cfg, with_integrity=integrity)
    blocked = Counter()
    for p in papers.values():
        blocked.update(p["blocking_kinds"])
    monitors = None
    if papers:
        verdicts = [p["verdict"] for p in papers.values()]
        monitors = {
            "reviewed": len([v for v in verdicts if v and v != "unparsed"]),
            "approve": len([v for v in verdicts if v == "approve"]),
            "reject": len([v for v in verdicts if v == "reject"]),
            "unparsed": len([v for v in verdicts if v == "unparsed"]),
            "blocking_kinds": dict(sorted(blocked.items(), key=lambda kv: (-kv[1], kv[0]))),
        }
    published = sorted(r["published_at"] for r in records.values() if r.get("published_at"))
    started = published[0] if published else cfg.get("created_at")
    last_published = published[-1] if published else None
    running = is_running(run, last_published)
    # elapsed is the loop ACTIVE span, not "time since the run was framed": the latter
    # grows without bound and always overshoots the budget, which breaks the one number
    # a viewer reads to answer "how far along is this" (handoff 14.2).
    if last_published is None:
        elapsed = None
    elif running:
        elapsed = format_elapsed(started, now)
    else:
        elapsed = format_elapsed(started, parse_utc(last_published) or now)
    hold = stop.get("wall_clock_hours")
    retrieval = (cfg.get("retrieval") or {}).get("tier")
    generated = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    return {
        "schema": "aar-dashboard/1",
        "generated_at": generated,
        "run": {
            "title": cfg.get("title") or title or title_from(cfg.get("question")) or run.name,
            "question": cfg.get("question"),
            "tier": cfg.get("tier"),
            "driver": cfg.get("driver"),
            "researchers": cfg.get("researchers"),
            "started": started,
            "last_published": last_published,
            "elapsed": elapsed,
            "since_last": format_elapsed(last_published, now) if last_published else None,
            "running": running,
            "budget": None if hold is None else "%sh" % hold,
            "plateau_window": window,
            "min_gain": min_gain,
            "retrieval_tier": retrieval,
            "config_hash": cfg.get("config_hash"),
            "generated_at_display": display_time(generated),
            "regen_note": ("实时刷新：每 %d 秒整页重载当前快照，不修改运行数据" % int(refresh))
                          if refresh else "重新生成：使用当前内联快照，不修改运行数据",
        },
        "status": {
            "methods": len(rows),
            "gates_pass": len([r for r in rows if r["gates_pass"] is True]),
            "best": None if not winner else winner["aggregate"],
            "excluded": len([r for r in rows if r["excluded"]]),
            "retrieval": retrieval,
        },
        "suite": [{"name": b.get("name"), "metric": b.get("metric"),
                   "baseline": b.get("baseline"), "optimum": b.get("optimum")}
                  for b in (cfg.get("suite") or [])],
        "gates": [{"name": g.get("name"), "direction": g.get("direction"), "line": g.get("line")}
                  for g in (cfg.get("gates") or [])],
        "held_out": held_out_block(cfg, reference, integ, winner),
        "findings": rows,
        "findings_total": len(rows),
        "ceiling": None if not winner else winner["aggregate"],
        "plateau_band": band,
        "climb": climb,
        "winner": winner,
        "bottleneck": bottleneck_of((winner or {}).get("per_bench")),
        "reference": reference,
        "monitors": monitors,
        "audit": audit_block(run),
        "integrity": integ,
        "refresh": {"seconds": int(refresh)} if refresh else None,
        "source": {"run_dir": str(run.resolve()), "template": "dashboard/template.html"},
    }
