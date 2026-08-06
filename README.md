# LitLib for JLU

面向吉林大学学生的 Agent-ready 文献获取与本地知识库工作流。LitLib 优先从合法 OA
来源获取论文；非开放文献仅在用户具有权限时，通过校园网、CARSI/机构登录或吉大
WebVPN 小批量访问。Zotero 是唯一文献主库。

> 当前状态：`0.2.0 alpha`。元数据、OA、PDF 校验、任务状态、RIS 导入、LitLib MCP
> 已有自动化测试；出版社与 CNKI 路线依赖实时页面，只做有监督 smoke test。

## 最终框架

本项目固定为 **一个 skill + 两个 MCP**：

| 组件 | 责任 | 是否写入 |
|---|---|---|
| `litlib-literature-workflow` skill | 判断检索/下载/读取路线，执行合规边界、人工 checkpoint 和故障决策 | 不直接写 |
| LitLib MCP | 精确读取 Zotero/任务库元数据、PDF 路径、分页全文、任务状态 | 严格只读 |
| ZotSeek MCP | 对已索引 Zotero 文献做 semantic/hybrid/keyword 检索 | MCP 只读 |
| `litlib` CLI | 建任务、下载、验证、生成 RIS、确认 Zotero 导入 | 会写 |

详细边界见 [架构文档](docs/ARCHITECTURE.md)。可移植 skill 源码位于
[`skills/litlib-literature-workflow`](skills/litlib-literature-workflow)。分发 skill 时必须
连同 `references/` 一起分发。

## 能做与不能做

LitLib 能处理已有 DOI/PMID/PMCID/arXiv/准确标题，完成元数据解析、OA/机构获取、
严格 PDF 校验、任务追踪和 Zotero 入库。主题级“找论文”仍应先调用 PubMed、Crossref、
OpenAlex、Semantic Scholar 等学术数据库，再把标识符交给 LitLib；项目不把普通网页搜索
伪装成学术检索。

项目不提供 Sci-Hub/LibGen、paywall/CAPTCHA 绕过、代理轮换、无人值守机构批量抓取、
整卷下载，也不直接修改 `zotero.sqlite`。

## 安装

要求：Windows 10/11、Python 3.11-3.13、[uv](https://docs.astral.sh/uv/)、Chrome/Edge、
Zotero 8/9。机构通道面向 JLU，其他学校需要新增 institution adapter。

```powershell
git clone https://github.com/ganpingzhu904-dev/jlu-literature-agent-mcp.git
Set-Location jlu-literature-agent-mcp
Copy-Item .env.example .env
# 编辑 .env，至少填写真实联系邮箱 LITLIB_EMAIL
uv sync --locked --extra dev
uv run litlib doctor
uv run pytest
```

`.env` 不能保存吉大密码、Cookie、VPN token 或 Zotero 密码。吉大统一认证凭证仅通过
`litlib inst set-cred` 写入 Windows Credential Manager。

没有 D 盘的用户设置 `LITLIB_REQUIRE_D_DRIVE=0`；有大容量 D 盘的用户可设置为 `1`，
并把 `LITLIB_RUNTIME_ROOT` 指向 D 盘。所有设置见 [.env.example](.env.example)。

## 快速工作流

### 单篇 DOI

```powershell
uv run litlib download 10.xxxx/example
uv run litlib verify
uv run litlib status --verbose
```

该入口会自动建任务、解析元数据、下载、校验并登记。目标文件存在时默认拒绝覆盖；只有
用户明确要求时使用 `--overwrite`。

### 批量 OA

```powershell
uv run litlib queue add --file examples/input.example.csv
uv run litlib run --stage fetch-metadata
uv run litlib run --stage oa
uv run litlib status --verbose
```

OA 候选顺序为 arXiv、可识别的 MDPI public static、Unpaywall、Europe PMC、OpenAlex，
最后才使用具有明确 OA license metadata 的 Crossref link。每个候选独立下载并验证。

### JLU 机构通道

只处理 `REQUIRES_INST`，每批最多 10 篇、并发 1、间隔 8-15 秒：

```powershell
uv run litlib inst set-cred
uv run litlib inst check-cred
uv run litlib inst open
uv run litlib run --stage inst --access-mode campus
# 校外使用 offcampus；网络未知使用 auto
uv run litlib inst close
```

遇到 Turnstile、滑块、OTP 或 CAPTCHA 时，程序必须暂停并由用户在可见专用浏览器完成。
出版社明确显示购买/租赁/HTML-only 时停止，不把登录成功等同于拥有 PDF 权限。

### CNKI

```powershell
uv run litlib inst open
uv run litlib cnki open
uv run litlib cnki search "检索词" --limit 10
uv run litlib cnki download "<详情页 URL>" --output "<目标.pdf>"
uv run litlib inst close
```

`bar.cnki.net` 滑块必须人工完成。CAJ 不是 PDF，当前不纳入 PDF 验证与全文管线。

### Zotero 入库

```powershell
uv run litlib proposal --doi-file <batch.csv>
# 用户在 Zotero 中导入 RIS 并检查条目/附件
uv run litlib review --doi-file <batch.csv>
uv run litlib import --lookup --batch <name> --doi-file <batch.csv>
```

只有精确匹配到一个 Zotero parent item、非空 item key 和可读取 PDF 附件时，状态才会变为
`IMPORTED`。Zotero 未运行或匹配歧义时返回非零且不虚假确认。

明确购买/租赁且无 PDF entitlement 的任务进入 terminal `PAYWALLED`，不会与 CAPTCHA 的
`HUMAN_REQUIRED` 或 429 的 `RATE_LIMITED` 混淆。

## Agent 接入

完整配置见 [Agent 接入](docs/AGENT_INTEGRATION.md) 和 skill 内的
[CLIENT_SETUP](skills/litlib-literature-workflow/references/CLIENT_SETUP.md)。OpenCode、Codex
或其他 MCP client 均需注册：

- LitLib：stdio，`<repo>\.venv\Scripts\python.exe -m litlib.cli mcp`
- ZotSeek：HTTP，`http://127.0.0.1:23119/zotseek/mcp`

ZotSeek 是外部 Zotero 插件，本仓库不捆绑 XPI。安装后先检查 active model 的 index
coverage，再解释语义搜索未命中。中文查询英文文献效果弱时，优先改用英文同义查询，而
不是直接认定库中没有相关论文。

## 站点经验

完整、带日期和证据标签的实测档案位于
[SITE_RECIPES.md](skills/litlib-literature-workflow/references/SITE_RECIPES.md)，包括 Wiley
signed `pdfdirect`、MDPI `/pdf?version=`、ScienceDirect `pdfft`、T&F CARSI/HTML-only、
OUP、Springer protocol、CNKI slider、ACS unsupported SP 和 RSC 429。

遇到新站点先按 [DECISION_TREE.md](skills/litlib-literature-workflow/references/DECISION_TREE.md)
区分 authentication、anti-bot、partial response、HTML-only、paywall 和 wrong-PDF，
不要直接增加 DOI-prefix 硬编码。

### 个人经验自进化（litlib learn）

仓库内的站点档案是只读基线；每个用户自己的成功经验会自动保存在本地
`<LITLIB_RUNTIME_ROOT>\experience\experiences.json`（默认 `D:\LitLibRuntime\experience\`），
不进 Git、不上传、不随项目分发：

- 机构通道或 CNKI 成功下载（通过严格 PDF 校验）后自动记录站点+路线。
- 也可手动补充：`litlib learn add --domain <域名> --route <路线> --note <说明>`。
- 查看：`litlib learn list --domain <站点>` 或 `litlib learn export`（Markdown）。
- 删除：`litlib learn remove <id>`。
- 付费墙/验证码/限流场景永远不会被当作成功经验学习；所有记录自动脱敏。

这样每个人"用一次、记一次"，越用越顺，而项目本身不需要持续维护。

## 开发与发布

```powershell
uv run pytest
uv run ruff check .
```

CI 在 Windows 上测试 Python 3.11 和 3.13。贡献新站点 adapter 前阅读
[CONTRIBUTING.md](CONTRIBUTING.md)，并用 fixture 测试；真实机构会话不能进入 CI。

运行数据、PDF/CAJ、全文 cache、Zotero/SQLite 数据库、XPI、浏览器 profile、日志、
Cookie、WebVPN token 和 `.env` 都被排除在 Git 之外。发布前检查见
[RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md)。

## License

LitLib 自有代码与文档使用 [MIT License](LICENSE)。第三方组件状态见
[THIRD_PARTY.md](docs/THIRD_PARTY.md)。出版社内容及下载论文不因本项目许可证而获得再分发
权限。
