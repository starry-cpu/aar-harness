# heldout.md — held-out 的三层可见性、构建与封存

## 1. 先纠正一个层次混淆

论文的原话是 briefing **never mentions the held-out benchmark**，且研究侧**看不到任何基准样例**。
但论文的 held-out 全是公开基准（DeceptionBench、SummEdits、InjecAgent……），
librarian 调研该领域时几乎必然撞上它们的名字。

所以正确的规则不是「不许知道」，而是分层：

| 层 | 可见性 | 理由 |
|---|---|---|
| items / gold / scorer | **绝不可见（硬）** | 一旦可见就是训练数据污染，等同作弊分类里的 `Benchmark-data use` |
| 身份（名字） | 可配置：`sealed`（论文默认）/ `named` | 公开基准的名字很难真正保密；装不知道不是安全 |
| 粗粒度描述符 | 可见：泛化类型（scenario / domain / format）+ 它探测的机制 | 否则研究者是盲优化；而 held-out 的设计前提本就是「同机制、异分布」，机制必须可被瞄准 |

`named` 只在 held-out 是**独立公开基准**时成立。如果 held-out 是**同一基准的不相交切分**
（论文在没有独立基准时的做法），名字毫无意义，**切分本身**才是秘密，必须走下面 b 或 c 的路径。

## 2. 三种构建来源（按优先级）

**a. 用户提供 / 用户确认（首选）**

skill 给的不是清单，而是**选择标准 + 候选模板**，让用户挑或确认。
这直接对应「评分基准由用户的场景提供」这条设计决策。

**b. 隔离的 curator 会话（用户交不出、需要切分或装配时）**

典型场景：把一个公开基准切成不相交的 scenario 子集、按 domain 切两半、
或者把模板生成的集合按底层场景分组。做法：

- orchestrator 派生一个**专用会话**，它的 prompt 里只有选择标准与公开源清单，
  **没有** survey、forum 或任何研究者上下文；
- 它的产物**只写进 heldout-store**，**不回写研究侧任何文件**（连构建日志都不进 run_dir）；
- 研究侧唯一能看到的是**不含条目的 manifest**。

**c. 评测时现场生成（最强）**

不构建固定条目，而是构建 **seed + rubric**，由 auditor 在**评测时发明**新场景。
论文的 Petri 审计就是这一形态：seed 说明机制、基线和 judge 维度，
并指示 auditor 现场发明新场景而不是复用已知模板。

这条路径的优势是决定性的：**条目在评测发生之前不存在，所以没有任何角色需要被信任去保守秘密**。
泄漏问题从「靠权限和纪律守」变成「结构上不可能」。
当「同机制」但找不到独立数据集时，这是**首选**而不是次选。

## 3. 时间顺序（否则存在污染路径）

    01-frame:
      construct.json（构念 + 方法空间 + 被评分基准名单）        <- 提前产出
       -> held-out 选定 / 构建（用户 or curator or seed+rubric）
       -> 封存进 <workspace>/heldout-store/ + 写 manifest（不含条目）
       -> 冻结 run_config.json
    02-instrument  ┐
                   ├─ 并行启动（held-out 已封存，二者互不依赖）
    03-survey      ┘

held-out **必须在综述与任何提案之前封存**。否则会出现「先读综述、再挑 held-out」的污染路径：
那样选出来的 held-out 已经不是没见过的了。

## 4. 两条选取标准（论文 App. A.1）

1. **同机制**：与爬山基准测的是同一个机制。一个构念可能由几种不同机制造成，
   对其中一种的修复不一定迁移到另一种。held-out 要测的是「修好了会不会泛化出去」，
   而不是「它是不是恰好也修好了另一个问题」。
2. **异分布**：来自不同领域或全新场景，这样方法不能靠记住爬山基准的分布来通过。

三类泛化，跑完要标明是哪一类：

| 类型 | 含义 | 论文例子 |
|---|---|---|
| scenario | 同一基准的不相交切分 | power seeking 用 MACHIAVELLI 的 held-out games |
| domain | 不同数据集 | hallucination 用 SummEdits |
| format | 不同任务形式 | prompt injection 用 InjecAgent 的 agentic 设定 |

## 5. 不靠信任，靠可检查

    python scripts/aar.py heldout manifest --store <store>              # 只看脱敏视图
    python scripts/aar.py heldout verify --store <store> --run <run>    # 泄漏扫描 + 重叠检查

`heldout verify` 做两件事：

1. **泄漏扫描**：把每条 held-out 条目的文本归一化后，扫描 run_dir 下的**每个文件**，
   确认它从未出现在研究侧。命中就报出具体文件路径。
2. **重叠检查**：用 5-gram Jaccard 比较 held-out 条目与 scoring 基准条目，
   任何重叠都判定「异分布」不成立并要求重建。这把 curator 的一句声称变成**可验证**的性质。

第三件事由 monitor 与审计承担：paper-monitor 在发布前扫 survey / forum / briefing 的泄漏；
integrity monitor 扫轨迹的 `Held-out peek` 与 `Benchmark-data use` 两类。

## 6. 保密强度排序与诚实声明

**结构保密（评测时现场生成）> 权限保密（ACL + 单向墙）> 无知保密（封住名字）**。

第三种基本是幻觉，不作为主要防线。这一条必须写进最终报告的诚实声明，
因为读者很容易把「held-out 保密」理解成比实际更强的保证。

Windows 单用户环境下如果建不起第二个运行身份，ACL 隔离会退化成
「独立目录 + verify 检查 + 轨迹审计」三件套；这种降级要在报告里声明。

