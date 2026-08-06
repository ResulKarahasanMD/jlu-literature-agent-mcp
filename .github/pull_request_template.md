## Change

Describe the user-visible behavior and why it is needed.

## Evidence

- [ ] Tests use synthetic/minimal fixtures and contain no protected full text.
- [ ] Site observations are labelled verified, inferred, or unverified with a test date.
- [ ] `docs` and the portable skill references are consistent with the implementation.

## Verification

- [ ] `uv lock --check`
- [ ] `uv run ruff check .`
- [ ] `uv run pytest`
- [ ] No PDF, CAJ, XPI, `.env`, database, browser profile, cookie, token, or log is included.
- [ ] No CAPTCHA/paywall/rate-limit bypass or unsafe Zotero database write was added.
