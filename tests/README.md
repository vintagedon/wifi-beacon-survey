<!--
---
title: "Tests"
description: "Regression tests for the Wi-Fi beacon collector and analysis tools"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-08-17"
version: "1.0"
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

Focused regression tests for the collector's embedded PCAP parser, the two
Python analysis tools, and the pilot derived pipeline (contract, enrichment,
DuckDB surface, briefing). The suite uses the Python standard library test
runner; the analysis and pipeline tests additionally require the shared-venv
dependencies and tshark. `_synthetic_pcap.py` builds tiny synthetic beacon
captures with real IE bytes so the pipeline tests run without live data.

Run from the repository root:

    python3 -m unittest discover -s tests -v
