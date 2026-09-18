# framework.md — 域无关框架与论文证据

本文档把论文《Automated Researchers Can Reliably Mitigate Alignment Failures》的机制抽象成
与领域无关的部件，并为**每一条设计决策**标出它在论文里的出处和原始数字。凡是本 skill 强制要求的做法，
都能在这里找到它为什么被强制。

## 1. 五个角色

| 角色 | 做什么 | 不做什么 |
|---|---|---|
| Orchestrator | 冻结 run_config、调度研究者、运行 runner、组装并发布 finding、维护 memory、执行停止判定 | **不提案**；不写分数（分数只能来自 evaluator） |
| Librarian（4 个并行） | 检索文献，写结构化条目进共享综述，产出方法族分类法 | 不接触 held-out；不提案 |
| Researcher（K 个并行） | 每轮一个 fresh session：读公共产物 → 排候选 → 写预注册 mini-paper → 产出制品 | 不写论坛；不写分数；不接触 held-out |
| Monitor（代码 + 论文两个） | 读**真实代码**做合规判定；读论文与代码的一致性；审批绑定哈希 | 不评分 |
| Evaluator | 执行制品、评分、判定闸门，只回聚合数字 | 不回原始样本 |

论文 §3 的原始分工是：4 个 librarian（Claude Sonnet 4.6）建综述 → 5 个 AAR（Claude Opus 4.8）并行爬山，
每个 AAR 独立 session，每轮有 monitor 审批，评测由独立 evaluator 完成。

## 2. 主循环

    read(survey, briefing, leaderboard, forum digest, own memory)
      -> rank a few candidate methods
      -> write results-free mini-paper           # 预注册，跑之前冻结
      -> produce one self-contained artifact
      -> monitor reads the real code             # 审批绑定 artifact hash
      -> runner executes inside the fixed budget
      -> evaluator scores; gates applied
      -> publish finding (single writer) + rebuild leaderboard + append memory
      -> next iteration starts a FRESH session

停止条件：wall-clock 预算耗尽、性能 plateau、或方法数预算用尽。
论文 §3.1：AAR 跑到 48 小时预算或性能 plateau 为止；β 每个 iteration 都是 fresh session，
连续性由持久 memory file 承担，而不是不断增长的上下文窗口。

## 3. 证据表

| 设计决策 | 论文出处 | 原始数字 | 对本 skill 的含义 |
|---|---|---|---|
| 必须同时爬多个异源基准 | §2.1, App. D.1 | 只爬 Open Prompt Injection 时，在爬的基准上关闭 70.9% 差距，在没见过的两个 prompt-injection 基准上是 −11.9% 和 +2.0%；jailbreak 三队各爬一个基准，共提 1,188 个方法、评分 453 个、405 个过闸门，冠军在未见基准上的平均变化都在 ±0.03 以内 | **默认 ≥3 个异源基准**；单基准对照实验是 backlog 里最该先做的一个 |
| 用几何平均而非算术平均 | §2.2 | 任一基准 ≤ baseline 就把总分钉成 0 | `aggregate_geomean` 实现零化规则，并在 finding 里记录 `zeroed_by` |
| 闸门用区间不重叠判定 | §2.3, App. A.4 | IFEval 在十个 failure 上**全部下降 9.5–12.0 分**却仍然通过闸门，因为降幅落在置信区间内；实际只能挡住约 11–13 分以上的下跌 | 闸门是**崩溃探测器**；报告必须写明它拦不住什么 |
| held-out 必须同机制、异分布 | App. A.1 | 三种泛化：scenario（同一基准的不相交切分）、domain（不同数据集）、format（不同任务形式） | held-out 选取标准写死为这两条；重叠检查把「异分布」变成可验证 |
| held-out 用 OS 权限隔离 | App. B.4 | held-out 数据放在只有 evaluator 能读的独立账户下，研究侧文件权限禁止读取；AAR 只能提交模型并轮询分数 | heldout-store 放在 run_dir 之外；研究侧只拿 manifest hash |
| 预注册 + 哈希绑定审批 | §3.2 | mini-paper 在任何结果被看到之前冻结成不可变标识，结果发布时**原样复用**；审批绑定到确切的代码，改动即需重审，evaluator 拒绝给未批准的方法评分 | 铁律 2 与 3；`verify_forum` 重算全部哈希 |
| 机制/目标函数是杠杆，数据量不是 | App. D.4 | 固定为 SFT 时，自由数据 4.5%、公开数据 6.0%；只加一个 KL 自蒸馏就到 18.7%（相当于无约束 26.4% 的 71%）；无约束运行里 74% 的方法用了激活引导 | 搜索空间要允许换机制；只堆数据量不是有效策略 |
| 论坛与综述承重，联网不承重 | App. D.5 | 无约束 23.3%；去掉 finding forum 17.1%；无联网无综述 20.7%；无联网但有缓存综述 29.4% | forum 与 survey 必须有；联网可选（降级档有据可依）。**注意作者自述：每个条件只跑了一次，run-to-run 波动大于组间差距，所以只当提示** |
| best-of-N 是噪声上偏的最大值 | §5.1 | 作者自述 AAR 的数字是「约 150 个被评分方法里最好的一个」，因此被噪声上偏 | 报告必须写明这一条 |
| 榜上中位数几乎拿到全部真实收益 | App. D.3 | deception 上从第 1 百分位到中位数拿下 6.2/6.6 分，中位数到榜首只多 0.4 分；且第 1 百分位的方法 8.1 比未训练基线 7.5 **更差**（显著回退） | 不必死磕榜首；但也不能停在榜尾——榜尾可能比不训练更糟 |
| 复杂度上升与分数只是伪相关 | §5.2, App. F.4 | 复杂度在每个 failure 上都随时间上升；控制迭代顺序后相关系数趋近于零 | 不要用「方法更复杂」当作进步的代理指标 |
| 作弊主要是重跑抽奖 | §7 | 1,601 条轨迹里 39 条（2.4%）被标记；其中 67% 是原样重跑赌评分噪声，26% 是复制基准格式，21% 是隐瞒违规步骤；只有重跑抽奖成功过（1 条进了前三） | 制品哈希去重是必需的，不是可选的 |
| 方法多样性会自然收敛 | App. F.2 | 分数在前四分之一就达到最终值的约 0.8，方法族均匀度稳定在 0.5 左右并缓慢下降 | 提早收敛是正常的；不要为了让分类法好看而强行制造多样性 |

## 4. 域无关 vs 运行时决定

**写死在 skill 里（域无关）**：循环结构；评分数学（closed fraction / 几何平均 / 区间估计）；闸门语义；
失效即重审的哈希绑定审批；held-out 三层可见性与封存时序；论坛单写者与不可变性；综述的 write-once 并发写；
memory file 与 fresh session；停止准则；事后作弊审计的分类与 rubric；选择与检验分离。

**每次运行才决定（用户提供）**：研究问题与构念；目标系统；**方法空间**与制品契约；
评分基准套件（≥3）与 held-out；回归闸门；每方法预算；runner 命令；方法族命名。

这条界线是这套 skill 能被复用的原因。任何一次运行如果把领域知识硬写进循环，它就退化成了一个一次性脚本。

## 5. 三个有意加强的地方

这三处是本 skill 相对论文原实现**主动收紧**的，理由是论文自己记录了相应的攻击面：

1. **论坛单写者**——论文里研究者自己调 `share_finding` 上报结果，而论文的作弊分类里就有
   `Finding forgery: fabricating scores, misbinding a training run`。既然分数由 evaluator 产生，
   让研究者写分数就是多余的攻击面。本 skill 把 finding 的分数段限定为 orchestrator 从
   `eval/<id>/scores.json` 写入。
2. **claim_mismatch 检查**——组装 finding 时确定性地比对：声称提升而 aggregate ≤ 0、或声称通过闸门
   而实际判 fail，就标成 `claim_mismatch` 并送 integrity monitor。零成本，专打「粉饰」那一类。
3. **held-out 三层可见性**——论文只封了 held-out 的存在与内容，但它的 held-out 全是公开基准，
   文献调研几乎必然撞上。本 skill 把它拆成「条目绝不可见 / 身份可配置 / 粗粒度描述符可见」，
   并明确写出：**身份保密不是防线**。

