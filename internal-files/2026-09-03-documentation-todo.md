<!--
---
title: "Documentation To-Do"
description: "Inventory of the public-facing and consumer-facing documentation this repository owes, with what each is blocked on"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-09-03"
version: "1.0"
status: "Active"
tags:
  - type: planning
  - domain: documentation
related_documents:
  - "[Repository README](../README.md)"
  - "[Agent Instructions](../AGENTS.md)"
  - "[Pilot Analysis Contract](../docs/pilot-analysis-contract.md)"
---
-->

# Documentation To-Do

An inventory, not a schedule. Nothing here carries a date and nothing here is
committed to. It exists so the same gap analysis does not get redone from
scratch every few weekends.

The governing decision, stated once: **no consumer-facing documentation gets
written until the target schema is settled.** A data dictionary is the schema
in prose. Writing one against the provisional pilot contract produces a
document that has to be thrown away, and worse, a public document that
describes a shape the project has already abandoned.

---

## 1. What exists

The public surface is larger than it feels from inside the work.

| Artifact | State |
|----------|-------|
| Root `README.md` | Substantial and genuinely public facing. Carries overview, architecture, hardware, measured instrument characteristics, scope boundaries, and related work |
| `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md` | Present |
| `LICENSE` (MIT), `LICENSE-DATA` (CC-BY-4.0) | Present, code and data split already decided |
| `docs/instrument-changelog.md` | IC-001 recorded with before and after evidence |
| `docs/operations-runbook.md` | Receiver failure modes and triage |
| `docs/pilot-analysis-contract.md` | Provisional derived contract. Written for us, not for a reader |
| `AGENTS.md` | Agent context and architectural constraints |

The instrument characteristics table in the root README is the strongest piece
of public documentation the project has, because it states limits rather than
capabilities.

---

## 2. What is missing

### 2.1 Dataset consumer documentation

Nothing here can be written before the schema decision.

- Data dictionary: every column, its type, its unit, its null semantics, and what a zero means as distinct from a null
- The negative-observation contract in reader-facing terms. A sampled-empty frequency is a measurement; a missing hourly slot is not. That distinction is the dataset's whole point and no public document explains it
- Attempt-state semantics: what `completed_sweep`, `skipped_no_interface`, `failed`, `malformed`, and `missing_hourly_slot` mean for someone computing a denominator
- Grain statements per table. Frame grain for RNR and BSS Load, BSSID-per-frequency for observations, and why RNR rows are preserved unpaired
- Series and epoch boundaries. Why capture before IC-001 is not comparable to capture after it, and how a consumer spanning the boundary is expected to handle that

### 2.2 Methodology

Writable sooner. Mostly independent of the schema.

- How a sweep works: regulatory-derived frequency list, fixed dwell, sequential tuning, what gets retained
- Why sequential scanning makes advertised-but-not-observed a timing statement rather than a miss rate
- Known instrument limits in one place rather than scattered across the README table and the review surfaces. No noise floor, no SNR, no PHY-rate classification from beacons, reception ratio ceiling unattributed
- The 6 GHz situation stated honestly for an outside reader: zero direct observations, no positive control, `no-ir` regulatory constraint, and the falsification test still open

### 2.3 Reproduction

- Hardware bill of materials with the antenna, cable, and the USB controller constraint
- Driver, regulatory domain setup, and the two failure modes that recur (controller assignment, domain reverting across driver reload)
- How to run a single sweep and how to rebuild the derived layer from retained evidence

### 2.4 Release documentation

Blocked on the release decision itself, which is blocked on the scrub and
re-identification review.

- What is published and what is withheld, with the reasoning
- Citation guidance and whether a DOI is minted. Note that DOI minting is
  permanent and making a private repo public exposes full history, so both are
  their own work unit
- Provenance chain from retained PCAP through to published table

### 2.5 Interpretation guardrails

The scope section of the root README already says what is out of scope. A
consumer-facing version needs to say the same thing in terms of claims rather
than features: this dataset does not support mobility, presence, occupancy, or
geolocation inference; near-field response changed at IC-001; and any claimed
change smaller than the observed run-to-run churn floor is noise.

---

## 3. Ordering

1. Methodology and reproduction. Independent of the schema, useful immediately,
   and mostly a matter of collecting what is already written down
2. The interpretation guardrails, which can ride along with methodology
3. Everything in 2.1, after the materialization decision
4. Everything in 2.4, after the release decision

---

## 4. Housekeeping already known

Tracked here so it does not get lost, and being repaired under the
`01a` amendment rather than left for a documentation pass:

- `docs/README.md` contents block carries leaked Python string delimiters and
  three duplicated lines, committed and rendering publicly
- `docs/README.md` does not list `gdr-prompt-02-ard-materialization.md`
- Root `README.md` structure tree omits `sql/`
- `internal-files/README.md` numbers its sections 1, 2, 4
