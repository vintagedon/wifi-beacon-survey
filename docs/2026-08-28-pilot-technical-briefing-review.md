<!--
---
title: "Pilot Technical Briefing Review"
description: "Operator approval surface for the pilot enrichment and briefing unit: live-evidence findings PBR-01 through PBR-08"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-09-03"
version: "1.1"
status: "Under review"
tags:
  - type: review
  - domain: [dataset, analysis]
  - tech: [python, tshark, parquet, duckdb]
related_documents:
  - "[Pilot Analysis Contract](pilot-analysis-contract.md)"
  - "[Agent Instructions](../AGENTS.md)"
  - "[Hourly Collection Review](2026-08-27-hourly-collection-review.md)"
---
-->

# Pilot Technical Briefing Review

Static review surface for the pilot data enrichment and technical briefing
unit (`spec/2026-08-28-wifiscan-spec-01-pilot-technical-briefing.md`). It
reviews the initial live backfill and the scheduled integration as of the
evidence cutoff below; `reports/pilot-latest.md` continues to update outside
Git after every collection attempt. Every finding below is confirmed or
contradicted from live evidence, never from the spec's own authority.

**Evidence cutoff:** run `20260830-010003` (started 2026-08-30T05:00:03Z),
collected and enriched by the first fully scheduled run of the integrated
playbook (Semaphore task 2147483568).

**Finding classes used below:** implementation defect, data-quality finding,
environmental observation, deferred design decision.

---

## PBR-01: Series boundary and commissioning exclusion

**Statement.** Confirmed — the inventory enforces `20260827-090003` as the
pilot start and keeps both commissioning runs outside every trend surface.

**Evidence.**

- Classification source: `scripts/pilot_contract.py` (`PILOT_SERIES_START`,
  `COMMISSIONING_RUNS`); mutation-checked by
  `tests/test_pilot_contract.py::MutationCheckTests`.
- Live inventory: 62 direct children of `pilot/` classified by
  `python3 scripts/pilot_contract.py .../pilot` — 60 pilot-series attempts at
  or after `20260827-090003`, both commissioning runs classified
  `commissioning_reference`.
- View query `SELECT run_id, state, in_trend FROM pilot_run_health WHERE
  run_id IN ('20260827-054734','20260827-060013')` → both rows
  `completed_sweep, in_trend=false`.
- View query `SELECT COUNT(*) FROM pilot_hourly_metrics WHERE run_id IN
  ('20260827-054734','20260827-060013')` → `0`.

**Class:** environmental observation (boundary is an approved decision; the
enforcement is the implementation).

**Question PBR-01.** Should `20260827-090003` remain the approved pilot
series start, with the two commissioning runs excluded from every trend? (yes/no)

---

## PBR-02: Count reconciliation across source, Parquet, DuckDB, and report

**Statement.** Confirmed — frequencies and observations reconcile exactly
across all four layers, and failures are itemized rather than suppressed.

**Evidence.**

- Independent re-read of all 60 source TSV pairs against the 60 derivation
  manifests: 6,060 frequency rows and 10,356 observation rows match
  `pilot_frequencies`/`pilot_observations` exactly; 0 mismatches
  (verification run during backfill and repeated at closeout).
- Every manifest output hash and row count recomputed independently: 0
  mismatches across 60 runs (`scripts/pilot_enrich.py::outputs_intact`, used
  by `pilot_database.py::verify_output`).
- Source evidence non-mutation: per-run source SHA-256 + size recorded before
  parsing and recomputed after backfill — 0 changes.
- Failures itemized: `pilot_run_health` shows the 2026-08-28 00:00–04:00
  local outage as five `missing_hourly_slot` rows, itemized in the briefing's
  Collection health and Data-quality sections; zero-observation and
  non-success states all remain visible.

**Class:** environmental observation with one implementation note — the
reconciliation gate inside `pilot_database.py` raises
`ReconciliationError` on any eligible attempt without a manifest (verified by
`tests/test_pilot_database.py::test_missing_manifest_is_a_reconciliation_error`).

**Question PBR-02.** Do the reconciliation rules (hash-verified ingestion,
manifest-required for every eligible attempt, itemized missing slots) match
what you want enforced for the rest of the pilot week? (yes/no)

---

## PBR-03: tshark field resolution

**Statement.** Confirmed — every requested tshark field resolved on the
installed build (tshark 4.2.2), and unresolved state is recorded as distinct
from an observed zero.

**Evidence.**

- View query `SELECT status, COUNT(*) FROM pilot_field_resolution GROUP BY
  status` → `resolved: 1800` (30 logical fields × 60 runs), no unresolved
  rows; `SELECT DISTINCT logical_name FROM pilot_field_resolution WHERE
  status = 'unresolved'` → empty.
- The distinction is enforced in code
  (`scripts/pilot_enrich.py::field_resolution_rows`) and exercised by
  `tests/test_pilot_enrich.py::test_unresolved_field_is_distinct_from_observed_zero`,
  which proves an unresolved candidate produces null values plus a
  `field_resolution` finding, never a zero.
- One candidate list did require repair during this unit: the extension
  namespace on this build exposes `wlan.ext_tag.number`, and the RNR TBTT
  layout assumptions in the synthetic fixtures were corrected against real
  dissection rather than documentation.

**Class:** environmental observation.

**Question PBR-03.** Is the per-run field-resolution table sufficient
evidence for the weekend review of what the dissector actually supports?
(yes/no)

---

## PBR-04: HE/EHT/Multi-Link, RNR, and BSS Load grains

**Statement.** Confirmed — the grains carry the pilot's analytical questions
without inventing repeated-field relationships.

**Evidence.**

- IE capabilities: 6,537 run×BSSID rows; 4,462 advertise HE, 639 EHT, 240
  Multi-Link, 0 HE 6 GHz (`pilot_ie_capabilities`), all derived from the
  resolved extension-element namespace (`wlan.ext_tag.number`), never from
  `wlan.tag.number == 255`.
- RNR: 55,728 frame rows — 48,341 `single_occurrence` and 7,387
  `unpaired_multi_occurrence`; the ambiguous rows retain verbatim raw cells
  (`raw_*` columns) and never receive a normalized target band
  (`target_band` is null exactly when `structure_status` is ambiguous).
- BSS Load: 252,049 rows across 110 BSSIDs; 100% carry `pcap_file`,
  `frame_number`, and `frame_time_epoch` (sum of null checks = 252,049 each).
- Synthetic fixtures in `tests/_synthetic_pcap.py` pin the repeated-neighbor
  and disabled-link cases against the installed dissection.

**Class:** implementation observation (grains chosen by this unit; no defect
found).

**Question PBR-04.** Are these grains (frame-grain RNR with ambiguity
preserved, frame-grain BSS Load with packet identity, per-BSSID capability
presence) sufficient for the remainder of the pilot without hierarchical TLV
re-parsing? (yes/no)

---

## PBR-05: What the 6 GHz evidence supports

**Statement.** Provisional: the evidence records advertised 6 GHz neighbors
and no direct observations, but it cannot distinguish sequential
nonconcurrency from an instrument that does not receive 6 GHz.

**Evidence.**

- View query `SELECT SUM(direct_bssids), SUM(direct_beacons),
  SUM(sampled_empty_frequencies), SUM(manifest_frequencies),
  SUM(advertised_6ghz_neighbors), SUM(advertised_6ghz_disabled_links),
  SUM(ambiguous_rnr_rows), SUM(advertised_not_observed_nonconcurrent) FROM
  pilot_6ghz_evidence` → `0, 0, 3540, 3540, 544, 0, 7387, 371`.
- Every one of the 3,540 6 GHz manifest rows across trend runs is
  `sampled_empty` — recorded negative observations, retained in Parquet.
- 544 distinct advertised 6 GHz neighbors from single-occurrence RNR rows;
  371 advertised-but-not-observed cases, every one qualified
  **nonconcurrent** in the briefing (enforced by
  `tests/test_pilot_report.py::test_nonconcurrent_qualifier_is_mandatory`,
  whose mutation would fail on a sensitivity/dwell conclusion).
- No RNR-advertised 6 GHz link carried the disabled indication in live data
  (0); the capability is covered by fixture (`tests/_synthetic_pcap.py`).
- No positive 6 GHz control exists on this instrument. The nonconcurrency
  reading remains provisional until the falsification test produces a direct
  6 GHz observation under known receivable conditions.

**Class:** environmental observation.

**Question PBR-05.** Do you accept "advertised 6 GHz neighbors exist; none
were directly observed; the nonconcurrency reading remains provisional
pending a positive-control falsification test" as the standing 6 GHz claim
for the pilot? (yes/no)

---

## PBR-06: Hourly integration and failure truth

**Statement.** Confirmed — the scheduled job updates the briefing while
preserving collector/report failure truth, inside the hourly headroom.

**Evidence.**

- Semaphore task 2147483568 (created 2026-08-30T05:00:00Z by the hourly
  schedule, not hand-triggered): status `success`; playbook
  `wifi-beacon-sweep.yml` ran sweep → analysis → ownership normalization →
  skip assert.
- Durations: collector 997 s (artifact mtimes 01:00:03→01:16:40 EDT),
  analysis ≈ 8 s in-task (report mtime 01:16:48; steady-state measured 2.4 s
  unchanged / seconds with new runs), total scheduled job 1,009 s
  (05:00:00→05:16:49Z). Headroom to the next hourly boundary: ~2,591 s
  (~43 min).
- Idempotence: immediate re-run of `pilot-update.py --stage all` processed 0
  runs and left `pilot-latest.md` byte-identical (SHA-256
  `c77522c0…33565a7` before and after).
- Failure truth, test-doubles under `/tmp/kilo/pb-scratch` against the real
  playbook: receiver-absent skip → analysis ran, task failed (exit 2);
  collector crash → rescue ran analysis and re-raised the collector cause
  with both outputs; forced report failure after a successful collector →
  task failed and the canonical report stayed byte-identical.

**Class:** implementation observation.

**Question PBR-06.** Does the integrated task's outcome semantics (skip
fails, collector failure fails with both causes, analysis failure fails)
match the visibility you want in Semaphore history? (yes/no)

---

## PBR-07: Is `pilot-latest.md` useful as the interim briefing?

**Statement.** Confirmed, with one presentation caveat — the ten required
sections answer collection health, coverage, longitudinal shape,
capabilities, 6 GHz, BSS Load, data quality, and provenance from one file,
but the ambiguity count (7,387 rows) will dominate the reader's attention
until the weekend review decides whether ambiguous RNR frames should be
summarized differently.

**Evidence.**

- `reports/pilot-latest.md` (data root), generated deterministically:
  byte-identical re-renders (three consecutive renders, identical SHA-256);
  section order asserted in
  `tests/test_pilot_report.py::test_all_ten_sections_in_required_order`.
- Independent spot-checks of report numbers against `pilot_band_metrics` and
  source TSVs reconcile exactly
  (`tests/test_pilot_report.py::test_report_values_match_independent_computation`,
  plus the live reconciliation under PBR-02).

**Class:** deferred design decision (presentation, not data).

**Question PBR-07.** Is `pilot-latest.md` useful enough as the interim
technical briefing for the remainder of the week, as rendered? (yes/no)

---

## PBR-08: PostgreSQL deferral

**Statement.** Confirmed — nothing in this unit created a PostgreSQL
connection, credential, DDL, or table, and the accumulated evidence supports
deferring schema design until the weekend distribution review.

**Evidence.**

- The only database artifact is the DuckDB projection
  (`derived/pilot.duckdb`), rebuilt entirely from Parquet plus
  `sql/pilot/pilot_views.sql`; no PostgreSQL DDL exists in the repository
  (`tests/test_pilot_contract.py::test_document_contains_no_ddl` guards the
  contract document).
- The distribution evidence the schema decision needs is accumulating: 60
  runs, 10,356 observations, 6,537 capability rows, 55,728 RNR frames, 252,049
  BSS Load rows as of this cutoff, with field-resolution state recorded per
  run.

**Class:** deferred design decision.

**Question PBR-08.** Should PostgreSQL schema design remain deferred until
you review the fuller pilot distribution at the weekend? (yes/no)

---

## Findings not requiring operator decision

- **Data-quality finding:** the 2026-08-28 00:00–04:00 local outage (5
  missing hourly slots) is visible in every health surface; no action needed
  for the pilot dataset itself.
- **Environmental observation:** all 3,540 6 GHz manifest rows are
  sampled-empty and every requested dissector field resolved; these are
  recorded facts of this window, not defects.
- **Implementation note:** Wireshark 4.2.2's RNR dissector dedupes identical
  adjacent TBTT occurrences, so two same-operating-class neighbors can
  present one `op_class` cell while `short_ssid` keeps the comma that marks
  the ambiguity. The ambiguity flag keys on any multi-valued cell, so no
  information is lost.
