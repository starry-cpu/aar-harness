import json, shutil, subprocess, sys
from pathlib import Path
HERE = Path(".").resolve()
RUN = HERE / "run"
def install(mid, tuner):
    d = RUN / "methods" / mid
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(HERE / "tuners" / tuner, d / "tune.py")
    (d / "mini-paper.md").write_text("# " + mid + chr(10), encoding="utf-8")
def run(mid, bench):
    p = subprocess.run([sys.executable, "runner.py", "--method", str(RUN / "methods" / mid), "--bench", bench, "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = [l for l in p.stdout.splitlines() if l.strip().startswith("{")]
    return json.loads(line[-1]) if line else {"error": (p.stdout + p.stderr)[-200:]}
for mid, tuner in [("single_col", "single_col.py"), ("covering", "covering.py"), ("naive_all", "naive_all.py")]:
    install(mid, tuner)
    print("== " + mid)
    for b in ("point", "rangesort", "joinagg", "sensors"):
        r = run(mid, b)
        if "error" in r:
            print("   %-10s REJECTED: %s" % (b, r["error"][:110]))
        else:
            print("   %-10s score=%.4f  indexes=%d" % (b, r["score"], len(r["detail"]["indexes"])))
