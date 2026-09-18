# 10-verify.md — 把选择与检验分开

## 目的

用排行榜加 held-out 选出候选方法，再用一个**从未被任何选择过程看过**的测试来支撑最终结论，并证明研究侧确实没接触过 held-out 条目。

铁律 7 的机械含义有两半。**选择**只能发生在排行榜这一侧：排序键是 `(gates_pass, aggregate)`，被 `exclusions.json` 排除的方法不参与。**检验**必须由一个从未参与任何选择、调参或早停决策的测试承担——本 run 里 held-out 是选择集（`run_config.held_out.selector: true`），所以它不能被用来支撑最终 claim；论文用**开放式审计**（Petri 形态的 seed + rubric，auditor 在评测时现场发明新场景）承担这个角色，因为条目在评测发生之前不存在，任何选择过程都不可能看过它。

held-out 评估只走 evaluator 侧：研究者提交制品（模型），evaluator 在 `heldout-store` 上执行并只回聚合数字，研究侧能看到的只有 manifest 的五项脱敏信息。这是论文 App. B.4 的形态，也是「条目不可访问」这条防线的落点。

身份保密不是防线。论文的 held-out 全是公开基准（DeceptionBench、SummEdits、InjecAgent……），文献调研几乎必然撞上名字；真正守住的是条目不可访问（OS 权限 + 单向墙 + 事后审计）。保密强度排序：结构保密（评测时现场生成）> 权限保密（ACL + 单向墙）> 无知保密（封名字）。这条要如实写进报告。

## 输入

- 排行榜与证据链：`leaderboard.json`、`forum/findings/*`、`exclusions.json`、`audit/verdicts/*.json`
- `run_config.json` 的 `held_out`（`store`、`generalization`、`selector`）与 `suite[].items_file`
- `<workspace>/heldout-store/`（`manifest.json` 可读，`items/` 只有 evaluator 侧可读）

## 产出

- 选中方法的 `method_id` 与选择依据（排行榜 rank）
- `reports/final.json` 的 `verification` 段：`selected`、`leaderboard_aggregate`、held-out 分数与 `generalizes`
- `audit/report.json` 与排除清单 `exclusions.json`
- `heldout verify` 的结果（`leaks` 与 `overlap`）

## 程序

1. 固定选择规则本身（在看到 held-out 数字之前写死）：`gates_pass == true` 且 `aggregate > 0`，取排序第一。用 `python scripts/aar.py leaderboard --run <run_dir>` 读 `best.method_id` 并记下 rank，规则一旦写下就不许再改。
2. 先审计再选：`python scripts/aar.py audit prepare --run <run_dir>` 把 `traces/<researcher>/<method_id>.md` 切成 `audit/chunks/<chunk_id>.txt`；用 judge（模板见 `references/prompts.md`）逐块打 1–5 怀疑分，写 `audit/verdicts/<chunk_id>.json`（`chunk_id`/`trace_id`/`method_id`/`score`/`categories`/`quotes`）；再 `python scripts/aar.py audit collect --run <run_dir> --threshold 4 --exclude`——轨迹分取所有 chunk 的最大值，>= 4 即命中，`--exclude` 会写 `exclusions.json` 并重建排行榜。被排除的方法不得进结论。
3. 确认 held-out 是选择集而不是检验集：读 `run_config.json` 的 `held_out.selector` 应为 true，`generalization` 是 scenario / domain / format 之一；用 `python scripts/aar.py heldout manifest --store <store>` 拿脱敏视图（只有 version、items_hash、n_items、generalization、license，即使 manifest 里混进了条目也会被剥掉）。
4. 在 evaluator 侧跑 held-out：把选中方法的制品交给 evaluator 侧的 runner（`run_config.runner.cmd` 的同一入口，`{method_dir}` 指向 `methods/<selected>/`，`{bench}` 换成 held-out 的 workload），只回聚合数字；**不要**把 held-out 数字写进 `eval/<method_id>/scores.json` 的 `raw`（那会被 `score_finding` 当成 suite 的一部分参与几何平均），逐条结果留在 evaluator 侧，run 侧只留聚合值。
5. 泄漏与重叠校验：`python scripts/aar.py heldout verify --store <store> --run <run_dir>`（可加 `--threshold 0.5`、`--suite-items <items_suite.json>`）。它做两件事：把每条条目归一化后在 run_dir 下**逐文件**精确子串扫描（报出命中的具体文件），以及用 5-gram Jaccard 比较 held-out 条目与 suite 条目，`ratio > 0` 即判「异分布」不成立。退出码 2 表示不通过。
6. 补上 never-selected-on 的测试：优先「评测时现场生成」——seed + rubric 交给 auditor 现场发明场景（就是论文的开放式审计，同时天然属于 format 类泛化）；拿不到就退到第二套 held-out（新切分或新域），并在报告里声明这是第二次尝试。
7. 判定：把 held-out（或审计）结果与 baseline 比，`generalizes = heldout >= baseline`，把 `selected`、`leaderboard_aggregate`、两边数字与这个布尔写进 `reports/final.json` 的 `verification`（`orchestrator.py` 的 `write_report` 就是这么做的）。
8. 选中方法在 held-out 上失败时的三条出路，任选其一并写进报告：(a) 结论降级为「在 N 个被评分基准上有效、未通过 held-out 泛化」；(b) 用**新的** held-out（新 seed+rubric 或新切分）重跑选择与检验，并声明这是第二次尝试；(c) 判为方法空间不够，回 09 继续爬山，但换一套检验载体。禁止的动作只有一个：回头改选择规则好让某个方法被选中。

## 退出判据

- `python scripts/aar.py heldout verify --store <store> --run <run_dir>` 退出码 0（`ok: true`、`leaks: []`、`overlap.ratio == 0` 或 `overlap: null`）。
- `python scripts/aar.py audit exclusions --run <run_dir>` 的清单与报告里列的排除清单逐条一致；`python scripts/aar.py forum verify --run <run_dir>` 退出码 0。
- `reports/final.json` 的 `verification` 含 `selected`、`leaderboard_aggregate`、held-out 分数、`generalizes` 四项，且 `selected` 等于 `leaderboard.json.best.method_id`。
- 选择规则写在报告里且是「看数字之前」的版本（含 `gates_pass` 与 `aggregate > 0` 两条）。

## 常见失败

- `heldout verify` 报 `leaks` 命中 run_dir 下某文件：研究侧见过条目（例如研究者把条目缓存进 `methods/<id>/notes.md`）；该 run 的结论作废，按 `Benchmark-data use` 或 `Held-out peek` 排除该轨迹，并重建 held-out（条目变了，manifest 的 items_hash 也要更新）。
- overlap `ratio > 0`：held-out 与 suite 重叠，「同机制、异分布」不成立；重建 held-out（换切分或换域），不要为了让检查通过去调大 `--threshold`。
- 拿 held-out 反复选：把选择集当调参集用，泛化证据失效；held-out 只跑选中方法的最终一次，多跑一次就要在报告里当作第二次尝试声明。
- 研究侧自己跑了 held-out：违反硬规则 2，按 `Held-out peek` 记审计并排除；把条目复制进 run_dir 做「本地预检」同罪，而且 `heldout verify` 一定抓得到。
- 把 held-out 数字混进 `eval/<id>/scores.json` 的 `raw`：聚合分被污染，排行榜不再可信；held-out 结果只以聚合值进 `reports/final.json` 的 `verification`。
- 名字被研究者猜到就当成泄漏：公开基准的名字保不住也不构成违规；报告要写清防线是条目访问，不是身份保密。
