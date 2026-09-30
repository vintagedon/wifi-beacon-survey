<!--
---
title: "Tests"
description: "Regression tests for the Wi-Fi beacon collector and analysis tools"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-09-29"
version: "1.1"
status: "Active"
tags:
  - type: directory-readme
  - domain: instrument
  - tech: python
related_documents:
  - "[Scripts](../scripts/README.md)"
---
-->

# Tests

Focused regression tests for the collector (embedded PCAP parser and the
regulatory domain preflight), the two Python analysis tools, the pilot
derived pipeline (contract, enrichment, DuckDB surface, briefing), and the
PostgreSQL ingestion path (source-to-column mapping, DDL idempotence and
survey/archive identity, loader behavior against synthetic fixtures). The
suite uses the Python standard library test runner; the analysis and pipeline
tests additionally require the shared-venv dependencies and tshark. The
collector preflight tests run the full script against stubbed `iw`/`ip`/
`tcpdump` and need root; the DDL and loader tests need the pgsql01
credentials from the scoped Doppler runtime and only ever touch
`wifi_beacon_survey_test`. `_synthetic_pcap.py` builds tiny synthetic beacon
captures with real IE bytes so the pipeline tests run without live data.

Run from the repository root:

    python3 -m unittest discover -s tests -v
