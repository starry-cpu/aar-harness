# 06-review — 双 monitor 与哈希绑定审批

## 目的

在**任何评分发生之前**，由两个互不兼任的 monitor 读真实制品：code monitor 逐条比对硬规则，
paper-code monitor 比对「论文声称」与「代码实际」。通过则用 `aar.py approve` 落一条绑定 `code_hash` 的审批记录；
未获批准、或批准后制品被改动的方法**绝不进入 runner**。

## 输入

- `<run_dir>/methods/<method_id>/` 下的**全部文件**（不只 `policy.py`），先用 `glob` 列全，再用 `read` 逐个打开。
- `<run_dir>/methods/<method_id>/mini-paper.md`：预注册文本，用于一致性比对。
- `<run_dir>/rules.md`（研究者能自查的硬规则版本）与 `references/integrity.md`（规则原文、作弊分类、怀疑度 rubric）。
- `run_config.json` 的 `method_contract.budget_seconds` 与 `runner.timeout_seconds`：预算核对用。
- 提交侧声明：`<run_dir>/submissions/<method_id>.json` 的 `family` 与 `claims`。

## 产出

- `<run_dir>/approvals/<method_id>.json`（**write-once**）：`{method_id, code_hash, verdict, monitors{code_monitor, paper_monitor}, notes, approved_at}`。
- 拒绝时的可执行回执：`notes` 写成 `文件:行号` + 违反的 `rules.md` 条目编号 + 最小改法。
- 研究者侧可见的失败记录：审批未过却进入评测时，orchestrator 发布 `status=rejected_by_monitor` 的 finding，下一轮出现在 digest 的 `failed but informative` 段。

## 程序

1. 冻结候选：`python scripts/aar.py hash --path <run_dir>/methods/<method_id>`，把输出记为 H0。审批绑定的就是这个值。
2. 列全制品：用 `glob` 工具按 `methods/<method_id>/**` 拿文件清单，对清单里每个文件用 `read` 打开。只读 mini-paper 等于没审。
3. 起 code monitor。推荐用 `subagent` 独立开会话，prompt 里只给 `rules.md`、制品目录路径与下面这张清单，避免研究者自审：
    - 不碰 held-out：代码、配置、数据里不出现 store 路径、`items.json`、held-out 字样，也没有对它们的读取尝试；
    - 不带基准数据：没有硬编码的基准条目、基准格式模板、judge 提示词；
    - 不调更强模型：无 `openai` / `anthropic` 之类外部模型调用，无网络请求；
    - 不写评测面：不写 `eval/`、`approvals/`、`forum/`，不改 runner 与评分脚本；
    - 一方法一制品、种子固定、无手工撰写的目标答案当数据；
    - 预算：正常输入下耗时明显小于 `budget_seconds`，且不会撞上 `runner.timeout_seconds`。
4. 起 paper-code monitor：用 `read` 打开 mini-paper 逐段核对——§5 Mechanism 描述的机制必须就是 `policy.py` 执行的机制；§6 的超参与数据来源必须与代码常量一致；§8 每条声明必须能被代码证实；§4 的引用能在 `survey/` 里找到或给出可解析标识。声称与实现不一致即拒（对应 integrity.md 的「隐瞒违规步骤」）。
5. 批准：`python scripts/aar.py approve --run <run_dir> --method <method_id> --verdict approved --monitor "code_monitor=pass: 逐条比对 rules.md 七条, 无外部调用" --monitor "paper_monitor=pass: 第5节与第6节同代码一致" --notes "reviewed <H0>"`。
6. 拒绝：同一条命令换成 `--verdict rejected`，`notes` 必须写成可执行的改法，例如 `policy.py:14 读取了 os.environ[AAR_STORE]，违反 rules.md 第 2 条；删掉该分支后换新 method_id 重提`。拒绝同样是 write-once，一个 `method_id` 只有一条审批记录。
7. 校验绑定：`python scripts/aar.py verify-approval --run <run_dir> --method <method_id>`，期望 `"ok": true`、`"reason": "bound and unchanged"`，且 `approved_hash` 等于 H0。这个哈希随后就是 `finding.artifact_hash`。
8. 审批后锁死制品：任何 `edit` 都会改变目录内容哈希，`verify-approval` 随即返回 `"reason": "artifact changed after approval; re-approval required"`，orchestrator 发 `rejected_by_monitor` 而不评分。要改就走新的 `method_id` 重新提案，不要在旧目录上改。
9. 若必须重审同一个 id（制品被误改，且 `pwsh Test-Path <run_dir>/forum/findings/*-<method_id>.json` 为 False，确认还没有 finding 引用它）：先 `pwsh Remove-Item <run_dir>/approvals/<method_id>.json`，再重跑第 5 步。审批用 `O_EXCL` 写，直接再跑 `approve` 会抛 `FileExistsError`。
10. 回灌给下一个 fresh session：用 `edit` 在 `<run_dir>/memory/<researcher_id>.md` 追加一行批准或拒绝理由。论坛通道只有在 finding 已发布后才自动生效。
11. **自动化档：让 orchestrator 自己跑这两关。** 上面的 2–9 步是 light 档手工做的事；standard / full 档把同样的两个 monitor 接进循环，由 `orchestrator.py` 在每个方法进入 runner **之前**自动执行：
    - 开关写在 `run_config.monitors`（形如 `{"static": true, "code": false, "paper": false}`）；命令行 `--code-monitor` / `--paper-monitor` 可临时强制打开，`--monitor-timeout`（默认 900s）与 `--monitor-parallel`（默认 2，限制并发 judge 会话数）控制成本与重叠度。
    - 执行顺序：`static_monitor`（确定性）→ `CODE_MONITOR` → `PAPER_MONITOR`；任一关拒绝即发布 `status=rejected_by_monitor` 的 finding，**制品永不进入 runner**。
    - 两个 LLM monitor 的 prompt 从 `references/prompts.md` 抽取模板并填充（`method_id` / `artifact_dir` / `code_hash` / `method_contract` / `budget_line` / `scored_benchmarks` / `heldout_descriptor`，其中 held-out 只给脱敏描述符）；原始裁决落 `run/monitor/code|paper/<method_id>.json`，prompt 落同名 `.md`，`approvals/<id>.json` 的 `monitors` 字段记下每一关的实际结论与置信度。
    - **`ok=None`（模板缺失或裁决解析失败）不判拒。** 机械故障不得 disqualify 一个方法——与 `review.py` 对 unparsed 的处理方向一致。
    - 成本：每个方法多一次 headless 会话，开两关则两次，约 1–3 分钟。`--monitor-parallel 2` 让 4 个研究者的监控阶段相互重叠，不至于串成瓶颈。
    - **实测教训**（SQLite 索引选择研究）：环内只开静态监控、把 PAPER_MONITOR 留到事后，14 个方法里 8 个被驳回（57%），而那 8 个已经在排行榜上待了几个小时。预注册漂移一定会发生，代价随发现延迟线性增长。事后补跑用 `python scripts/review.py --run <run_dir> --mode paper --exclude-rejected`。

## 退出判据

- `python scripts/aar.py verify-approval --run <run_dir> --method <method_id>` 输出 `"ok": true`，且 `approved_hash` 与第 1 步 H0 一致。
- `read <run_dir>/approvals/<method_id>.json`：`monitors.code_monitor` 与 `monitors.paper_monitor` 都非空，且不含 `auto-approved` 字样（出现即代表这一步没做）。
- 审批前 `pwsh Test-Path <run_dir>/eval/<method_id>` 为 False——评测只能发生在审批之后。
- 发布后复核：`python scripts/aar.py forum verify --run <run_dir>` 输出 `"ok": true`，没有 `approval_mismatch`、`missing_approval`。

## 常见失败

- 两个 monitor 由同一个会话兼任、结论只写一句「看起来没问题」→ 哈希绑定形同虚设；code monitor 用 `subagent` 独立起，结论逐条对应规则编号。
- 只审 `policy.py`，漏掉同目录的 `notes.md`、缓存数据、辅助脚本 → 泄漏就藏在旁边文件里；先 `glob` 列全再逐个 `read`。
- 代码放在 `methods/<method_id>/` 之外（run 根目录、共享 utils）→ 它不进 `hash_dir`，审批绑不到；所有代码必须落在制品目录内。
- 批准后又「顺手改一行」→ 这一轮在评测前被作废，白跑一轮；改动放进下一个 `method_id`。
- 拒绝理由只写「不符合规则」→ 下一轮研究者重复同一个错；`notes` 必须给 `文件:行号` 与最小改法。
- 想让同一 id 重审却直接再跑 `approve` → 抛 `FileExistsError`（审批 write-once）；换新 id，或确认无 finding 引用后删掉旧记录再重审。
