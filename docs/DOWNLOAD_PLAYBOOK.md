# 下载 Playbook 入口

为避免 skill 与项目文档漂移，详细经验以可分发 skill package 中的两个 reference 为唯一来源：

- [DECISION_TREE.md](../skills/litlib-literature-workflow/references/DECISION_TREE.md)：通用诊断、
  browser escalation、新 publisher 探索和停止条件。
- [SITE_RECIPES.md](../skills/litlib-literature-workflow/references/SITE_RECIPES.md)：Wiley、MDPI、
  Elsevier、T&F、OUP、Springer、Frontiers、CNKI、ACS、RSC、JLU IdP 和 WebVPN 实测记录。

## 最短决策顺序

```text
academic identifier
  -> OA candidates, each validated independently
  -> direct HTTP/browser under current authorized session
  -> existing WebVPN ticket+token when available
  -> JLU institution login
  -> human checkpoint / cooldown / purchase-only stop
```

## 完成条件

PDF 必须同时满足 `%PDF-`、尾部 `%%EOF`、至少一页、前三页目标 DOI、首页无冲突 DOI、
非 supplement、SHA-256，
并成功登记 task database。`200`、`.pdf` 后缀或浏览器 viewer 可见都不能单独证明下载完成。

## 新经验记录格式

向 `SITE_RECIPES.md` 增加记录时必须包含：

- 日期、network/access mode、DOI prefix、actual landing host 和 content type。
- `verified`、`observed restriction` 或 `inferred` 标签。
- 成功路线、失败路线、human checkpoint 和 stop condition。
- 验证结果：size、page count、expected DOI、EOF、是否 main article。
- 不含 Cookie、signed query、WebVPN token 或完整受保护内容的 fixture/test。
