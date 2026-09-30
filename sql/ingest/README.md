<!--
---
title: "Ingest DDL"
description: "Idempotent PostgreSQL DDL for the wifi_beacon_survey projection: survey and archive base tables, the ingest ledger, and derived views"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-09-29"
version: "1.0"
status: "Active"
tags:
  - type: directory-readme
  - domain: dataset
  - tech: postgres
related_documents:
  - "[Ingestion Contract](../../docs/ingestion-contract.md)"
  - "[SQL root](../README.md)"
---

# Ingest DDL

Idempotent DDL for the `wifi_beacon_survey` PostgreSQL projection, generated
from one definition: the `survey` and `archive` schemas carry identical base
tables, the `ingest` schema carries the slot/attempt/load ledger, and the
`derived` schema carries views only. Structure and semantics are defined by
the [ingestion contract](../../docs/ingestion-contract.md).

| File | Purpose |
|------|---------|
| `up.sql` | Creates the four schemas, base tables, ledger, and views. Safe to apply repeatedly; a second apply leaves the catalog identical |
| `down.sql` | Drops the four schemas. **Test database only** - no executor ever runs this against `wifi_beacon_survey`; production recovery is the operator's `DROP DATABASE` and a fresh drain |

Apply:

    psql -d wifi_beacon_survey -f up.sql

Credentials come from the scoped Doppler runtime, per
`docs/data-science-infrastructure-2026-04-07.md`:

    doppler run --project ml01 --config dev -- psql -h "$PGSQL01_HOST" \
        -U "$PGSQL01_ADMIN_USER" -d wifi_beacon_survey -f up.sql
