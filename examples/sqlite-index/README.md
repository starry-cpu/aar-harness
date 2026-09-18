# SQLite 索引选择研究（aar-harness 的第一次真实运行）

**已完成。** 4 个自动研究者跑了 1 小时 40 分、产出 14 个方法后，指标触顶，按操作者判断停止并收尾。

> ### 这份示例包含什么、不包含什么
>
> 本目录是那次运行的**领域侧框架代码**——`world.py` 怎么造域、`runner.py` 怎么跑方法、
> `frame.py` 怎么钉住基准与闸门。**运行数据不随仓库发布**：`run/`（findings、approvals、
> eval、audit、reports 等过程数据）与 `heldout-store/`（封存的 held-out）跑一次
> `python frame.py` 才会现场生成。
>
> 因此下文所有数字都来自**作者本地的那次运行**，仓库不附带支撑数据，**无法从这个 checkout
> 直接复现**——重跑只会得到你自己的数字。保留它们是为了记录真实发生过的结论与闸门行为
> （尤其是下面「8 个方法被 PAPER_MONITOR 拒掉」这个事前闸门生效的正面案例），
> 而不是为了让读者核对。

## 结论

**问题**：哪种索引选择策略在异质的 SQLite 查询负载上最有用？

**答案**：`m-r2-1-c2`，自报族为「covering composite indexes, dimension-first layered composition, optimizer statistics」。

| | aggregate（三条评分基准的几何平均） | held-out `sensors`（未见过的 schema） |
|---|---|---|
| 未调优基线 | 0 | — |
| 我手写的参考 tuner | 0.4954 | 0.5800 |
| **自动研究者最好方法** | **0.735979** | **0.748038** |

held-out 上是**另一套 schema**（devices/readings）和不同查询形态，成本从 4,499,300 个操作码降到 1,133,650——砍掉 75% 的工作量。**泛化成立，不是靠记住主 schema 拿到的。**

### 一个稳健性事实

四（五）个方法并列在同一个上限 `0.7359786420692659` 上，来自**三个不同研究者**、**四种不同的自报方法族**（covering composite / plan-layer composition / executed what-if on a synthetic replica / measured what-if selection）。这不是一次幸运命中，而是这个评测套件的最优值被多个独立路径同时达到。

## 目标系统与评测设计

内存 SQLite，固定种子确定性重建。三条评分基准在同一条 schema 上、查询形态互不相同：

| 基准 | 形态 | 无索引基线（VM 操作码） |
|---|---|---|
| `point` | 一半按外键等值查，一半再叠低基数 status 过滤 | 3,001,150 |
| `rangesort` | 时间戳范围扫描按 amount 排序，混一半 status 过滤的最近列表 | 2,339,250 |
| `joinagg` | 两表 join + GROUP BY，一半按 city 分组、一半按 tier 分组 | 4,800,600 |

held-out `sensors` 基线 4,499,300，封存在 `heldout-store/`（由 `frame.py` 生成，**不随仓库发布**），与评分集的 5-gram 重叠率 **0.0**。

**方法契约**：`propose(schema_ddl, sample_queries, budget) -> list[str]`，只接受 `CREATE INDEX` / `ANALYZE`，预算 **4 个索引**（小于覆盖全部查询形态所需），评测查询永不外传。

**指标**：成本 = 执行的操作码数（SQLite progress handler）。`score = 1 - 方法成本/基线成本`，三条取几何平均，任一 <= 0 归零。选操作码而不是计时，是因为它**完全确定性**——实测同一制品跑三次，四条基准的成本一字不差，**噪声地板为 0**。

## 审查结果（这是这一轮最有价值的部分）

| 关卡 | 开在哪 | 结果 |
|---|---|---|
| static_monitor（确定性） | 环内 | 14 个里拦下 1 个（用了 `eval(`） |
| verify_forum / heldout verify | 收尾 | 均 `ok: true`，零问题，零泄漏 |
| CODE_MONITOR（LLM） | **环内没开**，事后补测 | 干净制品 approve(0.9)；运行时读 `run_config.json` 反推评测集的制品 reject(0.95) |
| PAPER_MONITOR（LLM） | 事后 | 12 个里 **8 个 reject**，blocking 计 18× material_divergence、2× leaked_result、2× missing_budget、1× missing_data_construction |
| INTEGRITY_JUDGE（LLM） | 事后 | 137/299 块（45%，8 条轨迹），**无一块 >= 4**；但 2-3 分区间出现了 `Scorer or harness tampering` 1 次、`Finding forgery` 1 次 |

**关键**：把 8 个注册有问题的方法全部排除后，**并列在 0.735979 上限上的几个方法仍有两个是通过审查的**（`m-r2-1-c2` 置信度 0.82、`m-r3-2-c7` 置信度 0.84），且冠军的 `results_free: true`、引用 13 篇。结论不依赖于任何一个被驳回的方法。

## 这一轮暴露的三个真问题

1. **指标 1 小时就触顶**：11 个独立制品拿到小数点后 15 位完全一致的 aggregate。论文 App. D.3 列的第一种解释——爬山套件本身的天花板。**评测套件的区分度不足以支撑 8 小时搜索**，下一个实验该加一条异构基准或收紧索引预算，而不是延长运行时间。
2. **`plateau_window: 40` 是从论文规模照搬的，在这个域上失效**：`plateau_decision` 有 `len(vals) < window` 的守卫，方法数不到 40 时 plateau 永不触发，于是白跑了 5 个多小时同一个数字。廉价确定性域应用 10–20。已写回 `skills/aar-harness/references/steps/09-orchestrate.md`。
3. **预注册漂移一定会发生，代价随发现延迟线性增长**：环内只开静态监控，8 个违规方法在排行榜上待了几个小时才被事后审查抓出。已写回 `skills/aar-harness/references/steps/06-review.md` 第 11 步。

## 目录

    world.py            领域定义：schema、种子数据、四类负载、操作码成本测量
    runner.py           runner：建库 -> 调 tune.propose -> 校验并应用 DDL -> 测量评测负载
    frame.py            01-frame：实测基线、封存 held-out、写出并冻结 run_config
    variance_test.py    变异冒烟测试（同一制品跑三次，确认噪声地板为 0）
    probe_tuners.py     参考 tuner 的横向对比
    collect.ps1         一键收尾：完整性校验 -> 报告 -> PAPER_MONITOR -> 审计 -> 打印
    tuners/             参考 tuner（schema_aware 会解析 schema 因而能迁移；其余是负例）
    reference.json      参考 tuner 的实测分数（观测台 `--reference-file` 的输入，只读）

**不随仓库发布**——下面两项都由 `frame.py` 现场生成：

    run/                运行目录：findings、approvals、eval、monitor、audit、reports
    heldout-store/      封存的 held-out（条目只在这里，manifest 不含条目）

## 怎么重跑

    python frame.py                       # 重置 run/ 与 heldout-store/
    python ../../skills/aar-harness/scripts/orchestrator.py \
        --run run --driver dsh --max-parallel 4 --wall-clock 8h \
        --code-monitor --paper-monitor    # 这一轮缺的两个 LLM 监控，这次开在环内
    pwsh -File collect.ps1

`collect.ps1` 末尾会自动 `render` 一次观测台。

## 看观测台

    python ../../skills/aar-harness/scripts/dashboard.py render --run run --title "SQLite 索引选择研究" --reference-file reference.json
    python ../../skills/aar-harness/scripts/dashboard.py serve  --run run --title "SQLite 索引选择研究" --reference-file reference.json

`render` 写出 `run/reports/dashboard.html`（同目录 `dashboard.data.json` 是完整内联快照）；`serve` 在 `127.0.0.1:8787` 起同一份产物，每 30 秒整页重载一次。
观测台是**派生视图**：只读 run 目录，闸门/天花板/名次/排除/完整性全部复用 `aar_lib` 的判定，自己不定义判据，随时可以删掉重建。冠军详情里的 held-out 一行给两件事：主 = 冠军在封存 `sensors` 上的操作码 `1133650` 对未调优基线 `4499300`（砍掉 74.8% 工作量）；次 = 同场对比**参考实现**（`reference.json` 的 `held_out.score`，schema_aware 实测 0.5800）。**它不是基线**：本域 `score = 1 - cost / baseline_cost`，未调优基线的分数恒为 0.0，所以基线分不显示也不该显示。

## 已知限制

- 方法是**静态顾问**：只看 schema 与查询样本，拿不到数据库连接，因此无法采样数据估计选择率。这让 held-out 可迁移，代价是砍掉了「采样驱动」那一大类策略。
- 合成数据，分布平滑，没有真实库里的相关性倾斜与热点。
- 只有一条 held-out，且是 domain 泛化；scenario 与 format 两类没有覆盖。
- 作弊审计只覆盖 137/299 块（8 条轨迹），**不能声称每条轨迹都干净**，只能声称已判的块里没有确认作弊。

