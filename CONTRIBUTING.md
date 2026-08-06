# Contributing

LitLib is aimed first at Jilin University students who need a reproducible,
authorized literature workflow. Contributions must preserve that boundary.

## Development setup

```powershell
git clone https://github.com/ganpingzhu904-dev/jlu-literature-agent-mcp.git
cd jlu-literature-agent-mcp
Copy-Item .env.example .env
uv sync --locked --extra dev
uv run pytest
uv run ruff check .
```

Do not commit `.env`, PDFs, CAJ files, Zotero databases, browser profiles,
cookies, WebVPN tokens, downloaded XPI files, logs, or generated full text.

## Pull requests

1. Keep publisher-specific behavior in a small, testable adapter or routing branch.
2. Add a fixture-based test that does not require a live institutional session.
3. Update `docs/DOWNLOAD_PLAYBOOK.md` with the observed symptom, successful route,
   failed routes, stop condition, access environment, and verification date.
4. Label observations as `verified`, `inferred`, or `unverified`.
5. Never add CAPTCHA bypasses, paywall bypasses, high-concurrency scraping, or
   credential/cookie export that is enabled by default.

Live smoke tests must use the contributor's own authorized account, a visible
browser, batches of at most 10 papers, concurrency 1, and an 8-15 second delay.

## Reporting a site regression

Include the DOI prefix, landing host, access mode (`campus`, `offcampus`, or
WebVPN), HTTP status or visible error text, whether a human challenge appeared,
the redacted `litlib status --attempts <task-id>` output, and the date tested.
Never paste credentials, cookies, query tokens, or full publisher URLs that
contain session material.
