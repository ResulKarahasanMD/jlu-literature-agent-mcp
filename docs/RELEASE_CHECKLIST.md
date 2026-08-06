# GitHub Release Checklist

## Repository Content

- [ ] `git status --short --untracked-files=all` contains no PDF, CAJ, XPI, `.env`, database,
  browser profile, cookie, WebVPN token, log, extracted full text, or user-specific report.
- [ ] Search tracked content for usernames, email addresses, absolute home paths, API keys,
  tokens, and signed URLs.
- [ ] Confirm `IMPLEMENTATION_PLAN.md` and local WebVPN experiment scripts remain untracked.
- [ ] Confirm all test fixtures are synthetic and contain no protected article text.

## Metadata and Legal

- [ ] Verify `project.urls` still point to the intended public repository before tagging.
- [ ] Confirm maintainer name/contact and copyright wording.
- [ ] Keep ZotSeek XPI external until its upstream license file is authoritative.
- [ ] Generate and review a dependency-license report before distributing wheels/binaries.
- [ ] Enable GitHub Private Vulnerability Reporting.

## Verification

- [ ] `uv lock --check`
- [ ] `uv sync --locked --extra dev` with no active MCP executable lock.
- [ ] `uv run ruff check .`
- [ ] `uv run pytest`
- [ ] `uv build`
- [ ] Install the built wheel in a clean temporary environment and run `litlib --version`.
- [ ] `litlib learn list` runs from the clean wheel install and reports an empty library
  without error (personal experience is runtime-local, never packaged).
- [ ] Validate OpenCode and Codex config examples on clean client restarts.
- [ ] Distribute the entire skill directory and verify references resolve.
- [ ] Run one OA smoke test with a redistributable test DOI.
- [ ] Run institutional smoke tests only in a supervised authorized JLU session.

## Personal Experience

- [ ] Confirm `experience.py`, `test_experience.py`, and the `learn` CLI command are included
  in the sdist/wheel and covered by CI (`uv run pytest`).
- [ ] Confirm `experiences.json` and the `experience/` runtime directory are absent from the
  repo (git-ignored; default `LITLIB_RUNTIME_ROOT` lives outside the clone).
- [ ] Confirm automatic learning is wired only to verified successes: PAYWALLED /
  HUMAN_REQUIRED / RATE_LIMITED / FAILED routes cannot be recorded.
- [ ] Confirm all experience fields are sanitized before write (URL query tokens, WebVPN
  tokens, cookies, credentials redacted).
- [ ] README and skill `SKILL.md` document `litlib learn list | add | remove | export` and the
  precedence rule (personal experience over canonical `SITE_RECIPES.md`).

## Documentation

- [ ] README does not claim LitLib itself is a comprehensive scholarly search database.
- [ ] Every site recipe has date, evidence label, access mode, successful/failed routes, and
  stop condition.
- [ ] Known unverified paths remain labelled unverified.
- [ ] Release notes distinguish unit-tested behavior from live-site observations.
