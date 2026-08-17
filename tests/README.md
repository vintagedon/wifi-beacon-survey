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

Focused regression tests for the collector's embedded PCAP parser and the two
Python analysis tools. The suite uses the Python standard library test runner;
test_analyze_sweep.py additionally requires the analysis dependencies.

Run from the repository root:

    python3 -m unittest discover -s tests -v
