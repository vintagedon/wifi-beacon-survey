<!--
---
title: "Deep Research Prompt: MT7921AU Unused Data Surfaces"
description: "Bounded research prompt asking what the receiver and the 802.11 beacon body expose that the collector currently discards"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-08-16"
version: "1.0"
status: "Active"
tags:
  - type: reference
  - domain: [instrument, dot11]
  - tech: [tshark]
related_documents:
  - "[Surface probe](../scripts/probe-surfaces.py)"
  - "[Documentation index](README.md)"
---
-->

# Deep Research Prompt: MT7921AU Unused Data Surfaces

Bounded research prompt in the five-layer negative-space form. Run across three
models on 2026-08-16; its findings set the scope of the parse-only work in
`scripts/probe-surfaces.py`. Retained as the record of what was asked, since the
answers are only interpretable against the constraints that produced them.

---


Act as a wireless systems engineer with working knowledge of the Linux mac80211/mt76
stack. The goal is a field inventory and a shortlist of candidate measurements, grounded
in standard clause text and driver source rather than in survey literature.

The instrument already exists and works. The question is what data the hardware and
driver expose that the current collector is discarding, and what a single fixed station
could do with it.

---

## I. ANCHORS (Immutable Context)

**Hardware Reality:**

- Alfa AWUS036AXM, MediaTek MT7921AU chipset, `mt7921u` driver in the `mt76` tree
- One USB adapter, one radio, single antenna path. No second receiver available
- Monitor mode via mac80211/nl80211. Radio control via `iw`, capture via libpcap/tcpdump
- Linux host, current kernel. Regulatory domain US

**Deployment Reality:**

- Single fixed indoor station at one location, permanently sited
- Passive reception only. No transmission, no injection, no active scanning, no
  regulatory-domain override
- 6 GHz frequencies currently enumerate as `no-ir` in the kernel regulatory state

**Acquisition Reality:**

- Frequency-driven deterministic sweep. 101 frequencies enumerated at runtime from the
  kernel regulatory state (14 x 2.4 GHz, 28 x 5 GHz, 59 x 6 GHz), 98 attempted after
  regulatory skips, fixed 10 s dwell each, approximately 996 s per full sweep
- Capture currently BPF-filtered to beacon frames only
- Per-frequency PCAP retained permanently. Per-sweep artifacts: `freq-<MHz>.pcap`,
  `aggregate.tsv`, `frequencies.tsv`, `phy-info.txt`, `run.log`
- Currently extracted fields, and only these: BSSID, SSID, beacon interval, RSSI
  min/mean/max, first seen, last seen, beacon reception ratio

**Pipeline Reality:**

- Files are the immutable source of record. Parquet is the machine-readable artifact.
  PostgreSQL is a rebuildable projection, never the source
- Semaphore orchestrates bounded sweep jobs. Target cadence roughly hourly, intended to
  run continuously for 12 or more months
- Storage is explicitly not a constraint: 1.16 MB per sweep, 2 x 2 TB NVMe available
- Because PCAP is retained permanently, any change that is purely a parsing change can be
  backfilled across the entire historical archive retroactively

**Measured Baseline (single sweep, 2026-08-16 02:44):**

- 28 unique BSSIDs resolving to 13 probable physical radios; 39% locally administered
- 2490 beacons; 11 of 98 frequencies populated; 87 recorded as negative observations
- Zero detections across all 59 6 GHz frequencies, currently unvalidated because the band
  has no positive control
- Beacon reception ratio ceilings at 0.922 against a theoretical 97.7 beacons per 10 s
  dwell at 100 TU, implying roughly 0.78 s of instrumental tune-and-start latency

---

## II. WALLS (Domain Exclusions)

- **NO Channel State Information (CSI) sensing**, CSI extraction toolkits, or CSI-derived
  activity, gesture, or occupancy work (the MT7921AU does not expose CSI through `mt76`;
  this is a different acquisition path entirely)
- **NO multi-receiver, distributed-sensor, or time-synchronised capture techniques**
  (single fixed station is an anchor; anything requiring a second radio is unbuildable)
- **NO mobility, trajectory, presence, or occupancy inference** (a single fixed station
  cannot support these regardless of published multi-sensor precedent)
- **NO wardriving, BSSID-to-coordinate geolocation, or war-walking survey methodology**
  (one fixed point, no GPS, no movement)
- **NO active techniques**: probe request transmission, active scanning, deauthentication,
  injection, frame crafting, or regdomain override (passive-only is an anchor)
- **NO WIDS, IDS, rogue-AP detection, evil-twin detection, or penetration-testing tooling**
  (this is a measurement instrument, not security tooling)
- **NO storage compression, sampling-efficiency, or data-reduction research** (storage is
  explicitly not a constraint)
- **NO consumer Wi-Fi troubleshooting, home-network optimisation, or router-recommendation
  content** (SEO noise layer that will otherwise dominate results)

---

## III. VECTOR SEEDS (Positive Space Targeting)

**PRIORITIZE as the spine (standards and source, treated as ground truth):**

- IEEE 802.11-2020 and the 802.11ax / 802.11be amendments: beacon frame body structure,
  Information Element ID assignments, and element-specific field layouts
- The Radiotap specification (radiotap.org): defined field list, presence bitmap
  semantics, and which fields are optional in practice
- Linux `mt76` driver source, specifically
  `drivers/net/wireless/mediatek/mt76/` and the `mt7921` subtree, for which Radiotap
  fields the driver populates on receive and which it leaves absent
- `mac80211` and `cfg80211`/`nl80211` source and headers: the RX status structure, the
  survey interface, and channel-time accounting attributes
- Wireshark / tshark 802.11 dissector source (`epan/dissectors/packet-ieee80211.c`) as the
  practical reference for what is decodable in the field, including field-name expressions
- Kismet source, particularly the Linux Wi-Fi datasource and its IE parsing, as a working
  reference implementation for the same hardware class
- `iw` source and man page: `survey dump`, `station dump`, and phy capability reporting
- Wi-Fi Alliance certification programme specifications where they define capability bits
  that appear in beacon IEs

**PRIORITIZE as gated overlay:**

- Measurement-community venues: IMC, PAM, CoNEXT, SIGCOMM, MobiCom, WiNTECH
- Published Wi-Fi measurement datasets on Zenodo, IEEE DataPort, and CRAWDAD mirrors,
  where the schema itself is retrievable

**DE-PRIORITIZE:**

- Vendor marketing material and product datasheets lacking register-level or driver-level
  detail
- Medium, dev.to, and tutorial-farm content
- Aircrack-ng and Kali tooling walkthroughs
- Stack Overflow answers with no corroborating source or specification reference

---

## IV. GATES (Conditional Inclusion)

- **Academic papers**: PERMITTED ONLY IF the paper names a specific beacon IE, Radiotap
  field, or nl80211 statistic, or publishes a retrievable schema. Papers reporting results
  without identifying the underlying measured field are excluded.
- **Published datasets**: PERMITTED ONLY IF the actual column list or schema documentation
  is retrievable, not merely a paper describing one.
- **Client-frame and probe-request literature**: PERMITTED ONLY IF it establishes a
  fingerprinting or re-identification pathway that operates on *beacon-derived* fields, in
  which case it is in scope as release-risk evidence for this instrument.
- **Driver capability claims**: PERMITTED ONLY IF traceable to `mt76`/`mac80211` source, a
  named kernel commit, or reproducible command output. Forum reports asserting that
  something works, without either, are excluded.
- **Other MediaTek parts (MT7915, MT7922, MT7925)**: PERMITTED ONLY IF the shared `mt76`
  code path is identified, in which case findings may be treated as transferable and must
  be labelled as such.

- **PIVOT**: If `mt76` Radiotap field population cannot be established from source or
  kernel commits, stop searching and instead return the exact commands that would
  determine it empirically on this hardware.
- **PIVOT**: If fewer than three published fixed-sensor longitudinal Wi-Fi datasets with
  retrievable schemas exist, redirect to fixed-sensor instrument networks in adjacent
  domains (ADS-B receiver networks, spectrum monitoring, air quality sensor networks,
  radio astronomy pipelines) for schema, provenance, and calibration-drift precedent.

---

## V. RESEARCH QUESTIONS

The data the hardware exposes lives on three distinct surfaces. Treat them separately.

1. **Inventory, frame contents**: Which Information Elements appear in beacon frames as
   transmitted by current consumer and ISP-supplied access points, and what quantity does
   each carry? Distinguish elements that are mandatory, conditional on Wi-Fi generation,
   and vendor-specific.

2. **Inventory, Radiotap metadata**: Which Radiotap fields does `mt76` populate on receive
   for the MT7921AU in monitor mode, and which are defined by the specification but absent
   in practice? Separate per-packet fields from per-antenna fields, and state whether
   noise floor is among them.

3. **Inventory, nl80211 out-of-band**: What measurements are reachable through
   nl80211/`iw` that never appear in the capture path at all? Address survey channel-time
   accounting specifically, and state how it differs in kind from AP-advertised load
   figures carried inside beacons.

4. **Anti-portfolio**: Which of the fields identified above are unreliable,
   driver-dependent, misleading for a single fixed antenna, or commonly misinterpreted in
   published work? Name the specific failure mode for each.

5. **Champions**: Given every constraint above, propose 3 to 6 candidate measurements this
   instrument could produce that it currently does not.

6. **Hidden costs**: For each candidate, what is the non-obvious failure mode across a
   continuous 12-month series? Address calibration drift, kernel and driver version
   changes, and the risk of introducing a discontinuity mid-series.

---

## VI. OUTPUT STRUCTURE

1. **Field inventory table**, in three clearly separated sections (Frame IEs / Radiotap /
   nl80211). Columns: field name; identifier (element ID, Radiotap bit, or nl80211
   attribute); quantity measured; `mt76` population verdict (populated / absent /
   conditional / unknown); source citation.
   *Confidence: score each row 1-10 based on the number of independent sources.*

2. **Anti-portfolio**: fields to avoid or treat with caution, each with its specific
   failure mode and a citation.

3. **Candidate measurements**, 3 to 6, each carrying:
   - what it measures, and why it is interesting from a single fixed station
   - acquisition delta: precisely what changes (BPF filter, parser, new nl80211 call,
     dwell adjustment)
   - **PARSE-ONLY or CAPTURE-CHANGING** flag. Parse-only means the bytes are already
     present in the retained PCAP archive and the entire history can be backfilled.
     Capture-changing means data exists only from the change date forward and a
     discontinuity is introduced into the series
   - collector complexity: low / medium / high, with justification
   - single-station feasibility: explicit yes / no / degraded
   *Confidence: score each candidate 1-10.*

   Rank parse-only candidates first, then by ascending collector complexity.

4. **The 6 GHz question**, addressed directly: can the presence of 6 GHz access points be
   established from Reduced Neighbor Report elements carried in 2.4 and 5 GHz beacons that
   have already been captured? If so, give the element ID, the field layout, and the exact
   tshark field expression or filter that would extract it from an existing PCAP.

5. **Data gaps**: flag every recommendation resting on a single source, and every `mt76`
   population verdict marked unknown. For each, state the specific command or test that
   would resolve it on this hardware.
