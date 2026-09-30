<!--
---
title: "SQL"
description: "Checked-in SQL: the provisional pilot analytical views and the idempotent PostgreSQL ingestion DDL"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-09-29"
version: "1.1"
status: "Active"
tags:
  - type: directory-readme
  - domain: dataset
  - tech: [duckdb, postgres, sql]
related_documents:
  - "[Pilot Analysis Contract](../docs/pilot-analysis-contract.md)"
  - "[Ingestion Contract](../docs/ingestion-contract.md)"
  - "[Scripts](../scripts/README.md)"
---
-->

# SQL

Checked-in SQL. Two families live here: the provisional pilot analytical
views, which `pilot_database.py` executes against the versioned per-run
Parquet layer on every build, and the idempotent PostgreSQL ingestion DDL for
the `wifi_beacon_survey` projection. Nothing in the pilot family is durable
state. The ingest family is a projection whose recovery is a fresh drain from
files.

---

## 1. Contents

```
sql/
├── ingest/
│   ├── up.sql              # Idempotent DDL: survey/archive base tables, ingest ledger, derived views
│   ├── down.sql            # Drops the four schemas; test database only
│   └── README.md           # Interior README: apply and reverse instructions
├── pilot/
│   └── pilot_views.sql     # Staging-table contract and the twelve pilot_* views
└── README.md               # This file
```

---

## 2. Files

| File | Description | Status |
|------|-------------|--------|
| [ingest/up.sql](ingest/up.sql) | Creates `wifi_beacon_survey`'s four schemas from one base-table definition (`survey` and `archive` identical), the `ingest` slot/attempt/load ledger, and the `derived` views. Safe to apply repeatedly; defined by the [ingestion contract](../docs/ingestion-contract.md) | ✅ Active |
| [ingest/down.sql](ingest/down.sql) | Drops the four schemas so tests can prove the up-script builds from empty and leaves nothing behind. **Test database only** - production recovery is the operator's `DROP DATABASE` and a fresh drain | ✅ Active |
| [pilot/pilot_views.sql](pilot/pilot_views.sql) | Defines the twelve stable `pilot_*` views required by the contract: seven base views preserving source grain, plus run health, hourly/band/capability metrics, and 6 GHz evidence. Trend views restrict to `stg_run_health.in_trend`, which is true only for completed-sweep pilot-series attempts | ✅ Active |

---

## 3. Conventions

Staging tables (`stg_*`) are recreated by `scripts/pilot_database.py` from
Parquet on every build; this directory never creates them. Metric views carry
their denominators as explicit columns so every ratio in the briefing names
both numbers. Pilot view names are frozen by `pilot_contract.py`; renaming
one is a contract change, not a refactor. The ingest DDL is likewise frozen
by `scripts/ingest_contract.py` and the ingestion contract document.

---

## 4. Related

| Document | Relationship |
|----------|--------------|
| [Pilot Analysis Contract](../docs/pilot-analysis-contract.md) | The provisional contract the pilot views implement |
| [Ingestion Contract](../docs/ingestion-contract.md) | The contract the ingest DDL implements |
| [Scripts](../scripts/README.md) | The builder, updater, and loader that execute this SQL |
