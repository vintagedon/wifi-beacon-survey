<!--
---
title: "Scripts"
description: "Collector and analysis tooling for the beacon survey instrument"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-08-27"
version: "1.2"
status: "Active"
tags:
  - type: directory-readme
  - domain: instrument
---
-->

# Scripts

Tooling for the survey instrument: one collector that produces sweeps and two read-only tools that characterise what a sweep contains. Nothing here writes into the repository. The collector's output goes to the data volume, and the analysis tools take a sweep directory as an argument.

---

## 1. Contents

```
scripts/
├── wifi-beacon-sample.sh   # The collector: tri-band frequency-driven sweep
├── analyze-sweep.py        # Profile one sweep: coverage, calibration, identity
├── probe-surfaces.py       # Discover what a capture actually contains
├── pilot_contract.py       # Single-source pilot series contract (imported)
├── pilot_enrich.py         # Per-run PCAP enrichment to versioned Parquet
├── pilot_database.py       # DuckDB projection rebuild from Parquet + SQL
├── pilot_report.py         # Deterministic Markdown briefing renderer
├── pilot-update.py         # Stable CLI entrypoint for the pilot pipeline
└── README.md               # This file
```

---

## 2. Files

| File | Description | Status |
|------|-------------|--------|
| [wifi-beacon-sample.sh](wifi-beacon-sample.sh) | Derives permitted frequencies from live kernel regulatory state, tunes each in turn with `iw`, captures beacons with tcpdump, and writes per-frequency PCAP plus a sweep manifest. Every run also writes `instrument.json` (run status, regulatory domain, USB location, capture parameters); an absent interface produces a skip record and exits 0 | ⚠️ Discovery prototype; production completion contract pending |
| [analyze-sweep.py](analyze-sweep.py) | Profiles a completed sweep: band coverage, positive-control check, reception-ratio bounds, radio-family resolution, SSID and RF profiling, quality flags | ✅ Active |
| [probe-surfaces.py](probe-surfaces.py) | Seven read-only passes over a sweep: dissector field availability, Radiotap population, truncation check, Information Element census, Reduced Neighbor Report extraction with detection-completeness comparison, BSS Load, advertised identity structure | ✅ Active |
| [pilot_contract.py](pilot_contract.py) | Machine-enforced form of the [pilot analysis contract](../docs/pilot-analysis-contract.md): series eligibility, attempt states, expected hourly slots, derived table schemas. Every producer and consumer imports from here | ✅ Active |
| [pilot_enrich.py](pilot_enrich.py) | Replays one pilot run into versioned per-run Parquet (run, frequencies, observations, IE capabilities, RNR, BSS Load, field resolution) with hashed source identity and an atomic derivation manifest. Read-only against evidence | ✅ Active |
| [pilot_database.py](pilot_database.py) | Rebuilds `derived/pilot.duckdb` from the versioned Parquet layer, verified manifests, and [`sql/pilot/pilot_views.sql`](../sql/pilot/pilot_views.sql) | ✅ Active |
| [pilot_report.py](pilot_report.py) | Renders the deterministic technical briefing to `reports/pilot-latest.md` from fixed templates and query results; no LLM, no wall-clock prose | ✅ Active |
| [pilot-update.py](pilot-update.py) | The stable pipeline entrypoint: enrich (idempotent, incremental) -> database -> report, with overridable roots for tests | ✅ Active |

---

## 3. Usage

The collector requires root for monitor-mode control and writes to the data volume:

```bash
sudo ./wifi-beacon-sample.sh                       # full tri-band sweep, 10 s dwell
sudo ./wifi-beacon-sample.sh -b "2.4" -d 2         # quick 2.4 GHz validation
sudo ./wifi-beacon-sample.sh -o /some/other/path   # override output base
```

The default output base is `sweeps/`. Scheduled discovery-phase runs override it to `pilot/`, which is where the current hourly series accumulates; `sweeps/` stays empty until pilot data is promoted. The analysis tools are read-only and take whichever sweep directory you want to profile:

```bash
python3 analyze-sweep.py /opt/agents/repos/storage-mounted/wifi-beacon-survey/pilot/<sweep-id>
python3 probe-surfaces.py /opt/agents/repos/storage-mounted/wifi-beacon-survey/pilot/<sweep-id> --tsv ./out
python3 probe-surfaces.py <sweep-dir> --only radiotap
python3 pilot-update.py                # enrich + database + report, production paths
python3 pilot-update.py --stage enrich --pilot-root /tmp/kilo/pilot
```

---

## 4. Conventions

`probe-surfaces.py` resolves every dissector field name against `tshark -G fields` before using it, and reports an unresolved name as a finding rather than emitting an empty column. This is not defensive style, it is a correction: published references for the Reduced Neighbor Report namespace disagree with each other, and three defects in this repository came from treating a failed lookup as evidence that something was absent from the environment. Frames with repeated, unpaired RNR values are retained and marked structurally ambiguous rather than interpreted positionally.

The current collector writes its manifest directly and does not yet provide an atomic completion marker. Treat a sweep as a discovery-prototype artifact until the pending collection-contract specification defines manifest finalisation, checksums, runtime provenance, and completion semantics.

Run status is machine-readable without the completion marker: `instrument.json` carries `run_status` (`sweep`, `skipped_no_interface`, `running`, `failed`), and a skip record is distinguishable from an empty sweep by that field plus a zero-row manifest - never by inferring from an empty directory. Iteration and validation sweeps go to a scratch path (`-o`), never into `pilot/` or the archive.

Changes to these tools fall into two categories with very different costs. A parsing change is free, because retained PCAP can be reprocessed across the whole archive. A capture change, meaning dwell length, scan order, snaplen, or the capture filter, alters what future sweeps mean relative to past ones and introduces a discontinuity that no amount of reprocessing repairs.

---

## 5. Dependencies and tests

Install the analysis dependencies from the repository root:

```bash
python3 -m pip install -r requirements.txt
```

Run the focused regression suite:

```bash
python3 -m unittest discover -s tests -v
```

---

## 6. Related

| Document | Relationship |
|----------|--------------|
| [Repository root](../README.md) | Parent directory |
| [Agent Instructions](../AGENTS.md) | Constraints that govern changes to these scripts |
| [Shell script header](../docs/documentation-standards/script-header-shell.md) | Header convention for `.sh` files |
| [Python script header](../docs/documentation-standards/script-header-python.md) | Header convention for `.py` files |
