# 07-run-evaluate — 在预算内执行已批准制品并评分

## 目的

把一个**已通过哈希绑定审批**的制品交给 runner：对每个被评分基准与闸门基准各跑一次，收集原始分与逐窗口值，
用 closed fraction + 几何平均（含零化规则）聚合，逐闸门判非劣性，把结果原子落盘到 `eval/<method_id>/`。
分数只能由本步产生：研究者与 monitor 都不写分。

## 输入

- `verify-approval` 通过的结果（`approved_hash`）——没有它不许执行。
- `<run_dir>/run_config.json`：`suite[]`（name/metric/baseline/optimum）、`runner.cmd`（含 `{method_dir}` 与 `{bench}` 占位符）、`runner.gate_bench`、`runner.timeout_seconds`、`gates[]`（name/direction/stat/baseline_values）。
- `<run_dir>/methods/<method_id>/`：已批准且此后未被改动的那一份内容。
- 02-instrument 测得的噪声地板；判读提升与复跑解释都要用它。

## 产出

- 每个基准一次 runner 调用；每次 stdout 中最后一行以 `{` 开头的 JSON 是结果，当前 orchestrator 从里面读 `hit_rate`（原始分）与 `windows`（逐窗口数组）。
- `<run_dir>/eval/<method_id>/scores.json`：`raw`、`scored.scores`（每基准 raw/baseline/optimum/closed）、`scored.aggregate`（kind=geomean、value、zeroed_by）、`meta`（runner_cmd/started_at/ended_at/seed）。
- `<run_dir>/eval/<method_id>/gates.json`：`[gate_verdict, ...]`，每个含 `name/direction/stat/method/baseline/margin/pass`。
- 失败时：`status=run_failed` 的 finding，由 orchestrator 发布，`evidence.detail` 记错误原文前 600 字符。

## 程序

1. 前置门：`python scripts/aar.py verify-approval --run <run_dir> --method <method_id>` 必须 `"ok": true`。未批准就执行属违规，评测侧一律拒收。
2. 读 runner 契约：`read <run_dir>/run_config.json`，取 `runner.cmd` 原文，把 `{method_dir}` 换成 `<run_dir>/methods/<method_id>`、`{bench}` 换成基准名。**不许改** `runner.cmd` 本身，改 runner 属违规。
3. 对 `suite[]` 每个基准跑一次。toy 契约下即 `python scripts/toy/runner.py --method <run_dir>/methods/<method_id> --bench zipf --json`；standard/full 档由 orchestrator 的 `run_runner` 用 `cmd.format(...)` + `subprocess.run(timeout=...)` 执行。手工执行时用 `pwsh` 的 `timeoutMs`（设为 `runner.timeout_seconds * 1000` 或略大）兜住硬超时。
4. 收分：取每次 stdout 里最后一行 `{` 开头的 JSON，读出 `hit_rate` 与 `windows`。一行 JSON 都没有等价于 `runner produced no JSON`，按失败处理，不要手填。
5. 闸门基准也要真跑一次：`runner.gate_bench`（toy 例 `short_latency`），只取它的 `windows` 供第 7 步当 method 侧样本。只跑被评分基准就拿不到闸门值。
6. 落分：把原始分写成 `eval/<method_id>/raw.json`（形如 `{"zipf": 0.42, "scan": 0.51}`），然后跑

        python scripts/aar.py score --run <run_dir> --method <method_id> --raw @<run_dir>/eval/<method_id>/raw.json --runner-cmd "<runner.cmd 原文>" --started-at <t0> --ended-at <t1> --duration-s <秒> --seed 0

    它会打印每基准 `closed` 与 `aggregate`，并原子写 `eval/<method_id>/scores.json`。注意它**不写 `windows`**（`windows` 只在 orchestrator 的 `evaluate()` 路径里落盘）；light 档手工执行时把逐窗口值另存 `eval/<method_id>/windows.json`。
7. 逐闸门判定：先把闸门基准的窗口数组写成 `eval/<method_id>/gate-windows.json`（文件内容就是该数组本身，`aar.py` 的 `@file` 只做 json.loads），再跑 `python scripts/aar.py gate --run <run_dir> --method <method_id> --name <gate.name> --direction higher_better --stat mean_ci --method-values @<run_dir>/eval/<method_id>/gate-windows.json --baseline-values @<run_dir>/eval/<method_id>/gate-baseline.json`（后者是 `run_config.gates[i].baseline_values` 的原样落盘）。同名闸门被替换、其它闸门保留，落 `eval/<method_id>/gates.json`。语义：`higher_better` 过闸当且仅当 method 的 UCB ≥ baseline 的 LCB，`lower_better` 反之；`wilson` / `bootstrap` 用于 0/1 计数与非线性指标。
8. 判读结果：`aggregate.value == 0` 时看 `scored.aggregate.zeroed_by`，那就是停在或低于基线的基准名单；小于噪声地板的「提升」不得当成提升。任一闸门 `pass:false` 的方法发布时状态为 `gate_failed`，排行榜排在所有 passing 之后。报告里必须复述：闸门是崩溃探测器，论文 App. A.4 实测十个 failure 全降 9.5–12.0 分仍可通过，实际只挡得住约 11–13 分以上的下跌。
9. runner 失败或超时：orchestrator 捕获后发布 `status=run_failed` 的 finding（保留 `artifact_hash`、`scores` 为空、`evidence.detail` 记错误），重建排行榜且**不写** `eval/` 分数。这一轮就此花掉：wall-clock 照走，method 预算按 findings 条数计也跟着减一；但研究者的方法槽没被占用——下一轮它拿到新的 `method_id` 换实现重来，`run_failed` 不会被评分。
10. 预算执行的三个层次：① `runner.timeout_seconds` 是硬超时，超时即失败；② `method_contract.budget_seconds` 是研究者自证、06 已核对的上界；③ run 级 `stop.wall_clock_hours`、`--max-methods`、plateau 由 orchestrator 判定，单独查看用 `python scripts/aar.py plateau --run <run_dir>`。手工加跑基准、放宽超时都算违规。
11. 不要用复跑抽噪声：同一 `artifact_hash` 被发布两次时，`python scripts/aar.py leaderboard --run <run_dir>` 会把它标成 `DUP`，`python scripts/aar.py forum verify --run <run_dir>` 报 `duplicate_artifact_hash`——论文里 67% 的作弊正是这一条。

## 退出判据

- `pwsh Test-Path <run_dir>/eval/<method_id>/scores.json,<run_dir>/eval/<method_id>/gates.json` 全为 True。
- `read <run_dir>/eval/<method_id>/scores.json`：`scored.scores` 的键集合等于 `run_config.suite` 的 name 集合（少一个 `score_finding` 会直接抛 `missing raw score for benchmark`），且 `scored.aggregate.value` 非 null（0 也是合法值）。
- `read <run_dir>/eval/<method_id>/gates.json` 的元素个数等于 `run_config.gates` 的长度，每个都带布尔 `pass` 与 `margin`。
- 发布后：`python scripts/aar.py status --run <run_dir>` 的 `findings` 与 `gate_passing` 相应变化，且 `python scripts/aar.py forum verify --run <run_dir>` 无 `edited_score_file`。

## 常见失败

- 手改 `scores.json` 的数字 → 发布后 `forum verify` 报 `edited_score_file`（`evidence.score_file_hash` 对不上）；分数只能由 `aar.py score` 或 orchestrator 写。
- 少跑一个基准 → `aar.py score` 抛 `missing raw score for benchmark <name>` 且不落盘；先列全 `suite[].name` 再逐个跑。
- 闸门只传均值或单点 → 区间退化成点、判 pass 过宽；传逐窗口数组，样本量为 1 时必须在报告里声明区间退化。
- 拿超时当「分数低」→ 状态是 `run_failed`、`aggregate` 为 null，排行榜按 -1 垫底；先看 `evidence.detail` 里的 runner 错误原文再决定改什么。
- 闸门基准没跑却硬填 `--method-values` → 伪造闸门样本，属审计命中项；闸门基准必须真跑一次。
- 在 `eval/` 里手写 `gates.json` → 绕过 `gate_verdict` 的区间判定；一律用 `aar.py gate` 生成。
