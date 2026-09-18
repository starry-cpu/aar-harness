import json, subprocess, sys
from pathlib import Path
HERE = Path(".").resolve()
RUN = HERE / "run"
def run(mid, bench):
    p = subprocess.run([sys.executable, "runner.py", "--method", str(RUN / "methods" / mid), "--bench", bench, "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace")
    line = [l for l in p.stdout.splitlines() if l.strip().startswith("{")]
    return json.loads(line[-1])
print("variance smoke test: same artifact, 3 independent runs")
worst = 0
for bench in ("point", "rangesort", "joinagg", "sensors"):
    costs = [run("schema_aware", bench)["eval_cost"] for _ in range(3)]
    spread = max(costs) - min(costs)
    worst = max(worst, spread)
    print("  %-10s costs=%s  spread=%d" % (bench, costs, spread))
print("noise floor (max spread over all benches) =", worst)
