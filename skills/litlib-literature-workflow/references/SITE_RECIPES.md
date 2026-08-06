# Publisher and Database Recipes

These records come from supervised tests on one Windows/JLU setup. Dates refer to the local
verification session, not a permanent publisher guarantee. Recheck after major site changes.

Labels:

- **Verified:** observed with a complete PDF that passed file and DOI checks.
- **Observed restriction:** the failure/entitlement state was directly observed.
- **Inferred:** a reasonable next attempt that still requires live verification.

## Wiley (`10.1002`, `onlinelibrary.wiley.com`)

**Verified, 2026-08-05.** The article showed full access, but direct retrieval of
`/doi/epdf/{doi}` returned HTML and an unsigned `/doi/pdfdirect/{doi}` could return `403`.

Successful route:

1. Navigate the authenticated browser to `/doi/epdf/{doi}`.
2. Inspect `performance.getEntriesByType('resource')`.
3. Find the resource containing `/doi/pdfdirect/?hmac=...`.
4. Fetch that signed URL from the same Wiley page context.
5. Save only after full PDF validation.

Critical failure: CDP `Network.getResponseBody` returned a viewer byte-range response of
about 262 KB. It began like a PDF but parsed as zero pages and lacked the complete file tail.
Do not equate a PDF response fragment with a complete PDF.

General inference: on viewer-based sites, inspect signed performance resources and range
semantics before adding cookies or changing user agents.

## MDPI (`10.3390`, `www.mdpi.com`)

**Verified, 2026-08-05.** The current article page exposes `a.UD_ArticlePDF`; its href can
end in `/pdf?version=...` rather than the older `.pdf` pattern. Same-origin fetch returned a
complete OA PDF.

An observed Cloudflare `Access Denied` occurred in a new/frequently used session. A public
static resource on `mdpi-res.com` worked for tested journal/DOI formats:

```text
https://mdpi-res.com/d_attachment/{journal}/{journal}-{volume:02d}-{article:05d}/article_deploy/{journal}-{volume:02d}-{article:05d}.pdf
```

The current code recognizes the compact DOI pattern and includes explicit slug mappings for
tested `antib` and `biom` prefixes. Treat static-URL construction for other journals as
**inferred** and validate the DOI in the returned PDF. Do not assume every MDPI DOI encodes
volume/article number identically.

## Elsevier / ScienceDirect (`10.1016`, `sciencedirect.com`)

**Verified platform behavior, 2026-08-05.** An authorized article page exposes a `View PDF`
request resembling `.../pdfft?md5=...&pid=...-main.pdf`. It is session-bound and should be
requested from the authenticated page context.

Observed restrictions:

- `/user/institution/login` can present Cloudflare Turnstile.
- In some automated sessions the visible challenge widget did not render correctly.
- After institution login, reload or navigate back to the article before reading access
  metadata or clicking PDF.

At Turnstile, pause for the user in the visible dedicated browser. WebVPN can fail on strict
Cloudflare sites because the gateway's network/TLS fingerprint differs; institution login
in the direct browser is the preferred fallback.

## Taylor & Francis (`10.1080`, `tandfonline.com`)

**Verified WAYF behavior and observed restriction, 2026-08-05.** The platform required this
institution flow even when campus affiliation was visible:

1. Click `Access through your institution` / the Shibboleth `ssostart` action.
2. On the WAYF page, first select the CARSI/CERNET federation in
   `select#shib-search--fed`.
3. Search only `jilin`, then choose Jilin University.
4. Complete JLU authentication; the tool may fill/submit credentials only on an allowlisted
   HTTPS JLU IdP.
5. Manually review and decide the declaration/terms page. On the attribute-release page,
   scroll/read enough page text to locate `接受` near the
   lower part of the page. A 400-character body sample missed it; 2000+ characters worked.

For DOI `10.1080/17460441.2025.2599178`, the authenticated item exposed HTML but not an
institution-entitled PDF. `dc.Format` reported `text/HTML`, and the page offered a
`$104 / 48 hours` purchase. This is an **item-specific observed restriction**, not proof that
all T&F papers are HTML-only. Stop on an explicit purchase-only state.

## Oxford University Press (`10.1093`, `academic.oup.com`)

**Verified, 2026-08-05.** Article-page navigation followed by the PDF action and an
authorized same-origin/CDN request produced a complete PDF. OUP uses Silverchair
infrastructure; the final PDF can be on a CDN, so capture the link from the page instead of
constructing a permanent CDN URL.

## Springer Nature (`10.1007`, `link.springer.com`)

**Mixed.** Standard OA or entitled articles can use `/content/pdf/{doi}.pdf` and must still
pass validation. A tested *Methods in Molecular Biology* protocol chapter displayed
`Buy Protocol` and did not provide an authorized PDF. Content type matters: stop when the
specific chapter is purchase-only instead of repeatedly retrying the generic endpoint.

## Frontiers (`10.3389`)

**Verified OA behavior, 2026-08-05.** Direct OA retrieval worked. Continue to use OA metadata
and full PDF validation because landing URLs and CDN paths may change.

## CNKI (`cnki.net`, `bar.cnki.net`)

**Verified search; human checkpoint for download, 2026-08-05.** Search worked after hidden
challenge DOM was ignored. PDF/CAJ download triggered a `bar.cnki.net` slider. Direct fetch
without completing the visible challenge returned `来源应用不正确(01)`.

Required response:

1. Keep the dedicated browser visible.
2. Ask the user to complete the slider.
3. Reuse that browser session.
4. Detect whether the actual deliverable is PDF or CAJ.

Never save CAJ bytes with a `.pdf` extension. The current LitLib verified pipeline only
accepts PDF; CAJ conversion/reading is outside this implementation.

Campus access was tested. `litlib cnki login-carsi` exists, but off-campus CNKI CARSI remained
**unverified** in this project session.

## ACS (`10.1021`, `pubs.acs.org`)

**Observed restriction, 2026-08-05.** The JLU CARSI path returned an identity-provider page
stating that the web login service did not support the request. This indicates a service
provider/federation configuration problem, not a CAPTCHA to bypass. Stop that CARSI route.
Campus-IP or a legitimate WebVPN route may be tested separately when available.

## Royal Society of Chemistry (`10.1039`, `pubs.rsc.org`)

**Observed restriction, 2026-08-05.** The dedicated browser profile repeatedly received
`429 Too Many Requests`. The project did not attempt evasion because the source was low
priority. Mark `RATE_LIMITED`, close unnecessary tabs, wait for cooldown, and retest a
single DOI later.

## Generic Institution Pages

The JLU route encountered several post-login states. LitLib detects these pages but does not
accept legal terms or persistent attribute sharing on the user's behalf:

- Terms/declaration page requiring explicit agreement.
- Attribute-release/information-publication page requiring `接受`.
- Elsevier personalization page such as `we now know you're from...`.
- Remembered publisher sessions that redirect back without showing the credential form.

Detect these by both URL and sufficiently long visible body text. Do not assume that absence
of username/password fields means failure; first determine whether the session has already
advanced to a post-login or publisher page.

## WebVPN

JLU WebVPN rewrites a target as roughly:

```text
https://vpn.jlu.edu.cn/https/{publisher-host-token}/{path}
```

The host token and VPN cookies are session material. Never publish or log them. A token must
be learned from the user's authorized portal session and can become stale. Missing token or
ticket should skip the WebVPN route and continue to institution login where appropriate.

WebVPN is not universally superior: strict anti-bot/CDN platforms may reject the gateway.
Use it as one route, not a global proxy for all publishers.
