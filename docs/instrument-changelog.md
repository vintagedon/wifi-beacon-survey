<!--
---
title: "Instrument Changelog"
description: "Dated record of capture-changing modifications to the receiver, with before and after evidence"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-08-27"
version: "1.0"
status: "Active"
tags:
  - type: reference
  - domain: instrument
related_documents:
  - "[Repository root](../README.md)"
  - "[Operations Runbook](operations-runbook.md)"
---
-->

# Instrument Changelog

A longitudinal series is only comparable across time if the instrument is unchanged, or if every change to it is dated and characterised. This file is that record.

An entry belongs here when a change alters what the receiver can hear or how it reports what it hears. Antenna, position, orientation, cabling, regulatory domain, driver or kernel version, dwell time, and the frequency set all qualify. Changes to parsing, schema, or downstream analysis do not, because retained PCAP can be reprocessed and those changes are therefore reversible.

Each entry carries a change identifier. Any dataset release spanning a change identifier must expose it, so a consumer can see where the series discontinues.

---

## 1. Change Register

| ID | Date | Change | Reversible | Effect |
|----|------|--------|------------|--------|
| IC-001 | 2026-08-27 | Antenna replacement and sensor repositioning | No, in practice | Large far-field sensitivity gain, 6 to 11 dB near-field loss |

The reference sweep for the current instrument state is `pilot/20260827-060013`: full tri-band, 10 s dwell, US regulatory domain. It is the baseline any future change is measured against.

---

## 2. IC-001: Antenna Replacement and Repositioning

**Date**: 2026-08-27
**Type**: Capture-changing, unrecoverable for prior data
**Evidence**: `pilot/20260827-060013` (tri-band, US domain, the reference sweep) and `pilot/20260827-054734` (2.4/5 GHz, world domain, taken first) against baselines `sweeps/20260816-024440` and `pilot/20260817-071901`

### What changed

The stock stub antennas were replaced with an Eightwood 9 dBi tri-band unit, rated 2400-2500, 5150-5850, and 5900-7125 MHz. The unit's 6 ft cable allowed the antenna to move off the rear of the host, which sat in a corner, onto a separate five-tier shelf further into the room.

Antenna and position moved together. They are not separable from this evidence and no attempt was made to separate them.

The comparison sweep also ran under the world (00) regulatory domain rather than US, because the domain had reverted across a driver reload and was not restored until after the run. Reception is unaffected by the no-IR flag, so signal comparisons hold, but 2467 MHz was swept where the baselines skipped it as disabled.

The domain was restored and a full tri-band sweep repeated 13 minutes later as `20260827-060013`. That run is directly comparable to the baselines and is the authoritative one.

### Measured effect

| Measure | 20260816-024440 | 20260817-071901 | 20260827-060013 |
|---------|-----------------|-----------------|-----------------|
| Populated frequencies | 11 | 13 | 18 |
| Unique BSSIDs | 28 | 31 | 102 |
| 2.4 GHz BSSIDs | 5 | 5 | 71 |
| 5 GHz BSSIDs | 23 | 26 | 31 |
| 6 GHz BSSIDs | 0 | 0 | 0 |
| Beacon frames | 2490 | 2519 | 5557 |
| Weakest mean received | -89.9 dBm | -92.3 dBm | -95.0 dBm |

Baseline churn between the two pre-change sweeps, 29 hours apart with no configuration change, was two BSSIDs lost and five gained, all below -88 dBm. That is the noise floor the change had to clear, and it cleared it by more than an order of magnitude.

Near-field reception fell consistently:

| BSSID | SSID | Before | After | Delta |
|-------|------|--------|-------|-------|
| `b8:8c:2b:b3:a4:d5` | Whitmore House | -59.2 dBm @ 2437 | -67.9 dBm @ 2437 | -8.7 dB |
| `20:23:51:6f:80:7d` | Craintopia 5 GHz | -32.0 dBm @ 5180 | -43.4 dBm @ 5240 | -11.4 dB |
| `18:0c:7a:d5:53:a5` | Christal | -31.9 dBm @ 2437 | -38.1 dBm @ 2412 | approximately -6 dB |

Only the Whitmore House row compares the same BSSID on the same frequency. The other two access points changed channel during the ten-day outage that preceded the measurement, which is a recorded observation rather than a defect.

Far-field gain concentrated in 2.4 GHz, which rose fourteenfold, against 5 GHz which rose by a third. Access points now audible on 2.4 GHz remain below the floor on their 5 GHz radios, which is consistent with the two bands' propagation difference over the distances involved rather than with any property of the antenna.

### 6 GHz remains empty

All 59 6 GHz frequencies tuned and captured, all `sampled_empty`, zero frames. That is the third consecutive tri-band sweep with the same result, but the first taken with an antenna rated to 7125 MHz and a demonstrated sensitivity floor of -95 dBm.

This upgrades 6 GHz from untested to a measured absence. It does not yet distinguish "no 6E access points in range" from "this receiver cannot hear 6 GHz," and the dataset must not claim anything about 6E adoption until it does. The Reduced Neighbor Report is the discriminator: an RNR element advertising a co-located 6 GHz radio that is never received indicts the instrument, while an absence of any such advertisement across 102 BSSIDs supports the measurement.

### Detection stability at the new floor

The two post-change sweeps ran 13 minutes apart and returned 120 and 102 unique BSSIDs. Removing 2467 MHz when the domain was restored accounts for part of that, but counts fell across every 2.4 GHz frequency: 2462 went 30 to 23, 2437 went 26 to 20, 2412 went 23 to 19. The 5 GHz count was flat at 30 then 31.

The volatility sits entirely in the newly-reachable 2.4 GHz weak tail. Pre-change churn was roughly five BSSIDs on a base of thirty; post-change it appears to be roughly nineteen on a base of one hundred and ten. Similar in proportion, much larger in absolute terms, and concentrated where detection is probabilistic.

The regulatory domain differed between those two runs, so treat this as an indication rather than a measured churn figure until two consecutive sweeps under the same domain settle it. The consequence stands regardless: a single sweep's BSSID count is not a stable measurement at this sensitivity, and prevalence claims need aggregation across sweeps with an explicit detection threshold rather than a per-sweep count.

### Interpretation

Large far-field gain alongside consistent near-field loss is the signature of a high-gain omnidirectional antenna. Gain is obtained by flattening the vertical radiation pattern into a narrow horizontal lobe, which places nearby sources at steep angles into the pattern nulls while distant sources arrive near-horizontally in the main lobe. Moving out of the corner acts in the same direction.

For an instrument whose subject is the surrounding neighbourhood rather than the building it sits in, this is the intended trade.

### Consequences for the dataset

Capture before and after 2026-08-27 is not directly comparable. Both the sensitivity floor and the near-field response moved, so neither prevalence counts nor RSSI distributions carry across the boundary.

All capture predating this change is pilot data collected before the production collection contract exists, and was already designated discardable. The discontinuity therefore costs nothing. Any future change of this class arriving after the series begins will not be free, and the decision to make it should be taken against that cost.

---

## 3. Recording a New Change

1. Capture a full sweep before touching anything, if the instrument is currently working.
2. Make the change.
3. Capture a comparable sweep afterwards: same dwell, same bands, same regulatory domain.
4. Add a register row and a section here, with the same-BSSID same-frequency comparisons that the evidence supports.
5. State plainly which variables moved together and are not separable.

The most useful comparison is a single BSSID observed on an unchanged frequency across the boundary. Aggregate counts move for reasons unrelated to the instrument, including access points changing channel, appearing, and disappearing on their own schedule.

---

## 4. Epoch Boundary: Pre-IC-001 Capture Archived

**Date**: 2026-08-27
**Effect**: Layout only. No capture file was rewritten, recompressed, or deleted.

All capture predating IC-001 was relocated by filesystem rename to
`archive/pre-IC-001/` under the capture data root
(`/opt/agents/repos/storage-mounted/wifi-beacon-survey/archive/pre-IC-001/`):
the six development sweeps formerly under `sweeps/` plus `pilot/20260817-071901`,
492 files in total. The post-change runs `pilot/20260827-054734` and
`pilot/20260827-060013` remain in `pilot/`, where new collection lands.

Reconciliation: pre-move and post-move inventories (every file, size, SHA-256)
agree exactly - identical file count, identical digest set, zero changed, zero
unaccounted - and a scratch-copy mutation check confirmed the reconciliation
reports a corrupted file rather than passing. Inventory path:
`archive/pre-IC-001-inventory-pre-move.tsv` (with
`pre-IC-001-inventory-post-move.tsv` and `pre-IC-001-reconciliation.txt`
alongside, described in `archive/README.md`).

Any query spanning this boundary must be epoch-aware; prevalence counts and
RSSI distributions do not carry across IC-001.
