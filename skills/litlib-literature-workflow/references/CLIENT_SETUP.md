# Client and Installation Setup

## 1. Install LitLib from a Clone

Requirements: Windows 10/11, Python 3.11-3.13, `uv`, Chrome or Edge, and Zotero 8/9.
Institution credentials and JLU routes are Windows/JLU-specific; OA and metadata code can be
developed elsewhere, but the institutional smoke tests are Windows-only.

```powershell
git clone https://github.com/ganpingzhu904-dev/jlu-literature-agent-mcp.git
Set-Location jlu-literature-agent-mcp
Copy-Item .env.example .env
uv sync --locked --extra dev
uv run litlib doctor
uv run pytest
```

Set a real contact email in `.env` for Unpaywall and polite API identification. Do not put a
JLU password, Zotero password, API key, cookie, or VPN token in `.env`.

Storage settings:

- `LITLIB_RUNTIME_ROOT`: temp, cache, model, and dedicated Chrome profile root.
- `LITLIB_ROOT`: writable state/output workspace for wheel or global installs. Editable
  clones use the clone root automatically.
- `LITLIB_ZOTERO_DATA`: Zotero data-directory fallback for attachment resolution.
- `LITLIB_REQUIRE_D_DRIVE=1`: optional local policy for machines with a D: data drive.
- `LITLIB_EXPORT_SESSION_COOKIES=0`: recommended default. `1` stores only a DPAPI-encrypted
  backup bound to the current Windows user.

## 2. Prepare Zotero

1. Install Zotero 8 or 9 from the official Zotero site.
2. Start Zotero and confirm the active data directory under Advanced Files and Folders.
3. Allow Zotero's local HTTP server in Advanced settings so `127.0.0.1:23119` responds.
4. Keep Zotero running when using either MCP.
5. Do not point LitLib at or directly edit `zotero.sqlite`.

LitLib's import path is RIS plus a human confirmation. The RIS `L1` field references the
verified local PDF. After import, `litlib import --lookup` verifies the parent item and PDF
attachment through Zotero's Local API before setting `IMPORTED`.

## 3. Install ZotSeek Separately

ZotSeek is not bundled or redistributed by LitLib.

1. For reproducibility, install the locally verified baseline ZotSeek `v1.18.0` from
   `https://github.com/introfini/ZotSeek/releases/tag/v1.18.0`. A newer release must be
   rechecked for tool schema, index behavior, storage, and licensing before this skill claims
   equivalent behavior.
2. In Zotero, open Tools > Plugins > gear menu > Install Plugin From File.
3. Restart Zotero.
4. In Zotero Settings > ZotSeek, enable AI Agent Access/MCP.
5. Select an indexing mode and update the library index.
6. Call `zotseek_index_status` and confirm active-model coverage is `N of N` for the intended
   library before relying on search results.

Model guidance based on local testing and upstream documentation:

- `nomic-embed-text-v1.5`: bundled, English-focused, smallest setup burden.
- `paraphrase-multilingual-MiniLM-L12-v2`: smaller multilingual option.
- `multilingual-e5-base`: balanced multilingual model; on the tested English paper set,
  Chinese queries still retrieved less reliably than equivalent English queries.
- `BGE-M3`: larger multilingual option; use only when the accuracy benefit justifies model
  size and re-indexing time.

Switching models requires coverage for the active model. Embeddings from another model do
not make an item searchable with the newly active model.

As checked on 2026-08-06, ZotSeek's README says MIT, but the repository root returned no
`LICENSE` file and the GitHub API reported no detected license. Do not redistribute the XPI
as part of LitLib until upstream licensing is unambiguous; link users to upstream Releases.

## 4. Register Both MCP Servers

Use absolute paths in client configuration. Replace `<repo>` with the actual clone path.

### OpenCode

Add to `~/.config/opencode/opencode.json` and preserve all existing fields:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "litlib": {
      "type": "local",
      "command": ["<repo>\\.venv\\Scripts\\python.exe", "-m", "litlib.cli", "mcp"],
      "enabled": true
    },
    "zotseek": {
      "type": "remote",
      "url": "http://127.0.0.1:23119/zotseek/mcp",
      "enabled": true
    }
  }
}
```

Restart OpenCode after editing config or installing/updating the skill.

### Codex

Add to `~/.codex/config.toml`:

```toml
[mcp_servers.litlib]
command = '<repo>\.venv\Scripts\python.exe'
args = ["-m", "litlib.cli", "mcp"]

[mcp_servers.zotseek]
url = "http://127.0.0.1:23119/zotseek/mcp"
```

Restart Codex after editing config or installing/updating the skill.

For other MCP clients, register LitLib as a stdio server using
`python.exe -m litlib.cli mcp`, and ZotSeek
as a Streamable HTTP server at the URL above. Client-specific prefixes may change displayed
tool names; use the tool descriptions, not only a hard-coded prefix.

## 5. Install the Skill

Distribute the complete directory `skills/litlib-literature-workflow`, including
`references/`. Installing only `SKILL.md` loses the troubleshooting knowledge.

Common locations:

- OpenCode project: `.opencode/skills/litlib-literature-workflow/`
- OpenCode global: `~/.config/opencode/skills/litlib-literature-workflow/`
- Codex global: `~/.codex/skills/litlib-literature-workflow/`
- Agent Skills compatible clients: the client's documented skills directory

Skills and MCP configuration are loaded at client startup. Restart after changes.

## 6. Smoke Test

Run these without downloading a paywalled paper:

```powershell
uv run litlib doctor
uv run litlib status
uv run litlib verify
```

Expected nuance: `litlib verify` returns non-zero when there are no registered PDFs. That is
intentional and prevents an empty verification from being reported as success.

With Zotero running:

1. Call `library_list_collections`.
2. Call `library_search_metadata` with an exact known DOI.
3. Call `zotseek_index_status`.
4. Run one English hybrid query against an English-indexed paper.

Do not use a live institutional download as an unattended CI test. Publisher pages,
credentials, and human challenges are tested only through supervised smoke tests.
