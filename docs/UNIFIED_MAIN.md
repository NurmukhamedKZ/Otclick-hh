# Unified main contract

`main` is the canonical product line.

It must retain the persistent vacancy funnel (manual/automatic search, scoring,
selection rules, review/rejection, cover letters, send queue and statistics), the
single-user noncommercial UI, and the production deployment contract (loopback
frontend/API/Kong ports, Caddy behind the external reverse proxy, exact-SHA
content-addressed GHCR components, Release fallback, safe DB migration backup,
and runtime repair without local application builds).

The product frontend keeps its standalone `node server.js` runtime and same-origin
browser configuration. `docker-compose.prebuilt.yml` is intentionally a no-op
compatibility override; it must not replace the product frontend entrypoint.

Product migrations 034..041 belong to the vacancy pipeline. The cover-letter
prompt-version migration follows them as 042.
