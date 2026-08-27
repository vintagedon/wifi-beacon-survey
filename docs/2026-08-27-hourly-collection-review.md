<!--
---
title: "Hourly Collection and Epoch Archive: Operator Review"
description: "Review surface for the 2026-08-27 hourly-collection and pre-IC-001 epoch archive spec: six findings with evidence, each closed with a yes or no"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-08-27"
version: "1.0"
status: "under-review"
tags:
  - type: report
  - domain: instrument
  - tech: [bash, semaphore, tcpdump]
related_documents:
  - "[Instrument Changelog](instrument-changelog.md)"
  - "[Operations Runbook](operations-runbook.md)"
  - "[Execution worklog](/opt/agents/repos/work-logs/2026-08-27-wifiscan-worklog-01-hourly-collection-and-epoch-archive.md)"
  - "[Executed spec](/opt/agents/repos/spec/2026-08/2026-08-27-wifiscan-spec-01-hourly-collection-and-epoch-archive.md)"
---
-->

# Hourly Collection and Epoch Archive: Operator Review

This is the review surface for `2026-08-27-wifiscan-spec-01`. It states what
was found, what was moved, and what is still unenforced. Every finding ends in
a closed question. Until these are answered, the week of hourly collection that
follows is provisional.

| Gate | Deliverable | Evidence |
|------|-------------|----------|
| 1 | Semaphore state determination | Finding R1 below |
| 2 | Pre-IC-001 epoch archive | `archive/` under the data root; Finding R2 |
| 3 | Collector self-recording | `scripts/wifi-beacon-sample.sh`; Finding R3 |
| 4 | Hourly schedule armed | Semaphore project 1, schedule 5; Finding R4 |
| 5 | This document | - |

---

## R1. The schedule was never armed - not lost, not failing loudly

**Statement.** The ten-day collection gap happened because no schedule ever
existed for the Wi-Fi sweep template. The 2026-08-25 ML01 reboot is unrelated
to the scheduling fault.

**Evidence.**

- `GET /api/project/1/schedules` (2026-08-27, before this spec changed
  anything): four schedules, IDs 1-4, all attached to dashboard templates 1-4,
  all `active=false`. None references template 6
  (`wifi-beacon-sweep-pilot`).
- `GET /api/project/1/tasks`: template 6 has exactly one task in history -
  ID 2147483633, status `success`, created `2026-08-17T11:18:58Z`
  (07:18:58 EDT), finished `11:35:38Z`, which matches
  `pilot/20260817-071901`. Zero tasks at any later hour on any day.
- The receiver was healthy from 2026-08-17 until the 2026-08-25 reboot. An
  armed hourly schedule would have run and succeeded hourly from 08:00 EDT on
  Aug 17, and failed visibly hourly after Aug 25. Neither pattern exists.
- The Semaphore store survives host reboots: schedules 1-4, created
  2026-08-11, still existed on 2026-08-27 after the Aug 25 reboot. A Wi-Fi
  schedule that had ever been created would still exist. None does.

**Question.** Record "the cadence was never armed (silent omission)" as the
scheduling cause of the 2026-08-17..27 gap, rather than loss across the
reboot? Yes / No.

---

## R2. Pre-IC-001 capture now lives behind an epoch boundary

**Statement.** All capture predating the IC-001 antenna change (7 run
directories, 492 files) was relocated by filesystem rename to
`archive/pre-IC-001/` under the data root, with digest-reconciled inventories.
The post-change runs `pilot/20260827-054734` and `pilot/20260827-060013`
remain in `pilot/`, digest-confirmed untouched. Nothing was deleted, and no
file content changed. The layout was the executor's choice and is confirmable
here.

**Evidence.**

- `archive/pre-IC-001-inventory-pre-move.tsv` (774 rows: 492 pre-change, 282
  post-change-stays) and `archive/pre-IC-001-inventory-post-move.tsv`.
- `archive/pre-IC-001-reconciliation.txt`: 774 rows, identical digest set,
  zero changed, zero unaccounted; plus a scratch-copy mutation check that
  corrupted one byte and was correctly reported as exactly one changed file.
- `archive/README.md` states the boundary and the analysis rule without
  reference to the spec.
- The epoch record in [instrument-changelog.md](instrument-changelog.md)
  section 4 names the location, file count, and inventory path.

**Question.** Keep `archive/pre-IC-001/` (flat run directories under a
changelog-named epoch, inventories at archive level) as the permanent epoch
layout for future instrument changes? Yes / No.

---

## R3. Skip record: downtime is now data, and it fails loudly in history

**Statement.** When the interface is absent, the collector creates a run
directory, writes manifest-shaped headers plus a skip record in
`instrument.json`, and exits 0. The machine discriminator is the
`run_status` field: `skipped_no_interface` means the receiver was down;
`sweep` means frequencies were measured, however many were empty. A skip is
converted to a failed Semaphore task by a playbook assert, so downtime reads
as an error in run history rather than as a successful sweep. A new
`instrument.json` artifact also records, every run, the active regulatory
domain, the USB controller/bus/port of the adapter, and the capture
parameters (dwell, bands, snaplen, filter).

The design choice was a separate run-level file rather than new columns or
rows in `frequencies.tsv`: the manifest's schema is frozen by the
comparability constraint, and a synthetic frequency row would falsify the
negative-observation property. The real example below was produced by a
scratch run against a fictitious interface name (retained here inline; not
part of the series):

```json
{
  "schema": "wifi-beacon-survey/instrument/1",
  "run_status": "skipped_no_interface",
  "skip_reason": "ip link show wlxTESTABSENT00 failed at run start",
  "started_utc": "2026-08-27T10:54:50Z",
  "interface": "wlxTESTABSENT00",
  "interface_present": false,
  "phy": null,
  "regulatory_domain": "US",
  "regulatory_domain_phy": null,
  "usb": { "bus": null, "port": null, "device": null,
           "controller_pci": null, "speed_mbps": null, "driver": null },
  "capture": { "dwell_seconds": 2, "bands": "2.4", "snaplen": 1024,
               "bpf_filter": "type mgt subtype beacon" }
}
```

Alongside it, `frequencies.tsv` carries the normal header and zero data rows.
A completed empty sweep, by contrast, has `run_status: "sweep"` and 98
attempted-frequency rows with `sampled_empty` status - distinguishable by the
stated field, not by heuristics.

A mutation check forced the domain-detection path (PATH-shimmed `iw reg get`
reporting `country ZZ`) and the artifact recorded `ZZ`, proving the field is
read at run time rather than hardcoded.

**Question.** Is this skip-record shape and the instrument.json field set the
right contract for the series? Yes / No.

---

## R4. Hourly cadence against the observed sweep duration

**Statement.** A full tri-band sweep under the new collector build measured
997 s wall time (reference sweep `20260827-060013`: ~996 s; the
self-recording changes added no measurable time). The hourly schedule
`0 * * * *` therefore leaves roughly 43 minutes of headroom per hour, and the
playbook's 1800 s timeout bounds a hung run before the next hour collides
with it.

**Evidence.**

- Scratch validation sweep started `2026-08-27T10:57:01Z`, last artifact write
  `11:13:38Z`: 997 s; 101 frequencies listed, 98 attempted, 0 capture errors,
  frequency set byte-identical to the reference manifest.
- Semaphore schedule 5 `wifi-beacon-sweep-pilot-hourly`, cron `0 * * * *`,
  `active=true`, attached to template 6.

**Question.** Keep hourly as the collection cadence for the accumulation
period? Yes / No.

---

## R5. The output format is TSV, deliberately

**Statement.** You described this work as collecting CSVs. The collector
writes TSV on purpose: SSIDs are arbitrary octets, commas occur in them, and a
quoting layer would add a failure mode to the evidence tier. The spec froze
this ("Do not touch: the output format").

**Evidence.** `pilot/20260827-060013/aggregate.tsv` header:
`band, frequency_mhz, channel, bssid, ssid, beacons, ...` as tab-separated
fields; the parser sanitises tabs/newlines/carriage returns out of SSID
values (`scripts/wifi-beacon-sample.sh`, `summarize_pcap`).

**Question.** Confirm TSV remains the output format for the series, with CSV
conversion (if ever wanted) belonging to the release transform where quoting
can be tested? Yes / No.

---

## R6. Three preconditions of collection remain unenforced

**Statement.** The outage can recur. Recording has improved - each run now
carries the USB location and regulatory domain in `instrument.json`, so a
future failure is diagnosable from the run directory - but nothing enforces
any of the three preconditions that failed in August:

1. **USB controller placement.** The adapter must occupy a Bus 001 port
   (`0000:02:00.0`). Which port it occupies is a physical fact with no
   configuration holding it. No udev rule refuses to run on the wrong
   controller.
2. **Regulatory domain persistence.** The domain reverts to world (00) across
   driver reloads and is restored by hand (`iw reg set US`). It is now
   recorded per run, which converts silent series corruption into visible
   evidence, but nothing pins it - and whether the MT7921's self-managed
   regime even permits pinning is undetermined (no phy country section was
   present in `iw reg get` on 2026-08-27).
3. **`btusb` state.** The 2026-08-16 fix (`modprobe -r btusb`) was never made
   persistent. On a Bus 001 port it is currently unnecessary, but nothing
   asserts that state, and a future move to the other controller would
   reintroduce the wedge that took the device down before Wi-Fi could probe.

**Evidence.** [operations-runbook.md](operations-runbook.md) sections 2-4
(observations), section 5 (gaps); `instrument.json` from the validation sweep
recording `bus 1 / port 6 / 0000:02:00.0 / 480M / mt7921u`.

**Question.** Accept these as recorded-but-unenforced for the accumulation
period, and schedule enforcement decisions (udev rule, domain-persistence
approach, btusb policy) as the next unit rather than this one? Yes / No.

---

## Answering

Answer each finding's question yes or no (with any qualification). R1, R2,
and R6 close out this spec's record; R3 and R4 shape the production
collection contract; R5 settles the interchange question before anything
downstream builds a CSV assumption into tooling.
