<!--
---
title: "SQL"
description: "Checked-in SQL defining the provisional pilot analytical views"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-08-28"
version: "1.0"
status: "Active"
tags:
  - type: directory-readme
  - domain: dataset
  - tech: [duckdb, sql]
related_documents:
  - "[Pilot Analysis Contract](../docs/pilot-analysis-contract.md)"
  - "[Scripts](../scripts/README.md)"
---
-->

# SQL

Checked-in SQL defining the analytical semantics of the provisional pilot
surface. `pilot_database.py` executes `pilot/pilot_views.sql` against the
versioned per-run Parquet layer on every build, so a fresh database is always
reproducible from files plus this directory. Nothing here is durable state,
and none of it is a PostgreSQL schema.

---

## 1. Contents

```
sql/
├── pilot/
│   └── pilot_views.sql   # Staging-table contract and the twelve pilot_* views
└── README.md             # This file
```

---

## 2. Files

| File | Description | Status |
|------|-------------|--------|
| [pilot/pilot_views.sql](pilot/pilot_views.sql) | Defines the twelve stable `pilot_*` views required by the contract: seven base views preserving source grain, plus run health, hourly/band/capability metrics, and 6 GHz evidence. Trend views restrict to `stg_run_health.in_trend`, which is true only for completed-sweep pilot-series attempts | ✅ Active |

---

## 3. Conventions

Staging tables (`stg_*`) are recreated by `scripts/pilot_database.py` from
Parquet on every build; this directory never creates them. Metric views carry
their denominators as explicit columns so every ratio in the briefing names
both numbers. View names are frozen by `pilot_contract.py`; renaming one is a
contract change, not a refactor.

---

## 4. Related

| Document | Relationship |
|----------|--------------|
| [Pilot Analysis Contract](../docs/pilot-analysis-contract.md) | The provisional contract these views implement |
| [Scripts](../scripts/README.md) | The builder and updater that execute this SQL |
