# Agent 接入与运行 contract

## 接入前提

一个 Agent 要完整使用 LitLib，需要三类能力：

1. 加载完整 `litlib-literature-workflow` skill 目录。
2. 能执行本地 shell/CLI，用于所有下载与状态写入。
3. 注册 LitLib 和 ZotSeek 两个 MCP，用于本地读取。

主题级文献检索还需要 Agent 自身具备 PubMed/Crossref/OpenAlex 等学术数据库能力。
LitLib 不能单独完成系统综述式检索。

## 两个 MCP

### LitLib stdio MCP

启动命令：

```text
<absolute-repo-path>\.venv\Scripts\python.exe -m litlib.cli mcp
```

工具：

| Tool | Contract |
|---|---|
| `library_search_metadata(query, limit)` | 在 Zotero 与 task state 中按标题/DOI/作者查题录 |
| `library_get_pdf_path(query)` | 返回唯一匹配 PDF；歧义时返回 candidates 而非猜测 |
| `library_get_fulltext(query, offset, limit_chars)` | 无 cache 写入的分页全文，上限 20000 字符 |
| `library_list_collections()` | 读取 Zotero collections |
| `library_task_status(state)` | 读取任务状态，不创建/迁移数据库 |

LitLib MCP 使用 SQLite `mode=ro` 和 `query_only`，启动时不创建运行目录或日志。若需要精确
PDF，优先传 DOI 或 Zotero 8 位 item key。

### ZotSeek HTTP MCP

地址：`http://127.0.0.1:23119/zotseek/mcp`

上游 raw tools 通常为：

- `search`
- `index_status`
- `find_similar`

客户端可能显示为 `zotseek_search` 等 namespaced 名称。不要只靠名称判断，读取 tool
description。调用 `index_status` 确认 active model coverage 后再搜索。MCP 本身不修改 library
或 index；ZotSeek 插件的 auto-index 是独立后台行为。

## 客户端配置

OpenCode 与 Codex 的可复制配置见 skill 内
[`CLIENT_SETUP.md`](../skills/litlib-literature-workflow/references/CLIENT_SETUP.md)。关键点：

- 配置使用每台机器的绝对 executable path，不写死本项目开发机路径。
- OpenCode local MCP 的 `command` 是字符串数组。
- ZotSeek 使用 remote/HTTP MCP，不是 stdio。
- 修改 skill 或 MCP config 后必须完全重启 Agent client。
- Zotero 必须运行并允许 local HTTP server。

## Agent 启动序列

```powershell
litlib --version
litlib doctor
litlib status
```

然后：

1. Existing-library request：`zotseek index_status` → semantic search → LitLib exact fulltext。
2. New-topic request：academic database search → identifiers/provenance → LitLib acquisition。
3. Single DOI：`litlib download <DOI>` → `litlib verify`。
4. Batch：queue → metadata → OA → only `REQUIRES_INST` enters supervised institutional stage。
5. Import：proposal → human RIS import → review → `import --lookup`。
6. Personal experience (self-evolving)：before trying an unfamiliar site, read
   `litlib learn list --domain <site>` (or `litlib learn export`); personal experience takes
   precedence over the canonical `SITE_RECIPES.md`. Successful verified institutional/CNKI
   downloads are recorded automatically; agents may also add observations with
   `litlib learn add --domain <site> --route <route> --note "<what worked>"`.

## Exit Codes

Agent 必须以退出码而不是“看起来像成功”的 console text 为准：

| Code | Meaning |
|---:|---|
| 0 | 命令目标完成 |
| 1 | runtime、verification、no-result 或 partial failure |
| 2 | 用法错误或未满足前置条件，如将覆盖已有文件 |
| 3 | CNKI human verification checkpoint |

`litlib verify` 在零文件时返回 1。`litlib import` 未使用 `--lookup` 或无法验证 Zotero
item/PDF 时不会标记 `IMPORTED`。

`PAYWALLED` 是明确购买/租赁/no-entitlement 的终态，不应使用 `queue recover --paused`
自动重试。机构阶段即使传入更高 `--limit` 也会强制截断为 10。

## 人工参与

Agent 不得自动通过：CAPTCHA、Turnstile、CNKI slider、OTP、购买页、条款/属性发布的法律
同意。凭证首次保存、ZotSeek 安装、MCP config 修改、文件覆盖和 Zotero 写入都应向用户说明。

机构路线必须有监督，批量上限 10、并发 1、延迟 8-15 秒。出现 429 时停止并冷却，不能通过
切 profile、代理或身份规避。

## Personal Experience Contract

- 个人经验库位于 `<LITLIB_RUNTIME_ROOT>\experience\experiences.json`，不在仓库内、不进
  Git，按用户/机器隔离。
- 只有通过严格 PDF 校验的真实成功才会被自动记录；`PAYWALLED` / `HUMAN_REQUIRED` /
  `RATE_LIMITED` / `FAILED` 永不写入经验。
- Agent 读取新站点经验时必须先 `litlib learn list`，不得依赖记忆或凭空编造路线。
- 经验内容已脱敏（URL 去 query、WebVPN token、cookie、凭证）。Agent 不得把密钥写进
  `learn add` 的 note 或 URL pattern。
- 个人经验只加速检索决策，不改变合规边界：任何经验条目都不能授权绕过付费墙、验证码、
  限流或不支持的 CARSI SP。
- 纤维素酶数据默认规则：按构建体 × 底物 × 指标族 × 单位 × assay method 选择最大观测值；
  不跨底物或不可比单位竞争。突变体/截短体只有在明确序列或可由明确突变/边界严格重建时
  才进入正式数据集。图表估读须标记 `digitized`，无真值时只能报告不确定度/重复性，不能
  声称真实误差百分比。
- 清理错误经验：`litlib learn remove <id>`。

## 输出要求

每次交付报告 requested/resolved/downloaded/verified/imported/human-required/rate-limited/
paywalled 数量，逐篇保留 DOI/PMID、来源、成功 route 和 verified/inferred/unverified 标签。
不得输出 Cookie、密码、API key、signed URL、WebVPN host token 或未脱敏 route query。
