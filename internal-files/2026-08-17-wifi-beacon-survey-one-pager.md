# Wi-Fi Beacon Survey

**Domain:** Passive RF measurement and analysis-ready dataset production  
**Status:** Discovery prototype validated; production collection contract pending  
**Date:** 2026-08-17  
**Version:** 1.0  
**Prepared for:** cross-model repository onboarding

---

## Vision

A single fixed passive 802.11 receiver sweeps the 2.4, 5, and 6 GHz bands,
records detections and explicit non-observations, and produces a longitudinal
dataset for downstream analysis. The product is the dataset and its
methodology, not a scanner, WIDS, wardriving tool, or geolocation service.

The repository contains source code, tests, schemas, and methodology. Capture
evidence and identifier-bearing derived files stay outside Git under
/opt/agents/repos/storage-mounted/wifi-beacon-survey.

---

## Current Instrument

| Attribute | Value |
|-----------|-------|
| Adapter | Alfa AWUS036AXM, MediaTek MT7921AU, mt7921u |
| Host | ML01 |
| Mode | Passive monitor mode; beacon management frames only |
| Sweep | Frequencies derived from live kernel regulatory state |
| Prototype dwell | 10 seconds per frequency |
| Source of record | Per-frequency PCAP plus sweep metadata |
| Projection | PostgreSQL and Parquet are rebuildable outputs, not evidence |

The validated discovery sweep listed 101 frequencies, attempted 98, populated
11, retained 87 sampled-empty observations, and recorded 2,490 beacons from 28
BSSIDs. Those counts establish that the prototype can execute a complete
frequency-driven sweep; they do not establish calibrated sensitivity.

---

## Architectural Decisions

- The collector remains bounded and passive.
- Empty sampled frequencies are first-class measurements.
- PCAP and completion metadata are authoritative; databases are projections.
- Capture-changing decisions require an explicit series-continuity decision.
- Parsing changes are replayable against retained evidence.
- Generated evidence, derived identifier-bearing files, and private mappings
  never enter Git.
- Dataset release and re-identification review are separate future work.

---

## Known Limits

- The current frequencies.tsv is written during collection and is not yet an
  atomic completion marker.
- A maximum observed beacon-reception ratio from one sweep is an upper bound,
  not a calibrated fixed loss.
- RNR advertisements and received beacons come from non-concurrent dwell
  windows. An advertised-but-not-observed neighbour is not a calibrated miss.
- Multi-occurrence RNR rows cannot be paired positionally; the probe now
  quarantines them until hierarchical TLV parsing exists.
- Six-gigahertz reception has no positive control in the retained discovery
  evidence.
- Scan order and snaplen are capture-changing choices that must be settled
  before the continuous series starts.

---

## Repository Baseline

The initial repository baseline includes:

- frequency-driven beacon collector
- read-only sweep analyzer
- read-only data-surface probe
- regression tests for empty sweeps, RNR inference boundaries, field
  resolution, BSSID extraction, UTC timestamps, and the external data path
- documentation standards and project operating constraints

Generated discovery runs and probe TSVs are retained under the external data
root and ignored defensively by Git.

---

## Next Milestone

The next central-queue specification should define the production collection
contract: atomic completion metadata, per-artifact hashes, UTC and monotonic
dwell timing, scan index, requested and actual frequency, process exit state,
and runtime provenance. It must also settle scan order and snaplen before
longitudinal collection begins.

Parquet should remain a post-capture materialization rather than a hard
dependency of acquiring the authoritative PCAP evidence.
