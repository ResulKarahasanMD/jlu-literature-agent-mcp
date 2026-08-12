# Changelog

## 0.3.0 - 2026-08-12

- Added UniProt accession lookup with sequence, enzyme metadata, and linked DOI/PMID/PMCID
  references.
- Added conservative PDF evidence triage for target fields, figures, tables, and supplementary
  material references.
- Added supplementary artifact discovery/download/validation with a separate staging directory
  and sanitized JSONL manifest.
- Added cellulase measurement schema and maximum-observed selection grouped by construct,
  substrate, metric family, unit, and assay method; missing fields and digitized evidence remain
  explicit instead of being silently filled.
- Added safe substrate aliases and only unambiguous unit conversions; relative activity is not
  silently converted to absolute activity.

## 0.2.1 - 2026-08-06

- Added the personal experience library (`litlib learn list | add | remove | export`):
  successful institutional/CNKI downloads are recorded locally as `domain + route + URL
  pattern + DOI prefix` under `LITLIB_RUNTIME_ROOT\experience\experiences.json`; manual
  observations can be added; unsafe outcomes (PAYWALLED / HUMAN_REQUIRED / RATE_LIMITED /
  FAILED) are never learned; all recorded content is sanitized; personal experience takes
  precedence over the canonical site recipes and is never committed to Git.

## 0.2.0 - 2026-08-06

- Established the final one-skill/two-MCP architecture and portable skill references.
- Made LitLib MCP SQLite and full-text access filesystem read-only.
- Added strict PDF EOF and expected-DOI checks.
- Added Unicode-safe title/author deduplication and explicit metadata conflict failures.
- Required exact Zotero item and PDF verification before `IMPORTED`.
- Added reliable non-zero exits for empty verification and unmet import prerequisites.
- Added route URL/token redaction and disabled cookie export by default.
- Added portable runtime configuration, no-clobber single downloads, CI, release docs, and
  GitHub-safe ignore rules.
- Restricted credential submission to allowlisted HTTPS JLU IdP hosts and made terms/
  attribute release human-only.
- Added terminal `PAYWALLED`, hard institutional batch limit 10, no-clobber batch recovery,
  and partial-failure exit codes.
- Replaced PyMuPDF with BSD-licensed pypdf and strengthened first-page/first-three-page PDF
  identity checks.

## 0.1.0 - 2026-08-05

- Initial local workflow for metadata, OA/institution retrieval, PDF validation, RIS import,
  Zotero Local API reads, and publisher-route experiments.
