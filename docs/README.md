<!--
---
title: "Documentation"
description: "Project documentation, standards, and research inputs"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-08-27"
version: "2.1"
status: "Active"
tags:
  - type: directory-readme
  - domain: documentation
---
-->

# Documentation

Project documentation and the standards that govern it. The `documentation-standards/` subdirectory holds the template library and conventions applied across the repository. Loose files at this level are project documents that do not belong to a narrower directory.

---

## 1. Contents

```
docs/
├── documentation-standards/                  # Template library and conventions
│   ├── primary-readme-template.md
│   ├── interior-readme-template.md
│   ├── general-kb-template.md
│   ├── worklog-readme-template.md
│   ├── one-pager-template.md
│   ├── project-brief-template.md
│   ├── code-commenting-dual-audience.md
│   ├── writing-style-guide.md
│   ├── tagging-strategy.md
│   ├── script-header-python.md
│   ├── script-header-shell.md
│   ├── script-header-powershell.md
│   └── README.md
├── gdr-prompt-01-mt7921au-data-surfaces.md   # Research prompt: unused hardware data surfaces
├── 2026-08-27-hourly-collection-review.md    # Operator review surface: scheduling, archive, skip records
├── instrument-changelog.md                   # Dated record of capture-changing modifications
├── operations-runbook.md                     # Known receiver failure modes and triage
└── README.md                                 # This file
```

---

## 2. Files

| File | Description | Status |
|------|-------------|--------|
| [gdr-prompt-01-mt7921au-data-surfaces.md](gdr-prompt-01-mt7921au-data-surfaces.md) | Bounded research prompt asking what the MT7921AU and the 802.11 beacon body expose that the collector currently discards. Run across three models; findings drove the current parser scope | ✅ Active |
| [2026-08-27-hourly-collection-review.md](2026-08-27-hourly-collection-review.md) | Review surface for the hourly-collection and epoch-archive spec: schedule-fault determination, archive layout, skip-record shape, cadence, output format, unenforced dependencies. Each finding ends in a closed question | 🔍 Under review |
| [instrument-changelog.md](instrument-changelog.md) | Dated register of changes that alter what the receiver can hear, with before and after evidence. Any release spanning a change identifier must expose it | ✅ Active |
| [operations-runbook.md](operations-runbook.md) | Observed failure modes of the receiver on ml01: USB controller enumeration, `btusb` contention on the combo device, and regulatory domain reversion | ✅ Active |

---

## 3. Subdirectories

| Directory | Description |
|-----------|-------------|
| [documentation-standards/](documentation-standards/README.md) | Templates for READMEs, knowledge base articles, briefs, one-pagers, and script headers, plus tagging, commenting, and writing conventions |

---

## 4. Related

| Document | Relationship |
|----------|--------------|
| [Repository root](../README.md) | Parent directory |
| [Agent Instructions](../AGENTS.md) | Loads these standards as part of session context |
| [Tagging Strategy](documentation-standards/tagging-strategy.md) | Controlled vocabulary used by every document here |
