# Operations

## Setup and Health

```powershell
Copy-Item .env.example .env
uv sync --locked --extra dev
uv run litlib doctor --storage
uv run pytest
uv run ruff check .
```

Use `scripts/run.ps1` when a wrapper is preferred. It honors `LITLIB_RUNTIME_ROOT`, defaults
to `D:\LitLibRuntime` for a clone on D:, and otherwise uses `.litlib-runtime` in the clone.
It changes process-level environment only.

## Routine Workflow

```powershell
uv run litlib status --verbose
uv run litlib queue add --file <input.csv>
uv run litlib run --stage fetch-metadata
uv run litlib run --stage oa
uv run litlib verify
```

Only then open the supervised institutional browser for `REQUIRES_INST` tasks. Always close it
after the batch:

```powershell
uv run litlib inst open
uv run litlib run --stage inst --access-mode auto
uv run litlib inst close
```

## Recovery

```powershell
uv run litlib status --attempts <task-id>
uv run litlib queue recover
uv run litlib queue recover --failed
uv run litlib queue recover --paused
```

Use `--failed` only after fixing the cause. Use `--paused` after the user completed a challenge
or a rate-limit cooldown. Repeated retries without classification are not an operational fix.

## Zotero Import

1. Run `litlib proposal`; it refuses to create an empty proposal or include a missing PDF.
2. User imports the RIS in Zotero and inspects item metadata/PDF attachments.
3. Run `litlib review` for the intended batch.
4. Run `litlib import --lookup`; it verifies exact parent items and PDFs before `IMPORTED`.

If Zotero is stopped, an item is ambiguous, or an attachment is absent, restart/repair Zotero
and rerun. Do not manually update SQLite to skip the verification.

## Logs and State

- `logs/litlib.log`: 20 MB rotation, five backups.
- `state/litlib.db`: task and audit state; not a bibliographic master database.
- `staging/downloads`: verified or recovery PDF artifacts.
- `output`: RIS/manifests/full-text cache; all generated and excluded from Git.
- `LITLIB_RUNTIME_ROOT/chrome`: dedicated profile/cache/downloads.
- `LITLIB_RUNTIME_ROOT/experience/experiences.json`: personal experience library (see below).

Back up the project `state/` directory only when no LitLib write command is running. Zotero
backup follows Zotero's own guidance and must include its configured data directory. ZotSeek's
index is derived and can be rebuilt.

## Personal Experience (`litlib learn`)

Successful institutional or CNKI downloads are recorded automatically into
`<LITLIB_RUNTIME_ROOT>\experience\experiences.json`; entries hold `domain`, `route`,
`url_pattern`, `doi_prefix`, success count and timestamps, and are sanitized before writing.
PAYWALLED / HUMAN_REQUIRED / RATE_LIMITED / FAILED are never recorded.

- `litlib learn list [--domain <site>]` — view; `litlib learn export` — Markdown for agents.
- `litlib learn add --domain <site> --route <route> --note "<what worked>"` — manual entry.
- `litlib learn remove <id>` — delete a wrong entry.

Personal experience lives outside the repository (git-ignored) and is per-user/per-machine.
If the JSON is corrupted it is ignored and read as empty; deleting the file resets learning.

## Upgrade

```powershell
git pull --ff-only
uv lock --check
uv sync --locked --extra dev
uv run pytest
uv run litlib doctor
```

Older MCP configuration that starts `.venv\Scripts\litlib.exe` can lock that wrapper on
Windows. The documented configuration uses `python.exe -m litlib.cli mcp`; migrate old
clients, restart them, then run `uv sync`. Restart Zotero after upgrading ZotSeek.

## Cleanup

There is no implemented `litlib clean` command. Inspect generated directories and ask the
user before deleting anything. Never automatically delete PDFs, Zotero attachments, task
state, browser profiles, or quarantine/recovery files.
