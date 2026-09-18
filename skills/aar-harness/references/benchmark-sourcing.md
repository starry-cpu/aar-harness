# 基准获取（benchmark sourcing）

> 用在 step 01-frame。输入 = 用户场景的构念与约束；输出 = 一套可评分的 benchmark suite（scored / gate / held-out）+ 许可与污染记录 + 每条入选基准的来源 query。
> 论文对应：Sec. 2.1（三种角色、三种 scorer 类型）、Appendix A.1（held-out 两条判据）、A.3（入选数值门槛）、A.5（人工验证协议与降级代理）、A.6（Petri 审计）。
> 本文件只管「基准从哪来、怎么验、不合格怎么降级」。评分数学见 scoring.md，封存与隔离见 heldout.md。

## 1. 提问清单（intake；全部答完才允许动检索）

任何一项留空就停在这里问用户，不要用默认值填。

- **construct（目标构念）**：要改的失败/行为是什么？写成一句可判定的行为定义（「在压力下改口」可以，「不够安全」不可以）。论文的十个 failure 每个都有一句「the behavior we study」（Table 1），照这个粒度写。
- **target system**：改的是哪个系统（模型 id / checkpoint / 训练流水线）？能不能固定种子重训同一个起点？跨尺寸迁移是否在范围内（Sec. 5.1 的 1.8×–4.7× 只对可复现的训练管线成立）？
- **intervention surface**：方法允许动什么、禁止动什么？论文的三条审批约束必须原样继承：不做自蒸馏、不动用任何 frontier model 产数据、不使用任何 benchmark/eval 数据（Sec. 3.2）。约束本身要写进 construct.json 并被 monitor 强制。
- **per-method budget**：一个方法允许多少 GPU 分钟 / 美元 / API 调用？固定预算才能比较（Sec. 3.1）。论文侧参考：AAR 推理成本约 $4/小时（Sec. 4）。
- **acceptable evaluation cost**：一次完整评测的墙钟上限与美元上限。论文的评测预算是 **约 30 分钟**（Appendix A.5）；用户的预算若显著小于它，A.5 的代理规则从「可选项」变成「必选项」。
- **LLM judge 是否允许**：允许哪几个 judge 模型？允不允许 judge 联网（涉及污染与 judge injection，Sec. 7）？judge 结论要不要人工抽检？不允许 judge 时只剩 rule-based / 人工两条路，直接影响降级档。
- **licence 与保密**：基准许可证是否允许本地缓存条目、是否允许把条目写进 run 目录、是否允许出现在报告里？用户数据的保密等级？held-out 能否公开命名（命名可以，条目不行，见 heldout.md）。
- **languages / domains 在范围内**：语言、领域、交互设定（single-turn / multi-turn / agentic）。三个异源基准必须在同一 construct 下覆盖不同 surface（Sec. 2.1）。

产出 = 一份打完勾的 intake 记录 + 检索源可用性探测结果（`python scripts/aar.py sources probe`）。

## 2. 检索策略（按顺序，命中即记 queries.jsonl）

顺序是有意的：越靠前信噪比越高、越容易拿到条目本体。每步的 query 串、来源、命中数写进 `<run_dir>/survey/queries.jsonl`（可复现要求）。

### 2.1 GitHub topic / code search（gh CLI；已验证）

- 状态：本机 `gh` 2.94.0，账号已认证，token scopes 含 `repo`，code search 与 repo search 均可用。
- 仓库面：`gh search repos --topic <topic> --limit 30 --json fullName,description,url,stargazersCount,updatedAt`
- 关键词面：`gh search repos "<query> topic:<topic>" --limit 30 --json fullName,description,url`
- 条目面（污染探测的主武器）：`gh search code "<benchmark 独有字符串>" --limit 20 --json repository,path,url`
- topic 名字要试同义词/单复数：`llm-evaluation` / `evaluation-harness` / `safety-benchmark` / `red-teaming` / `jailbreak` / `hallucination-detection`。
- 命中仓库之后必须打开看三件事：条目是否可直接下载、licence 是否允许使用、scorer 是代码还是人。
- harness 封装：`python scripts/lib/sources.py gh "<query>" <limit>`。

### 2.2 HuggingFace hub API 数据集检索

- 端点（canonical）：`https://huggingface.co/api/datasets?search=<query>&limit=<n>`。
- 这是 Papers with Code 关停之后事实上的「数据集/榜单索引」入口；同一 API 还能查到 dataset card、licence tag、lastModified（用来判断是否已随模型更新被吃进预训练）。
- 关键词面要覆盖：construct 词、失败名、任务名、已知基准名 + `benchmark`、`eval` 后缀。
- harness 封装：`python scripts/lib/sources.py hf "<query>" <limit>`。
- **可达性要先探测**：编写本文档的机器上 huggingface.co 与 datasets-server.huggingface.co 被网络策略拦住（TLS handshake 失败），gh 与 arXiv 正常。所以 HF 两步必须先跑 00-intake 的 probe，不可达时按 sources.py 的 tier 降档，并把「HF 路径未跑」写进 run report，不能默认它跑过了。

### 2.3 HuggingFace datasets-server 全文检索（BM25，污染探测用）

- 端点：`https://datasets-server.huggingface.co/search?dataset=<id>&config=<cfg>&split=<split>&query=<q>&offset=0&length=<≤100>`
- 语义：对已导出 Parquet 的数据集做 BM25 全文检索，返回带 row 位置的命中，用来判断「这条基准条目是否已经出现在公开语料里」。
- 限制（必须按限制来写脚本）：
  - **只有带 Parquet 导出的数据集被索引**；404/500 表示这条数据集不可这样检索，不是 query 写错。
  - **端点慢**：timeout 给 90 s 以上并带指数退避重试；不要用一个 10 s 超时把它判死。
  - 回退路径：直接读 Parquet。`https://huggingface.co/api/datasets/<id>/parquet` 拿文件清单 → 下载 → 本地建索引；或走 datasets-server 的 `/rows`、`/filter` 分页自己打分。
- harness 封装：`sources.py` 的 `hf_dataset_search_rows(dataset, config, split, query, offset, length, timeout=90)`。

### 2.4 论文侧检索（arXiv / OpenAlex / Crossref）

- arXiv Atom API（`export.arxiv.org/api/query`）：字段前缀 `ti: abs: au: cat: all:`；**必须节流 ≥3 s**（sources.py 内置）。
- OpenAlex：`api.openalex.org/works`，支持 filter/sort；最高产的雪球动作是**前向引用**（`filter=cites:<id>`）与后向引用。
- Crossref：DOI 回填、publisher 元数据、licence 字段；用来给候选基准找「官方出处与许可证」。
- Semantic Scholar Graph API（`api.semanticscholar.org/graph/v1/paper/search`）作为 OpenAlex 的替代引用图。
- 这一层的作用不是找基准本体，而是找**基准的出处论文**：很多基准的 licence、条目生成流程、scorer 细节只写在论文附录里，dataset card 上没有。
- harness 封装：`python scripts/lib/sources.py multi "<query>" <per-source-limit>`（自动跨源去重）。

### 2.5 awesome-lists

- `gh search repos "awesome <topic>" --limit 20`，再顺着 README 里的链接走。
- 命中率低于前四步，只用来补漏（尤其是「某个失败有哪些公认基准」这类领域共识）。
- 用完即止，不要把 awesome-list 当作权威来源；每个条目都要回到 2.1–2.4 去确认真实出处与 licence。

### 2.6 已关停来源（禁止使用）

- **Papers with Code 已关停，不得作为 leaderboard / dataset / SOTA 榜单来源**，也不要引用它作为「某基准存在」的证据。
- 替代：HuggingFace datasets + HuggingFace leaderboards（榜单面）、GitHub topics（实现面）、OpenAlex / Semantic Scholar（引用图与出处面）。

## 3. 适配度清单（每个候选都要过一遍）

逐行填，任何一行「不明」都不算通过。

| 字段 | 通过条件 | 不通过怎么办 |
|---|---|---|
| `construct_match` | 条目直接测 intake 里写下的那一条行为定义 | 换基准；不要靠换 prompt 硬套 |
| `mechanism_match` | 与已有基准测的是**同一机制**（Appendix A.1 的第一条：同一 failure 可以有多个机制，修一个不必然迁移） | 换基准或明确标注为「另一机制」的独立维度 |
| `scorer_type` | 明确是 rule-based / judge-based / trajectory-based（Sec. 2.1） | judge-based 必须写清 judge 模型与是否联网；trajectory-based 必须能拿到完整 transcript |
| `sample_count` | ≥25 个 scorable samples（A.3），目标 ~200 | 低于 25 只能降级为 gate 或 exploratory，不进几何平均 |
| `runtime` | 完整跑一遍在评测预算内（论文口径 ≈30 min，A.5） | 走 A.5 的代理规则（见第 4 节） |
| `licence` | 允许本地缓存 + 允许在报告里引用结论 | 只读不落盘，或换基准；licence 不明 = 不入选 |
| `contamination_risk` | 第 5 节的探测有结论 | 疑似污染 → 降到 R2（本地合成） |

## 4. 基准入选门槛（论文数值，逐条核）

**数值门槛（Appendix A.3，用于选 (failure, model) 对，逐基准核）**

- baseline **低于 ceiling 0.9**：基准不能已经接近饱和，要留出可爬的空间。
- baseline **高于 floor 0.05**：接近 0 的 baseline 更可能是「模型没这个能力」而不是「行为可被方法改」，测不出方法。
- **至少 25 个 scorable samples**：scorable = scorer 会给判定、且置信区间在其上计算的独立单元；模板生成的集合按其**底层 scenario** 计数，不按展开后的行数计数。样本量不够就分不开真实增益与噪声。
- 经验值：论文入选的基准平均约 **200 条 test examples**。
- 同一个 failure 下有多个模型可选时，选**空间最大**的那个作为 target（A.3）。

**人工验证协议（Appendix A.5；每个候选约 25 条原始样本 + 25 条模型回复）**

- `label_correctness`：gold label 在抽查样本上正确。
- `distinctiveness`：与同一 construct 下的其他基准相比，至少在 **domain / data-generation pipeline / scorer / interaction setting（single-turn / multi-turn / agentic）** 四项里有一项不同——否则等于把同一个构念测了好几遍。这也是几何平均能起作用的前提。
- `behavioral_validity`：抽查的模型回复确认基准**确实在诱发目标行为本身**，而不是模型看不懂评测设定（读懂题失败 ≠ 行为失败）。这是最容易被跳过、也最容易让整轮结论作废的一条。
- `runtime`：在评测预算内跑完（论文约 30 min）。跑不完时用**faithful proxy**：取有代表性的子样本；或当 scorer 依赖本地微调 judge（如 HarmBench）时，换更强的 API judge，并**验证它复现原始判定**。代理必须尽量保留原 prompt、原 judge、原 scorer。
- 另外记录论文的角色划分口径（Sec. 2.1）：每个 failure 的 hill-climbing 基准 **3–5 个**，另有一个 held-out（判据见 A.1：同机制 + 不同分布，泛化类型为 scenario / domain / format 之一），以及固定的 capability basket（MMLU / GSM8K / IFEval，seed 42，A.4）。

**门槛与几何平均的耦合**：任一 scored 基准的 closed fraction ≤ 0 就把聚合分钉成 0（Sec. 2.2 + 铁律 5）。所以入选阶段就要逐个基准算 baseline；算不出 baseline 的基准不许进 scored 集合。

## 5. 污染探测（contamination probe）

目标：回答「这条基准的条目是否已经出现在公开语料/公开仓库里」，并留下证据。

- **HF datasets-server BM25**：从每个基准取 8–20 条独有长短语（完整题干、罕见的模板句、独有的选项组合），逐条作为 `query` 打到 2.3 的 `/search`；记录命中数、命中的 dataset id、命中的 row 片段。命中 0 与命中 N 都是结果，都要记。
- **gh code search**：用同样的独有字符串 + 基准名 + 文件名（`items.jsonl`、`test_set.csv` 等）搜 `gh search code`；命中仓库要看是「引用/复现」还是「条目本体被复制」。
- **记录格式**（每条基准一行）：`{benchmark, probe_query, source, hits, hit_examples, verdict}`，verdict ∈ `clean` / `suspected` / `contaminated`。
- **判定与动作**：`suspected` 或 `contaminated` 时不许进 scored 集合；走第 6 节的降级阶梯（通常直接跳到 R2 本地合成），并把探测结论写进终局报告。
- **诚实边界**：这套探测只覆盖公开可达的语料与仓库，覆盖不到闭源训练集、私有语料、以及数据集导出时间之后的抓取。报告里要原样写明这一点，不能把 `clean` 读成「无污染」。

## 6. 降级阶梯（四档，按顺序，不许跳档）

- **R0 直接采用（adopt as-is）**：条目、scorer、协议原样使用。只能用于 licence 清白、第 3 节全过、第 5 节 `clean` 的基准。
- **R1 适配（adapt）**：取有代表性的子样本；或替换 judge。替换 judge 必须做**复现验证**——在原 scorer 与替代 scorer 都能跑的 N 条上比一致率，并把这个一致率写进 construct.json 与报告（A.5 对 HarmBench 用的是同一手法）。
- **R2 本地合成（synthesise locally）**：按同一 construct 与同一机制现场生成条目 + 写 scorer。保密强度最高（结构保密 > 权限保密 > 无知保密），但必须重新过第 4 节的 behavioral validity（现场生成的题目最容易「模型没读懂」而不是「行为失败」），并在报告里声明它是合成基准。
- **R3 半自动 + 人工评分（semi-automatic with human scoring）**：条目与执行自动，判定由人做。
  - 方法数上限：本 harness 约定 **一次 run ≤ 8 个方法**（再多人就评不动了）；超了就缩小构念或退回 R2。
  - 结论强度降级：只能给 direction-of-effect（「这个方法比 baseline 好/差」），**不得**报 closed fraction 的区间估计、不得声称泛化——人类逐条打分没有 scorer 的方差结构，几何平均与 Wilson 区间在这条路上不成立。
  - 报告里必须显式写「本轮含人工评分，结论强度受限」，并列出评分人、评分口径、抽样复核比例。
- **每次换挡都要落盘**：`{rung, from, reason, affected_benchmarks, effect_on_comparability}` 写进 run report；换挡之后不再与换挡前的分数直接比较。

## 7. 工作记录（run 期间必须持久化）

- 每条入选基准一条记录：
  - `role`：`scored`（进几何平均）/ `gate`（capability 或 over-refusal 闸门）/ `held-out`（封存，只留 manifest）。
  - `licence`：许可证 id + 是否允许再分发条目。
  - `item_file`：条目落盘的相对路径（held-out 的条目路径只写进 heldout-store 侧，不进 run 目录）。
  - `found_by`：发现它的那条 query（source + query string + hits），与 `survey/queries.jsonl` 对应。
  - `admission`：第 3、4、5 节各字段的实测值（baseline、sample_count、runtime、verdict）。
- 落点：`construct.json`（基准与角色）、`run_config.json`（预算与闸门）、`survey/queries.jsonl`（检索可复现）、`heldout-store/manifest.json`（held-out 只写元数据：版本、hash、item 数、泛化类型、licence）。
- 缺任何一项都算 baseline 未冻结，不许开跑研究者（见 steps/01-frame.md 的冻结门槛）。
