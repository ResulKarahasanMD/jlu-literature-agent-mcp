# 最终架构：一个 skill + 两个 MCP

## 组件边界

```text
                         academic database tools
                                  |
                                  v
User request --> litlib-literature-workflow skill
                   |          |            |
                   |          |            +--> ZotSeek MCP (semantic recall)
                   |          +---------------> LitLib MCP (exact local reads)
                   +--------------------------> litlib CLI (all mutations)
                                                        |
             metadata APIs / OA / JLU browser ----------+
                                                        v
                  task SQLite + verified PDFs --> RIS --> Zotero
                                                        |
                                                        +--> ZotSeek local index
```

### Skill

`skills/litlib-literature-workflow/` is the portable Agent policy package. It contains:

- `SKILL.md`: triggers, routing, compliance, success contracts, human checkpoints.
- `references/DECISION_TREE.md`: generalized failure diagnosis and new-site exploration.
- `references/SITE_RECIPES.md`: dated, evidence-labelled publisher observations.
- `references/CLIENT_SETUP.md`: clone, Zotero, ZotSeek, MCP, and skill installation.

The skill does not execute by itself and does not replace a scholarly search database. It
orchestrates the Agent's academic search capability, LitLib CLI, and both MCP servers.

### LitLib MCP

Project-owned stdio server: `litlib mcp`.

- Exact/local metadata search across Zotero Local API and the LitLib task database.
- PDF path resolution with ambiguity detection.
- Paged PDF text extraction.
- Zotero collection and task-state reads.
- Opens SQLite with `mode=ro` and `PRAGMA query_only=ON`.
- Does not initialize schema, create logs, write full-text cache, mutate tasks, or write Zotero.

### ZotSeek MCP

External Zotero-plugin HTTP server: `http://127.0.0.1:23119/zotseek/mcp`.

- Semantic, hybrid, and keyword retrieval over the active model's local index.
- Index coverage/status and similar-paper lookup.
- MCP calls are read-only; the ZotSeek plugin can separately auto-index Zotero changes when
  that setting is enabled.
- ZotSeek is installed from upstream and is not redistributed in this repository.

## Mutation Matrix

| Operation | Skill | LitLib MCP | ZotSeek MCP | LitLib CLI / human |
|---|---:|---:|---:|---:|
| Search existing metadata | routes | yes | keyword part | optional |
| Semantic library search | routes | no | yes | no |
| Download PDF | routes | no | no | CLI |
| Change task state | routes | no | no | CLI |
| Generate RIS | routes | no | no | CLI |
| Import into Zotero | checkpoint | no | no | human Zotero action |
| Confirm `IMPORTED` | routes | no | no | CLI `import --lookup` |
| Build embeddings | checkpoint | no | status only | ZotSeek plugin UI |

## Data Flow and Trust Boundaries

1. Identifiers come from academic databases or user input.
2. SQLite stores workflow state and route audit, not full paper text.
3. PDFs are accepted only after header, EOF, page, DOI, supplement, and SHA-256 checks.
4. RIS import is intentionally human-gated.
5. Zotero is the bibliographic source of truth. LitLib never edits `zotero.sqlite`.
6. ZotSeek maintains its own `zotseek.sqlite`; it is a derived local index, not the master
   library.

Credentials live in Windows Credential Manager. Browser cookies remain in the dedicated
Chrome profile; optional cookie export is off by default and, if explicitly enabled, uses a
DPAPI-encrypted file. CAPTCHA/Turnstile/slider/OTP handling is always human.

## State Contract

```text
QUEUED -> METADATA_FETCH -> DEDUPED
  |                           |-- OA_OK -> DOWNLOADING -> VERIFYING -> READY
  |                           `-- REQUIRES_INST -> INST_QUEUED -> ... -> READY
  |-- FAILED

READY -> PROPOSAL_GENERATED -> USER_REVIEWED -> IMPORTED

DOWNLOADING/VERIFYING -> PAYWALLED (explicit purchase-only terminal outcome)
```

`IMPORTED` is not a user assertion. It requires one exact Zotero parent item, a non-empty
item key, and a resolvable PDF attachment. Human challenges and rate limits use
`HUMAN_REQUIRED` and `RATE_LIMITED`, then explicit `queue recover --paused`.

## Portability

No public instruction assumes a fixed clone path. Runtime storage is controlled by
`LITLIB_RUNTIME_ROOT`; D-drive enforcement is optional via `LITLIB_REQUIRE_D_DRIVE`. The
institution adapter is currently JLU/Windows-specific, while metadata, OA, validation, task
state, and MCP code are designed for isolated tests and future adapters.
