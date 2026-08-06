# Third-Party Components

## Runtime Dependencies

Python dependencies are declared and locked in `pyproject.toml` and `uv.lock`. Their upstream
licenses remain their own; the repository's MIT license does not relicense them. Runtime PDF
parsing uses BSD-3-Clause `pypdf`; tests generate synthetic PDFs with BSD-licensed ReportLab.
PyMuPDF was removed before public release to avoid its AGPL/commercial distribution ambiguity.
Release CI should still add an automated dependency-license report before publishing binaries.

A `pip-licenses` audit of the locked Python 3.13 development environment on 2026-08-06 found
MIT, BSD, Apache-2.0, PSF, MIT-CMU, and MPL-2.0 (`certifi`) packages and no GPL/AGPL runtime
dependency. Re-run this audit whenever `uv.lock` changes; package metadata is evidence to
review, not a substitute for the authoritative upstream license text.

## Reviewed Projects and Plugins

| Component | Upstream claim / observed license | Use in LitLib | Distribution status |
|---|---|---|---|
| `zju-paper-fetcher` | MIT | CDP/WebVPN design reference only | No copied package/binary |
| `zju-literature-downloader` | MIT | Workflow reference only | No copied package/binary |
| `pygetpapers` | Apache-2.0 | Europe PMC workflow reference | Not bundled |
| `cli-anything-zotero` v1.2.1 snapshot | Apache-2.0 | Security evaluation only | Rejected; not installed/bundled |
| ZotSeek | README says MIT; repository license unresolved below | External semantic MCP | Link to upstream release; never bundle XPI |

## ZotSeek License Check

Checked 2026-08-06 against `introfini/ZotSeek`:

- Upstream README says `MIT License - see LICENSE`.
- `https://raw.githubusercontent.com/introfini/ZotSeek/main/LICENSE` returned 404.
- GitHub repository API returned `license: null`.
- The locally downloaded XPI did not provide a license file suitable for redistribution.

Conclusion: users may install ZotSeek directly from its upstream Releases according to the
upstream author's terms, but LitLib must not redistribute the XPI or state that the binary is
verified MIT until upstream adds or identifies an authoritative license file.

## Rejected Zotero Bridge

The evaluated `cli-anything-zotero` bridge was not adopted because its snapshot exposed a
local HTTP endpoint that evaluated submitted JavaScript without an authentication boundary,
and utility code directly modified `zotero.sqlite`. Both violate LitLib's threat model.

Supported integration remains:

- Read through Zotero Local API.
- Human-gated RIS import with `L1` attachment paths.
- Post-import verification through read-only Local API.
- No direct SQLite writes and no arbitrary-code bridge.

## Publisher Content

Publisher pages, PDF files, metadata responses, and CNKI CAJ files are not third-party source
dependencies and are never part of the public repository. Test fixtures must be synthetic or
minimal metadata representations that do not reproduce protected full text.
