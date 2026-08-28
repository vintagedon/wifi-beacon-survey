<!--
---
title: "Deep Research Prompt: ARD Layer 0/1 Materialization for the Beacon Survey"
description: "Bounded research prompt asking which derived quantities to materialize once, as Layer 1 columns, from a fixed passive single-vantage 802.11 beacon series"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-08-28"
version: "1.0"
status: "Active"
tags:
  - type: reference
  - domain: [dataset, analysis]
  - tech: [postgres, parquet]
related_documents:
  - "[Sweep profiler](../scripts/analyze-sweep.py)"
  - "[Surface probe](../scripts/probe-surfaces.py)"
  - "[GDR 01, data surfaces](gdr-prompt-01-mt7921au-data-surfaces.md)"
  - "[ARD framework](https://github.com/vintagedon/analysis-ready-datasets)"
  - "[Documentation index](README.md)"
---
-->

# Deep Research Prompt: ARD Layer 0/1 Materialization for the Beacon Survey

Bounded research prompt in the five-layer negative-space form. GDR 01 asked what the
receiver and the beacon body expose; that question is answered, and `probe-surfaces.py`
now extracts those surfaces. This prompt asks the next question: of everything we can
extract, which derived quantities should we compute once and store as columns, so that
downstream users query them instead of recomputing them.

The target is an Analysis-Ready Dataset in the layer model of the ARD framework
(Layer 0 raw, Layer 1 literature-validated scalars, Layer 2 vectors, Layer 3 graphs).
This prompt is scoped to Layer 0 and Layer 1 plus a shallow inventory of the Layer 2/3
surface, deliberately. It sets the foundation. The embedding and graph work is a later,
separately bounded prompt.

Written to be run across the three-model set. Its findings set the Layer 1 column
inventory and the capture-configuration floor that the collection contract is written
against.

---

Act as a research data engineer who builds Analysis-Ready Datasets from longitudinal
instrument measurements, with working knowledge of 802.11 beacon semantics and RF
measurement practice. The goal is a materialization inventory: a ranked set of candidate
derived columns, each grounded in what the measurement community actually computes and in
the schemas of existing published datasets, not in generic tutorials or in what is merely
possible to calculate.

The instrument exists, works, and is producing an hourly series. The raw surfaces are
known and extractable. The open question is which of them are worth precomputing, at which
layer, and what each one costs to acquire.

---

## I. ANCHORS (Immutable Context)

**Instrument Reality:**

- Single fixed indoor passive receiver, permanently sited. Alfa AWUS036AXM, MediaTek
  MT7921AU, `mt7921u` driver, monitor mode via mac80211/nl80211
- One radio, single antenna path. No second receiver, no GPS, no mobility
- Passive reception only. No transmission, injection, active scanning, or regulatory
  override. Regulatory domain US; 6 GHz enumerates `no-ir`, so it yields no beacons under
  passive reception and is a structural zero for now

**Data Surface Reality (already demonstrated extractable):**

- Aggregate surface: per-BSSID, per-frequency observations carrying band, frequency,
  channel, BSSID, SSID, beacon count, beacon interval (TU), RSSI min/mean/max, first seen,
  last seen, beacon reception ratio; plus a per-frequency manifest that retains negative
  observations and regulatory state, and a per-sweep provenance log
- Deep beacon-body surface: the full Information Element set across the standard and
  extension (element 255) namespaces, Reduced Neighbor Report, BSS Load, Multiple BSSID,
  and per-chain Radiotap receive metadata
- Out-of-band surface, not currently collected: nl80211/`iw survey` channel-time
  accounting, which is the receiver's own measurement of medium-busy fraction, distinct in
  kind from the AP-advertised BSS Load figure carried in beacons

**Capture-Configuration Reality (adjustable, this is the key degree of freedom):**

- Capture parameters are NOT fixed. snaplen, per-frequency dwell, cadence, and whether an
  nl80211 survey read is added at sweep time can all be set to whatever a target column
  requires, before the production collection contract is written
- Current pilot values are snaplen 1024, 10 s dwell, hourly. snaplen 1024 truncates large
  HE/EHT beacons, so the deep-surface elements that ride in the beacon tail are at risk at
  the current value; this is a current setting to be revised, not a constraint

**Pipeline and ARD Reality:**

- Files are the immutable source of record. Per-frequency PCAP is retained permanently.
  Parquet is the machine-readable artifact. PostgreSQL is a rebuildable projection, never
  the source
- Because PCAP is retained, a column derived purely by parsing can be backfilled across
  the entire historical archive retroactively (PARSE-ONLY). A column that needs a new
  capture behaviour exists only from the change date forward and introduces a series
  discontinuity (CAPTURE-CHANGING)
- Storage is explicitly not a constraint. Roughly 1 MB per sweep, multiple TB of NVMe

**Longitudinal Reality:**

- Hourly cadence, intended to run continuously for 12 or more months from one vantage
- The time axis is the dataset's reason to exist. A derived quantity that only becomes
  meaningful across many sweeps is higher-value here than one computable from a single
  sweep, and both are in scope

**Measured Baseline (single sweep, 2026-08-27 23:00):**

- 118 unique BSSIDs, 88 on 2.4 GHz and 30 on 5 GHz; 18 of 98 attempted frequencies
  populated, 80 recorded as negative observations
- Zero detections across all 6 GHz frequencies, expected under `no-ir`
- Modal beacon interval 100 TU; reception ratio ceilings near 0.9 for strong local APs

---

## II. WALLS (Domain Exclusions)

The following categories are OFF-LIMITS. Do not search, retrieve, or propose columns from
them:

- NO wardriving, war-walking, BSSID-to-coordinate geolocation, or trilateration metrics
  (one fixed point, no GPS, no movement; any location-derived column is unbuildable here)
- NO multi-receiver, distributed-sensor, or time-synchronised metrics (single radio is an
  anchor; anything needing a second receiver is unbuildable)
- NO human presence, occupancy, trajectory, or activity inference, and NO Channel State
  Information sensing (the MT7921AU does not expose CSI through `mt76`; this is a different
  acquisition path)
- NO metrics requiring client-side frames: probe requests, association, or data frames.
  The capture surface is beacon-only; broadening it is a separate future decision, not this
  foundation. Restrict to beacon-body, Radiotap receive-side, and nl80211 survey quantities
- NO active techniques of any kind (passive-only is an anchor)
- NO WIDS, IDS, rogue-AP, or evil-twin detection framing (this is a measurement dataset,
  not security tooling; a beacon-derived quantity may still qualify as a neutral column, see Gates)
- NO real-time, streaming, or online-processing architecture (the projection is a
  rebuildable batch product, materialised offline from retained files)
- NO storage compression, sampling, or data-reduction research (storage is not a constraint)
- NO consumer Wi-Fi troubleshooting, home-network optimisation, router recommendation, or
  "best Wi-Fi analyser" content (the SEO layer that will otherwise dominate results)

## III. VECTOR SEEDS (Positive Space Targeting)

PRIORITIZE, existing dataset schemas as the primary evidence:

- Published Wi-Fi and RF measurement datasets where the actual column list or data
  dictionary is retrievable, treated as evidence of what experienced builders chose to
  precompute: WiGLE's data dictionary, the Kismet `kismetdb` log schema and its IE parsing,
  and any academic beacon-census or spectrum-occupancy dataset on Zenodo, IEEE DataPort, or
  CRAWDAD mirrors
- The ARD framework repository and its DESI and Steam case studies, for the layer-model
  materialization pattern: what "high-friction metric" means, and how a Layer 1 column is
  defined and documented

PRIORITIZE, measurement literature for the derived quantities themselves:

- Network measurement venues, for what beacon and spectrum-occupancy studies actually
  compute: IMC, PAM, CoNEXT, SIGCOMM, MobiCom, WiNTECH, TMA
- Spectrum-occupancy and ISM-band measurement literature, for the temporal-occupancy metric
  family (duty cycle, channel-busy fraction, occupancy over time), directly transferable to
  a fixed-vantage series
- IEEE 802.11-2020 and the ax/be amendments, for the standard semantics of any IE field
  that would become a column, so each definition is anchored to clause text rather than
  folklore
- Wireshark/tshark dissector source and Kismet IE parsing as the practical field-name
  reference (already resolved against this build in `probe-surfaces.py`)

PRIORITIZE, adjacent fixed-sensor networks for provenance and drift precedent:

- ADS-B receiver networks (OpenSky), spectrum monitoring, radio astronomy pipelines, and
  air-quality sensor networks, specifically for how they materialise instrument-health,
  provenance, and calibration-drift columns alongside the measurements over long runs

DE-PRIORITIZE:

- Vendor marketing and datasheets lacking field-level detail
- Aircrack-ng, Kali, and pentest tooling walkthroughs
- Medium, dev.to, and tutorial-farm content
- Papers that report findings without naming the measured or derived field, or without a
  retrievable schema; they cannot be mapped to a column

## IV. GATES (Conditional Inclusion)

- Academic papers: PERMITTED ONLY IF the paper defines a derived quantity computable from
  beacon-body IEs, Radiotap receive metadata, or nl80211 survey statistics, AND names the
  input field. Papers reporting conclusions without the underlying computed quantity are
  excluded
- Published datasets: PERMITTED ONLY IF the actual column list or data dictionary is
  retrievable, not merely a paper describing one
- Mobile and wardriving datasets: PERMITTED ONLY IF a specific column is vantage-independent
  (for example an IE-derived capability or generation flag) and therefore transferable to a
  fixed station. Their location and trajectory columns stay walled
- Security and WIDS literature: PERMITTED ONLY IF it defines a neutral, beacon-derived
  measurable quantity (for example beacon-interval consistency or a capability-bit
  distribution) usable as a dataset column once stripped of its detection framing
- Adjacent fixed-sensor domains: PERMITTED for provenance, instrument-health, and
  calibration-drift column precedent only, and must be labelled as transferred from that
  domain

- PIVOT: If fewer than three fixed-vantage longitudinal 802.11 datasets with retrievable
  schemas exist, which is likely because most public 802.11 data is mobile wardriving, then
  redirect to reverse-engineering columns from mobile-dataset schemas while keeping only the
  vantage-independent ones, and to the spectrum-occupancy literature for the temporal metric
  family
- PIVOT: If a candidate column's literature basis is thin but the raw field is clearly
  present in our captures, return it flagged as novel or underspecified, with the exact
  definition we would have to fix ourselves, rather than dropping it

## V. RESEARCH QUESTIONS

With the above constraints applied:

1. **Champions, per-observation scalars**: Which per-BSSID or per-sweep derived quantities
   do the measurement literature and existing dataset schemas actually materialise from
   beacon observations? For each, name the input field and surface and give the precise
   definition. Cover at least identity resolution, capability and generation flags,
   AP-reported load, and RSSI summary statistics.

2. **Champions, longitudinal scalars**: Which derived quantities exist only across the time
   series and are the reason a longitudinal ARD has value? Consider BSSID persistence and
   dwell-fraction over N sweeps, churn and turnover, diurnal occupancy, appearance and
   disappearance events, per-BSSID RSSI drift, and generation-mix trend. Define each and
   state the minimum series length before it is meaningful.

3. **Provenance and instrument health**: What Layer 0 provenance and instrument-health
   columns do mature fixed-sensor datasets carry so that a 12-month series stays
   interpretable across kernel and driver bumps and configuration changes? Address
   per-sweep provenance, per-band positive-control status, reception ratio as a health
   signal, and explicit configuration-change markers.

4. **Acquisition cost**: For each proposed column, what capture configuration does it
   require: a snaplen floor, a per-frequency dwell floor, or an nl80211 survey read added at
   sweep time? Flag each as PARSE-ONLY, backfillable from retained PCAP, or CAPTURE-CHANGING,
   requiring a collector change and introducing a series discontinuity.

5. **Anti-portfolio**: Which commonly published beacon-derived quantities are unreliable,
   misleading, or meaningless from a single fixed passive vantage and should not be
   materialised, or must carry a mandatory confound caveat? Name the specific failure mode
   for each. Address at minimum AP-advertised BSS Load as the AP's self-report rather than
   our measurement, RNR non-observation in a sequential sweep as not a calibrated miss rate,
   and single-vantage RSSI as not a distance.

6. **Prior-art schemas**: What column sets do the closest existing public datasets publish
   (WiGLE, `kismetdb`, any academic beacon census), and for each relevant column, should we
   adopt, adapt, or reject it given the fixed-vantage anchor?

7. **Layer 2/3 forward inventory, bounded**: Name the natural embedding targets (per-BSSID
   behavioural vectors) and graph edges (RNR advertises-neighbour, co-located radio family,
   shared-service SSID membership, channel co-occupancy) that a later phase could build, so
   that the Layer 1 design does not foreclose them. Inventory only. Do not research
   embedding models or graph algorithms.

## VI. OUTPUT STRUCTURE

1. **Materialization inventory table**, the core deliverable. One row per candidate column,
   grouped by scope: per-observation scalar, longitudinal scalar, and provenance or health.
   Columns: proposed column name; precise definition, standard-referenced where applicable;
   input field and surface (beacon IE / Radiotap / nl80211); ARD layer; PARSE-ONLY or
   CAPTURE-CHANGING; capture-configuration requirement (snaplen, dwell, survey); single-
   vantage validity (valid / degraded / invalid); confound note stating what the column is
   NOT; literature or schema basis with citation.
   *Confidence: score each row 1-10 by count of independent sources.*
   Rank PARSE-ONLY rows first, then by ascending collector complexity.

2. **Longitudinal-metric detail**: for the cross-sweep quantities, the minimum series length
   and the temporal aggregation each requires.

3. **Anti-portfolio**: quantities to avoid or to caveat, each with its specific failure mode
   from a single fixed passive vantage and a citation.

4. **Provenance and health schema**: recommended Layer 0 provenance and instrument-health
   columns, each with why it matters across a 12-month series.

5. **Prior-art schema comparison**: the closest public datasets, their column sets, and an
   adopt / adapt / reject verdict per relevant column.

6. **Capture-contract implications**: a consolidated short list of the capture-configuration
   changes implied by the PARSE-ONLY versus CAPTURE-CHANGING split, in particular the snaplen
   floor needed to stop truncating deep-surface elements, any dwell floor, and whether to add
   an nl80211 survey read. This is the bridge to the collection contract spec.

7. **Layer 2/3 forward inventory**: named embedding targets and graph edges, inventory only,
   with the Layer 1 columns each would depend on.

8. **Data gaps**: flag every recommendation resting on a single source, and every column
   whose definition we would have to fix ourselves. For each, state the specific test or
   decision that would resolve it.
