# 09-orchestrate.md — 跑 K 路并行研究者直到停止判据触发

## 目的

驱动 K 个并行研究者反复走「读公共产物 → 预注册 → 产出制品 → 审批 → 执行评分 → 发布」这一轮，并把「谁来跑研究者」按档位落到实际进程上；同时维护失败记账、断点续跑与成本记账，直到 wall-clock、方法数预算或 plateau 三条之一触发。

三档的执行载体不同，循环与契约相同：

- **light**：主 agent 直接开 2–4 个 `subagent`，每个 subagent 就是一轮 fresh session；执行用 `pwsh`（前台或 `run_in_background`）。规模 1–3 小时 / 20–50 个方法，用来打通闭环或跑便宜域。
- **standard**：本地 orchestrator 进程每轮 spawn 一个 `dsh --profile headless` 子进程（`orchestrator.py` 的 `driver_dsh`：把 prompt 写到 `prompts/<method_id>.md`，任务串是「Read <prompt> and follow it exactly」，cwd 是 run_dir），默认 8–24 小时 / 约 100 个方法。
- **full**：同一条命令加更长预算与持久化（数天 / 200+ 个方法）。

## 输入

- 已冻结的 `run_config.json`（`researchers`、`max_methods`、`stop`、`runner`、`gates`、`forum.enabled`）
- `briefing.md`、`rules.md`、`survey.md`、`forum/findings`、`memory/<researcher_id>.md`（每轮 prompt 的上下文来源）
- `method_contract` 与 runner 命令

## 产出

- `methods/<method_id>/`、`submissions/<method_id>.json`、`approvals/<method_id>.json`、`eval/<method_id>/`
- `forum/findings/*`、`leaderboard.json|md`、`memory/<researcher_id>.md`
- `prompts/<method_id>.md`、`traces/<researcher_id>/<method_id>.md`、`logs/orchestrator.jsonl`
- （随时可重建，不参与判定）`reports/dashboard.html` 与 `reports/dashboard.data.json`：运行观测台
- 停止时自动写的 `reports/final.md` 与 `reports/final.json`

## 程序

1. 预检：`python scripts/aar.py status --run <run_dir>`（`frozen_at` 必须非空，看 `tier`、`best`、`plateau`）；再跑 `python scripts/orchestrator.py --run <run_dir> --dry-run`，它只打印这一轮会启动哪些 `method_id` 后退出。
2. light 档：在一个 `run_code` 程序里对 2–4 个研究者并发调用 `subagent`，每个 prompt 给全 `method_id`、硬规则、`methods/<id>/` 与 `submissions/<id>.json` 两个写面；收齐制品后用 `pwsh` 跑 runner，再依次 `python scripts/aar.py score` / `gate` / `approve` / `publish`。
3. standard / full 档用后台长跑起 orchestrator：
   `python scripts/orchestrator.py --run <run_dir> --driver dsh --max-parallel 4 --wall-clock 8h --max-methods 200 --session-timeout 1800`
   - `--driver dsh` 才是真的 spawn 会话（默认 `stub` 只是确定性替身，用于管线自检）；
   - `--max-parallel` 是同时在跑的研究者数；`--wall-clock` 接受 `8h`/`30m`/`90s`/纯小时数；`--max-methods` 覆盖 `run_config.max_methods`；`--session-timeout` 是单轮 headless 会话上限；
   - `--tie-run N` 覆盖 `run_config.stop.tie_run`（默认 8，0 关闭）：连续 N 个方法的 aggregate 完全并列就停；
   - **起跑时加上 `--code-monitor --paper-monitor`**。若两个 LLM 监控没开，orchestrator 会在启动时打一行 WARNING 提醒——注册漂移就只能等事后才发现。
   - `--inject-cheats` 只在 toy 自检时注入两种已知作弊（重发与抄 held-out）；`--toy`、`--workspace` 用于搭 toy run。
4. 用 `job_output` 收 orchestrator 的 stdout，每轮一行形如 `m-r2-3-c6 -> scored agg=0.07834723854444982`；全量事件日志在 `logs/orchestrator.jsonl`（每条 `{at, msg}`）。
5. 看进度有两条路。机械快照：每轮用 `python scripts/aar.py status --run <run_dir>` 或 `python scripts/aar.py plateau --run <run_dir>` 看 `plateau` 块。人看的运行观测台：
   `python scripts/dashboard.py serve --run <run_dir>`（默认 `127.0.0.1:8787`，每 30 秒整页重载一次；端口被占用会明确报错，不会静默换端口）。
   观测台是**派生视图**：它只读 run 目录，闸门、天花板、名次、排除、完整性全部复用 `aar_lib` 的判定，自己不定义任何判据，也不写任何 run 状态，随时可以删掉重建。
   长跑时用 `pwsh run_in_background` 起它，收尾用 `job_kill` 停。循环内部按「wall clock → 方法数预算 → plateau → tie」的次序判定，四者任一触发都会跳出并写报告。**tie 排在 plateau 之后检查，但它才是那个能在小规模运行上真正救命的规则**（见第 6 步的实测校准）。
6. 校准停止判据：`wall_clock_hours` 取 `run_config.stop`（论文用 48 小时，§3.1；App. E 的放大版是 12 个 AAR × 7 天）；`plateau_window` 用论文两个数字定——App. E 里 32B 组冠军出现在结束前 15 小时、之后 41 次提交没有更好，72B 组是结束前 80 小时、之后 112 次提交没有更好，所以论文取 40（≈41）是保守档，full 档可放到 100–120；`min_gain` 取 02-instrument 方差冒烟测出的噪声地板（默认 0.005），小于地板的提升不算提升。App. F.2 显示分数在前四分之一就到最终值的约 0.8，早停是正常现象。

   **实测校准（SQLite 索引选择研究，2026-09）**：照抄 40 在这个域上失败了。4 个研究者 15 分钟摸到指标天花板，之后 11 个独立制品拿到**完全相同**的 aggregate（小数点后 15 位一致，且 artifact hash 互不相同，不是重复提交），而 `plateau_decision` 因为有 `len(vals) < window` 的守卫、方法数又不到 40，永远不触发，于是白跑了 5 个多小时同一个数字。
   域越便宜、搜索空间越小，`plateau_window` 就该越小：**默认已从 40 改为 15**（`aar_lib.plateau_decision` 与 orchestrator 的兜底值都改了），更便宜或更小的空间可以再往下压。两个可操作的判据：一是 02-instrument 测出的方差地板（地板为 0 时，任何并列都是真并列，不是噪声）；二是前 20 个方法里有没有出现并列——一旦出现，搜索已经到顶，继续跑只是烧配额。论文 App. D.3 正好预言了这种情形：「爬山套件本身的天花板，方法一旦满足它，再往上爬就不再对应任何东西」。
7. 失败记账：一轮 iteration 只要启动就一定被花掉——iteration 计数、wall-clock、以及 `max_methods` 名额都照算（`run_failed`/`rejected_by_monitor` 也会以 finding 形式发布，而停止条件是 `len(list_findings) >= max_methods`）；但 plateau 的 window 只统计 `aggregate` 非空的 finding，所以 `run_failed`/`rejected_by_monitor` 不占用 plateau 窗口名额，只有 `scored`/`gate_failed` 推进窗口。每轮结束后读 stdout 尾部的 `counts` 与 `logs/orchestrator.jsonl` 记下各状态数量。
8. 中断后续跑：run 的状态全部在文件里（`forum/findings`、`approvals`、`eval`、`leaderboard.json`、`memory/`），新进程重读即可，但 `iteration`/`slot` 计数器从 0 重来，method_id 会被重新生成为 `m-r1-1-c1` 这类老名字。判断分两种：中断发生在还没有 `approvals/<id>.json` 的那一轮（进程被杀在 driver 阶段），直接重跑同一命令即可补上；中断发生在已有审批之后，同一个 id 会在 `approve_method` 撞 `O_EXCL`（`FileExistsError`），该轮记 `run_failed`，随后每个失败也发 finding、很快撞到方法数预算而停，`forum verify` 还会对这些 finding 报 `approval_mismatch`。此时不要删 `approvals/` 或 `methods/`（那会毁掉哈希证据链），改用 light 档接着爬山：主 agent 自己命名新 method_id（例如 `m-r1-4-c31`）逐轮跑 `aar.py` 四步，把老 finding 当上下文。本实现没有 `--resume` 开关，续跑就是上面这套文件状态判断。
9. 成本记账：`logs/orchestrator.jsonl` 给每轮时间与状态，`traces/<researcher_id>/<method_id>.md` 存完整 prompt + stdout + stderr（事后审计的输入），`prompts/<method_id>.md` 存注入 prompt；报告里用 `counts` 与状态分布交代花掉多少轮、多少轮是白跑的。
10. 收尾前确认校验通过：`python scripts/aar.py forum verify --run <run_dir>` 与 `python scripts/aar.py status --run <run_dir>`。
11. **决定监控开在环内还是事后**。这直接决定预注册漂移会不会被抓到：
    - **在环内**（每个方法跑之前走 CODE_MONITOR 与 PAPER_MONITOR，模板见 `references/prompts.md`）：贵，但能在方法进入排行榜之前拦住它。域便宜、方法多、或者预注册纪律重要时必须开。
    - **事后**（`python scripts/review.py --run <run_dir> --mode paper|audit|both`）：跑完之后补，适合长跑时先把算力花在搜索上。
    - 实测教训：SQLite 研究那一轮只在环内开了确定性静态监控（entrypoint 是否存在、必需符号是否定义、有没有 `import socket/urllib/subprocess`、有没有引用 held-out 路径），PAPER_MONITOR 留到事后——结果 14 个方法里 **8 个被驳回（57%）**，其中一条是 `results_free: False`，即 mini-paper 里写进了自己这次运行的分数表。研究者一次性写完预注册、然后继续改代码，论文就漂移了；事后审查能抓出来，但那 8 个方法在排行榜上已经存在了几个小时。`review.py` 的 `--exclude-rejected` 会把它们标记排除并重建排行榜，**记录不删除**，保持可审计。

## 退出判据

- `logs/orchestrator.jsonl` 末行出现 `run stop: <stop_reason>`，且 `stop_reason` 是三者之一：`wall clock budget reached`、`method budget reached`、`plateau: no gain over the last N scored methods`。
- `reports/final.md` 与 `reports/final.json` 存在，且 `reports/final.json.meta.stop_reason` 非空、`meta.counts` 给出各状态计数。
- `python scripts/aar.py status --run <run_dir>` 的 `findings` 不再增长，`plateau.stop` 为 true 或方法数已达 `max_methods`。

## 常见失败

- 每轮都是 `run_failed` 且 trace 里写着 `dsh CLI not found on PATH`（exit 127）：orchestrator 起不了 headless 子进程；用 `Get-Command dsh` 确认 shim 在 PATH 上（Windows 上它会经 `cmd.exe /c` 调 `.cmd`）。
- 单轮会话超时：`--session-timeout` 到点会 `taskkill /F /T` 整棵进程树（只杀直接子进程会留下孙进程占着管道），该轮记 `run_failed`；加大 timeout 或把每轮任务压小到一个方法。
- 重启后撞 `FileExistsError: ... approvals\<method_id>.json`：见程序第 8 条，别删 approvals；改用 light 档续跑或让新 method_id 不重号。
- `runner failed for <bench>` / `runner produced no JSON for <bench>`：runner 命令或输出格式不合约（要求 stdout 最后一行是 JSON）；用 `run_config.runner.cmd` 把 `{method_dir}`/`{bench}` 填实手工跑一次定位。
- wall-clock 被重置：`--wall-clock` 是**每个进程**的预算（`run_loop` 用进程启动时刻计时），重启等于重新计时；跨进程的总预算要在报告里自己累加。
- 停不下来或一轮就停：`--max-methods` 与 `run_config.max_methods` 都缺省时按 40 计；一条 `--wall-clock 0` 或极小预算会让循环立刻判 wall clock 到点，检查参数单位（`8h` 而不是 `8`）。
