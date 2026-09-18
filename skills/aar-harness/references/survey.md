# survey.md — 文献综述：分工、检索 playbook 与并发写

## 1. 触发与输入闸门

综述的输入是 **01-frame 早期产出的 `construct.json`**（构念 + 方法空间 + 被评分基准名单），
不是完整的 run_config。因此 **03-survey 可以与 02-instrument 并行启动**——
综述只依赖构念，不依赖可跑的闭环。论文没这么做，只是因为它的评测环境是现成的。

明确**不给** librarian：held-out 的身份与内容。综述可以点名公开基准（论文的 briefing 也点名被评分基准），
但**不得描述 held-out 的条目内容**。

## 2. 四个 librarian 并行分工（论文 App. B.1 的域无关化）

| # | 子领域 | 论文对应 | 目标条目数 |
|---|---|---|---|
| L1 | 通用方法族：该干预面上已有的技术族 | 偏好优化、激活引导、unlearning | 20–40 |
| L2 | 问题专属：构念的经典论文、数据集、基准、既有 SOTA 及其已知缺陷 | 该 failure 的 canonical papers / datasets / benchmarks | 20–40 |
| L3 | 机制与测量：问题为何产生，以及主流评测的陷阱 | training-time causes + pitfalls of usual metrics | 10–20 |
| L4 | 邻近与最新：近 12 个月相关工作 + 可迁移的其他领域技术 | recent adjacent work | 10–20 |

论文的 librarian 是 4 个并行 agent，每个覆盖一个子领域，各自检索、读论文、
把每个方法写成**一条结构化条目**（复现指南而非引用），并且**先读 survey 再写**以免互相重复。
综述全程存活：任何研究者随时可读、可自行检索、可在爬山过程中追加条目。

## 3. 检索源（本机实测状态）

| 源 | 用途 | Key | 实测 |
|---|---|---|---|
| arXiv API（`export.arxiv.org/api/query`） | 预印本；字段前缀 `ti:` `abs:` `au:` `cat:`；可按提交日期排序；**限速约 5s/请求，且不要并行** | 免 | ✓ 可用；**被限流时返回 HTTP 406 而不是 429**，连接器按限流处理并长退避重试 |
| OpenAlex（`api.openalex.org/works`） | 全覆盖书目、引用计数、`cited_by` 前向引用、filter 语法 | 免（带 mailto 进 polite pool） | ✓ 200 |
| Crossref（`api.crossref.org/works`） | DOI 回填、元数据、许可 | 免 | ✓ 200 |
| Semantic Scholar Graph | `/paper/search`、`/search/bulk`、`/citations`、`/references`、Recommendations | **强烈建议配 key** | ✗ **429 匿名被限流** |
| HuggingFace Hub API（`huggingface.co/api/datasets?search=`） | 数据集 / 基准发现 | 免 | ✓ 200 |
| HF datasets-server `/search` | 数据集内 BM25 全文检索 → 污染探测 | 免（大库建议 token） | ⚠ 较慢，需长超时，且只支持有 Parquet 导出的数据集 |
| `gh` CLI（`gh search code` / `gh search repos`） | 代码与仓库检索、官方实现、awesome 列表 | 需登录 | ✓ 可用（含 repo scope） |
| PaperQA2（Future-House/paper-qa） | 全文精读问答（L3 用） | LLM key | 可选加速档 |
| paper-search-mcp（openags） | 一站式 20+ 源并发 + 去重 + 下载回退 | 可选 | 可选加速档，**不是依赖** |
| Papers with Code | — | — | **已关闭**，不可作为基准来源 |

本机网络经本地代理（`http_proxy` / `https_proxy` 环境变量），连接器已显式尊重代理设置。
`python scripts/aar.py sources probe` 会逐源探测并给出 `full / basic / offline` 降级档，
结果写进 run_config 的 `retrieval` 字段，最终报告会复述。

## 4. 四个 librarian 的查询配方

**L1 通用方法族**

1. 用 OpenAlex / S2 按被引数 + 综述类型筛出 2–3 篇权威综述作种子；
2. 主检索：arXiv `cat:` 分类 + `abs:` 术语；OpenAlex `filter=from_publication_date:2023-01-01,cited_by_count:>20`；
3. 对种子做**后向**（references）与**前向**（citations）滚雪球；
4. 产出方法族骨架——它就是后面 `taxonomy.json` 的底稿。

**L2 问题专属**

1. 用 `construct.json` 的构念关键词**与**被评分基准名分别检索，arXiv / OpenAlex / Crossref 三源并发（各 1/3 配额）；
2. `huggingface.co/api/datasets?search=` 找数据集与基准实体；`gh search repos` / `gh search code` 找官方实现；
3. 对每个基准额外查一次 `<benchmark> critique | pitfall | contamination | limitations`，把已知缺陷一并入库。

**L3 机制与测量**

1. 取 L1 / L2 里被引最高的机制类论文做**全文精读**（PaperQA2 或下载 PDF），抽取因果解释、失效条件、关键设计选择；
2. 专门检索评测陷阱：`benchmark contamination`、`construct validity`、`leaderboard overfitting`、`metric gaming`；
3. 产出每条机制的 `helps_when` / `fails_when` 与一份测量陷阱清单。

**L4 邻近与最新**

1. 时间过滤：`from_publication_date:<今天减 12 个月>`；arXiv 按 `SubmittedDate` 排序；
2. 对 L2 里最新的 3 篇做**前向引用**滚雪球；
3. OpenReview / workshop / tech report；`gh search repos --created` 找新仓库。

## 5. 通用检索协议（每个 librarian 都走）

1. **查询构造**：构念 → 术语集（同义词 + 上下位词 + 领域惯用缩写）→ 布尔展开；
   **每条查询串都写进 `survey/queries.jsonl`**（含时间与命中数），保证可复现。
2. **去重**：DOI → arXiv id → 归一化标题（小写、去标点、折叠空白）；跨源合并保留最全元数据。
3. **三筛**：标题/摘要筛（按纳入排除标准）→ 全文可得性筛 → 精读筛；
   按 **PRISMA 式计数**（identified / after title-abstract screen / included）写在 `survey.md` 头部。
   方法学依据：PRISMA 2020 及其 **living systematic review 扩展（PRISMA-LSR, BMJ 2024）**——
   后者正是「综述要活着、要能更新」这件事的标准参考。
4. **配额**：每源设上限，防止单一源支配；每 librarian 的目标条目数见第 2 节。
5. **饱和度停止**：连续 k 条查询的新增条目率低于阈值即停（k 与阈值写进 run_config）。
6. **速率与礼貌**：arXiv 约 3s/请求；OpenAlex 带 `mailto` 进 polite pool；
   S2 匿名 429 时改用 OpenAlex 的 `cited_by` 前向引用 + Crossref 后向引用补齐。
7. **记账**：每条目记录来源查询串、检索时间与许可。

## 6. 条目 schema（见 contracts.md 第 10 节）

核心是：它不是一条引用，而是一份**复现指南**。
`reproduction_recipe.ordered_steps` 加 `hyperparameters` 是必填的，
因为研究者的下一步是「照着做出来并改进」，而不是「知道有这么个东西」。

## 7. 并发写策略（与论坛刻意不同）

论坛需要全局定序（排行榜），所以是单写者 + 锁。
综述是**每条目一个 write-once 文件**，天然无冲突，多个 librarian 与研究者可以并发追加。
`survey.md` 与 `survey/index.json` 是**派生视图**，在 `survey/.index.lock` 下整体重建，
所以并发追加不会写出一份过期的索引。

原则一句话：**定序类状态单写者，写一次类内容允许并发。**

## 8. live 更新

研究者在 `submissions/<id>.json` 里可以带 `survey_additions[]`，orchestrator 校验 schema 后落成条目。
所以综述在爬山过程中会继续长大——这正是论文描述的形态（任何 AAR 随时可读、可检索、可追加）。

## 9. 污染探测复用

HF datasets-server 的 BM25 全文检索 + `gh search code` 用来查「基准条目是否已经出现在公开语料或仓库里」。
**同一套能力服务两处**：`benchmark-sourcing.md` 的污染检查，以及 `heldout verify` 的重叠检查。

## 10. 降级阶梯

| 档 | 条件 | 行为 |
|---|---|---|
| 全量 | 内置连接器 + S2 key（或选用 paper-search-mcp） | 多源并发 + 滚雪球 + 全文精读 |
| 基本（默认） | 只有免 key 的源 | arXiv / OpenAlex / Crossref / HF / gh，够用 |
| 无 S2 key | — | OpenAlex `cited_by` 前向 + Crossref 后向替代引用功能 |
| 离线 | 无联网 | 用模型自身知识 + 用户提供的本地语料构建综述，**报告里显式声明离线综述** |
| 无全文 | 拿不到 PDF | 退到仅摘要级筛选，声明覆盖度上限 |

论文 App. D.5 支持这个降级是有意义的而不是归零：在同样没有联网的两臂之间，
有缓存综述的一臂是 29.4%，没有综述的一臂是 20.7%。**承重的是综述本身，联网只是加速。**
（作者标注单次运行，仅供参考。）

## 11. 退出判据

1. `taxonomy.json` 产出 7–10 个方法族（带名字、定义、代表条目）；
2. survey 在每个被评分基准上覆盖若干候选方法族；
3. 触发饱和度停止，或达到条目配额。

任何一条不满足，判为「文献基础不足」，要么加预算重跑，要么在报告里降级声明。

