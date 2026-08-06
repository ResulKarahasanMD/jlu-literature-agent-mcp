# Acquisition Decision Tree

This reference separates observations that generalize from publisher-specific recipes.
Apply each step only within the user's authorized access rights.

## 1. Establish the Target

Prefer DOI, then PMID/PMCID/arXiv, then exact title. Normalize DOI URLs such as
`https://doi.org/10.xxxx/...` before queueing. Record the source database and intended item
type. A dataset, protocol chapter, correction, supplement, book chapter, and journal article
can share publisher infrastructure but require different retrieval logic.

Before downloading, answer:

- Is the target a paper PDF, HTML article, CAJ file, supplement, or dataset?
- Is it OA, institution-entitled, purchase-only, or unknown?
- Is the user on campus, off campus with CARSI, or using WebVPN?
- Does the task already exist in LitLib or Zotero?

## 2. Try Routes in This Order

1. **OA discovery:** arXiv, MDPI public static candidate where recognized, Unpaywall,
   Europe PMC, OpenAlex, then a Crossref link only when its license metadata proves OA.
2. **Direct HTTP candidate:** use a known stable PDF endpoint only when authorization and
   content type are appropriate.
3. **Visible browser direct:** resolve DOI, inspect the rendered article page, and reuse the
   user's current campus or authenticated publisher session.
4. **WebVPN:** only when a valid JLU ticket and a publisher token already exist. A missing
   token is a skipped route, not a reason to abort all later routes.
5. **Institution login:** resolve the actual DOI landing host, select Jilin University in the
   WAYF/CARSI federation, authenticate only on an allowlisted HTTPS JLU IdP, pause for the
   user to review and manually decide terms/attribute release, return to the publisher, then
   retry the PDF.

Each candidate must be validated independently. A failed OA landing page must not block the
next OA provider. A failed WebVPN route must not block a direct institution-login route.

## 3. Diagnose the Returned Object

Inspect in this order:

1. HTTP status and final URL.
2. `Content-Type`, `Content-Length`, and `Content-Disposition`.
3. First five bytes (`%PDF-`) and `%%EOF` near the tail.
4. Parsed page count and extracted text.
5. Expected DOI in the first three pages, a conflicting page-1 DOI, and supplement indicators.

Interpret common combinations:

| Observation | Likely cause | Next action |
|---|---|---|
| `200 text/html` from a PDF URL | Login page, anti-bot page, HTML viewer, or HTML-only entitlement | Inspect visible page and authentication state; do not save as PDF |
| `206 application/pdf`, very small, zero pages | Viewer range fragment | Obtain the full resource through same-origin fetch, native download, or completed range assembly |
| `%PDF-` but no `%%EOF` | Truncated transfer or partial response | Reject and retry another route |
| Valid PDF but target DOI absent | Wrong paper, supplement, issue front matter, or extraction failure | Reject by default; inspect manually before any override |
| One different DOI in first-page header | Wrong article | Reject immediately |
| `403` direct but article visible in browser | Signed URL, origin/session requirement, or anti-bot policy | Fetch from the same page origin or trigger the publisher's native download |
| `429` | Rate limit | Stop, cool down, and retain `RATE_LIMITED` state |
| Purchase/rental text | No current entitlement | Stop and report purchase-only |

## 4. Browser Escalation Ladder

When a browser is needed, use the least invasive method that preserves the authorized
session:

1. Read `citation_pdf_url`, `dc.*`, JSON-LD, canonical URL, and visible PDF anchors.
2. Navigate to the publisher's PDF viewer and inspect `performance.getEntriesByType('resource')`.
3. Prefer browser-native download when it produces a complete file.
4. Use a same-origin page-context `fetch` for a signed or session-bound PDF URL.
5. Use CDP response bodies only after checking status and transfer semantics. A viewer often
   requests byte ranges; `Network.getResponseBody` may return one fragment rather than the
   complete PDF.

Do not inject credentials into arbitrary third-party pages. Credentials may only be read
from Windows Credential Manager and submitted to the expected JLU identity-provider host.

## 5. Authentication Decision

Distinguish four failures:

- **No publisher session:** click the institution-access entry and continue through WAYF.
- **Human challenge:** wait in the visible browser. Do not loop automated retries.
- **Unsupported SP:** the JLU IdP says the service/request is unsupported; stop CARSI for
  that publisher and report campus-IP/WebVPN alternatives.
- **Authenticated but no PDF entitlement:** article HTML may be readable while PDF remains
  purchase-only. Treat entitlement separately from successful login.

After authentication, reload or revisit the article. Some publishers do not update access
metadata in the already-open document.

## 6. Generalizing to a New Publisher

For an unknown host, do not immediately add a hard-coded DOI-prefix route. Collect:

- DOI prefix and actual redirect host.
- Article type and OA/license metadata.
- Stable page metadata/DOM selector for the PDF action.
- Whether the PDF URL is same-origin, signed, short-lived, or a CDN URL.
- Whether direct HTTP, native navigation, same-origin fetch, or institution login worked.
- Challenge, rate-limit, and purchase-only indicators.
- A complete validated PDF from a user-authorized session.

Then implement the smallest adapter and a fixture-based test. Keep host detection separate
from DOI-prefix detection because publishers acquire journals and redirect hosts change.

Useful inferred attempts, in order:

1. Resolve DOI and inspect standards-based metadata.
2. Inspect a visible PDF link and its target after a click.
3. Look for a signed PDF resource in the performance timeline.
4. Compare a successful browser request with the failing direct request: origin, referer,
   cookies, method, status, range semantics, and redirect chain.
5. Check whether the item is HTML-only or a non-article content type before writing code.

Never generalize a workaround from one DOI until at least one additional article on the
same platform is checked. Record unconfirmed routes as `inferred`, not `verified`.

## 7. Recovery and Delivery

After a crash:

```powershell
litlib queue recover
litlib queue recover --failed
litlib queue recover --paused
```

Use `--failed` only after the root cause was corrected and retry limits permit it. Use
`--paused` only after a human challenge or cooldown is complete.

Before delivery:

```powershell
litlib verify
litlib status --verbose
```

A PDF on disk without a task file record is a recovery artifact, not a completed download.
An RIS file without a verified Zotero parent item and PDF attachment is not `IMPORTED`.
