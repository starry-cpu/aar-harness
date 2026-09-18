# contracts.md — 全部 schema 与字段语义

机器可读状态一律 JSON，人类可读状态一律 markdown。每个 schema 都标了**由谁写**，
这是整套 harness 的权限模型：定序类状态单写者，写一次类内容允许并发。

字段名与 `scripts/lib/aar_lib.py` 的实现一致，改代码时同步改本文档。

## 1. run_config.json（orchestrator 写，01-frame 末尾冻结）

    {
      "schema": "aar/1", "created_at": ..., "run_dir": ...,
      "tier": "light|standard|full|toy",
      "question": "研究问题原文",
      "construct": "被测构念的一句话定义",
      "target_system": "目标系统描述（固定部分）",
      "method_contract": { "interface": ..., "budget_seconds": ..., "artifact": "methods/<method_id>/" },
      "suite": [ { "name": ..., "metric": ..., "baseline": 0.11, "optimum": 1.0,
                   "source": ..., "items_file": "可选，用于 held-out 重叠检查" } ],
      "held_out": { "store": ..., "manifest": ..., "generalization": "scenario|domain|format",
                    "selector": true, "items_file": ... },
      "gates": [ { "name": ..., "direction": "higher_better|lower_better",
                   "stat": "mean_ci|wilson|bootstrap", "bench": ...,
                   "baseline_values": [ ... ], "note": "闸门拦不住什么" } ],
      "runner": { "cmd": "... --method {method_dir} --bench {bench} --json",
                  "gate_bench": ..., "timeout_seconds": 120 },
      "stop": { "wall_clock_hours": 8, "plateau_window": 40, "min_gain": 0.005 },
      "forum": { "enabled": true },
      "retrieval": { "tier": "full|basic|offline", "checks": [ ... ] },
      "researchers": 4, "max_methods": 200,
      "frozen_at": ..., "config_hash": "sha256:..."
    }

- `frozen_at` 一旦写入，`freeze_run_config` 会拒绝再次冻结（除非显式 force）。
- `runner.cmd` 是**唯一**允许与评测数据接触的入口；`{method_dir}` 与 `{bench}` 是占位符。
- `retrieval.tier` 记录 00-intake 探测到的检索源可用性，最终报告会复述这个降级档。

## 2. construct.json（01-frame 早期产出）

librarian 的输入闸门。它比 run_config 早出现，因为综述只依赖构念，不依赖可跑的闭环——
这正是 02-instrument 与 03-survey 能并行启动的原因。

    { "schema": ..., "question": ..., "construct": ..., "method_space": ...,
      "scored_benchmarks": [ ... ], "held_out_note": "只说明存在且会重测泛化",
      "method_families_seed": [ ... ], "written_at": ... }

`held_out_note` 是**唯一**允许写进研究侧的 held-out 信息：存在、且会重测泛化。不含身份与条目。

## 3. 方法制品（研究者写）

    <run_dir>/methods/<method_id>/
      <entrypoint>            # 按 method_contract.interface 实现
      mini-paper.md           # 预注册，必须在任何结果之前写完
      ... (配置、数据等自包含文件)

制品目录的**内容哈希**就是它的身份：`hash_dir()` 对排序后的相对路径 + 每个文件的 sha256 求一次哈希。

### submission.json（研究者写，唯一的上报通道）

    { "researcher_id": "r1", "claims": [ "一句话结论" ],
      "reuse_hint": "别人怎么接着改", "family": "方法族",
      "tags": [ ... ], "supersedes": null,
      "survey_additions": [ <survey entry> ] }

`claims` 与 `reuse_hint` 是研究者唯一能影响 finding 的字段；**分数不由它提供**。

## 4. approval.json（monitor 产出，orchestrator 落盘）

    { "schema": ..., "method_id": ..., "code_hash": "sha256:...",
      "verdict": "approved|rejected", "monitors": { "code_monitor": ..., "paper_monitor": ... },
      "notes": ..., "approved_at": ... }

`code_hash` 必须等于制品目录当前的内容哈希，否则 `verify_approval` 判定失效，
且 evaluator 拒绝评分。制品改动一次就要重新审批一次——这是铁律 3 的机械实现。

## 5. 评测产物（evaluator 写）

    eval/<method_id>/scores.json
    { "schema": ..., "method_id": ...,
      "raw": { "<bench>": 0.42 }, "windows": { "<bench>": [ ... 逐窗口分数 ... ] },
      "scored": { "scores": { "<bench>": { "raw", "baseline", "optimum", "closed" } },
                  "aggregate": { "kind": "geomean", "value": 0.31, "zeroed_by": [ ... ] } },
      "meta": { "runner_cmd": ..., "started_at": ..., "ended_at": ... } }

    eval/<method_id>/gates.json   ->  [ gate_verdict, ... ]
    gate_verdict = { "name", "direction", "stat",
                     "method": { "mean|p", "lo", "hi", "n" },
                     "baseline": { ... }, "margin": ..., "pass": true|false }

## 6. finding.json（**只有 orchestrator 写**）

    { "schema": ..., "finding_id": "F00042", "seq": 42, "method_id": ...,
      "artifact_hash": "sha256:...",            # 必须等于 approval.code_hash
      "mini_paper": { "id", "hash", "path" },   # 预注册，跑之前冻结
      "author": { "researcher_id", "session_id" },
      "status": "scored|gate_failed|run_failed|rejected_by_monitor|claim_mismatch",
      "family": ..., "scores": { ... }, "aggregate": { "kind", "value", "zeroed_by" },
      "gates": [ gate_verdict ],
      "evidence": { "score_file", "score_file_hash", "runner_cmd", "started_at", "ended_at" },
      "claims": [ ... ], "reuse_hint": ..., "tags": [ ... ], "supersedes": null,
      "claim_mismatch": "仅在命中时出现",
      "published_at": ..., "integrity": { "record_hash": "sha256:..." } }

三条哈希把「预注册论文 ↔ 跑的代码 ↔ 产出的分数」钉在一起：
`mini_paper.hash`、`artifact_hash`、`evidence.score_file_hash`。
`integrity.record_hash` 是对「去掉 record_hash 字段后的规范化 JSON」求的哈希，
用于发现事后编辑——自引用哈希的常规做法。

finding **只写一次**（`O_EXCL`），修正靠新 finding 带 `supersedes`，从不编辑。

## 7. leaderboard.json / leaderboard.md（orchestrator 写）

    { "schema": ..., "rebuilt_at": ..., "count": N, "passing": M, "best": <row|null>,
      "rows": [ { "rank", "finding_id", "method_id", "artifact_hash", "status", "family",
                  "aggregate", "gates_pass", "gates_failed": [ ... ], "researcher_id",
                  "published_at", "duplicate_artifact": bool } ] }

排序键是 `(gates_pass, aggregate)` 降序——先看闸门，再看分。
被 `exclusions.json` 排除的方法**不出现在**排行榜里（除非显式 include_excluded）。

## 8. memory/<researcher_id>.md（orchestrator 追加写）

每个研究者一份，纯 markdown，按方法追加小节：状态、aggregate、各基准 closed、失败原因、自己的 claim。
它就是「fresh session 之间」的连续性载体：下一轮的新会话读这个文件，而不是继承上一轮的上下文。

## 9. heldout-store（评测侧写，研究侧只读 manifest 的脱敏视图）

    <workspace>/heldout-store/
      manifest.json      # 单向可见：版本、items_hash、n_items、泛化类型、许可、可见性声明
      items/items.json   # 封存条目，**只有 evaluator 侧可读**
      gold/  scorer/

重要：**条目只放在 items/items.json**，不要放进 manifest.json。
`aar.py heldout manifest` 只打印版本、hash、条数、泛化类型、许可这五项，
即使 manifest 里混进了条目也会被剥掉。

## 10. survey 条目（研究者与 librarian 并发写，write-once）

    survey/entries/<slug>.json
    { "schema", "method_name", "family", "relevance",
      "problem_and_idea", "key_insight": { "helps_when", "fails_when" },
      "mechanism": { "objective_or_algorithm", "load_bearing_design_choices" },
      "reproduction_recipe": { "ordered_steps": [ ... ], "hyperparameters": { ... } },
      "applicability_to_this_target", "source": { "urls": [ ... ], "year", "doi", "arxiv_id" },
      "cost_estimate", "known_failure_modes",
      "provenance": { "query_id", "retrieved_at", "license" },
      "dedupe_key", "added_at" }

必需字段：`method_name`、`family`、`problem_and_idea`、`source`（至少要有 urls 或 year）。
去重键顺序：DOI → arXiv id → 归一化方法名。
`survey.md` 与 `survey/index.json` 是**派生视图**，可以随时重建，不要手改。

    survey/queries.jsonl    # 每条检索查询串 + 时间 + 命中数，保证可复现

## 11. 审计与排除

    audit/chunks/<chunk_id>.txt     # 第一行是 JSON 头：chunk_id / trace_id / method_id / chunk_index
    audit/verdicts/<chunk_id>.json  # judge 产出：{ chunk_id, trace_id, method_id, score, categories, quotes }
    audit/report.json               # 归并结果：每条轨迹取所有 chunk 的**最大**怀疑分
    exclusions.json                 # [{ method_id, reason, category, evidence, at }]

轨迹分 = 各 chunk 怀疑分的最大值，所以任何一处作弊都足以标记整条轨迹（论文 App. G.1 的规则）。
被排除的方法从排行榜消失，但 finding 仍在论坛里可查——排除不是删除。

