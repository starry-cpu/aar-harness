# 04-brief — briefing、硬规则、mini-paper 模板与 memory 骨架

## 目的

在**任何**研究者 session 启动之前，渲染研究侧的统一标准：briefing.md（五段简报）、rules.md（硬规则）、
mini-paper 模板（八段预注册骨架）、memory 骨架（每个研究者一份）。
K 个研究者是 fresh session，彼此不继承上下文，所以「优化什么、怎么算分、什么不许做」只能来自这四份文件。
渲染完必须自证：简报既不泄漏 held-out 身份，也不含任何基准样例。

## 输入

- `<run_dir>/construct.json`：构念一句话定义、`method_space`、`scored_benchmarks`、`held_out_note`（唯一允许引用的 held-out 信息）。
- `<run_dir>/run_config.json`（已冻结）：`method_contract`、`suite[]`（name/metric/baseline/optimum/source）、`gates[]`、`runner`、`stop`、`researchers`。
- held-out 的**脱敏视图**：`python scripts/aar.py heldout manifest --store <workspace>/heldout-store`，只回 version / items_hash / n_items / generalization / license / sealed。
- `<run_dir>/survey.md` 与 `<run_dir>/taxonomy.json`：方法族名字表；简报的改进提示只许引用族名，不许点名具体实现。
- 02-instrument 记录的**方差地板**（同一制品重复跑的分数波动），以及 `runner.seeds`。
- 本 skill 的 `references/integrity.md`（硬规则原文）与 `references/scoring.md`（closed fraction / 几何平均 / 零化规则）。

## 产出

- `<run_dir>/briefing.md`：五段——① 构念与目标系统；② 评分口径（closed fraction、几何平均、零化规则、噪声地板）；③ 被评分基准表（bench / metric / baseline / optimum + 每行一句改进提示）；④ held-out 声明；⑤ 硬规则指针。
- `<run_dir>/rules.md`：integrity.md 的七条通用硬规则逐条落地，每条附「检查方式」与「违反即拒批」的后果。
- `<run_dir>/mini-paper.template.md`：八段模板；研究者复制成 `methods/<method_id>/mini-paper.md` 后填写。
- `<run_dir>/memory/r1.md` … `memory/rK.md`（K = `run_config.researchers`）：骨架首行 `# memory: <researcher_id>`。

## 程序

1. 确认配置已冻结：`python scripts/aar.py status --run <run_dir>`，`frozen_at` 必须非空。未冻结就不要渲染简报，否则标准会在跑之间漂移。
2. 取 held-out 脱敏视图：`python scripts/aar.py heldout manifest --store <workspace>/heldout-store`。只允许 `generalization` 进简报；连 `items_hash` 都不写，它属于评测侧证据，不是研究侧输入。
3. 用 `read` 读 `construct.json` 与 `run_config.json`，再用 `write` 出 `briefing.md` 第 ① 段：照抄 `construct.construct` 与 `target_system`，不要改写措辞——改写等于换了一个构念。
4. ② 评分段写死公式与后果：`closed = (score - baseline) / (optimum - baseline)`；`aggregate = exp(mean(ln(closed_i)))` 仅当所有 `closed_i > 0`，否则 `aggregate = 0` 并由 `zeroed_by` 列出把总分钉成 0 的基准；再写一句「小于噪声地板的提升不算提升」。
5. ③ 基准表：为 `suite[]` 每行写 `name / metric / baseline / optimum / source`，追加一句改进提示。提示只许写「要动哪一类机制」（引用 `taxonomy.json` 的族名）+ 该基准离 optimum 的距离，不许写具体算法或超参。
6. ④ held-out 段只写三件事：存在一个封存在 `<run_dir>` 之外的工作负载；评测时由 evaluator 侧重测泛化；泛化类型 = `manifest.generalization` 里的 scenario / domain / format。不写名字、不写条目、不写文件路径。
7. ⑤ 用一行指向 `rules.md`（例如：见 rules.md，monitor 在审批前逐条读你的真实代码），并在简报开头写明后果：违反硬规则的方法不进入评分，只发一条 rejected 记录。
8. 用 `write` 出 `rules.md`：七条改成研究者能自查的祈使句——不读写/猜测 held-out 条目；不把基准条目或其格式搬进方法；不调用更强模型或外部 API；不改 runner、评分脚本、分数文件；一个方法一个制品且必须在固定预算内跑完；种子固定、禁止择优报告；不得手工撰写目标答案当数据。
9. 用 `write` 出 `mini-paper.template.md`，八段固定为 1 Title、2 Abstract、3 Motivation（含候选方法排序与淘汰理由）、4 Related Work（≥5 条可解析引用）、5 Mechanism、6 Data and Config（所有超参写死）、7 Predictions and Falsification（跑之前写死的预期与证伪条件）、8 Compliance Declarations（逐条对应 rules.md）。模板头部写明：本文件必须在任何 runner 调用之前完成，且不得包含任何分数。
10. 用 `write` 出 K 份 memory 骨架：首行 `# memory: <researcher_id>`，其余留空。orchestrator 的 `append_memory` 每轮追加 `## <method_id>` 与 `- status / - aggregate / - closed / - detail / - claim` 五行；研究者只追加读，不手改历史行。
11. 泄漏自检一（held-out 条目）：`python scripts/aar.py heldout verify --store <workspace>/heldout-store --run <run_dir>`，期望 `"ok": true` 且 `"leaks": []`。
12. 泄漏自检二（基准样例）：用 `pwsh` 把每个 `suite[].items_file` 的条目文本前 8 个词当 pattern，在 briefing.md / rules.md 上做 `Select-String -SimpleMatch`，有命中即样例泄漏。同一命令把 manifest.json 里除 generalization 之外的每个字符串值（`owner`、`public_name`、条目路径等）也扫一遍，命中即 held-out 身份泄漏：

        $cfg = Get-Content <run_dir>/run_config.json | ConvertFrom-Json
        $cfg.suite | ForEach-Object { if ($_.items_file) { (Get-Content $_.items_file | ConvertFrom-Json) | ForEach-Object { (($_.text -split ' ')[0..7] -join ' ') } } } | ForEach-Object { Select-String -Path <run_dir>/briefing.md,<run_dir>/rules.md -SimpleMatch -Pattern $_ }

13. 交给 05 之前记指纹：`python scripts/aar.py hash --path <run_dir>/briefing.md`，用 `write` 把结果落到 `<run_dir>/logs/briefing.sha256`。此后 briefing.md 与 rules.md 一律只读，中途改动会让前后两轮标准不一致。

## 退出判据

- 四份文件都在：`pwsh Test-Path <run_dir>/briefing.md,<run_dir>/rules.md,<run_dir>/mini-paper.template.md` 全为 True，且 `pwsh (Get-ChildItem <run_dir>/memory/*.md).Count` 等于 `run_config.researchers`。
- `python scripts/aar.py heldout verify --store <workspace>/heldout-store --run <run_dir>` 输出 `"ok": true`。
- briefing.md 五个二级标题齐全，且基准表数据行数等于 `run_config.suite` 的长度：`pwsh (Select-String -Path <run_dir>/briefing.md -Pattern '^\|').Count - 2`（减去表头与分隔行）。
- 第 12 步的 `Select-String` 零命中（pwsh 无输出）；`<run_dir>/logs/briefing.sha256` 存在。

## 常见失败

- 简报里写了 held-out 的名字或一条样例 → `heldout verify` 报 `leaks`，泛化结论作废；删掉除 `generalization` 类型外的全部描述，重跑 verify。
- 基准表漏 `optimum`，或写成与 baseline 相等 → `aar.py score` 抛 `optimum must exceed baseline`，这一轮跑不出分；照抄 `run_config.suite[i].optimum`。
- 改进提示写成具体算法或超参 → 简报变成答案清单，K 个研究者的提案同质化；提示只写机制族与差距。
- 只在简报里写「见 rules.md」却没渲染 rules.md → monitor 拒批时研究者无从自查；两份必须同批产出。
- memory 骨架缺失，或被写成整段历史 → 第一轮研究者读不到锚点，或读到未经 orchestrator 记录的伪历史；骨架只放首行标题。
- 渲染完又回头改简报 → 前后两轮标准不一致，且与第 13 步记录的哈希不符；要改就整步重跑并声明此前提案作废。
