# Changelog

本项目遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

版本号同时出现在三处，升版本时**三处一起改**：
`.claude-plugin/plugin.json` 的 `version`、`.claude-plugin/marketplace.json` 的 `version`
与 `marketplace.json` 的 `metadata.version`。

## 0.1.0 — 2026-09-18

首次发布。

- skill 本体：`skills/aar-harness/`，43 个文件，零第三方依赖（纯 Python 标准库）。
  通过 `install.ps1 -RunTests`（`layout ok: 21 required files present` + `Ran 57 tests ... OK`）。
- 插件清单：`.claude-plugin/plugin.json`（格式 A，Claude Code 插件仓库形态）。
- marketplace：`.claude-plugin/marketplace.json`，`source: "./"` + `strict: false` + `skills: ["./skills/aar-harness"]`。
- 示例：`examples/sqlite-index/`，15 个文件，只含领域侧框架代码，
  **不含** `run/`（过程数据）与 `heldout-store/`（held-out 封印）。
