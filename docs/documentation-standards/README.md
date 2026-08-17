<!--
---
title: "Documentation Standards"
description: "Templates and guidelines for project documentation"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-04-26"
version: "2.1"
status: "Active"
tags:
  - type: directory-readme
  - domain: documentation
---
-->

# Documentation Standards

Templates for RAG-optimized documentation. Each template follows the "template + guide woven in" pattern: inline HTML comments provide per-section guidance on what to write, where to source it, and when to include or omit sections. Start lean, expand as needed.

---

## 1. Contents

```
documentation-standards/
├── primary-readme-template.md       # Repository root README
├── interior-readme-template.md      # Directory README
├── general-kb-template.md           # Standalone documents
├── worklog-readme-template.md       # Work log entries
├── one-pager-template.md            # Ideation capture (portable context unit)
├── project-brief-template.md        # Project brief (build, engagement, advisory slants)
├── code-commenting-dual-audience.md # Code comment methodology
├── writing-style-guide.md           # Prose conventions and AI tell suppression
├── tagging-strategy.md              # Controlled vocabulary for tags
├── script-header-python.md          # Python script header
├── script-header-shell.md           # Bash script header
├── script-header-powershell.md      # PowerShell script header
└── README.md                        # This file
```

---

## 2. Templates

### Document Templates

| Template | Use For |
|----------|---------|
| [primary-readme-template.md](primary-readme-template.md) | Repository root README.md |
| [interior-readme-template.md](interior-readme-template.md) | Any directory that needs a README |
| [general-kb-template.md](general-kb-template.md) | Standalone documents (guides, specs, reports, runbooks) |
| [worklog-readme-template.md](worklog-readme-template.md) | Date-based work log entries in `work-logs/` |
| [one-pager-template.md](one-pager-template.md) | Ideation capture, AI handoff context units |
| [project-brief-template.md](project-brief-template.md) | Project definition: build, engagement, or advisory slant |

### Script Header Templates

| Template | Use For |
|----------|---------|
| [script-header-python.md](script-header-python.md) | All `.py` files |
| [script-header-shell.md](script-header-shell.md) | All `.sh` files |
| [script-header-powershell.md](script-header-powershell.md) | All `.ps1` files |

### Guidelines

| Document | Use For |
|----------|---------|
| [tagging-strategy.md](tagging-strategy.md) | Controlled vocabulary for YAML frontmatter tags |
| [code-commenting-dual-audience.md](code-commenting-dual-audience.md) | Writing comments for humans and AI agents |
| [writing-style-guide.md](writing-style-guide.md) | Prose conventions, AI tell suppression |

---

## 3. Core Principles

### RAG Infrastructure (Always Keep)

- **YAML frontmatter** enables retrieval and filtering
- **Semantic numbering** provides predictable section structure
- **Preserved gaps** maintain stability: if you omit section 4, keep numbering as 1, 2, 3, 5 (never renumber)

### Template + Guide Pattern

Every template includes inline HTML comment guidance at each section. The guidance covers what to write, where to source it (brief, one-pager, GDRs), and when to include or omit the section. Bottom comment blocks, when present, cover cross-cutting template mechanics only.

### Bottom-Up Approach

- Start with minimal template
- Add sections as content requires
- Don't fill sections for completeness
- Wrapper is thin; content is the point

---

## 4. Template Selection

### Documents

```
Is it the repository root README?
├─ Yes → primary-readme-template.md
└─ No: Is it a directory README?
        ├─ Yes → interior-readme-template.md
        └─ No: Is it an ideation capture?
                ├─ Yes → one-pager-template.md
                └─ No: Is it a project definition (build, engagement, advisory)?
                        ├─ Yes → project-brief-template.md
                        └─ No: Is it a work log?
                                ├─ Yes → worklog-readme-template.md
                                └─ No → general-kb-template.md
```

### Scripts

```
What language?
├─ Python (.py)     → script-header-python.md
├─ Bash (.sh)       → script-header-shell.md
└─ PowerShell (.ps1)→ script-header-powershell.md
```

---

## 5. Related

| Document | Relationship |
|----------|--------------|
| [docs/](../README.md) | Parent directory |
