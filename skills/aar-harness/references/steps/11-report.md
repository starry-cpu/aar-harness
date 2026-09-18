# 11-report.md — 最终交付物

## 目的

把一次 run 变成人类可读、可复算、带诚实声明的交付物：一份终局报告加一个可读性包，让读者能顺着哈希回到每个方法的预注册论文、制品与分数文件。

报告必须回答：研究问题是什么、跑的是哪一档、为什么停、排行榜长什么样、选了哪个方法、它在 held-out（或开放式审计）上如何、闸门判了什么、排除了哪些方法、检索是哪个档。三条诚实声明是硬性的，不是客套话（见程序第 6 条）。

## 输入

- `leaderboard.json`、`leaderboard.md`、`forum/findings/*.json|*.md`
- `reports/final.json`（若已有）、`logs/orchestrator.jsonl`（停止原因）
- `audit/report.json`、`exclusions.json`
- `run_config.json`（`config_hash`、`seeds`、`retrieval.tier`、`suite`、`runner.cmd`、`gates`）
- `python scripts/aar.py heldout manifest --store <store>` 打印的五项（`version`/`items_hash`/`n_items`/`generalization`/`license`）
- 每个方法的 `methods/<id>/mini-paper.md` 与 `submissions/<id>.json`、`eval/<id>/scores.json`

## 产出

- `reports/final.md`：终局报告（问题 / 档位 / 停止原因 / 排行榜 / 选中方法 / held-out 结果 / 闸门判定 / 排除清单 / 检索档 / 诚实声明 / 复现附录 / 可读性包）
- `reports/final.json`：`meta`（含 `stop_reason`、`counts`、起止时间、driver）、`leaderboard`、`verification`、`exclusions` 四段
- 可选 `reports/legibility.md`：可读性包单独成文
- 可选 `reports/dashboard.html` 与 `reports/dashboard.data.json`：运行观测台静态页（`python scripts/dashboard.py render --run <run_dir> --reference-file <ref>.json`）。页面内联前 `--top` 条 finding，数据文件始终完整；对比条整组由 `--reference-file` 决定，没有它就不渲染

## 程序

1. 收集输入：`python scripts/aar.py status --run <run_dir>`、`python scripts/aar.py leaderboard --run <run_dir> --full`、`python scripts/aar.py forum list --run <run_dir>`、`python scripts/aar.py audit exclusions --run <run_dir>`。
2. 证据链不通过就不发报告：`python scripts/aar.py forum verify --run <run_dir>` 退出码 0、`python scripts/aar.py heldout verify --store <store> --run <run_dir>` 退出码 0、`python scripts/aar.py verify-approval --run <run_dir> --method <selected>` 退出码 0。
3. 装配 `reports/final.json`：走 orchestrator 时 `write_report` 停止时已写好 `meta`/`leaderboard`/`verification`/`exclusions` 四段；手工路径（light 档）就用 `write` 落同样四段，`verification` 至少含 `selected`、`leaderboard_aggregate`、held-out 分数、`generalizes`。
4. 写排行榜小节：从 `leaderboard.json` 的 `rows` 抄 `rank`/`method_id`/`aggregate`/`gates_pass`/`gates_failed`/`family`/`researcher_id`/`duplicate_artifact` 进 `reports/final.md` 的表格，并写明 `count`（被评分方法数）与 `passing`。
5. 写选中方法与 held-out 小节：抄 `reports/final.json.verification` 的 `selected`、`leaderboard_aggregate`、两边数字与 `generalizes`，并注明 held-out 的泛化类型（scenario / domain / format）与它是不是选择集。
6. 写三条强制诚实声明，措辞照抄：(1) 被报告的方法是**约 N 个被评分方法里最好的一个**，因此被评分噪声向上偏（论文 §5.1 的自述）；(2) **闸门只是崩溃探测器**，不是无损证明——论文 App. A.4 实测 IFEval 在十个 failure 上全部下降 9.5–12.0 分仍然通过闸门，实际只挡得住约 11–13 分以上的下跌；(3) 事后审计排除了哪些方法、依据哪一类作弊（原样重跑 67% / 复制基准格式 26% / 隐瞒违规步骤 21%），以及**没有被排除的轨迹仍可能存在未被发现的作弊**。
7. 写可读性包：对 `leaderboard.json.rows` 里的**每一个** method_id（不只选中那个），从 `forum/findings/<seq>-<method_id>.json` 取 `mini_paper.hash`、`artifact_hash`、`evidence.score_file_hash` 三项，配 `methods/<id>/mini-paper.md` 的路径列成表，写进 `reports/final.md` 或单独的 `reports/legibility.md`；人凭这三行就能复跑制品、复算分数。
   把同一批证据渲染成人能一眼看完的一页：`python scripts/dashboard.py render --run <run_dir> [--reference-file <ref>.json]` 产出 `reports/dashboard.html`（爬山曲线、排行榜、逐基准明细、冠军详情与三关监控、审计直方图、完整性条）与同目录的 `dashboard.data.json`。
   观测台是派生视图，判定全部复用 `aar_lib` 与 `final.json`；它不写 run 状态，随时可重建，因此不能替代报告里那三条诚实声明。
8. 写闸门判定小节：逐条抄 `eval/<id>/gates.json` 的 `name`/`direction`/`stat`/`method.mean`/`baseline.mean`/`margin`/`pass`，并复述 `run_config.gates[].note` 里写的「闸门拦不住什么」。
9. 写排除清单：逐条列 `exclusions.json` 的 `method_id`/`reason`/`category`/`evidence`；说明被排除的方法从排行榜消失但 finding 仍在论坛可查——排除不是删除。
10. 写停止原因与档位：`reports/final.json.meta.stop_reason`（或 `logs/orchestrator.jsonl` 的 `run stop:` 行）、`tier`、`driver`、起止时间。
11. 写复现附录：`run_config.json` 的 `config_hash`、`seeds`、`suite[].baseline`/`optimum`、`runner.cmd`、`gates[].baseline_values` 的出处、`retrieval.tier`（由 `python scripts/aar.py sources probe` 判定：≥4 源可用为 full，否则 basic / offline），以及 held-out 的 `items_hash`/`n_items`/`generalization`/`license`。
12. 声明降级：held-out 可见性降级（Windows 单用户下建不起第二运行身份时 ACL 退化为「独立目录 + verify + 轨迹审计」）与离线综述（`retrieval.tier = offline`）必须写进附录，不能省。

## 退出判据

- `reports/final.md` 与 `reports/final.json` 都存在；在 `final.md` 里能搜到三条诚实声明的关键词（best-of-N / 向上偏、崩溃探测器、未被发现的作弊）与 `stop_reason`。
- `reports/final.json.verification.selected` 非空，且等于 `leaderboard.json.best.method_id`（不等就必须在同一文件里写明为什么降级）。
- 可读性包覆盖 `leaderboard.json.count` 条方法，每条给出三个哈希；某项为 null（例如缺 `mini-paper.md`）要在表里写明原因。
- `python scripts/aar.py forum verify --run <run_dir>` 与 `python scripts/aar.py heldout verify --store <store> --run <run_dir>` 都是退出码 0。

## 常见失败

- 直接把 orchestrator 自动生成的 `reports/final.md` 当终稿交出去：它只有排行榜、verification 与三段 honesty notes，缺可读性包和复现附录；用本步骤补齐，追加而不是重写 `verification` 段。
- 报了 rank 1 却不写 best-of-N 偏差：违反声明 1；把 N（`leaderboard.count`）与「约 N 个被评分方法里最好的一个」写清楚。
- 把闸门 pass 说成「能力无损」：违反声明 2；必须复述 App. A.4 的 9.5–12.0 分实测与「约 11–13 分以上才挡得住」。
- 报告里删掉了被排除的方法：排除不是删除，finding 仍在论坛可查；报告要列 `exclusions.json` 每条的 reason 与 category。
- 复现附录缺 `config_hash` 或 `items_hash`：读者无法确认跑的是哪份配置、哪套基准；用 `run_config.json` 与 `python scripts/aar.py heldout manifest --store <store>` 补齐。
- 检索降级没声明：`retrieval.tier` 是 `offline` 时必须写明离线综述与覆盖度上限，否则读者会高估文献基础。
