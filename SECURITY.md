# StockTool Security Policy

## Scope

StockTool is a local, research-only Windows application. It does not place
orders, connect to a broker, or require a cloud account. Runtime data stays in
the user-data directory selected by `STOCK_TOOL_USER_DATA_DIR` (or the local
default when that override is absent).

## Reporting a vulnerability

Do not include credentials, private portfolio data, local documents, or report
contents in an issue. Provide a minimal, redacted reproduction to the product
owner through the established private support channel. The product owner
coordinates triage and any disclosure decision.

## Security boundaries

- Provider credentials are read from the process environment only and must not
  be serialized into reports, caches, logs, installers, or source archives.
- Research-library document registrations retain reference metadata and a
  content hash; they do not copy document payloads or perform OCR.
- Release staging, installers, and source archives are allowlisted and scanned
  for private data, credential material, caches, logs, and traversal entries.
- The StockTool v1.4.0 Windows installer is deliberately unsigned. It must be
  distributed with an explicit unknown-publisher warning and must never be
  presented as code-signed.

## Supported baseline

The formal acceptance baseline is StockTool v1.4.0, accepted through Sprint
33.1.1 and promoted on 2026-08-29.
