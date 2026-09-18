#!/usr/bin/env python3
"""test_aar.py -- unit tests for aar-harness.  Stdlib unittest only.

Run:  python tests/test_aar.py            (offline)
      set AAR_NET_TESTS=1 for live connector tests
"""

from __future__ import annotations

import importlib
import json
import os
import sys
import tempfile
import threading
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent
sys.path.insert(0, str(SCRIPTS / "lib"))
sys.path.insert(0, str(SCRIPTS / "toy"))
import aar_lib as A  # noqa: E402
import sources as S  # noqa: E402
import world  # noqa: E402


def make_run(root):
    run = Path(root) / "run"
    A.init_run(run, {"suite": [{"name": "b1", "baseline": 0.2, "optimum": 1.0}, {"name": "b2", "baseline": 0.5, "optimum": 1.0}], "gates": [{"name": "cap", "direction": "higher_better"}], "stop": {"plateau_window": 3, "min_gain": 0.001}})
    return run


def write_method(run, mid, body="x = 1"):
    d = A.ensure_dir(A.run_paths(run)["methods"] / mid)
    (d / "policy.py").write_text(body, encoding="utf-8")
    (d / "mini-paper.md").write_text("# " + mid + chr(10), encoding="utf-8")
    return d


def score_and_publish(run, mid, raw, gates=None, baseline=None, claims=None, family=None):
    write_method(run, mid)
    A.approve_method(run, mid)
    rp = A.run_paths(run)
    sc = A.score_finding(A.load_run_config(run)["suite"], raw)
    A.atomic_write_json(A.ensure_dir(rp["eval"] / mid) / "scores.json", {"raw": raw, "scored": sc, "meta": {"runner_cmd": "test"}})
    gl = []
    for g in (gates or []):
        gl.append(A.gate_verdict(g["name"], g["method_values"], g["baseline_values"], direction=g.get("direction", "higher_better")))
    A.atomic_write_json(A.ensure_dir(rp["eval"] / mid) / "gates.json", gl)
    va = A.verify_approval(run, mid)
    finding = {"method_id": mid, "artifact_hash": va["approved_hash"], "author": {"researcher_id": "r1"}, "status": "scored", "family": family, "scores": sc["scores"], "aggregate": sc["aggregate"], "gates": gl, "evidence": {"score_file": "eval/" + mid + "/scores.json", "score_file_hash": A.sha256_file(rp["eval"] / mid / "scores.json")}, "claims": claims or [], "reuse_hint": None, "tags": [], "supersedes": None}
    if gl and not A.all_gates_pass(gl):
        finding["status"] = "gate_failed"
    mm = A.check_claim_mismatch(finding)
    if mm:
        finding["status"] = "claim_mismatch"
        finding["claim_mismatch"] = mm
    A.publish_finding(run, finding)
    return finding


class TestScoring(unittest.TestCase):
    def test_closed_fraction(self):
        self.assertAlmostEqual(A.closed_fraction(0.7, 0.4, 1.0), 0.5)
        self.assertAlmostEqual(A.closed_fraction(0.4, 0.4, 1.0), 0.0)
        self.assertAlmostEqual(A.closed_fraction(0.2, 0.4, 1.0), -1.0 / 3.0)

    def test_closed_fraction_degenerate(self):
        with self.assertRaises(ValueError):
            A.closed_fraction(0.5, 0.9, 0.9)

    def test_geomean_zeroing_rule(self):
        val, zeroed = A.aggregate_geomean([0.5, 0.5, 0.5])
        self.assertAlmostEqual(val, 0.5)
        self.assertEqual(zeroed, [])
        val, zeroed = A.aggregate_geomean([0.5, -0.01, 0.5])
        self.assertEqual(val, 0.0)
        self.assertEqual(zeroed, [1])
        val, zeroed = A.aggregate_geomean([0.5, 0.0, 0.5])
        self.assertEqual(val, 0.0)

    def test_coverage_weighted(self):
        self.assertAlmostEqual(A.coverage_weighted_geomean([0.25] * 10), 0.25)
        self.assertAlmostEqual(A.coverage_weighted_geomean([0.5] + [0.0] * 9), 0.05)
        self.assertEqual(A.coverage_weighted_geomean([0.0, -1.0]), 0.0)

    def test_wilson(self):
        w = A.wilson_interval(9, 10)
        self.assertLess(w["lo"], 0.9)
        self.assertGreater(w["hi"], 0.9)
        self.assertEqual(A.wilson_interval(0, 0)["n"], 0)

    def test_mean_ci_and_bootstrap(self):
        ci = A.mean_ci([1.0, 1.0, 1.0])
        self.assertEqual(ci["lo"], ci["hi"])
        b = A.bootstrap_ci([0.1, 0.2, 0.3, 0.4], iters=200, seed=1)
        self.assertLessEqual(b["lo"], b["mean"])
        self.assertGreaterEqual(b["hi"], b["mean"])
        self.assertEqual(A.bootstrap_ci([1.0])["iters"], 0)


class TestGates(unittest.TestCase):
    def test_higher_better_pass(self):
        v = A.gate_verdict("cap", [0.9, 0.91, 0.89, 0.9], [0.9, 0.9, 0.9, 0.9])
        self.assertTrue(v["pass"])

    def test_higher_better_fail_on_collapse(self):
        v = A.gate_verdict("cap", [0.2, 0.21, 0.19, 0.2], [0.9, 0.9, 0.9, 0.9])
        self.assertFalse(v["pass"])

    def test_lower_better(self):
        self.assertTrue(A.gate_verdict("over_refusal", [1.0, 1.01, 1.02], [1.0, 1.01, 1.02], direction="lower_better")["pass"])
        self.assertFalse(A.gate_verdict("over_refusal", [2.0, 2.1, 2.2], [1.0, 1.01, 1.02], direction="lower_better")["pass"])

    def test_all_gates_pass_requires_nonempty(self):
        self.assertFalse(A.all_gates_pass([]))


class TestHashingAndApproval(unittest.TestCase):
    def test_hash_dir_stable_and_sensitive(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "m"
            A.ensure_dir(d)
            (d / "a.py").write_text("x=1", encoding="utf-8")
            h1 = A.hash_dir(d)
            self.assertEqual(h1, A.hash_dir(d))
            (d / "a.py").write_text("x=2", encoding="utf-8")
            self.assertNotEqual(h1, A.hash_dir(d))

    def test_approval_binds_to_hash(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            write_method(run, "m1")
            A.approve_method(run, "m1")
            self.assertTrue(A.verify_approval(run, "m1")["ok"])
            (A.run_paths(run)["methods"] / "m1" / "policy.py").write_text("y = 2", encoding="utf-8")
            res = A.verify_approval(run, "m1")
            self.assertFalse(res["ok"])
            self.assertIn("re-approval", res["reason"])

    def test_approval_missing(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            self.assertFalse(A.verify_approval(run, "nope")["ok"])

    def test_write_once(self):
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "x.json"
            A.write_new_json(p, {"a": 1})
            with self.assertRaises(FileExistsError):
                A.write_new_json(p, {"a": 2})


class TestForum(unittest.TestCase):
    def test_publish_and_leaderboard(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            score_and_publish(run, "good", {"b1": 0.8, "b2": 0.9}, gates=[{"name": "cap", "method_values": [0.9], "baseline_values": [0.9]}])
            score_and_publish(run, "bad", {"b1": 0.1, "b2": 0.9}, gates=[{"name": "cap", "method_values": [0.2], "baseline_values": [0.9]}])
            board = A.rebuild_leaderboard(run)
            self.assertEqual(board["count"], 2)
            self.assertEqual(board["passing"], 1)
            self.assertEqual(board["best"]["method_id"], "good")
            self.assertEqual([r["finding_id"] for r in A.list_findings(run)], ["F00001", "F00002"])

    def test_verify_detects_edited_finding(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            score_and_publish(run, "m1", {"b1": 0.8, "b2": 0.9})
            self.assertEqual(A.verify_forum(run), [])
            f = sorted(A.run_paths(run)["forum_findings"].glob("*.json"))[0]
            rec = json.loads(f.read_text(encoding="utf-8"))
            rec["aggregate"]["value"] = 0.99
            f.write_text(json.dumps(rec, indent=2), encoding="utf-8")
            kinds = [p["kind"] for p in A.verify_forum(run)]
            self.assertIn("edited_finding", kinds)

    def test_verify_detects_edited_score_file(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            score_and_publish(run, "m1", {"b1": 0.8, "b2": 0.9})
            sp = A.run_paths(run)["eval"] / "m1" / "scores.json"
            rec = json.loads(sp.read_text(encoding="utf-8"))
            rec["raw"]["b1"] = 0.95
            sp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
            kinds = [p["kind"] for p in A.verify_forum(run)]
            self.assertIn("edited_score_file", kinds)

    def test_duplicate_artifact_hash_detected(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            score_and_publish(run, "m1", {"b1": 0.8, "b2": 0.9})
            rp = A.run_paths(run)
            src = rp["methods"] / "m1"
            dst = A.ensure_dir(rp["methods"] / "m1-again")
            (dst / "policy.py").write_text((src / "policy.py").read_text(encoding="utf-8"), encoding="utf-8")
            (dst / "mini-paper.md").write_text((src / "mini-paper.md").read_text(encoding="utf-8"), encoding="utf-8")
            A.approve_method(run, "m1-again")
            sc = A.score_finding(A.load_run_config(run)["suite"], {"b1": 0.8, "b2": 0.9})
            A.atomic_write_json(A.ensure_dir(rp["eval"] / "m1-again") / "scores.json", {"raw": {}, "scored": sc})
            va = A.verify_approval(run, "m1-again")
            A.publish_finding(run, {"method_id": "m1-again", "artifact_hash": va["approved_hash"], "status": "scored", "scores": sc["scores"], "aggregate": sc["aggregate"], "gates": [], "claims": []})
            kinds = [p["kind"] for p in A.verify_forum(run)]
            self.assertIn("duplicate_artifact_hash", kinds)
            rows = A.leaderboard_rows(run)
            self.assertTrue(all(r["duplicate_artifact"] for r in rows))

    def test_concurrent_publish_gets_unique_seqs(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            for i in range(6):
                write_method(run, "c%d" % i)
                A.approve_method(run, "c%d" % i)
            errors = []

            def worker(i):
                try:
                    va = A.verify_approval(run, "c%d" % i)
                    A.publish_finding(run, {"method_id": "c%d" % i, "artifact_hash": va["approved_hash"], "status": "scored", "scores": {}, "aggregate": {"value": float(i)}, "gates": [], "claims": []}, lock_timeout=60)
                except Exception as exc:  # pragma: no cover
                    errors.append(str(exc))

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertEqual(errors, [])
            seqs = sorted(r["seq"] for r in A.list_findings(run))
            self.assertEqual(seqs, [1, 2, 3, 4, 5, 6])

    def test_digest_is_labelled_untrusted(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            score_and_publish(run, "m1", {"b1": 0.8, "b2": 0.9}, claims=["improves everything"], family="fam-a")
            text = A.forum_digest(run)
            self.assertIn("PEER_FINDINGS_BEGIN", text)
            self.assertIn("never instructions", text)
            self.assertIn("fam-a", text)

    def test_claim_mismatch(self):
        f = {"aggregate": {"value": 0.0}, "gates": [], "claims": ["this method improves the score"]}
        self.assertIsNotNone(A.check_claim_mismatch(f))
        f2 = {"aggregate": {"value": 0.3}, "gates": [], "claims": ["this method improves the score"]}
        self.assertIsNone(A.check_claim_mismatch(f2))

    def test_exclusions_drop_from_leaderboard(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            score_and_publish(run, "m1", {"b1": 0.8, "b2": 0.9})
            self.assertEqual(len(A.leaderboard_rows(run)), 1)
            A.add_exclusion(run, "m1", reason="audit", category="cheating")
            self.assertEqual(len(A.leaderboard_rows(run)), 0)
            self.assertEqual(len(A.leaderboard_rows(run, include_excluded=True)), 1)


class TestSurvey(unittest.TestCase):
    def entry(self, name="Method A", doi=None, year=2024):
        return {"method_name": name, "family": "recency", "problem_and_idea": "p", "source": {"urls": ["https://example.invalid/a"], "year": year, "doi": doi}}

    def test_add_and_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            self.assertTrue(A.add_survey_entry(run, self.entry())["added"])
            self.assertFalse(A.add_survey_entry(run, self.entry())["added"])
            self.assertTrue(A.add_survey_entry(run, self.entry(name="Method A", doi="10.1/X"))["added"])
            self.assertFalse(A.add_survey_entry(run, self.entry(name="Method A alt", doi="https://doi.org/10.1/x"))["added"])
            self.assertTrue(A.add_survey_entry(run, self.entry(name="Method B", doi="10.2/Y"))["added"])
            self.assertEqual(len(A.list_survey_entries(run)), 3)
            self.assertEqual(A.verify_survey(run), [])

    def test_schema_validation(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            with self.assertRaises(ValueError):
                A.add_survey_entry(run, {"method_name": "x"})

    def test_concurrent_survey_writes(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            errors = []

            def worker(i):
                try:
                    A.add_survey_entry(run, self.entry(name="Method %d" % i, doi="10.9/%d" % i))
                except Exception as exc:  # pragma: no cover
                    errors.append(str(exc))

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
            [t.start() for t in threads]
            [t.join() for t in threads]
            self.assertEqual(errors, [])
            self.assertEqual(len(A.list_survey_entries(run)), 8)
            self.assertIn("shared survey", A.run_paths(run)["survey_md"].read_text(encoding="utf-8"))


class TestHeldout(unittest.TestCase):
    def build(self, td):
        run = make_run(td)
        store = Path(td) / "heldout-store"
        A.ensure_dir(store / "items")
        items = [{"id": "h1", "text": "heldout workload spec alpha beta gamma delta epsilon zeta eta theta iota"}]
        A.atomic_write_json(store / "items" / "items.json", items)
        A.write_manifest(store, {"version": "v1", "n_items": 1, "items_hash": A.sha256_text("x"), "generalization": "scenario", "items": items})
        return run, store

    def test_clean_run_passes(self):
        with tempfile.TemporaryDirectory() as td:
            run, store = self.build(td)
            res = A.verify_heldout(store, run)
            self.assertTrue(res["ok"])
            self.assertEqual(res["leaks"], [])
            self.assertEqual(res["manifest"]["n_items"], 1)

    def test_leak_detected(self):
        with tempfile.TemporaryDirectory() as td:
            run, store = self.build(td)
            leaky = A.ensure_dir(A.run_paths(run)["methods"] / "m1")
            (leaky / "notes.md").write_text("copied: heldout workload spec alpha beta gamma delta epsilon zeta eta theta iota", encoding="utf-8")
            res = A.verify_heldout(store, run)
            self.assertFalse(res["ok"])
            self.assertEqual(len(res["leaks"]), 1)

    def test_overlap_detected(self):
        with tempfile.TemporaryDirectory() as td:
            run, store = self.build(td)
            suite = Path(td) / "suite_items.json"
            A.atomic_write_json(suite, [{"id": "s1", "text": "heldout workload spec alpha beta gamma delta epsilon zeta eta theta iota"}])
            res = A.verify_heldout(store, run, suite_item_files=[str(suite)])
            self.assertFalse(res["ok"])
            self.assertEqual(res["overlap"]["ratio"], 1.0)

    def test_disjoint_suite_is_clean(self):
        with tempfile.TemporaryDirectory() as td:
            run, store = self.build(td)
            suite = Path(td) / "suite_items.json"
            A.atomic_write_json(suite, [{"id": "s1", "text": "completely different uniform random workload over five hundred keys"}])
            res = A.verify_heldout(store, run, suite_item_files=[str(suite)])
            self.assertTrue(res["ok"])
            self.assertEqual(res["overlap"]["matched"], 0)


class TestStopCriteria(unittest.TestCase):
    def test_plateau(self):
        rows = [{"aggregate": v} for v in [0.1, 0.2, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3]]
        self.assertTrue(A.plateau_decision(rows, window=3, min_gain=0.001)["stop"])
        rows2 = [{"aggregate": v} for v in [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8]]
        self.assertFalse(A.plateau_decision(rows2, window=3, min_gain=0.001)["stop"])
        self.assertFalse(A.plateau_decision([{"aggregate": 0.1}], window=3)["stop"])

    def test_tie_plateau(self):
        """The rule exists because the SQLite study tied 11 ways while the slow plateau rule
        could not fire: its window guard needs more methods than the run ever produced."""
        self.assertEqual(A.plateau_decision([{"aggregate": 0.1}] * 40)["window"], 15)
        tie = [{"aggregate": v} for v in [0.1, 0.2, 0.7, 0.7, 0.7]]
        self.assertEqual(A.tie_plateau_decision(tie, run_length=3)["tie_run"], 3)
        self.assertTrue(A.tie_plateau_decision(tie, run_length=3)["stop"])
        self.assertFalse(A.tie_plateau_decision(tie, run_length=4)["stop"])
        # one differing value in the middle breaks the run
        mixed = [{"aggregate": v} for v in [0.7, 0.7, 0.6, 0.7, 0.7]]
        self.assertEqual(A.tie_plateau_decision(mixed, run_length=3)["tie_run"], 2)
        self.assertFalse(A.tie_plateau_decision(mixed, run_length=3)["stop"])
        # a single finding is a tie run of one, never a stop, and zero disables the rule
        self.assertFalse(A.tie_plateau_decision([{"aggregate": 0.5}], run_length=3)["stop"])
        self.assertFalse(A.tie_plateau_decision(tie, run_length=0)["stop"])
        self.assertEqual(A.tie_plateau_decision(tie, run_length=0)["reason"], "tie rule disabled")
        # findings without an aggregate do not enter the run
        self.assertFalse(A.tie_plateau_decision([{"aggregate": None}, {"aggregate": 0.7}], run_length=2)["stop"])

    def test_wall_clock(self):
        self.assertFalse(A.wall_clock_exceeded("", 1))
        self.assertTrue(A.wall_clock_exceeded("2000-01-01T00:00:00Z", 1))


class TestAudit(unittest.TestCase):
    def test_prepare_and_collect(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            tr = A.ensure_dir(A.run_paths(run)["traces"] / "r1")
            (tr / "iter1.md").write_text("a" * 13000, encoding="utf-8")
            prep = A.audit_prepare(run, chunk_chars=6000)
            self.assertEqual(prep["chunks"], 3)
            vdir = A.ensure_dir(A.run_paths(run)["run"] / "audit" / "verdicts")
            A.atomic_write_json(vdir / "c0.json", {"chunk_id": "r1-iter1md__0000", "trace_id": "r1-iter1md", "score": 1, "categories": []})
            A.atomic_write_json(vdir / "c1.json", {"chunk_id": "r1-iter1md__0001", "trace_id": "r1-iter1md", "score": 5, "categories": ["Held-out peek"], "quotes": ["q"]})
            rep = A.audit_collect(run, threshold=4)
            self.assertEqual(len(rep["flagged"]), 1)
            self.assertEqual(rep["flagged"][0]["max_score"], 5)
            self.assertEqual(rep["flagged"][0]["categories"], ["Held-out peek"])


class TestSources(unittest.TestCase):
    def test_normalize_doi(self):
        self.assertEqual(S.normalize_doi("https://doi.org/10.1/ABC"), "10.1/abc")
        self.assertEqual(S.normalize_doi("doi:10.2/x"), "10.2/x")
        self.assertIsNone(S.normalize_doi(""))

    def test_dedupe_by_doi_then_arxiv_then_title(self):
        papers = [{"source": "a", "doi": "10.1/x", "title": "T"}, {"source": "b", "doi": "10.1/X", "title": "T", "abstract": "z"}, {"source": "c", "arxiv_id": "2401.1", "title": "U"}, {"source": "d", "arxiv_id": "2401.1", "title": "U"}]
        out = S.dedupe(papers)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["sources"], ["a", "b"])
        self.assertEqual(out[0]["abstract"], "z")

    def test_paper_key_title_fallback(self):
        k1 = S.paper_key({"title": "A Study of Memory!"})
        k2 = S.paper_key({"title": "a study of memory"})
        self.assertEqual(k1, k2)

    def test_ngrams_and_jaccard(self):
        a = A.ngrams("the quick brown fox jumps over the lazy dog")
        b = A.ngrams("the quick brown fox jumps over the lazy dog")
        self.assertEqual(A.jaccard(a, b), 1.0)
        c = A.ngrams("entirely unrelated content about caching")
        self.assertLess(A.jaccard(a, c), 0.2)
        self.assertEqual(A.jaccard(set(), set()), 1.0)

    def test_multi_search_reports_errors_without_raising(self):
        errs = []
        with self.assertRaises(ValueError):
            S.multi_search("q", sources=("nope",), errors=errs)

    @unittest.skipUnless(os.environ.get("AAR_NET_TESTS"), "set AAR_NET_TESTS=1 for live connector tests")
    def test_live_probe(self):
        res = S.probe_sources(timeout=30)
        self.assertIn("arxiv", res["available"])
        self.assertIn("openalex", res["available"])


class TestToyWorld(unittest.TestCase):
    def test_baselines_in_admission_band(self):
        for name in world.SUITE_BENCHES:
            rate = world.baseline_for(name)["hit_rate"]
            self.assertGreater(rate, 0.05, name)
            self.assertLess(rate, 0.9, name)

    def test_lfu_improves_all_three(self):
        import lfu_aged
        for name in world.SUITE_BENCHES:
            base = world.baseline_for(name)["hit_rate"]
            got = world.simulate(lfu_aged.Policy(world.CAPACITY), world.gen_trace(world.spec_for(name)), world.CAPACITY)["hit_rate"]
            self.assertGreaterEqual(got, base, name)


class TestDashboard(unittest.TestCase):
    """dashboard.py render path: the page is a derived view, so every assertion here is
    about reading the run correctly -- never about a verdict of its own."""

    @classmethod
    def setUpClass(cls):
        if str(SCRIPTS) not in sys.path:
            sys.path.insert(0, str(SCRIPTS))
        cls.D = importlib.import_module("dashboard")
        cls.RD = importlib.import_module("rundata")

    def bundle(self, run, **kw):
        kw.setdefault("integrity", False)          # the held-out tree scan is slow and unrelated here
        return self.RD.build_bundle(run, **kw)

    def publish(self, run, mid, aggregate, gates=None, status="scored", excluded=False):
        write_method(run, mid)
        A.approve_method(run, mid)
        va = A.verify_approval(run, mid)
        A.publish_finding(run, {"method_id": mid, "artifact_hash": va["approved_hash"], "status": status,
                                "scores": {}, "aggregate": {"kind": "geomean", "value": aggregate},
                                "gates": gates or [], "author": {"researcher_id": "r1"},
                                "family": "fam-" + mid, "claims": ["claim of " + mid]})
        if excluded:
            A.add_exclusion(run, mid, reason="audit", category="cheating")

    def passing_gate(self, name="cap"):
        return [{"name": name, "direction": "higher_better", "stat": "mean_ci", "pass": True,
                 "method": {"mean": 1.0}, "baseline": {"mean": 1.0}, "margin": 0.0}]

    def test_bundle_shape_types_and_order(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            self.publish(run, "m1", 0.20, self.passing_gate())
            self.publish(run, "m2", 0.75, self.passing_gate())
            b = self.bundle(run)
            for key in ("schema", "generated_at", "run", "status", "suite", "gates", "held_out",
                        "findings", "findings_total", "ceiling", "plateau_band", "climb", "winner",
                        "bottleneck", "reference", "monitors", "audit", "integrity", "refresh", "source"):
                self.assertIn(key, b)
            self.assertEqual([f["seq"] for f in b["findings"]], sorted(f["seq"] for f in b["findings"]))
            self.assertEqual(b["findings_total"], 2)
            self.assertEqual(b["status"]["methods"], 2)
            self.assertEqual(b["status"]["gates_pass"], 2)
            self.assertEqual([s["name"] for s in b["suite"]], ["b1", "b2"])
            self.assertEqual(b["run"]["plateau_window"], 3)
            self.assertIsInstance(b["run"]["title"], str)
            self.assertTrue(b["run"]["title"])
            self.assertIsNone(b["reference"])                 # no --reference-file
            self.assertIsNone(b["audit"])                     # nothing audited
            self.assertIsNone(b["monitors"])                  # no paper verdicts
            self.assertIsNone(b["plateau_band"])           # the champion is the last scored method: no flat run yet
            self.assertEqual(b["winner"]["method_id"], "m2")
            self.assertEqual(b["ceiling"], 0.75)

    def test_top_truncates_page_but_not_the_data_file(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            for i in range(4):
                self.publish(run, "m%d" % i, 0.1 * (i + 1), self.passing_gate())
            b = self.bundle(run)
            page, data = self.D.write_outputs(run, b, top=2)
            view = self.D.page_view(b, 2)
            self.assertEqual(len(b["findings"]), 4)                # the bundle is always complete
            self.assertEqual(len(view["findings"]), 2)             # the page inlines the head only
            self.assertEqual(view["findings_total"], 4)
            page_blob = json.loads(A.read_text(page).split("const DATA = ", 1)[1].split(";\n", 1)[0])
            self.assertEqual(len(page_blob["findings"]), 2)
            self.assertEqual(page_blob["findings_total"], 4)
            self.assertEqual(len(json.loads(A.read_text(data))["findings"]), 4)   # dashboard.data.json stays whole

    def test_excluded_finding_kept_but_unranked(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            self.publish(run, "keep", 0.40, self.passing_gate())
            self.publish(run, "drop", 0.90, self.passing_gate(), excluded=True)
            b = self.bundle(run)
            rows = {f["method_id"]: f for f in b["findings"]}
            self.assertEqual(len(rows), 2)                    # the evidence chain stays on the page
            self.assertTrue(rows["drop"]["excluded"])
            self.assertFalse(rows["keep"]["excluded"])
            self.assertEqual(b["status"]["excluded"], 1)
            self.assertEqual(b["ceiling"], 0.40)              # an excluded method cannot set the ceiling
            self.assertEqual(b["winner"]["method_id"], "keep")

    def test_unscored_method_is_null_not_zero(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            self.publish(run, "live", 0.30, self.passing_gate())
            write_method(run, "rejected")
            A.publish_finding(run, {"method_id": "rejected", "status": "rejected_by_monitor",
                                    "aggregate": {"kind": "geomean", "value": None}, "gates": [],
                                    "evidence": {"problems": ["forbidden construct: eval("]}})
            b = self.bundle(run)
            rows = {f["method_id"]: f for f in b["findings"]}
            self.assertIsNone(rows["rejected"]["aggregate"])
            self.assertNotEqual(rows["rejected"]["aggregate"], 0)
            self.assertIsNone(rows["rejected"]["gates_pass"])
            self.assertEqual(rows["rejected"]["paper"], "n/a")
            self.assertIn("eval(", rows["rejected"]["reason"])
            self.assertEqual(b["ceiling"], 0.30)              # the null never masquerades as a score
            html = self.D.render_page(b)
            self.assertIn("○ 无数据", html)                    # the JS renders the dash branch

    def test_ceiling_and_band_start_at_the_first_ceiling_hit(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            self.publish(run, "rise1", 0.20, self.passing_gate())
            self.publish(run, "rise2", 0.50, self.passing_gate())   # first finding to touch the ceiling
            self.publish(run, "flat1", 0.50, self.passing_gate())
            self.publish(run, "flat2", 0.50, self.passing_gate(), excluded=True)
            b = self.bundle(run)
            self.assertAlmostEqual(b["ceiling"], 0.50)
            self.assertEqual(b["winner"]["method_id"], "rise2")
            self.assertEqual(b["plateau_band"]["from"], 2)
            self.assertEqual(b["plateau_band"]["to"], 4)
            self.assertEqual(b["plateau_band"]["scored_after"], 2)
            self.assertEqual(b["plateau_band"]["excluded_after"], 1)
            self.assertIn("从 #2 起 2 个已评分方法", b["plateau_band"]["text"])
            self.assertEqual(b["climb"]["note"], b["plateau_band"]["text"])

    def test_climb_narrative_three_states(self):
        peaked = self.RD.climb_narrative([{"aggregate": 0.1}, {"aggregate": 0.3}, {"aggregate": 0.3}])
        self.assertEqual(peaked["state"], "peaked")
        self.assertEqual(peaked["label"], "⚠ 已见顶")
        climbing = self.RD.climb_narrative([{"aggregate": 0.1}, {"aggregate": 0.2}, {"aggregate": 0.3}])
        self.assertEqual(climbing["state"], "climbing")
        self.assertEqual(climbing["label"], "▲ 仍在上升")
        empty = self.RD.climb_narrative([])
        self.assertEqual(empty["state"], "empty")
        # the descriptive reading keeps plateau_decision's min_gain test: a sub-noise bump is not progress
        self.assertEqual(self.RD.climb_narrative([{"aggregate": 0.5}, {"aggregate": 0.501}])["state"], "peaked")
        self.assertEqual(self.RD.climb_narrative([{"aggregate": 0.5}, {"aggregate": 0.51}])["state"], "climbing")

    def test_reference_is_optional_and_guarded(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            self.publish(run, "m1", 0.5, self.passing_gate())
            plain = self.bundle(run)
            page = self.D.render_page(plain)
            blob = page.split("const DATA = ", 1)[1].split(";\n", 1)[0]
            self.assertIsNone(plain["reference"])
            self.assertIsNone(json.loads(blob)["reference"])   # nothing to draw a comparison bar from
            self.assertIn("if (DATA.reference)", page)        # the whole comparison group is behind this guard
            ref = {"name": "ref-impl", "per_bench": {"b1": 0.9, "b2": 0.1}, "aggregate": 0.3}
            withref = self.bundle(run, reference=ref)
            self.assertEqual(withref["reference"]["name"], "ref-impl")
            self.assertIn("ref-impl", self.D.render_page(withref))
            self.assertEqual(self.RD.bottleneck_of(withref["winner"]["per_bench"]), None)  # synthetic finding has no scores

    def test_held_out_shows_cost_pair_and_labels_the_reference(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            self.publish(run, "m1", 0.5, self.passing_gate())
            self.assertIsNone(self.bundle(run)["held_out"])        # no verification block -> null, no invention
            A.atomic_write_json(A.run_paths(run)["reports"] / "final.json",
                                {"verification": {"selected": "m1", "heldout_bench": "sensors",
                                                  "heldout_score": 0.748038583779699, "heldout_cost": 1133650,
                                                  "heldout_baseline_cost": 4499300, "generalizes": True}})
            ref = {"name": "ref-impl", "per_bench": {"b1": 0.9, "b2": 0.1},
                   "held_out": {"bench": "sensors", "score": 0.58}}
            h = self.bundle(run, reference=ref)["held_out"]
            self.assertEqual(h["subject"], "冠军")                 # verification.selected == the leaderboard head
            self.assertEqual(h["method_cost"], 1133650)
            self.assertEqual(h["baseline_cost"], 4499300)
            self.assertAlmostEqual(h["removed_fraction"], 0.748, places=3)
            self.assertEqual(h["baseline_score"], 0.0)             # by construction of the closed fraction
            self.assertEqual(h["reference_score"], 0.58)           # a reference implementation, not a baseline
            page = self.D.render_page(self.bundle(run, reference=ref))
            self.assertIn("操作码 对未调优基线", page)
            self.assertIn("参考实现", page)
            self.assertNotIn("对基线 <span", page)                  # the mislabelled sentence must not come back
            self.assertEqual(self.bundle(run, reference=ref)["reference"]["name"], "ref-impl")

    def test_held_out_subject_follows_the_selected_method(self):
        """The cost pair belongs to the method the report selected, not to the rank-1 row."""
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            self.publish(run, "m1", 0.50, self.passing_gate())
            self.publish(run, "m2", 0.90, self.passing_gate())
            A.atomic_write_json(A.run_paths(run)["reports"] / "final.json",
                                {"verification": {"selected": "m1", "heldout_bench": "held", "heldout_cost": 30,
                                                  "heldout_baseline_cost": 100, "generalizes": True}})
            h = self.bundle(run)["held_out"]
            self.assertEqual(self.bundle(run)["winner"]["method_id"], "m2")
            self.assertEqual(h["subject"], "选中方法")             # not the champion, so it says so
            self.assertEqual(h["method_id"], "m1")
            self.assertAlmostEqual(h["removed_fraction"], 0.7)
            self.assertIn("选中方法", self.D.render_page(self.bundle(run)))

    def test_audit_unknowns_stay_unknown(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            vdir = A.ensure_dir(A.run_paths(run)["run"] / "audit" / "verdicts")
            A.atomic_write_json(vdir / "c0.json", {"chunk_id": "x__0000", "trace_id": "x", "score": 2,
                                                   "categories": ["Other"]})
            a = self.bundle(run)["audit"]
            self.assertIsNone(a["threshold"])                      # no report.json -> unknown, never 4
            self.assertIsNone(a["flagged"])                        # and never "none"
            page = self.D.render_page(self.bundle(run))
            self.assertIn("阈值未知", page)
            self.assertIn("○ flagged: 未判定", page)
            A.atomic_write_json(A.run_paths(run)["run"] / "audit" / "report.json",
                                {"threshold": 4, "flagged": [], "traces": [{"trace_id": "x"}]})
            a = self.bundle(run)["audit"]
            self.assertEqual((a["threshold"], a["flagged"], a["traces"]), (4, 0, 1))

    def test_render_has_no_network_or_module_dependency(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            self.publish(run, "m1", 0.5, self.passing_gate())
            page = self.D.render_page(self.bundle(run))
            for forbidden in ("fetch(", 'type="module"', "import ", "http://", "https://", "XMLHttpRequest", "cdn.",
                              "0.607", "2f0c", "0.5800", "1133650", "schema_aware"):
                self.assertNotIn(forbidden, page)                  # no prototype placeholder, no study data

    def test_empty_run_renders(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            b = self.bundle(run)
            self.assertEqual(b["findings"], [])
            self.assertIsNone(b["ceiling"])
            self.assertIsNone(b["winner"])
            self.assertIsNone(b["plateau_band"])
            self.assertEqual(b["climb"]["state"], "empty")
            self.assertEqual(b["status"]["methods"], 0)
            page = self.D.render_page(b)
            self.assertIn("const DATA = {", page)
            self.assertIn("尚无方法被评分", page)

    def test_serve_serves_data_json_and_answers_404(self):
        """The route set is exactly / and /data.json, by decision.

        /health was rejected on purpose: a cheap one passes while extraction is broken, and
        an honest one costs the same as /.  This test pins the decision so a later edit
        cannot quietly add a route that lies.
        """
        import threading
        import urllib.error
        import urllib.request
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            self.publish(run, "m1", 0.42, self.passing_gate())
            args = type("Args", (), {"run": str(run), "reference_file": None, "title": None,
                                     "top": 200, "no_integrity": True, "out": None,
                                     "data_out": None, "interval": 30})()

            def render():
                bundle = self.D.build(args, refresh=args.interval)
                view = self.D.page_view(bundle, args.top)
                return self.D.render_page(view), self.D.summarize(view), bundle

            server = self.D.Server(("127.0.0.1", 0), render)
            port = server.server_address[1]
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/data.json" % port, timeout=20) as resp:
                    self.assertEqual(resp.status, 200)
                    self.assertIn("application/json", resp.headers.get("Content-Type", ""))
                    payload = json.loads(resp.read().decode("utf-8"))
                self.assertEqual(payload["findings"][0]["method_id"], "m1")
                self.assertIn("ceiling", payload)
                with urllib.request.urlopen("http://127.0.0.1:%d/" % port, timeout=20) as resp:
                    page = resp.read().decode("utf-8")
                self.assertIn("const DATA = {", page)
                for missing in ("/health", "/anything"):
                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        urllib.request.urlopen("http://127.0.0.1:%d%s" % (port, missing), timeout=20)
                    self.assertEqual(ctx.exception.code, 404)
            finally:
                server.shutdown()
                server.server_close()
                worker.join(timeout=10)

    def test_elapsed_is_the_loop_span_not_time_since_framing(self):
        """handoff 14.2: elapsed must measure the loop, not the age of the artifact.

        Pins the bug: the old definition was "started -> render time", which grows without
        bound and always overshoots the budget once a run has stopped, so the one number a
        viewer reads to answer "how far along is this" was wrong and got worse over time.
        """
        import datetime
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            self.publish(run, "m1", 0.2, self.passing_gate())
            self.publish(run, "m2", 0.3, self.passing_gate())
            now = datetime.datetime.now(datetime.timezone.utc)
            files = sorted(A.run_paths(run)["forum_findings"].glob("*.json"))
            self.assertEqual(len(files), 2)
            for i, path in enumerate(files):
                rec = json.loads(path.read_text(encoding="utf-8"))
                ts = now - datetime.timedelta(hours=5 - i)      # m1: now-5h, m2: now-4h
                rec["published_at"] = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
                path.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")

            # A final report newer than the last finding means the loop has stopped.
            final = A.run_paths(run)["reports"] / "final.json"
            final.write_text("{}", encoding="utf-8")
            stopped = self.bundle(run)["run"]
            self.assertFalse(stopped["running"])
            self.assertEqual(stopped["elapsed"], "1h00m")        # the loop span
            self.assertNotEqual(stopped["elapsed"], "5h00m")     # NOT time since framing
            self.assertEqual(stopped["since_last"], "4h00m")

            # Without the report the run counts as live again and elapsed tracks now.
            final.unlink()
            live = self.bundle(run)["run"]
            self.assertTrue(live["running"])
            self.assertEqual(live["elapsed"], "5h00m")

    def test_placeholder_is_replaced_with_parsable_data(self):
        with tempfile.TemporaryDirectory() as td:
            run = make_run(td)
            self.publish(run, "m1", 0.5, self.passing_gate())
            bundle = self.bundle(run)
            page = self.D.render_page(bundle)
            self.assertNotIn(self.D.PLACEHOLDER, page)
            blob = page.split("const DATA = ", 1)[1].split(";\n", 1)[0]
            self.assertEqual(json.loads(blob), json.loads(self.D.bundle_json(bundle)))
            self.assertEqual(json.loads(blob)["findings"][0]["method_id"], "m1")

    def test_reference_file_loader(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "reference.json"
            A.atomic_write_json(path, {"name": "ref", "per_bench": {"b1": 0.5, "b2": 0.5}})
            ref = self.RD.load_reference(path)
            self.assertEqual(ref["name"], "ref")
            self.assertAlmostEqual(ref["aggregate"], 0.5)      # geomean filled in when absent
            with self.assertRaises(ValueError):
                A.atomic_write_text(path, "[1, 2, 3]")
                self.RD.load_reference(path)
            self.assertIsNone(self.RD.load_reference(None))


if __name__ == "__main__":
    unittest.main(verbosity=2)
