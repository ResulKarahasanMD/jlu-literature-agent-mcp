# Security and Privacy

## Scope

LitLib handles institutional credentials, browser sessions, local papers, and bibliographic
metadata. A mistake can expose an account, copyrighted full text, or a user's research
interests. Security claims therefore distinguish defaults from optional behavior.

## Secrets

- JLU username/password are stored with Windows Credential Manager under the current user.
- The password is submitted only over HTTPS to an explicit JLU IdP hostname allowlist.
- Terms of use and attribute-release choices are detected but never accepted automatically;
  the visible tab is preserved for the user when a checkpoint times out.
- `.env` is for non-secret runtime settings and a contact email. Do not put passwords,
  cookies, VPN tokens, Zotero passwords, or provider API keys in it.
- WebVPN host tokens and session files are runtime state and are excluded from Git.
- `litlib inst tokens` displays only presence and length, not token values.

Browser cookies normally remain inside the dedicated Chrome profile. Optional
`LITLIB_EXPORT_SESSION_COOKIES=1` stores a DPAPI-encrypted backup bound to the current Windows
user; it is off by default and the resulting `.bin` is ignored by Git.

## Local Services

- Chrome DevTools Protocol binds to `127.0.0.1` only.
- Zotero Local API and ZotSeek MCP listen on loopback (`127.0.0.1:23119`).
- LitLib MCP is stdio and performs no network listening.
- Do not expose these services through public port forwarding or an unauthenticated tunnel.

## Read-Only Claims

LitLib MCP is filesystem/task/library read-only: it opens existing SQLite with `mode=ro`,
uses `query_only`, disables full-text cache writes, and skips CLI log/directory initialization.

ZotSeek MCP calls are read-only according to upstream behavior. The ZotSeek plugin may
separately update `zotseek.sqlite` through manual or automatic indexing. The index is derived
data and is not Zotero's source of truth.

## Logs and Audit

- File logs rotate at 20 MB with five backups.
- Logger messages remove URL query strings and common key/token/password fields.
- Route-attempt records separately redact URL query strings, JLU WebVPN host tokens, and
  secret-like error fields before SQLite insertion.
- DOI and non-secret path segments can remain for reproducibility.

Do not paste raw browser network exports, HAR files, cookies, signed PDF URLs, or unredacted
route databases into an issue.

## Full Text and Copyright

`.gitignore` excludes PDF, CAJ, XPI, databases, extracted full text, output, staging, state,
logs, browser profiles, and `.env`. Contributors must still inspect `git status` because an
ignore rule is not a substitute for rights review.

The MIT license applies only to LitLib code and documentation. It does not grant the right to
redistribute downloaded papers, publisher HTML, or licensed Zotero attachments.

## Access-Control Boundary

LitLib does not bypass CAPTCHA, Turnstile, sliders, OTP, paywalls, purchase/rental pages,
unsupported CARSI service providers, or rate limits. Institution access is supervised,
low-concurrency, and uses the user's own authorization. A challenge pauses for the user; a
purchase-only item stops.

## Storage Policy

`litlib doctor` reports configured project/runtime paths. `LITLIB_REQUIRE_D_DRIVE=1` enforces
D-drive output for explicit single-paper and CNKI destinations; internal large-output paths
derive from the project/runtime configuration. This is a local storage policy, not a general
security requirement. Users without D: should set it to `0` and choose another private disk.
Wheel/global installs use a platform user-data workspace unless `LITLIB_ROOT` is configured;
they never derive writable state from `site-packages`.

## Reporting Vulnerabilities

Before the repository is public, report privately to the maintainer. After GitHub publication,
enable GitHub Private Vulnerability Reporting and use it instead of a public issue for
credential, local-service, arbitrary-file, code-execution, or session-leak problems.
