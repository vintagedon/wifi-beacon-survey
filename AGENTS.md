<!--
---
title: "Agent Instructions"
description: "Repository identity, architectural constraints, and session conventions for agents working on wifi-beacon-survey"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-09-29"
version: "1.3"
status: "Active"
tags:
  - type: guide
  - domain: documentation
related_documents:
  - "[Project README](README.md)"
  - "[Tagging Strategy](docs/documentation-standards/tagging-strategy.md)"
---
-->

# Agent Instructions

## Repository Identity

`wifi-beacon-survey` operates a single fixed passive 802.11 receiver that sweeps the 2.4, 5, and 6 GHz bands on a schedule and produces longitudinal analysis-ready datasets of access point beacon telemetry. The instrument records non-observations as explicitly as detections, so an empty frequency is a measurement rather than a gap.

The product is the dataset and its methodology. This is not a scanner, a wireless intrusion detection system, a wardriving tool, or a geolocation service.

## Context Loading

Agents working on this repository should load context in this order:

1. This file (`AGENTS.md`), which covers repository identity, constraints, and conventions
2. `README.md` for project overview and current state
3. `docs/documentation-standards/` for templates and standards to follow
4. `internal-files/2026-08-17-wifi-beacon-survey-one-pager.md` when full project context is needed

## Architectural Constraints

- **The receiver is passive.** It never associates, transmits, sends probe requests, injects frames, or enables active monitor mode. A regulatory tuning refusal is a recorded result, not an error to work around.
- **The regulatory domain is established by the collector, never assumed.** The declared domain is US. Before frequency discovery, the collector reads the effective domain; if it differs from the declared one, the collector sets the declared domain and verifies it, recording the domain found and the domain applied. If the declared domain cannot be established within a bounded time, the run refuses: a recorded refusal and a non-zero exit. A run never sweeps on an undeclared domain. Setting the domain emits nothing, so this rule does not conflict with the passivity constraint above; IC-002 is what it cost when nothing asserted the domain, and IC-003 is what it cost when detection existed but nothing acted on the record.
- **Capture data never enters Git.** Sweep artifacts and identifier-bearing derived files live at `/opt/agents/repos/storage-mounted/wifi-beacon-survey`, outside this repository. Nothing in `scripts/` writes captures into the working tree, and `.gitignore` is a defensive backstop rather than the primary storage mechanism.
- **Files are the source of record.** Retained PCAP and its sweep manifest are authoritative. PostgreSQL is a rebuildable projection and may be dropped and reconstructed at any time. Never treat a database row as evidence.
- **The collector does not interpret.** It records what the radio observed. Entity resolution, capability judgement, congestion assessment, and anomaly detection are downstream concerns and must not influence what gets captured or how it is normalised.
- **Absence is recorded, not omitted.** Every attempted frequency produces a row whether or not it yielded frames. Dropping empty observations destroys the negative-observation property the dataset depends on.
- **A field is not absent until the lookup is verified.** Before reporting that a dissector field, Information Element, or driver capability does not exist, confirm the name resolves on the installed build. Three separate defects in this repository came from treating a failed lookup as an environmental fact.
- **Instrument changes that break series continuity require a decision, not a commit.** Dwell length, scan order, snaplen, and capture filter all alter what future sweeps mean relative to past ones. Parse-only changes are free because the archive can be reprocessed; capture-changing edits are not.

## Documentation Conventions

- All Markdown files require YAML frontmatter (see `docs/documentation-standards/tagging-strategy.md`)
  - Exempt: standard repo furniture (CONTRIBUTING.md, SECURITY.md, CODE_OF_CONDUCT.md, licenses) and source materials in `internal-files/`
- New directories require an interior README (see `docs/documentation-standards/interior-readme-template.md`)
- Script files require language-appropriate headers (see `docs/documentation-standards/script-header-*.md`)
- Follow dual-audience commenting (see `docs/documentation-standards/code-commenting-dual-audience.md`)
- Follow writing style conventions (see `docs/documentation-standards/writing-style-guide.md`)
- Agents never delete files; move unnecessary files to `recycle-bin/` with documented justification

## Commit Messages

- Present tense, imperative mood
- 72-character first line limit
- Reference issues after first line

## Session Pattern

1. Load context (this file + README)
2. Work within defined scope
3. Document changes appropriately
4. Update the central `/opt/agents/repos/work-logs/` area if significant work completed
