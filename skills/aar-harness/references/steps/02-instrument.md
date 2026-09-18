# 02-instrument — 把「方法进 → 分数出」做成全自动闭环

## 目的

在启动任何研究者之前，把评分回路做成一段可重复、可检查、无人工的管道：输入一个制品目录，
输出一行 JSON 分数。论文的 AAR 一晚上试上百个方法，靠的就是这条通道；通道不稳，后面所有名次都是噪声。
本步与 03-survey 并行（held-out 已在 01-frame 封存，污染路径已关闭）。

## 输入

- `<run_dir>/run_config.json` 草稿：`suite`（基准 + baseline/optimum）、`runner`、`method_contract`、`gates`、`seeds`。
- `<run_dir>/construct.json`：构念与方法空间，用来把制品契约写窄。
- 目标系统的可执行入口：能被 runner 加载、跑一个基准、返回一个数。
- held-out store 路径（`<workspace>/heldout-store/`）：只用来确认隔离，runner 绝不读它。

## 产出

- `run_config.runner.cmd`：唯一允许接触评测数据的命令，含 `{method_dir}` 与 `{bench}` 两个占位符。
- runner 脚本（在 skill 之外，例如 `<workspace>/instrument/runner.py`）：吃 `--method <dir> --bench <name> --json`。
- 实测基线：`suite[].baseline` 与 `gates[].baseline_values`，由跑未改动目标系统得到，不是假设值。
- `run_config.variance`：同一制品重复 2–3 次的分数清单与噪声地板 `noise_floor`。
- 确定性声明：`run_config.seeds` 与温度 / 网络 / 缓存策略。
- `eval/baseline-smoke/scores.json` 与 `gates.json`：冒烟制品的真实产物。
- `<run_dir>/logs/instrument.md`：基线复测差异、新旧 `config_hash`、谁在跑 runner。

## 程序

1. **写死制品契约**（`run_config.method_contract`）：`interface`（entrypoint 文件名、必须导出的类与构造签名）、
   `budget_seconds`、`artifact` 固定为 `methods/<method_id>/`。契约由 `orchestrator.build_prompt` 原样注入每轮研究者 prompt，
   所以要窄到可机械实现：入口、签名、可用依赖、禁止事项各一行。
2. **写 runner**，`runner.cmd` 形如
   `python <workspace>/instrument/runner.py --method {method_dir} --bench {bench} --json`。
   orchestrator 的读法就是硬约束：退出码必须为 0；stdout 里**最后一行以 `{` 开头**的内容被当 JSON 解析；
   字段名固定为 `hit_rate`（分数值）与 `windows`（逐窗口分数数组，供闸门用），换域也不要改名；日志一律走 stderr。
   输出为空或非 0 退出 → 判 `run_failed`，不是 0 分。
3. **用 runner 实测基线**：runner 必须支持 `--method baseline` 走未改动目标系统。对每个被评分基准跑一次，
   把 `hit_rate` 写进 `suite[].baseline`、把 `windows` 写进 `gates[].baseline_values`；自检 `optimum > baseline`
   （否则 `closed_fraction` 抛错），并按基准入选门槛看一眼（baseline 低于 0.9、可评分样本 ≥ 25）。
4. **冒烟打分**：造一个平凡制品 `methods/baseline-smoke/`（行为等价于基线），手工跑 runner 拿到 raw，再走 CLI 的正规两跳：

        python scripts/aar.py score --run <run_dir> --method baseline-smoke --raw @raw.json --runner-cmd "<cmd>" --seed 0
        python scripts/aar.py gate --run <run_dir> --method baseline-smoke --name cap --method-values @mw.json --baseline-values @bw.json --direction higher_better --stat mean_ci

   `--raw` 接受 `{"<bench>": 0.31, ...}`（或带 `raw` 外壳）；`gate` 的 values 是**逐窗口列表**。冒烟制品的闸门必须 pass，否则是闸门配置写错了。
5. **方差冒烟测试**（本步的核心资产）：同一个 `baseline-smoke` 制品不做任何改动，重复跑 2–3 次，每次把 raw 另存为
   `raw-1.json` / `raw-2.json` / `raw-3.json` 再分别 `score`（`score` 会覆盖 `eval/<id>/scores.json`，必须另存）。
   结果写进 `run_config.variance = {"method_id": ..., "runs": 3, "values": [...], "noise_floor": max-min, "measured_at": ...}`。
   任何小于 `noise_floor` 的「提升」都不得当成提升宣称（scoring.md 第 6 节；论文 §7：67% 的作弊就是原样重跑赌噪声）。
6. **钉死确定性**：固定 `run_config.seeds.runner`（toy 用 `{"seeds": {"runner": 0}}`）；方法若调用 LLM，契约要求 temperature 0 与固定模型名；
   评测期间禁网（runner 不开 socket），需要的外部数据随制品自带或从只读缓存读；缓存目录只读且内容哈希固定，禁止评测时下载。
7. **两层超时**：`run_config.runner.timeout_seconds` 是 orchestrator 的外层硬超时（`subprocess.run(timeout=...)`），
   `method_contract.budget_seconds` 是制品自己的预算；必须 `budget < timeout`，并由 runner 在内部先杀子进程，避免孤儿占卡。
8. **隔离 held-out**：store 在 run_dir 之外，runner 与制品都不得读；跑
   `python scripts/aar.py heldout verify --store <store> --run <run_dir>`，它扫描 run_dir 下每个文件做泄漏检查，
   并把 held-out 条目与 suite 条目做 5-gram 重叠检查。Windows 单用户建不起第二运行身份时，隔离退化为
   「独立目录 + verify + 轨迹审计」，必须在报告里声明这一降级。
9. **重新冻结**：补齐基线、方差与确定性字段后重新冻结，因为冻结哈希是后面审批与 finding 的锚点：

        python -c "import sys; sys.path.insert(0,'scripts/lib'); import aar_lib as A; A.freeze_run_config(r'<run_dir>', force=True)"

   把新旧 `config_hash` 与基线差异写进 `logs/instrument.md`；`force` 只在这类补测场景使用。
10. **先跑玩具域全链**（无网、无 GPU，几分钟）：
    `python scripts/orchestrator.py --toy --run <workspace>/toy-run --driver stub --max-methods 2`，
    它会把 approve → evaluate → publish → leaderboard → `reports/final.md` 走完；这是启动研究者之前唯一能证明「闭环通了」的检查。
11. **空跑真实 run 目录**：`python scripts/orchestrator.py --run <run_dir> --dry-run`，只打印 `dry-run would launch m-r1-1-c1 ...`
    且不 spawn 任何会话；确认调度、researcher 数与 wall-clock 解析都对。发现错就改 run_config 再冻结，别等第一批研究者跑偏。

## 退出判据

- 手跑 runner：`python <workspace>/instrument/runner.py --method methods/baseline-smoke --bench <b> --json`，stdout 末行是合法 JSON 且含 `hit_rate`。
- `eval/baseline-smoke/scores.json` 存在且 `scored.aggregate.value` 非 null；`eval/baseline-smoke/gates.json` 里冒烟制品的闸门 `pass: true`。
- `run_config.variance.noise_floor` 已写入（2–3 次重复测量的极差），且 `run_config.frozen_at` / `config_hash` 是补测后重新冻结的值。
- `python scripts/aar.py heldout verify --store <store> --run <run_dir>` 退出码 0。
- `python scripts/orchestrator.py --toy --run <workspace>/toy-run --max-methods 2` 打印 `stop_reason`，且 `toy-run/reports/final.md` 存在。
- `python scripts/orchestrator.py --run <run_dir> --dry-run` 打印 dry-run 行，且 `methods/` 下没有新增目录。

## 常见失败

- **runner 往 stdout 打日志。** 解析取的是最后一个以 `{` 开头的行，多打一行 JSON 形状的日志就会把分数读成别的数。日志改走 stderr。
- **基线是假设值。** 用论文或 README 里的数字，`closed` 就整体偏移。必须用同一个 runner 的 `--method baseline` 实测，并保证 `optimum > baseline`。
- **runner 不确定。** 采样、时间戳、并发顺序、评测时下载都会让同一制品分数漂移，噪声地板高过真实提升。回到第 6 步固定种子、温度、网络与缓存。
- **超时设置错位。** 外层 timeout 小于制品正常耗时 → 全批 `run_failed`；没有内层 kill → 孤儿进程堆在卡上。保证 `budget_seconds < timeout_seconds` 且 runner 自己先杀。
- **runner 读了 held-out 或评测条目。** 这是作弊分类里的 `Benchmark-data use`，`heldout verify` 会报出文件路径。把数据路径从 runner 里删掉，只留 `{method_dir}` 与 `{bench}`。
- **跳过 dry-run 直接开跑。** 占位符拼错、契约写不清、闸门 values 为空这类错会在第一批研究者全部 `run_failed` 之后才暴露。第 10、11 步是强制的。
