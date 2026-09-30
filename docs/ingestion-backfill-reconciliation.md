<!--
---
title: "Ingestion Backfill Reconciliation"
description: "The operator's review surface for the wifi_beacon_survey backfill: aggregate counts, findings with evidence, and the merge decision"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-09-29"
version: "1.0"
status: "Awaiting operator review"
tags:
  - type: specification
  - domain: [dataset, instrument]
  - tech: [postgres, bash]
related_documents:
  - "[Ingestion Contract](ingestion-contract.md)"
  - "[Agent Instructions](../AGENTS.md)"
  - "[Instrument Changelog](instrument-changelog.md)"
---

# Ingestion Backfill Reconciliation

This document is the operator's review surface for gate 1.6. It carries
aggregate counts only - no BSSIDs, SSIDs, or other identifiers. Every
finding states one line, shows the evidence that produced it, and closes
with a question. The prior findings from the spec are answered from evidence
recomputed at execution time, never carried forward as answers.

**Unit under review**: spec 01 (domain preflight and direct PostgreSQL
ingestion). **Reconciliation cutoff run**: `20260929-210003` - the last
completed sweep before the first post-preflight run began. The first run
after the collector preflight landed (`20260929-220003`) is accounted for
separately in finding R9.

**Verification rule**: every figure in this document was produced twice, once
by the loader and once by an independent recomputation from the source files
using `jq` and line counts that share no code with the loader. The two
agreements are finding R8.

---

## R1: The completed-run domain split at the cutoff is 312 US and 445 world

**Statement.** At cutoff `20260929-210003`, 757 completed runs split into
312 routed to `survey` (US) and 445 routed to `archive` (world). The split
at the spec's `20260929-080003` cutoff was 299 US and 445 world; the 13
additional US runs are the post-restore hours `20260929-090003` through
`20260929-210003`. No completed run since the restore has reverted.

**Evidence.**

    # independent: per-run jq, effective domain by schema version
    # (command summarised; full form in the worklog)
    survey=312 archive=445 completed=757

    # projection, same cutoff:
    SELECT count(*) FROM survey.runs  WHERE run_id <= '20260929-210003';  -- 312
    SELECT count(*) FROM archive.runs WHERE run_id <= '20260929-210003';  -- 445

**Closed question.** Does the operator accept 445 world-domain runs into
`archive` as the disposition for IC-002 and IC-003, superseding
retain-and-flag?

## R2: Every completed run lists exactly 101 frequencies

**Statement.** All 757 completed runs at the cutoff have a manifest with
exactly 101 data rows. Zero violations.

**Evidence.** The independent recomputation tested
`wc -l frequencies.tsv - 1 == 101` per completed run:
`manifest_101_violations=0`.

**Closed question.** Confirmed as expected - no action.

## R3: Six slots are missing, and they are the two known outage windows

**Statement.** Six expected UTC hours have no attempt at all: 2026-08-28
04:00 through 08:00 UTC (the 2026-08-28 early-morning reboot window, five
slots) and 2026-09-09 06:00 UTC (the host rebooting at the 02:00 EDT job
trigger recorded in the operations runbook).

**Evidence.**

    SELECT slot_utc_hour FROM derived.slot_health WHERE slot_state = 'no_run'
    ORDER BY 1;
      2026-08-28 04:00:00+00 ... 2026-08-28 08:00:00+00  (5 rows)
      2026-09-09 06:00:00+00                             (1 row)

The legacy surface agrees:
`ingest_crosscheck.py --database wifi_beacon_survey` reports
"no_run slots: projection 6, legacy 6 (6 after local-to-UTC mapping)" with
slot-for-slot equality.

**Closed question.** Confirmed at 6, matching the prior finding - no action.

## R4: There are exactly 42 receiver-absent skips

**Statement.** 42 attempts carry `run_status=skipped_no_interface`, all
disposition `not_loaded`.

**Evidence.**

    # independent: jq over instrument.json, whole series
    skip=42
    # projection:
    SELECT count(*) FROM ingest.attempts WHERE attempt_state =
    'receiver_absent_skip';  -- 42

**Closed question.** Confirmed - no action.

## R5: No attempt resolves to unresolved_domain

**Statement.** Zero. Every completed run recorded a readable domain under
its own schema's rules, so every completed run is loaded into `survey` or
`archive`.

**Evidence.**

    SELECT count(*) FROM ingest.attempts
    WHERE disposition = 'unresolved_domain';  -- 0

**Closed question.** Confirmed - no action.

## R6: No UTC hour holds more than one attempt

**Statement.** Zero hours hold more than one attempt.

**Evidence.**

    SELECT slot_utc_hour, count(*) FROM ingest.attempts
    WHERE slot_utc_hour IS NOT NULL
    GROUP BY 1 HAVING count(*) > 1;  -- 0 rows

**Closed question.** Confirmed - no action.

## R7: The gate 1.5 legacy cross-check matches exactly on production

**Statement.** For all 312 `survey` runs present in both surfaces,
`derived.run_metrics` matches legacy `pilot_hourly_metrics` and
`derived.band_coverage` matches legacy `pilot_band_metrics` exactly on
distinct BSSIDs, beacon frames, every frequency outcome count, and mean
RSSI (no definitional difference needed). `derived.slot_health` carries
exactly the legacy `missing_hourly_slot` set after local-to-UTC mapping.

**Evidence.**

    doppler run --project ml01 --config dev -- python3 \
      scripts/ingest_crosscheck.py --database wifi_beacon_survey
    runs in both surfaces: 312 (projection 312, legacy 757)
    run/band rows in both surfaces: 936 (projection 936, legacy 2271)
    no_run slots: projection 6, legacy 6 (6 after local-to-UTC mapping)
    Cross-check clean: every shared metric matches exactly.

**Closed question.** Confirmed - no action.

## R8: The projection equals an independent recomputation from the files

**Statement.** Per-disposition attempt counts and per-table row counts in
`wifi_beacon_survey` equal the independent `jq`/line-count recomputation at
the cutoff, exactly, on every figure.

**Evidence.**

    figure                  independent    projection
    survey_runs             312            312
    archive_runs            445            445
    survey_frequencies      31512          31512
    survey_observations     51805          51805
    archive_frequencies     44945          44945
    archive_observations    80771          80771
    completed               757            757
    receiver_absent_skip    42             42
    refused/failed/malformed 0/0/0         0/0/0
    unresolved_domain       0              0

**Closed question.** Confirmed - no action.

## R9: A second drain loads nothing, and the first instrument/2 run is live

**Statement.** A second drain against `wifi_beacon_survey` produced 757
no-ops, zero failures, and identical base-table content hashes. The first
scheduled run after the collector preflight commit,
`20260929-220003`, is an `instrument/2` run: started 2026-09-30T02:00:03Z,
`run_status=sweep` at completion with found, applied (no set needed), and
post-sweep domains all US, and 101 manifest rows - the same frequency-row
count as the preceding US runs.

**Evidence.**

    second-drain outcomes: {'noop': 757}; failures: []
    hashes identical: True

    jq '{schema,run_status,regulatory_domain,regulatory_domain_declared,
         regulatory_domain_set_attempted,regulatory_domain_set_result,
         regulatory_domain_at_discovery,regulatory_domain_post_sweep}' \
      pilot/20260929-220003/instrument.json
    => {"schema":"wifi-beacon-survey/instrument/2","run_status":"sweep",
        "regulatory_domain":"US","regulatory_domain_declared":"US",
        "regulatory_domain_set_attempted":false,
        "regulatory_domain_set_result":"already_declared",
        "regulatory_domain_at_discovery":"US",
        "regulatory_domain_post_sweep":"US"}
    wc -l pilot/20260929-220003/frequencies.tsv   # 102 (101 data rows)

The follow-up drain loaded it as survey run 313 (`loaded=1, noop=757`).

**Closed question.** Confirmed - the preflight is live and the series
continuity holds across the deployment.

## R10: The cross-file relationship holds across the whole archive

**Statement.** For every completed run at load time (757), every
`aggregate.tsv` band and frequency appears in `frequencies.tsv` as sampled,
and each manifest row's beacon and BSSID counts equal the aggregate sums.
Zero mismatches. The relationship was verified before the loader made it a
load gate, as the spec required.

**Evidence.** Gate 1.4 verification, independent of the loader:

    completed runs checked: 757
    beacon-sum mismatches:  0
    bssid-count mismatches: 0
    aggregate keys not sampled in manifest: 0
    file errors: 0

**Closed question.** Confirmed - the load gate is safe to keep enforced.

---

## Ledger snapshot at reconciliation

Final state after the drain that ledgered `20260929-220003`:

| Measure | Value |
|---------|-------|
| Expected UTC slots | 806 (series start through last fully elapsed hour, plus the first post-preflight hour) |
| Attempts | 800 (758 completed, 42 receiver-absent skips) |
| Loaded | 758 (313 survey, 445 archive) |
| Not loaded | 42 (all receiver-absent skips) |
| Missing hours (no_run) | 6 |
| Loader version | `ingest-load/1` |

---

## The decision

Closed question for the operator: **approve the merge of this unit, and the
dispatch of spec 02?**

Spec 02 deploys the merged `main` to the live tree, adds the loader's
Semaphore job, removes `pilot-update.py` from the hourly job, and retires
the pilot contract, DuckDB, and briefing in place. Until that dispatch, the
legacy pipeline continues to run unchanged and this database is a parallel
projection, rebuilt by draining again at any time.
