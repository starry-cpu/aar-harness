# 03-survey — 四个 librarian 并行，产出活综述与分类法

## 目的

在研究者提案之前，把该领域的**方法族、已有 SOTA、机制解释、评测陷阱**变成一份结构化、可检索、
可持续追加的共享综述，并给出 7–10 个方法族的分类法，作为候选方法的骨架。
论文 App. D.5：无网无综述 20.7%，无网但有缓存综述 29.4%——承重的是综述本身，联网只是加速。

## 输入

- `<run_dir>/construct.json`（01-frame 早期产出）：`question` / `construct` / `method_space` /
  `scored_benchmarks` / `method_families_seed` / `held_out_note`。
- `run_config.retrieval.tier`（full / basic / offline，00-intake 探测得到）。
- 可选：用户提供的本地 PDF / 语料目录。
- **不给** librarian：held-out 的身份与条目；唯一允许写进研究侧的 held-out 信息是 `construct.json.held_out_note`。

**为什么能与 02-instrument 并行**：综述只依赖构念，不依赖可跑的闭环；held-out 已在 01-frame 封存，
「先读综述再挑 held-out」的污染路径已经关闭。两条工作流唯一共享的写面是 `survey/entries/`，而它是 write-once 的。

## 产出

- `survey/entries/<slug>.json`：一条一个 write-once 条目（方法名 / 族 / 问题与思路 / 机制 / 复现配方 / 出处 / 已知失效模式）。
- `survey/queries.jsonl`：每条查询串 + 时间 + 命中数，保证综述可复现。
- `survey/prisma.json`：`identified` / `screened` / `included` 三个计数。
- `survey.md` 与 `survey/index.json`：派生视图，只能由 `aar.py survey index` 重建。
- `<run_dir>/taxonomy.json`：7–10 个方法族（名字、定义、代表条目）。

## 程序

1. **验输入闸门**：`read` `<run_dir>/construct.json` 确认六个字段齐全；`python scripts/aar.py heldout manifest --store <store>`
   只回版本 / items_hash / 条数 / 泛化类型 / 许可五项（条目会被剥掉）。construct 缺字段先补，别让 librarian 拿半份闸门开工。
2. **定配额与饱和度参数**：L1 20–40、L2 20–40、L3 10–20、L4 10–20 条（`references/prompts.md` 的四个模板里已写死）；
   饱和度规则（`prompts.md` 默认「最近 3 轮查询每轮新增 < 5 条即停」）同步写进 `run_config.survey`，改了就两边一起改。
3. **并发派四个 librarian**：在一个 `run_code` 程序里同时调 4 次 `subagent`，prompt 用 `references/prompts.md` 的四个子领域模板：
   L1 通用方法族、L2 问题专属（经典论文 / 数据集 / 基准 / 既有 SOTA 与缺陷）、L3 机制与测量（问题为何产生 + 评测陷阱）、
   L4 邻近与最新（近 12 个月 + 可迁移技术）。每个 prompt 自带 construct.json 全文、条目 schema、检索纪律（第 4–6 步）与自己
   的目标条目数。librarian 不是研究者：不接触 held-out、不写 `methods/`、不写论坛。
4. **接检索源**：先 `python scripts/aar.py sources probe`；日常用
   `python scripts/aar.py sources search --query "<query>" --source arxiv --source openalex --limit 5`；
   需要按源细控时用 `python scripts/lib/sources.py arxiv "<query>" 5`（子命令 `multi|arxiv|openalex|crossref|hf|gh`）。
   无 key 时 Semantic Scholar 会 429，用 OpenAlex 的 `cited_by` 前向 + Crossref 后向补齐引用；仍有缺口再补一次
   DSH 的 `web_search`，但必须把 URL 写进条目 `source`。
5. **每条查询立刻记账**（不要批量补记，中断就丢账）：`python scripts/aar.py survey log-query --run <run_dir> --entry @q.json`，
   `q.json` 形如 `{"query": "...", "source": "arxiv", "hits": 12}`，`log_query` 自动补 `at`；
   事后用 `python scripts/aar.py survey queries --run <run_dir>` 复核总数。
6. **写条目**：`python scripts/aar.py survey add --run <run_dir> --entry @entry.json`。代码级必需 `method_name` / `family` /
   `problem_and_idea` / `source`（至少 urls 或 year）；语义上 `reproduction_recipe.ordered_steps` 与 `hyperparameters` 必填——
   条目是复现指南，不是引用。去重键顺序 DOI → arXiv id → 归一化方法名；命中重复时返回 `{"added": false, "reason": "duplicate"}`，这不是错误。
7. **先读再写**：每个 librarian 开工时与每写完一批都读一次 `survey/index.json`（或跑 `survey index` 重建），
   避免四个 agent 撞同一批论文——论文的做法就是先读综述再写条目。
8. **重建派生视图并校验**：`python scripts/aar.py survey index --run <run_dir>`（在 `survey/.index.lock` 下整体重建
   `survey.md` 与 `index.json`），再 `python scripts/aar.py survey verify --run <run_dir>`；退出码 0 表示无 schema 缺失、无重复键。这两个文件禁止手改。
9. **PRISMA 计数**：把三筛结果写成 `<run_dir>/survey/prisma.json`，键名必须是 `identified` / `screened` / `included`；
   `survey index` 会把它们打进 `survey.md` 头部。写完再跑一次 index。
10. **饱和度停止**：按第 2 步的规则停；用 `survey queries` 的计数与 `survey add` 返回的 `added` 复核，停止时的轮次与正在跑的查询
    写进 `survey.md` 头部（prompts.md 的输出要求里点名要这两个）。达不到饱和度又没到配额 → 判「文献基础不足」，加预算重跑或降级声明。
11. **建 taxonomy.json**：以 L1 的方法族骨架起手，用 `survey/index.json` 的 `families` 分组收敛成 7–10 个族，
    每族给 `name` / `definition` / `representatives`（方法名列表）/ `entry_count`，用 write 工具写到 `<run_dir>/taxonomy.json`。
    族数偏多说明切得太细，合并同义族；偏少说明 L1 没跑出骨架，回补检索。
12. **边界检查**：综述可以点名**公开的被评分基准**（论文的 briefing 也点名），但不得描述 held-out 条目，也不得把条目文本、
    切分规则或 gold 写进任何研究侧文件。跑 `python scripts/aar.py heldout verify --store <store> --run <run_dir>`：
    它扫描 run_dir 下每个文件的泄漏，并对 held-out 条目与 suite 条目做 5-gram 重叠检查。命中就删文本重跑，直到 `ok: true`。
13. **离线降级路径**：`retrieval.tier = offline` 时用模型自身知识 + 用户提供的本地语料建综述，在 `survey.md` 头部显式声明
    「离线综述，覆盖度有限」；拿不到全文时退到仅摘要级三筛并声明覆盖度上限。降级不是跳过——有综述（29.4%）好过没综述（20.7%），
    且 `retrieval.tier` 会被最终报告复述。
14. **移交**：orchestrator 组装研究者 prompt 时只取 `survey.md` 的**前 4000 字符**，所以 PRISMA 计数、分类法、每族代表方法
    与已知的坑要写在文件开头，细节留在 `entries/` 里让研究者深读。

## 退出判据

- `python scripts/aar.py survey verify --run <run_dir>` 退出码 0（无 schema 缺失、无重复键）。
- `<run_dir>/taxonomy.json` 存在且族数在 7–10：
  `python -c "import json;print(len(json.load(open(r'<run_dir>/taxonomy.json',encoding='utf-8'))['families']))"`。
- `python scripts/aar.py survey queries --run <run_dir>` 的 count > 0，且与 `survey/queries.jsonl` 行数一致。
- `<run_dir>/survey/prisma.json` 含 `identified` / `screened` / `included` 三键。
- `python scripts/aar.py heldout verify --store <store> --run <run_dir>` 退出码 0。
- `python scripts/aar.py status --run <run_dir>` 的 `survey_entries` 已覆盖 `construct.json.scored_benchmarks` 的每个基准。

## 常见失败

- **四个 librarian 撞车。** 同一篇论文被写四遍，去重键会拦下三条但配额被浪费。让每个 librarian 开工先读 `survey/index.json` 并按 L1–L4 分工检索。
- **条目写成引用而不是复现指南。** 缺 `ordered_steps` / `hyperparameters`，研究者无法照着做，综述就白建了。提交前按条目 schema 逐字段过一遍。
- **查询不记账。** `queries.jsonl` 空着，综述不可复现，也判不了饱和度。检索完成立刻 `log-query`。
- **泄漏 held-out。** 把 held-out 条目文本或切分细节写进 `survey.md`、查询串或条目里，`heldout verify` 会报出文件路径；删掉再扫。
- **没网却当作有网。** 静默退化成模型记忆里的综述还不声明，读者会高估覆盖度。先把 `retrieval.tier` 与声明写进 `survey.md` 头部。
- **族数不在 7–10 就收工。** 分类法是 05-propose 排候选的骨架，族太粗会让方法扎堆、太细会让相似方法互不相认；合并或回补后再交。
