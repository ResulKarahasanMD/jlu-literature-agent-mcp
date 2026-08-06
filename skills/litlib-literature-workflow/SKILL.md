---
name: litlib-literature-workflow
description: Use when a user asks to find/acquire papers or says 文献检索、下载文献、批量获取论文、吉大机构访问、CARSI/WebVPN、知网/CNKI、PDF 校验、导入 Zotero、检索本地文献库, LitLib, or ZotSeek. Orchestrates academic search tools, the litlib CLI, the read-only LitLib MCP, and the read-only ZotSeek MCP without bypassing CAPTCHA or paywalls.
license: MIT
compatibility: Windows 10/11; Python 3.11-3.13; uv; Zotero 8/9; Jilin University routes are institution-specific.
metadata:
  author: LitLib contributors
  version: "0.2.0"
---

# LitLib Literature Workflow

## Purpose

Use this skill as the execution policy for a three-part system:

1. **This skill** decides which capability to use, applies compliance and human checkpoints,
   interprets failures, and records what was verified.
2. **LitLib MCP** performs deterministic, local, read-only lookup of metadata, task state,
   PDF paths, Zotero collections, and paged PDF text.
3. **ZotSeek MCP** performs local semantic or hybrid retrieval over a separately maintained
   Zotero index.

All mutations use the `litlib` CLI or an explicit human Zotero action. MCP tools do not
download papers, change task state, import items, or modify the Zotero library.

## Do Not Overclaim

LitLib is an acquisition and local-library workflow, not a complete bibliographic search
database. For a topic search, first use the Agent's installed academic database capability
(for example PubMed, Crossref, OpenAlex, Semantic Scholar, or another approved scholarly
source), retain DOI/PMID and source provenance, then pass identifiers to LitLib. Do not
substitute generic web search when an academic database tool is available.

ZotSeek is an external Zotero plugin, not code shipped by LitLib. Its MCP can only search
items already covered by the active embedding model. Semantic similarity is retrieval
evidence, not evidence that a paper supports a scientific claim.

## Locate and Inspect the Installation

Never assume `D:\op\projects\literature-library` on another machine. Resolve the project in
this order:

1. User-provided project path.
2. `LITLIB_ROOT`, if set.
3. The repository containing `pyproject.toml` with project name `litlib`.
4. An installed `litlib` executable on `PATH`.

Before a write workflow, run:

```powershell
litlib --version
litlib doctor
litlib status
```

Examples use `litlib` for readability. In an unactivated source clone, run the equivalent
`uv run litlib ...`; on Windows, MCP clients should use the absolute `.venv\Scripts\python.exe`
with arguments `-m litlib.cli mcp` so the console-script wrapper is not locked during upgrades.

If the executable is absent, read [references/CLIENT_SETUP.md](references/CLIENT_SETUP.md).
Do not install packages, plugins, change Zotero settings, store credentials, or alter an
Agent's MCP configuration without telling the user what will change.

## Classify the Request

### Search the existing library

1. Call `zotseek_index_status` first when ZotSeek is available.
2. For concepts, use `zotseek_search` in `hybrid` mode. Use English queries for an
   English-only library when Chinese-to-English retrieval is weak.
3. Use `library_search_metadata` for exact title, DOI, author, or task lookup.
4. Use `library_get_pdf_path` or `library_get_fulltext` with an exact DOI or item key.
   Broad queries can be ambiguous and must not silently select the first paper.
5. Read only the needed pages or character window. Do not inject a whole paper into the
   Agent context unless the user explicitly requires full-document processing.

### Find new papers on a topic

1. Search an academic database using the Agent's scholarly search capability.
2. Return and preserve DOI or PMID, source database, retrieval date, and uncertainty.
3. Deduplicate the identifiers before acquisition.
4. Continue with the acquisition workflow below.

### Acquire one DOI

Use the single entry point. It creates a task when needed, resolves metadata, downloads,
validates, and registers the file:

```powershell
litlib download 10.xxxx/example
litlib verify
```

The command refuses to overwrite an existing target unless `--overwrite` is explicit.
Registration failure is a failure even when a PDF file exists; preserve the file and inspect
the task database instead of claiming success.

### Acquire a batch

```powershell
litlib queue add --file examples/input.example.csv
litlib run --stage fetch-metadata
litlib run --stage oa
litlib status --verbose
```

Only tasks in `REQUIRES_INST` proceed to institutional access. Keep institutional batches at
10 papers or fewer, concurrency 1, with 8-15 second delays:

```powershell
litlib inst check-cred
litlib inst open
litlib run --stage inst --access-mode campus
litlib inst close
```

Use `offcampus` only when the user is off campus and has authorized JLU credentials.
Use `auto` when network status is unknown. Read
[references/DECISION_TREE.md](references/DECISION_TREE.md) before diagnosing a failure and
[references/SITE_RECIPES.md](references/SITE_RECIPES.md) before changing a publisher route.

### Acquire CNKI content

CNKI is a separate browser flow. Search can work before the download challenge is passed;
do not treat search success as download authorization.

```powershell
litlib inst open
litlib cnki open
litlib cnki search "检索词" --limit 10
litlib cnki download "<detail-page-url>" --output "<storage-path>"
litlib inst close
```

If `bar.cnki.net` presents a slider, return `HUMAN_REQUIRED` and ask the user to complete it
in the visible dedicated browser. Never automate or outsource the slider. CAJ is not PDF;
preserve the correct extension and do not pass CAJ through PDF validation.

## PDF Success Contract

A download is successful only when all applicable checks pass:

1. The file begins with `%PDF-`.
2. `%%EOF` exists near the file tail; a `206 Partial Content` fragment is not enough.
3. `pypdf` parses at least one page.
4. The expected DOI appears in the first three extracted pages, including DOI text split by
   line breaks; a different DOI on page 1 is a hard mismatch.
5. The first three pages do not identify the file as supplementary/supporting material.
6. SHA-256 matches the task record on later verification.
7. The task database registration succeeded.

Run `litlib verify` before delivery. A zero-item verification is not success.

## Zotero Import Contract

The supported write path is deliberately human-gated:

```powershell
litlib proposal --doi-file <batch.csv>
# User imports the generated RIS in Zotero and checks the collection/items.
litlib review --doi-file <batch.csv>
litlib import --lookup --batch <name> --doi-file <batch.csv>
```

`IMPORTED` means LitLib found exactly one Zotero parent item by exact DOI (or normalized exact
title fallback), obtained a non-empty Zotero item key, and resolved an existing PDF
attachment. If Zotero is stopped, no exact item exists, multiple matches exist, or the PDF
attachment is missing, do not mark the task imported.

Never edit `zotero.sqlite` directly. Do not install a Zotero bridge that evaluates arbitrary
code. Zotero library writes beyond the RIS import need separate user approval and security
review.

## Human Checkpoints and Stop Conditions

Pause and ask the user when any of these occurs:

- CAPTCHA, Turnstile, slider, OTP, or a visible human-verification page.
- First-time credential storage, plugin installation, Zotero configuration, or MCP config edit.
- Terms of use or attribute-release page whose acceptance has legal/account implications.
- An existing output would be overwritten.
- The only available object is CAJ or HTML and the requested deliverable is PDF.

Stop automated attempts and report the reason when:

- The page explicitly offers purchase, rental, `Buy Protocol`, or otherwise shows no
  authorized PDF entitlement.
- The institution's identity provider rejects the service provider as unsupported.
- Repeated `429` or publisher rate limiting occurs. Cool down; do not rotate identities,
  profiles, or proxies to evade it.
- A route would require bypassing a paywall, CAPTCHA, technical access control, or license.

## Failure Handling

Use `litlib status --attempts <task-id>` and classify the failure before retrying:

- `HUMAN_REQUIRED`: visible challenge; wait for the user, then
  `litlib queue recover --paused`.
- `RATE_LIMITED`: stop and cool down; recover only after a reasonable interval.
- `PAYWALLED`: explicit purchase/rental/no-entitlement stop; terminal unless a human changes
  the access situation outside LitLib and creates a new task.
- `REQUIRES_INST`: OA candidates failed but an authorized institution route may remain.
- `FAILED`: inspect metadata, dedupe conflict, file identity, or internal exception.
- HTML from a PDF-looking URL: diagnose authentication, anti-bot response, landing-page
  indirection, or HTML-only entitlement. Do not rename HTML to `.pdf`.

CLI exit status is authoritative: `0` success, `1` runtime/verification/no-result failure,
`2` usage or unmet precondition, and `3` a CNKI human checkpoint. Never report completion
from console text alone when the exit status is non-zero.

## Reporting

For every batch report:

- Requested, resolved, downloaded, verified, imported, human-required, rate-limited, and
  paywalled counts.
- DOI/PMID and source for each paper.
- Route used for each successful PDF.
- Explicit distinction between `verified`, `inferred`, and `unverified` behavior.
- Any live-browser step the user still needs to complete.

Do not expose credentials, cookies, WebVPN host tokens, API keys, signed PDF URLs, or full
query strings. Do not commit PDFs, extracted full text, Zotero databases, browser profiles,
logs, XPI files, or runtime state.

## Personal Experience (Self-Evolving)

The repository recipes are a read-only baseline shipped with the code. Every user also has a
local, private experience library (`litlib learn`) that grows automatically:

- **Location**: `<LITLIB_RUNTIME_ROOT>\experience\experiences.json` (default
  `D:\LitLibRuntime\experience\experiences.json`). It is never committed to Git.
- **Automatic learning**: after a verified successful institutional or CNKI download through a
  route that worked, LitLib records `domain + route + url_pattern + doi_prefix` locally.
  PAYWALLED / HUMAN_REQUIRED / RATE_LIMITED / FAILED are never recorded as success.
- **Manual learning**: an agent or user can add observations with
  `litlib learn add --domain <domain> --route <route> --note "<what worked>"`.
- **Read before trying a new site**: run `litlib learn list --domain <site>` or
  `litlib learn export` first. Personal experience takes precedence over the canonical
  `SITE_RECIPES.md` when they conflict.
- **All recorded content is sanitized** (URLs lose query tokens, WebVPN tokens, cookies and
  credentials are redacted). Personal experience is per-user and per-machine; it is not shared
  by the repository.
- Manage with `litlib learn list | add | remove | export`. Cleaning a wrong entry:
  `litlib learn remove <id>`.

Personal experience is a retrieval aid only. It never authorizes bypassing a paywall,
CAPTCHA, rate limit, or unsupported CARSI service provider.

## References

- [Decision tree and generalized diagnostics](references/DECISION_TREE.md)
- [Verified publisher and database recipes](references/SITE_RECIPES.md)
- [Installation, Zotero, ZotSeek, and MCP client setup](references/CLIENT_SETUP.md)
