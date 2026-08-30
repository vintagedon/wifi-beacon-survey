<!--
---
title: "Pilot Analysis Contract"
description: "Provisional derived-data contract for the hourly pilot: series eligibility, attempt states, versioned per-run artifacts, and the rebuildable analytical surface"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-08-28"
version: "1.0"
status: "Active"
tags:
  - type: specification
  - domain: [dataset, analysis]
  - tech: [python, tshark, parquet, duckdb]
related_documents:
  - "[Repository AGENTS.md](../AGENTS.md)"
  - "[Hourly Collection Review](2026-08-27-hourly-collection-review.md)"
  - "[Scripts](../scripts/README.md)"
---
-->

# Pilot Analysis Contract

**Status: provisional and rebuildable.** Everything in this document defines a
*derived* analytical surface over retained evidence. Retained PCAP,
`frequencies.tsv`, `aggregate.tsv`, and `instrument.json` under the external
data root remain the source of record. The Parquet layer and the DuckDB
database described here can be dropped and regenerated from those files at any
time; no row in them is evidence. This contract is not a database adoption
decision, and it contains no PostgreSQL schema.

The machine-enforced form of this contract is
[`scripts/pilot_contract.py`](../scripts/pilot_contract.py). That module is the
single source of truth: the enrichment stage, the database builder, the
briefing renderer, and the test suite all import series boundaries,
classification rules, and table definitions from it. No other code may restate
eligibility logic.

---

## 1. Series identity

| Item | Value |
|------|-------|
| Approved pilot series start | `20260827-090003` |
| Commissioning/reference runs | `20260827-054734`, `20260827-060013` |
| Derived schema identifier | `wifi-beacon-survey/pilot-derived/1` |
| Per-run derived root | `<data-root>/derived/pilot/v1/runs/<run-id>/` |
| Persistent database | `<data-root>/derived/pilot.duckdb` |
| Canonical briefing | `<data-root>/reports/pilot-latest.md` |

`<data-root>` is `/opt/agents/repos/storage-mounted/wifi-beacon-survey`. Every
path above is a CLI-overridable default so tests run against scratch trees and
never write into the live pilot or the canonical report.

### 1.1 Run identity

A run's identity is its directory name, a timestamp of the form
`YYYYMMDD-HHMMSS` written by the collector in host-local time. When
`instrument.json` is present, its `started_utc` is the authoritative capture
moment for that run and takes precedence over any inference from the directory
name; the directory name remains the identity key that ties derived artifacts
back to source paths. The two commissioning runs predate `instrument.json` and
are identified by name alone.

### 1.2 Series eligibility

Every direct child of `pilot/` receives exactly one membership and one reason:

| Membership | Rule |
|------------|------|
| `commissioning_reference` | Directory name is one of the two named commissioning runs. Always excluded from pilot trends; shown separately. |
| `pilot_series` | Directory name is at or after `20260827-090003` (string compare is exact for the fixed-width format). These are the eligible attempts. |
| `outside_series` | Anything else: names that are not run timestamps, non-directories, or pre-series runs that are not named commissioning runs. Never enters the inventory that feeds the briefing. |

An eligible attempt is included in collection-health counts **regardless of
its state**. A failed, skipped, running, or malformed attempt is never
silently dropped; that is the entire point of the health model.

## 2. Attempt states

`instrument.json`'s `run_status` discriminates the collector's own outcomes;
file evidence refines them. These states are deliberately distinct:

| State | Meaning | Discriminator |
|-------|---------|---------------|
| `completed_sweep` | The sweep ran to completion; manifest and aggregate are parseable | `run_status=sweep` plus parseable `frequencies.tsv` and `aggregate.tsv` |
| `skipped_no_interface` | Receiver absent at run start; skip record written | `run_status=skipped_no_interface` |
| `failed` | Collector exited before completing the sweep | `run_status=failed` |
| `running` | In progress at the last instrument write | `run_status=running` |
| `malformed` | A series member whose evidence is incomplete or unreadable | Missing/unparseable `instrument.json`; `run_status=sweep` with a missing or unparseable manifest or aggregate; unknown `run_status` |
| `missing_hourly_slot` | An expected hour with no attempt in the tree | Expected-slot reconciliation, not a directory |

A malformed input is classified and reported. It is never repaired in place,
and its state is never folded into `completed_sweep` or `missing_hourly_slot`.

### 2.1 Expected hourly slots

Slot identity is the local wall-clock hour, matching how the collector names
runs. Expected slots run from the series-start hour through the **most recent
elapsed local hour boundary**. The current, partially elapsed hour is never
expected: inventing a slot for it would report the instrument missing while it
is mid-collection.

Known limitation, accepted for the pilot window: slot arithmetic is naive
local-hour arithmetic. A DST fall-back would map two real hours onto one slot
id; the pilot window contains no DST transition.

### 2.2 Collection health

Collection health is the union of (a) every discovered pilot-series attempt
with its state and (b) every expected slot not covered by an attempt, as a
`missing_hourly_slot` row. Commissioning runs appear in health flagged
`in_trend=false` so they stay visible without entering any trend denominator.
`in_trend` is true only for `completed_sweep` attempts.

## 3. Derived artifacts (schema version 1)

One derived generation per run lives at
`derived/pilot/v1/runs/<run-id>/`. A per-run output is **authoritative only
when its derivation manifest exists and is complete**. Outputs without a
manifest are staging residue and are ignored by every consumer.

The executor-chosen file names for the logical artifacts, mapped here so
consumers need not guess:

| Logical artifact | File | Grain |
|------------------|------|-------|
| Run | `run.parquet` | Exactly one row per run: identity, source path, classification, source timing/status, eligibility, input completeness, extraction status, and extractor/tool versions |
| Frequencies | `frequencies.parquet` | Exactly one row per source `frequencies.tsv` row, including `sampled_empty` and regulatory skips |
| Observations | `observations.parquet` | Exactly one row per source `aggregate.tsv` row; no entity consolidation |
| IE capabilities | `ie_capabilities.parquet` | One row per run and observed BSSID: sorted raw standard/extension element sets plus explicit presence flags |
| RNR | `rnr.parquet` | One row per RNR-carrying beacon frame (at minimum): source PCAP, frame number/time, transmitter, raw extracted values, field-resolution state, structural status; safely paired single occurrences may carry normalized target band/frequency |
| BSS Load | `bss_load.parquet` | One row per BSS-Load-carrying beacon frame with source PCAP, frame number/time, BSSID, station count, utilization, admission capacity where resolved, and raw values |
| Field resolution | `field_resolution.parquet` | One row per logical requested field: the installed tshark field selected, or all candidates that failed to resolve |
| Derivation manifest | `manifest.json` | Schema/extractor version, source file list with SHA-256 and size, output row counts and SHA-256, status, errors. Written last via atomic rename |

Column lists live in `TABLES` in `pilot_contract.py`. Null semantics follow
the source: an empty SSID is a hidden network (empty string, not null);
unresolved numeric values are null, never zero.

### 3.1 Field-resolution semantics

These four outcomes are different facts and are recorded differently:

| Outcome | Meaning | Where recorded |
|---------|---------|----------------|
| Unresolved dissector field | No candidate display-filter name exists on the installed tshark build. The logical field was never queried. | `field_resolution.parquet` with status `unresolved` and all candidate names. An extraction-quality finding. |
| Resolved field with zero values | The field exists on this build and was queried; no frame carried it. | `field_resolution.parquet` with status `resolved`, zero values in the data tables. A potential environmental observation. |
| Absent Information Element | A specific frame or BSSID does not carry a known element. | Presence flags in `ie_capabilities.parquet` and null values in `rnr.parquet`/`bss_load.parquet`. |
| Extraction failure | tshark or the derivation pipeline failed on this run. | Manifest `status=failed` with the error. The run keeps its explicit failure record; nothing is silently absent. |

A failed lookup is never reported as an environmental absence. Three defects
in this repository's history came from exactly that confusion.

### 3.2 Repeated-field safety

tshark joins repeated field occurrences with commas. A beacon carrying several
RNR neighbor-info blocks therefore produces multi-valued cells whose internal
pairing is unknown without hierarchical TLV parsing. The derived layer keeps
such a frame as **one row with `structure_status=unpaired_multi_occurrence`**
and never positionally invents pairs into neighboring columns. Only a
single-occurrence frame may carry normalized target band/frequency fields.

### 3.3 BSS Load packet identity

Every BSS Load row carries its source PCAP, frame number, and frame time. A
fixture or live row missing those fields fails validation rather than being
emitted as an apparently longitudinal value: utilization without packet time
is not a series.

### 3.4 Capability presence

HE, HE 6 GHz, EHT, and Multi-Link presence is derived from the extension
element namespace (`wlan.ext_tag`), not from `wlan.tag.number == 255`.
Wireshark does not report extension elements in `wlan.tag.number`, so gating
on 255 hides every Wi-Fi 6/7 advertisement and makes a rich environment look
legacy.

## 4. Idempotence and change detection

The updater recognizes an already-processed run by **source identity**: the
manifest records SHA-256 and size for `instrument.json`, `frequencies.tsv`,
`aggregate.tsv`, and every `freq-*.pcap`; the updater recomputes that identity
and reprocesses the run when anything differs, when the manifest is missing or
unsuccessful, when versions changed, or when recorded output hashes/row counts
no longer match the files on disk. An unchanged successful run is never
re-parsed; a new or changed input cannot be mistaken for an already processed
run.

## 5. Rebuild path

The rebuild order is always: retained evidence → versioned per-run Parquet →
DuckDB → Markdown briefing. Any stage can be rebuilt from the stage above it.
A change in column selection or grain produces a **new derived schema version**
(a new `derived/pilot/vN/` generation and a new schema identifier) and
rebuilds the database from files; raw evidence is never migrated or rewritten.
Regenerating the derived layer is expected behavior, not a failure.

Derived generations that are abandoned mid-write or superseded with a defect
move to a recycle-bin location; they are never deleted, and evidence is never
a cleanup target.

## 6. Analytical surface

The DuckDB database exposes exactly these stable view names:

| View | Content |
|------|---------|
| `pilot_runs` | One row per derived run with classification, status, and eligibility |
| `pilot_frequencies` | Source-frequency grain with provenance |
| `pilot_observations` | Source-observation grain with provenance |
| `pilot_ie_capabilities` | Per run and BSSID capability presence |
| `pilot_rnr` | Frame-grain RNR records with structural status |
| `pilot_bss_load` | Frame-grain BSS Load with packet identity |
| `pilot_field_resolution` | Per run and logical field resolution state |
| `pilot_run_health` | Every eligible attempt and every expected slot, including missing |
| `pilot_hourly_metrics` | Per-run BSSID/beacon/frequency/signal summaries; trend denominators exclude commissioning and non-success runs |
| `pilot_band_metrics` | Per run and band summaries with denominators |
| `pilot_capability_metrics` | Advertised-capability counts with denominators |
| `pilot_6ghz_evidence` | Direct 6 GHz observations, sampled-empty frequencies, RNR-advertised 6 GHz neighbors, unresolved operating classes, disabled links, and nonconcurrent advertised-but-not-observed cases |

Base views preserve source grain. Metric views state their denominators and
exclude commissioning runs from trends. Failed, skipped, incomplete, running,
and missing attempts stay visible in `pilot_run_health`.

The database is a projection: a fresh database built into a scratch target
from the same Parquet and the checked-in SQL must return identical ordered
results. No manually created view or table is ever required for a rebuild.

## 7. Briefing surface

`reports/pilot-latest.md` renders from fixed templates and query results with
no LLM call and no wall-clock prose. Its sections, in required order:
Scope and cutoff; Collection health; Coverage; Longitudinal snapshot;
Capability advertisements; RNR and 6 GHz evidence; BSS Load; Data-quality
findings; Commissioning reference; Provenance. Its cutoff comes from the
latest included source event, not from the clock. Writes are atomic: validate
a temporary file on the same filesystem, then replace the canonical report.

Every ratio in the briefing displays numerator and denominator or names the
view row that carries both. Advertised-but-not-observed neighbors are always
qualified **nonconcurrent**: a sequential sweep cannot produce a calibrated
miss, sensitivity, or dwell conclusion.

---

*Interpretation boundary:* this surface records observed advertisements and
receiver observations only. Entity resolution, adoption estimates, and
calibrated sensitivity claims are out of scope by construction.
