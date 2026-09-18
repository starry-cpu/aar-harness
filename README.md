# aar-harness

**自动化研究 harness（automated research harness）**，一个 Claude Code / DSH skill。

给定一个有可测评分标准的研究问题，它并行跑 K 个 AI 研究者，反复执行
「提案 → 预注册 → 监控审批 → 执行 → 评分 → 上榜 → 迭代」，产出带**泛化验证**、
**作弊审计**、**哈希可追溯证据链**的结论。

**域无关**：评分基准、方法空间、回归闸门全部由你在使用时提供，skill 本身不内置任何领域基准。

实现对齐论文 *Automated Researchers Can Reliably Mitigate Alignment Failures*
(Chen, Wen, Kirchner, 2026) 的 AAR harness，并做了三处有意加强：**论坛单写者**、
**预注册哈希绑定**、**held-out 条目硬隔离**。

> **适用前提**：存在可自动闭合的评分回路（方法进 → 分数出）。
> 不适用于：没有可测标准的研究、纯定性综述、无法在固定预算内程序化执行的方法。

## 装到 DSH

这是**唯一在本机被完整验证过的**安装路线（skill 本体 43 个文件全部到位，测试全绿）。

```powershell
git clone https://github.com/starry-cpu/aar-harness
pwsh -File aar-harness/skills/aar-harness/install.ps1 -Global -RunTests
```

- `-Global` 把 skill 镜像到 `$env:USERPROFILE\.agents\skills\aar-harness`，也就是 DSH 的 skill 扫描根。
- `-RunTests` 会先校验 21 个必需文件、SKILL.md frontmatter 与目录名一致，清掉 `__pycache__`，
  再跑 57 个单元测试。

装完**新开一个 DSH 会话**。skill catalog 是会话启动时扫描的，热装不生效。

也可以不带参数就地校验：

```powershell
pwsh -File skills/aar-harness/install.ps1 -RunTests
```

## 装到 Claude Code

```
/plugin marketplace add starry-cpu/aar-harness
/plugin install aar-harness@aar-harness
```

本仓库同时是一个自托管 marketplace（`.claude-plugin/marketplace.json`，`source: "./"`），
插件内容就在仓库根，skill 在 `skills/aar-harness/`。

已在本机 Claude Code 2.1.175 实测：安装后 `claude plugin list` 显示 `Status: √ enabled`，
`claude plugin details` 显示 `Skills (1) aar-harness`，插件缓存
（`~/.claude/plugins/cache/aar-harness/`）里 `references/`（22 个文件）与 `scripts/`（19 个文件）**完整**。
仓库源、插件缓存、DSH 全局安装三处逐文件比对 43/43 一致。

### 升级

```bash
claude plugin marketplace update aar-harness
claude plugin update aar-harness@aar-harness      # 必须带 @marketplace 后缀
```

**`@marketplace` 后缀不能省。** 实测 `claude plugin update aar-harness`（不带后缀）会报
`× Plugin "aar-harness" not found`，即使 `claude plugin list` 里明明写着
`aar-harness@aar-harness`。升级后要重启会话才生效，旧版本目录会留在插件缓存里。

> **注意：这条路线不会把 skill 装进 DSH 的 skills 根。** 实测安装后
> `~/.agents/skills/aar-harness` 与 `~/.claude/skills/aar-harness` **都不存在**，
> `~/.agents/.skill-lock.json` 里也没有 `aar-harness` 条目——插件只落在
> `~/.claude/plugins/cache/`。所以**要让 DSH 用上它，请走上面的手动路线**
> （`install.ps1 -Global`）。Claude Code 与 DSH 是两条落点独立的安装路线。

> **运行前提：standard / full 档需要 PATH 上有 `dsh`。** skill 的自动编排是 DSH 原生的——
> `orchestrator.py` 用 `dsh --profile headless` spawn 每一个研究者会话，`review.py` 与
> `lib/agent_run.py` 的 judge 会话同样先 `shutil.which("dsh")`，找不到就抛
> `dsh CLI not found on PATH`。只装了 Claude Code 的机器上，插件照常安装、skill 照常被发现
> （名字是 `aar-harness:aar-harness`，Claude Code 会给插件 skill 加命名空间），但**只能跑 light 档**
> ——light 档由主 agent 直接开 subagent，不 spawn `dsh`。

## 怎么用

主入口是 [`skills/aar-harness/SKILL.md`](skills/aar-harness/SKILL.md)。它会先让你回答三个问题
——**可测吗 / 可闭合吗 / 有异源基准吗**——三个都答得上才启动。

### 三档规模

| 档 | 研究者 | 执行载体 | 典型规模 |
|---|---|---|---|
| light | 主 agent 直接开 2–4 个 subagent | pwsh 前台/后台 | 1–3 小时 / 20–50 个方法 |
| standard | orchestrator 进程 spawn `dsh --profile headless` | orchestrator 调 runner | 8–24 小时 / ~100 个方法 |
| full | 同上，加持久化与断点续跑 | 同上 | 数天 / 200+ 个方法 |

三档共用同一套 run 目录、契约、评分与审计脚本，档位只改变「谁来跑研究者」和「跑多久」。

### 十二条步骤

| # | 步骤 | 关键产出 |
|---|---|---|
| 00 | intake | run_config 草稿 + 闭环等级 + 检索源可用性探测 |
| 01 | frame | construct.json；基准获取与校验；**held-out 选定/构建/封存**；冻结 run_config |
| 02 | instrument | runner + evaluator + 制品契约 + 隔离 + 确定性；方差冒烟测试 |
| 03 | survey | librarian 并行 → survey/entries + taxonomy.json |
| 04 | brief | briefing.md + rules.md + mini-paper 模板 |
| 05 | propose | 研究者单轮：读 → 检索 → 排候选 → 预注册 → 产出制品 |
| 06 | review | 双 monitor → approvals 绑定 artifact hash |
| 07 | run-evaluate | 沙箱执行 → 评分 → 闸门 → eval/ 落盘 |
| 08 | publish | finding 发布（单写者）+ 排行榜重建 |
| 09 | orchestrate | K 路并行、wall-clock/plateau 停止、失败记账 |
| 10 | verify | 选择规则 + never-selected-on 测试 + heldout verify |
| 11 | report | 终局报告 + 可读性包 + 诚实声明 |

**加载协议**：一次只读一个 step 文件，读完就执行，执行完再读下一个。这是刻意设计——把 12 个
step 文件一次性读进来会挤掉真正需要的工作记忆。

### 先看示例

[`examples/sqlite-index/`](examples/sqlite-index/) 是一次真实运行的**领域侧代码**，用来参照
「一个真域该怎么写 `world.py`（造域）、`runner.py`（跑方法）、`frame.py`（钉基准与闸门）」。

它**只含框架搭法，不含运行数据**：`run/` 与 `heldout-store/` 已被排除，详见该目录的 README。

### 跑完之后去哪看

每次运行收尾会**自动渲染观测台**——论坛、排行榜、监控矩阵与完整性状态合成一页 HTML：

    <run>/reports/dashboard.html

论坛本身是文件式的哈希绑定记录库（不是聊天室）。人类可读的原文在
`<run>/forum/findings/*.md`，每条 finding 一个文件，带分数表与闸门表。
`reports/final.md` 末尾有一节 `where to read this run`，把这次运行的每个读面列成绝对路径。

任何时候都可以重新渲染或起实时页：

    python skills/aar-harness/scripts/dashboard.py render --run <run>
    python skills/aar-harness/scripts/dashboard.py serve  --run <run>   # 127.0.0.1:8787

> `aar.py forum digest` **不是给人看的**：它的输出被不可信同伴哨兵包着，因为那是注入
> 研究者 prompt 的防提示注入包装。

## 依赖

无第三方依赖：脚本全部是 Python 标准库，需要 Python 3 与 PowerShell 7（`pwsh`）。
观测台 dashboard 是单页静态产物，不发任何网络请求，不引 CDN。

## 仓库结构

```
.claude-plugin/plugin.json        插件清单
.claude-plugin/marketplace.json   自托管 marketplace 清单
skills/aar-harness/               skill 本体（43 文件）
  SKILL.md                        入口：三档 + 12 步 + 铁律 + 脚本速查
  install.ps1                     安装/校验：layout + frontmatter + 单测 + 可选 -Global 镜像
  references/                     10 个机制文档 + steps/ 下 12 个步骤文件
  scripts/                        aar.py / orchestrator.py / review.py / dashboard.py
                                  + lib/ + dashboard/ + tests/ + toy/
examples/sqlite-index/            真实运行的领域侧代码（15 文件，不含 run/ 与 heldout-store/）
```

## 引用

Chen, Wen, Kirchner. *Automated Researchers Can Reliably Mitigate Alignment Failures*, 2026.
代码与基准：<https://github.com/YuehHanChen/automated_alignment_researcher>

## 许可

MIT，见 [LICENSE](LICENSE)。