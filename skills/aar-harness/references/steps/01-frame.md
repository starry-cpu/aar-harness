# 01-frame — 基准、held-out、闸门与冻结

## 目的

把 00-intake 的草稿变成一份**冻结的、可被机械执行的评测规格**：构念定义、评分基准套件、held-out、
回归闸门、预算与停止准则。这一步做完之后，任何人（包括研究者）都不许再改评测规则。

这也是整条链路上最容易被糊弄过去、代价又最大的一步。论文的核心教训就在这里：
**基准选错，后面爬山爬得再漂亮也不泛化。**

## 输入

- `run_config.json` 草稿与 `logs/intake.md`（00-intake 的产出）。
- 用户对候选基准/数据集的访问权限与许可信息。
- 目标系统可运行（02-instrument 需要它，但本步骤只需要知道怎么跑）。

## 产出

- `construct.json`（**尽早产出**，它是 03-survey 的输入闸门）。
- 冻结的 `run_config.json`：`suite` 至少三个异源基准，每个带实测 baseline 与 optimum。
- `<workspace>/heldout-store/`：封存的 held-out 条目 + **不含条目的** `manifest.json`。
- `gates`：至少一个回归闸门，带基线逐样本值与方向。
- `stop`：wall-clock 预算、plateau 窗口与最小增益。

## 程序

1. **先写 `construct.json`，不要等全部想清楚。**

       python -c "import sys; sys.path.insert(0,'scripts/lib'); import aar_lib as A; A.write_construct('<run_dir>', {...})"

   至少要有：`question`、`construct`、`method_space`、`scored_benchmarks`（哪怕是暂定名单）、
   `held_out_note`（只写「存在且会重测泛化」）、`method_families_seed`。
   写出来之后 03-survey 就能并行启动，不必等本步骤全部完成。

2. **取基准。** 按 `references/benchmark-sourcing.md` 的检索策略与适配度清单，
   为每个候选回答四件事：测什么构念、什么打分器、多少可评分样本、跑一次多久。
   找不到现成的就走降级阶梯（适配 → 自建 → 人工），每一步都在 `logs/` 留痕。

3. **逐个校验入选门槛**（论文 App. A.3 / A.5）：

   | 门槛 | 阈值 | 为什么 |
   |---|---|---|
   | 基线下限 | 大于 0.05 | 接近 0 的基线可能反映的是能力缺失，而不是可改进的行为 |
   | 基线上限 | 小于 0.9 | 接近饱和的基准没有提升空间 |
   | 可评分样本 | 至少 25 | 区间估计要足够窄，才分得清真实提升与噪声 |
   | 差异性 | 与同构念的其他基准至少在 domain / 数据生成流程 / 打分器 / 交互形式之一上不同 | 否则是在把同一个构念测好几遍 |
   | 行为效度 | 抽看约 25 个原始样例与 25 条系统响应 | 确认它真的在诱发目标行为，而不是系统没看懂任务 |
   | 运行时长 | 落在评测预算内；超了就换忠实代理（代表性子集，或换成能复现原判的更强 judge） | 每个方法都要重跑一遍 |

   论文的平均值是每个基准约 200 道题；这些门槛的作用是「分得清真假」，不是为了好看。

4. **实测 baseline**：对未改动的目标系统逐个跑一遍，把数字写进 `suite[].baseline`。
   不要假设，不要抄论文。任何一个基准的 baseline 掉出第 3 步的区间，就回去换基准。

5. **定 held-out**（详见 `references/heldout.md`）。三条硬要求：

   1. **同机制**：与爬山基准测的是同一个机制，不是碰巧也修好的另一个问题；
   2. **异分布**：scenario / domain / format 三类之一，跑完要标明是哪一类；
   3. **早封存**：必须在 03-survey 与任何提案之前写进 heldout-store。

   优先级：用户提供/确认 → 隔离 curator 会话切分或装配 → **评测时现场生成 seed + rubric**（最强）。
   最后一条是「同机制但找不到独立数据集」时的**首选**：条目在评测之前不存在，所以没有角色需要被信任。

   `manifest.json` 里**只放**版本、`items_hash`、条数、泛化类型、许可与可见性声明；
   条目只放在 `items/items.json`。

6. **定回归闸门。** 至少一个，写清方向与基线逐样本值：

   - 方向 `higher_better`（能力类）：通过条件是方法的上界 ≥ 基线的下界；
   - 方向 `lower_better`（1 为最优类，如过度保守率）：通过条件是方法的下界 ≤ 基线的上界。

   在 `gates[].note` 里**写清它拦不住什么**。论文 App. A.4 的实测值得抄进 note：
   IFEval 在十个 failure 上全降 9.5–12.0 分仍然通过，实际只挡得住约 11–13 分以上的崩跌。

7. **定预算与停止准则**：

   - `runner.cmd` 与 `runner.timeout_seconds`（单方法预算的机械体现）；
   - `stop.wall_clock_hours`（论文用 48 小时；standard 档建议 8–24）；
   - `stop.plateau_window` 与 `stop.min_gain`。论文的 40 是校准在 150–200 个方法的运行上的；
     **廉价确定性域用 15**，因为搜索空间可能远早于此就被穷尽，而 `plateau_decision` 里
     `len(vals) < window` 的守卫会让规则永远不触发（SQLite 研究为此白跑了五小时，见 09-orchestrate）。
   - `stop.tie_run`（默认 8）：**连续这么多个方法的 aggregate 完全并列就停**。这是并列信号，
     不是缓慢爬升信号——确定性评分下并列意味着空间已穷尽。0 表示关闭。

8. **平凡解诊断（在冻结之前做，别跳）**：

   用最笨、最不需要思考的做法构造一个方法，跑一遍，看它同时满足几条基准。

   - **同时满足全部基准 → 换域，或者补一条与现有基准真正冲突的基准。**
     这种做法会在十几轮内被穷尽，之后所有的运行时间都只是在重复同一个数字。
   - 只在部分基准上有效，且剩下的那些有明显的、需要取舍的改进空间 → 这个套件有区分度。

   SQLite 研究的实例：三条基准看起来形态各异（点查 / 范围排序 / join 聚合），但「给三张表各建一个
   覆盖索引」同时满足了三条，4 个索引的预算刚好够用，于是 15 个方法就触顶，之后 11 个方法拿到
   小数点后 15 位完全相同的分数。**形态不同不等于需要取舍。**

9. **写 `monitors` 与 `reference` 两项**（都进 `run_config`，**必须在冻结之前**定好）：

    - `monitors: {"static": true, "code": true, "paper": true}`：**建议默认全开**。SQLite 研究把两个 LLM
      监控留到事后，结果 14 个方法里 8 个（57%）被 PAPER_MONITOR 驳回，其中一条是 `results_free: false`
      ——而那 8 个已经在排行榜上待了几个小时。便宜域完全可以负担在环内的成本。
    - `reference`：手写一个合理基线的实测分，写成 `reference.json` 传给 `dashboard.py --reference-file`。
      没有它，观测台上就只有一个绝对分数，读者无法判断这个分数是好是坏。

10. **冻结。**

       python -c "import sys; sys.path.insert(0,'scripts/lib'); import aar_lib as A; A.freeze_run_config('<run_dir>')"

    冻结会写入 `frozen_at` 与 `config_hash`，之后任何改动都要显式 force 并在报告里说明。

11. **把冻结结果给用户确认一次**，特别是五样：基准套件、held-out 的泛化类型、闸门方向、
    `stop` 的三个数（wall clock / plateau_window / tie_run）、`monitors` 的开关。

## 退出判据

同时满足：

- `construct.json` 存在且含 `scored_benchmarks`；
- `suite` 长度 ≥ 3，每个条目都有非空 `baseline` 且落在 (0.05, 0.9) 之外的情况已被记录并解释；
- `heldout-store/manifest.json` 存在，`n_items` 大于 0，且**不含条目内容**；
- `gates` 非空且每条都有 `baseline_values`；
- **平凡解诊断已做过并记录**：最笨的做法没有同时满足全部基准，或者已经据此换域/补基准；
- `monitors` 与 `reference` 已写入（`reference` 可以是「本域不适用」的显式声明）；
- `run_config.frozen_at` 已写入；
- `python scripts/aar.py status --run <run_dir>` 输出正常。

## 常见失败

- **只凑到一个基准就开跑。** 这是最贵的一种失败。论文 App. D.1：单基准爬出来的方法在爬的那个上关闭 70.9%，
  在没见过的同构基准上是 -11.9% 和 +2.0%；三个 jailbreak 团队在未见基准上的平均变化都在 ±0.03 以内。
  少于三个异源基准，**不要启动**。
- **把一个基准切成几份当多个基准。** 随机切分不是异源：差异必须落在 domain、数据生成流程、打分器或交互形式上。
  论文 App. A.1 明确要求「同机制、异分布」，随机切分两侧同分布，测不出泛化。
- **held-out 选得太晚。** 先读综述再挑 held-out，等于让它进过选择过程，泛化声明就不成立了。
- **manifest 里带了条目。** 一旦 manifest 可读而它又含条目，单向墙就形同虚设。
  用 `python scripts/aar.py heldout manifest --store <store>` 看一眼实际暴露了什么。
- **baseline 靠抄。** 目标系统一换，baseline 就作废。任何「沿用上次的数字」都会让 closed fraction 失去意义。
- **闸门方向写反。** 1 为最优的指标（拒答率、过度保守率）必须用 `lower_better`，写反了闸门会放行最糟的方法。

