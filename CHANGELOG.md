# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

版本号同时出现在三处，升版本时**三处一起改**：
`.claude-plugin/plugin.json` 的 `version`、`.claude-plugin/marketplace.json` 的 `version`
与 `marketplace.json` 的 `metadata.version`。

## 0.2.0 — 2026-09-18

**运行收尾现在会自己产出并指出论坛的读面。**

起因：论坛的人类视图（观测台）一直存在——`dashboard.py` 能渲染出含 findings 表、
冠军 claims、四个监控矩阵与 `forum verify` 状态的一页 HTML——但 `orchestrator.py`
收尾从不生成它，`final.md` 也不提它。跑完只得到一堆 JSON，操作者不知道去哪看论坛。

- `orchestrator.py` 收尾自动渲染一次观测台，并在收尾 JSON 里给出 `forum` 与
  `dashboard` 两个路径。渲染是 **best-effort**：失败只记一条 WARNING，绝不影响运行
  （已用删掉 `dashboard.py` 的残缺副本实测：exit 0，其余产物照常产出）。
- 渲染安排在 `write_report` **之后**——观测台会读 `reports/final.json` 的
  selection/held-out 段，提前渲染会发布过期页面。
- `reports/final.md` 新增 `## where to read this run`：把论坛 findings、观测台、
  排行榜、per-method 评分、traces、事后审查产物列成绝对路径，并给出 render/serve 命令。
- `--report-only` 路径同样渲染。
- 判定逻辑（闸门 / 评分 / 哈希 / 论坛单写者）**一个字符未动**；57 个单测全绿。

## 0.1.0 — 2026-09-18

首次发布。

- skill 本体：`skills/aar-harness/`，43 个文件，零第三方依赖（纯 Python 标准库）。
  通过 `install.ps1 -RunTests`（`layout ok: 21 required files present` + `Ran 57 tests ... OK`）。
- 插件清单：`.claude-plugin/plugin.json`（格式 A，Claude Code 插件仓库形态）。
- marketplace：`.claude-plugin/marketplace.json`，`source: "./"` + `strict: false` + `skills: ["./skills/aar-harness"]`。
- 示例：`examples/sqlite-index/`，15 个文件，只含领域侧框架代码，
  **不含** `run/`（过程数据）与 `heldout-store/`（held-out 封印）。
