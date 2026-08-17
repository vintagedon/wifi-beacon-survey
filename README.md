<!--
---
title: "Wi-Fi Beacon Survey"
description: "A fixed passive 802.11 receiver producing longitudinal analysis-ready datasets of access point beacon telemetry"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-08-17"
version: "1.1"
status: "Discovery prototype"
tags:
  - type: project-root
  - domain: [instrument, dataset]
  - tech: [bash, python, tcpdump, tshark, parquet, postgres]
related_documents:
  - "[Agent Instructions](AGENTS.md)"
  - "[Documentation Standards](docs/documentation-standards/README.md)"
  - "[Scripts](scripts/README.md)"
---
-->

<div align="center">

<img src="assets/icon.svg" alt="Wi-Fi Beacon Survey" width="128" height="128" />

# Wi-Fi Beacon Survey

---

**Longitudinal passive 802.11 beacon telemetry from a single fixed vantage point.**

One receiver, one location, every frequency the regulatory domain permits.
Non-observations are recorded as explicitly as detections, because an empty
frequency is a measurement rather than a gap.

![Capture](https://img.shields.io/badge/Capture-Passive-2F7D76)
![Bands](https://img.shields.io/badge/Bands-2.4%20%2F%205%20%2F%206%20GHz-2F7D76)
![Receiver](https://img.shields.io/badge/Receiver-MT7921AU-555555)
![Clients](https://img.shields.io/badge/Client%20Frames-None%20Retained-555555)
![Status](https://img.shields.io/badge/Status-Discovery%20Prototype-orange)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)
[![Data License](https://img.shields.io/badge/Data-CC--BY--4.0-blue)](LICENSE-DATA)

[Overview](#overview) &middot;
[Architecture](#architecture) &middot;
[Hardware](#hardware-and-environment) &middot;
[Instrument](#instrument-characteristics) &middot;
[Tooling](#tooling) &middot;
[Scope](#scope) &middot;
[Related Work](#related-work)

</div>

---

Most Wi-Fi tooling answers "what is around me right now." This answers "what has been around this one spot, measured the same way, for a long time." The instrument tunes every frequency its regulatory domain permits, dwells for a fixed interval, and records what it heard along with what it did not hear. An empty frequency produces a row.

---

## Overview

The acquisition layer is deliberately small. A monitor-mode adapter is tuned to each permitted 20 MHz frequency in turn, beacons are captured with tcpdump, and each sweep produces per-frequency PCAP alongside a manifest describing every frequency the kernel listed and what happened at it. Nothing is interpreted at capture time.

Retained PCAP is the source of record. Any change to how a field is parsed can be replayed across the entire archive, so the schema is never urgent and the evidence never expires. PostgreSQL, when it exists, is a projection that can be dropped and rebuilt.

The property that makes the output useful is symmetry between detection and non-detection. A sweep that finds nothing on 59 of 98 frequencies has measured those 59 frequencies, and a series of such sweeps supports questions about prevalence and change that a snapshot cannot.

The current repository is a validated discovery prototype, not yet the
production longitudinal collector. Its per-frequency manifest is written during
the run rather than atomically at completion. The next central-queue
specification will establish the production collection contract before the
continuous series begins.

---

## Architecture

```
AWUS036AXM (monitor, passive)
  → per-frequency PCAP + sweep manifest        [evidence, permanent]
    → normalised beacon observations           [Layer 0]
      → reusable derived quantities            [Layer 1]
        → release transform
          → published dataset
```

| Layer | Contents | Rebuildable |
|-------|----------|-------------|
| Evidence | PCAP per frequency, sweep manifest, collector metadata | No, this is the measurement |
| Layer 0 | Decoded beacon observations, one row per BSSID per frequency | Yes, from evidence |
| Layer 1 | Reception ratio, capability decode, security normalisation, identity grouping | Yes, from Layer 0 |
| Release | Published tables with release-stage content decisions applied | Yes, from Layer 1 |

Scheduled execution is planned as bounded Semaphore jobs rather than a long-lived daemon. Scheduling begins only after the production collection contract defines an atomic completion marker and makes partial runs unambiguous.

---

## Hardware and Environment

| Component | Detail |
|-----------|--------|
| Adapter | Alfa AWUS036AXM (MediaTek MT7921AU, `mt7921u` driver in the `mt76` tree) |
| Chains | Single antenna path; the driver reports two receive chains |
| Host | ML01, Linux, `iw` for radio control, libpcap for capture |
| Regulatory | US. All 6 GHz frequencies enumerate as `no-ir` |
| Sweep | 101 frequencies derived from live kernel regulatory state, 98 attempted, 10 s dwell, roughly 996 s per full sweep |
| Data path | `/opt/agents/repos/storage-mounted/wifi-beacon-survey`, outside the Git repository |

Capture volume is approximately 1.16 MB per sweep, which is 425 MB per year at daily cadence and 10 GB per year at hourly.

---

## Instrument Characteristics

These are measured properties of this receiver, established against retained capture rather than from documentation. They constrain what the dataset can claim.

| Property | Finding |
|----------|---------|
| Noise floor | Not reported by the driver in either Radiotap representation. SNR is not derivable |
| Per-chain signal | Delivered as repeated dBm antenna signal values through Radiotap namespace repetition, three values per frame |
| PHY rate fields | Beacons transmit at legacy basic rates, so Radiotap MCS and VHT fields are absent and cannot classify AP capability |
| Reception ratio ceiling | 0.922 against a theoretical maximum, with the shortfall not yet attributed to a specific cause |
| Detection completeness | Four access points advertised by Reduced Neighbor Report were not received in the sweep that recorded the advertisement. Sweeps are sequential, not simultaneous, so this is not yet a measured miss rate |

The Reduced Neighbor Report deserves particular note. Beacons on one band advertise co-located radios on another, which gives a single fixed station an external reference for access points that should be receivable. That is the only available path to characterising the instrument's own false-negative behaviour.

---

## Repository Structure

```markdown
wifi-beacon-survey/
├── assets/                       # Repository images and diagrams
├── docs/                         # Documentation
│   └── documentation-standards/  # Template library and conventions
├── internal-files/               # Reviewed repository-safe context
├── recycle-bin/                  # Retired files, never deleted
├── scripts/                      # Collector and analysis tooling
├── tests/                        # Focused regression tests
├── .gitignore                    # Evidence and generated-output guard
├── AGENTS.md                     # Agent context and constraints
├── CLAUDE.md                     # Pointer to AGENTS.md
├── CODE_OF_CONDUCT.md            # Community standards
├── CONTRIBUTING.md               # Contribution guidelines
├── LICENSE                       # MIT License (code)
├── LICENSE-DATA                  # CC-BY-4.0 (data and content)
├── SECURITY.md                   # Security policy
├── cspell.json                   # Spell checker configuration
└── requirements.txt              # Python analysis dependencies
```

Capture data is deliberately absent from Git. It lives under the external data root described above; ignore rules provide a second guard against accidental inclusion.

---

## Tooling

| Script | Purpose |
|--------|---------|
| [wifi-beacon-sample.sh](scripts/wifi-beacon-sample.sh) | The collector. Derives frequencies from kernel regulatory state, tunes each in turn, captures beacons, writes PCAP and manifest |
| [analyze-sweep.py](scripts/analyze-sweep.py) | Profiles a single sweep: coverage, positive controls, reception-ratio bounds, identity grouping, quality flags |
| [probe-surfaces.py](scripts/probe-surfaces.py) | Discovers what a capture actually contains: dissector field availability, Radiotap population, Information Element census, RNR and BSS Load extraction |

`probe-surfaces.py` resolves dissector field names against the installed Wireshark build before using them rather than assuming, because published references for the Reduced Neighbor Report namespace disagree with each other and with reality.

---

## Scope

**In scope.** Passive beacon acquisition from one fixed station, normalisation to a stable schema, and longitudinal dataset production with explicit provenance.

**Out of scope permanently.** Channel State Information sensing, which this hardware does not expose. Multi-receiver or time-synchronised capture. Mobility, trajectory, presence, and occupancy inference, none of which a single fixed station can support. Wardriving and BSSID-to-coordinate geolocation. Active scanning and injection. Intrusion detection and rogue access point identification.

**Deferred.** The production collection contract, Semaphore scheduling, PostgreSQL projection, release packaging and its content decisions, ARD Layer 1 materialisation, and the nl80211 survey surface. Dataset release requires its own scrub and re-identification review.

---

## Related Work

[beacondb](https://github.com/beacondb/beacondb) is the nearest active project, a public-domain wireless geolocation database in the Ichnaea lineage. It exists to turn observed BSSIDs into coordinates, which is close to the inverse of this project's purpose: here the receiver's position is fixed and known, and the question is what changes around it over time.

[Kismet](https://www.kismetwireless.net/) is the mature general-purpose reference for monitor-mode capture and channel control. It is treated here as a validation oracle rather than a dependency, since its data model is built for a general sniffer and this instrument's contract is deliberately narrower.

---

## License

- **Code**: [MIT License](LICENSE)
- **Data and content**: [CC-BY-4.0](LICENSE-DATA)

---

Last Updated: August 17, 2026 | Status: Discovery prototype
