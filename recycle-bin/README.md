<!--
---
title: "Recycle Bin"
description: "Agent trash can for files deemed unnecessary"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-08-16"
version: "1.1"
status: "Active"
tags:
  - type: directory-readme
  - domain: documentation
---
-->

# Recycle Bin

Agent trash can. This directory receives files that an agent has determined are unnecessary for the project. It is always gitignored.

**Agents never delete files.** When an agent determines a file is unnecessary, it moves the file here and documents the reason in the table below. The human reviews this directory during QC and either permanently deletes the files or restores them to their original location.

This convention exists because agents sometimes misjudge what's needed. A deleted file requires re-creation from memory or template; a recycled file requires a move command. The cost asymmetry favors recycling.

---

## 1. Recycled Files

| File | Original Location | Reason | Date |
|------|--------------------|--------|------|
| data-science-infrastructure-2026-04-07.md | docs/ | Project-specific example from the astronomy cluster; does not belong in a generic template repo | 2026-04-26 |

---

## 4. Related

| Document | Relationship |
|----------|--------------|
| [Repository Root](../README.md) | Parent directory |
| [AGENTS.md](../AGENTS.md) | Documents the recycle convention |

---

## 5. Rules

**Agents must never recycle:**

- Anything in `internal-files/` (human's source materials)
- Templates in `docs/documentation-standards/` (reused for future documents)
- Licenses, CODE_OF_CONDUCT.md, CONTRIBUTING.md, SECURITY.md (standard repo furniture)
- AGENTS.md, README.md (agent context and project identity)

**Agents may recycle with justification:**

- Script header templates for languages not in the project's tech stack
- Gitignore sections for technologies not in use (but prefer commenting out over removing)
- Utility scripts the project won't use

**Never recycled because it never lives here:** capture data. Sweep artifacts are
held outside the repository at
`/opt/agents/repos/storage-mounted/wifi-beacon-survey` and are the project's
primary evidence. Nothing in the repository tree should ever contain a PCAP to
recycle in the first place.
