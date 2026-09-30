<!--
---
title: "Ingestion Contract"
description: "How the collector's per-run files project into PostgreSQL: schemas, ledger, routing, fingerprints, and the derived views"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-09-29"
version: "1.0"
status: "Active"
tags:
  - type: specification
  - domain: [dataset, instrument]
  - tech: [postgres, python]
related_documents:
  - "[Repository AGENTS.md](../AGENTS.md)"
  - "[Pilot Analysis Contract](pilot-analysis-contract.md)"
  - "[Ingest DDL](../sql/ingest/README.md)"
  - "[Backfill Reconciliation](ingestion-backfill-reconciliation.md)"
---

# Ingestion Contract

PostgreSQL is a rebuildable projection of the collector's per-run files.
Retained PCAP, `frequencies.tsv`, `aggregate.tsv`, and `instrument.json` under
the pilot data root remain the source of record. The database may be dropped
and reconstructed by draining the same files again; no row in it is evidence.

The loader reads only the three per-run files: `instrument.json`,
`frequencies.tsv`, and `aggregate.tsv`. It never reads Parquet, DuckDB, Arrow,
PCAP, or the per-frequency `freq-*.tsv` summaries - those are inputs to
`aggregate.tsv`, and loading them would double every observation.

---

## 1. Database and schemas

Database `wifi_beacon_survey` on pgsql01, with four schemas:

| Schema | Contents |
|--------|----------|
| `survey` | Base scalars from US-domain runs |
| `archive` | The same base tables, holding off-domain runs |
| `ingest` | The UTC slot, attempt, and load ledger |
| `derived` | Views computed from the base tables |

The `survey` and `archive` base tables are generated from one definition in
[`sql/ingest/up.sql`](../sql/ingest/up.sql); a structural difference between
the two schemas is a defect. The DDL is idempotent to apply. Its down-script
drops the four schemas and is tested against `wifi_beacon_survey_test` only;
no executor ever drops a database or runs the down-script in production.

## 2. Base tables

Three base tables in each of `survey` and `archive`:

| Table | Grain |
|-------|-------|
| `runs` | One row per completed sweep: run identity, `started_utc`, the slot UTC hour, typed columns for every `instrument.json` field, and the raw document as `jsonb` |
| `frequencies` | One row per `frequencies.tsv` data row: every source column typed, plus the run id and the source row ordinal. Sampled-empty and regulatory-skip rows are included |
| `observations` | One row per `aggregate.tsv` data row: every source column typed, plus the run id and the source row ordinal |

**Base tables hold source values only.** No derived columns, and no
normalisation beyond type conversion. The one deliberate repair: PostgreSQL
text cannot store NUL bytes, and beacon SSIDs from the air occasionally
carry them, so the loader strips NUL characters from text cells; nothing
else is ever altered. The loader never updates or deletes a
base row after commit; a changed source file for an already-loaded run is a
`source_changed` finding for the operator, never a reload.

Null semantics follow the [pilot analysis contract](pilot-analysis-contract.md)
section 3: an empty SSID is a hidden network and is stored as an empty string,
never null; an unresolved numeric is null, never zero. Every other empty
source cell is null. `usb_speed_mbps` is the one integer the source defines
beyond doubt (the sysfs speed file); every other instrument field that is not
inherently boolean or numeric is text.

Run identity is the run directory name. A run's `instrument.json` schema is
`wifi-beacon-survey/instrument/1` or `/2`; both load into the same typed
columns, with the `/2`-only keys null on `/1` rows.

## 3. The ledger (`ingest`)

| Table | Grain |
|-------|-------|
| `slots` | One row per expected UTC hour, from the series start through the last fully elapsed UTC hour |
| `attempts` | One row per run directory at or after the series start, carrying its instrument fields, attempt state, and disposition |
| `loads` | One row per load action: the attempt, the per-file SHA-256 of the three inputs, the outcome, the loader version, and a timestamp |

A slot is the attempt's `started_utc` floored to the UTC hour, stored as a
`timestamptz`. An attempt whose `started_utc` is missing or unreadable has
no slot: its ledger row carries a null slot and it never joins a slot in
`slot_health`. An attempt inside the current incomplete hour (a running run)
owns its hour's slot even though that hour is not expected yet; the attempt
is pending and never judged. **Slot identity is always UTC.** Local
wall-clock slot
arithmetic would map two real hours onto one slot at the 2026-11-01
fall-back; the collector's local-time directory names are a known, separately
tracked collision risk and do not affect slot identity here.

The series start is the approved hourly-series beginning
`20260827-090003`, whose `started_utc` is `2026-08-27T13:00:03Z`; expected
slots are the UTC hours from `2026-08-27T13:00:00Z` through the last fully
elapsed UTC hour. The current incomplete hour is never judged. The two
commissioning runs predate the series start and are excluded by the same
rule.

**Attempt states** derive from `run_status` plus file readiness:

| State | Meaning |
|-------|---------|
| `completed` | Terminal sweep with parseable `frequencies.tsv` and `aggregate.tsv` |
| `receiver_absent_skip` | `run_status=skipped_no_interface` |
| `refused` | `run_status=refused_regulatory_domain`: the collector could not establish the declared domain and refused the run |
| `failed` | `run_status=failed` |
| `running` | `run_status=running` or no `instrument.json` terminal status yet |
| `malformed` | Missing or unreadable `instrument.json`, `run_status=sweep` with missing or unparseable TSVs, headers that fail contract validation, or values that fail their declared types |

**Dispositions:**

| Disposition | Meaning |
|-------------|---------|
| `survey` | Loaded into `survey` |
| `archive` | Loaded into `archive` |
| `not_loaded` | Skip, refusal, failure, or malformed: a recorded outcome with no base rows |
| `pending` | Running: readiness comes from a terminal `run_status`, never from the clock or file existence alone |
| `unresolved_domain` | A completed run whose effective domain is missing or unreadable: not loaded, held for a human |

**Routing.** The host's current domain is never an input. For
`instrument/1`, the run's effective domain is `regulatory_domain_phy` when
non-null, otherwise `regulatory_domain` (the run-start snapshot). For
`instrument/2`, a run routes to `survey` only when both its discovery-time
domain (`regulatory_domain_at_discovery`) and its post-sweep domain
(`regulatory_domain_post_sweep`) equal the declared US. Every other completed
run routes to `archive`. A missing or unreadable domain is
`unresolved_domain` and is not loaded.

**Fingerprints.** The loader records a SHA-256 per input file (the three
columns of `ingest.loads`); the triple is the attempt's fingerprint. An
unchanged fingerprint makes a drain a no-op. A changed fingerprint on an
attempt already loaded records the outcome `source_changed` and leaves its
base rows untouched.

**Cross-file checks.** Before loading a completed run, the loader verifies
that every `aggregate.tsv` band and frequency appears in `frequencies.tsv`
as `sampled`, and that each manifest row's `beacon_count` and `bssid_count`
equal the aggregate beacon sum and distinct-BSSID count for that band and
frequency. The relationship was verified across the whole retained archive
before enforcement - 757 completed runs, zero mismatches - so a violation is
a load gate: the run is not loaded, the outcome `check_failed` is recorded
in the ledger, and the exit is non-zero for the operator to judge.

**Load outcomes.** `ingest.loads.outcome` is `loaded` (base rows committed
with the ledger record in one transaction), `source_changed` (no reload),
`check_failed` (cross-file gate refused the load), or `failed` (the
transaction failed; base rows rolled back, failure ledgered, next drain
retries). The loader is [`scripts/ingest_load.py`](../scripts/ingest_load.py)
and stamps its version into every row.

**Missing hours.** An expected slot that has fully elapsed with no attempt is
`no_run` in `derived.slot_health`. It is a gap with a reason, never zero.

**Concurrency.** Each drain takes a session-level PostgreSQL advisory lock
for the duration of the drain, so two concurrent invocations serialize and
never double-load. Per-run work commits base rows and ledger records together
in one transaction, or not at all.

**Exit status.** The loader exits non-zero when any load failed or any
`source_changed` occurred in the drain. Archived, skipped, refused, and
missing attempts are outcomes, not errors.

## 4. Derived views

Views only; there are no tables or materialised views in this unit. All
definitions live in [`sql/ingest/up.sql`](../sql/ingest/up.sql).

| View | Content |
|------|---------|
| `derived.slot_health` | Every expected slot with its attempt count, states, and dispositions; a missing hour is a `no_run` row |
| `derived.run_metrics` | Per `survey` run: distinct BSSIDs, beacons, frequency outcome counts by `sample_status`, and mean RSSI |
| `derived.band_coverage` | Per `survey` run and band: frequencies attempted, sampled, sampled-empty, regulatory-skipped, and capture-errored, plus BSSIDs and beacons |

`run_metrics` mirrors the legacy `pilot_hourly_metrics` definitions so the
backfill cross-check compares like with like: `observed_bssids` is
`COUNT(DISTINCT bssid)` over the run's observations; `beacon_frames` is
`COALESCE(SUM(beacons), 0)`; `mean_rssi_dbm` is `ROUND(AVG(rssi_mean_dbm), 1)`
over the non-null per-observation means; the four outcome counts group
manifest rows by `sample_status`; `manifest_frequencies` is the manifest row
total. `band_coverage` mirrors `pilot_band_metrics`: `attempted_frequencies`
counts every manifest row in the band - a regulatory-skip row is a recorded
attempt refused at dwell 0, not an unlisted frequency.

---

*Interpretation boundary:* this database projects what the collector
recorded. Capability flags, RNR, and BSS Load exist only in the legacy
Parquet layer today and are out of scope here; they arrive later, from
retained PCAP, into `derived` tables.
