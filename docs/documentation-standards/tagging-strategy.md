<!--
---
title: "Tagging Strategy Guide"
description: "Controlled vocabulary for document classification and hydration guide"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-03-28"
version: "2.1"
tags:
  - type: guide
  - domain: documentation
related_documents:
  - "[Primary README Template](primary-readme-template.md)"
  - "[Interior README Template](interior-readme-template.md)"
  - "[General KB Template](general-kb-template.md)"
  - "[Worklog README Template](worklog-readme-template.md)"
  - "[One-Pager Template](one-pager-template.md)"
  - "[Project Brief Template](project-brief-template.md)"
---
-->

# Tagging Strategy Guide

## 1. Purpose

This guide explains how to build a controlled tag vocabulary for a repository. Consistent tagging enables human navigation and RAG system retrieval. When forking this template, replace the example domain vocabulary with your project's actual content areas.

---

## 2. Why Controlled Vocabulary

Uncontrolled tagging leads to synonyms fragmenting search (`database` vs `db` vs `databases`), inconsistent granularity (`postgres` vs `relational-database`), and tag proliferation that reduces signal. A controlled vocabulary defines allowed values upfront, ensuring consistency across contributors and time.

---

## 3. Tag Categories

Each category answers a different question about the document. Keep categories orthogonal; each captures a distinct dimension.

| Category | Question Answered | Required |
|----------|-------------------|----------|
| `type` | What kind of document is this? | Yes |
| `domain` | What subject area? | Yes |
| `status` | What's the lifecycle state? | Recommended |
| `tech` | What technologies involved? | When applicable |
| `framework` | What compliance framework? | When applicable |

---

## 4. Domain Tags

Domain tags are project-specific. Replace this section with your project's vocabulary.

### Building Your Domain Vocabulary

1. **Inventory content types.** What kinds of content does this repository contain? Group by function, not format.
2. **Define 5-12 domain values.** Cover your content without excessive overlap.
3. **Write boundary definitions.** One sentence per tag clarifying what belongs and what doesn't.

### Project Domain Vocabulary

```yaml
domain:
  - instrument        # The receiver, capture path, sweep control, calibration
  - dot11             # 802.11 protocol knowledge: frames, elements, operating classes
  - dataset           # Schema, ARD layers, provenance, release packaging
  - analysis          # Downstream interpretation of collected data
  - documentation     # Templates, standards, meta-content
```

| Tag | Belongs Here | Does Not Belong Here |
|-----|--------------|----------------------|
| `instrument` | Hardware behaviour, driver and Radiotap population, dwell and tuning, reception calibration, collector operation | What the captured frames mean |
| `dot11` | Frame structure, Information Element semantics, operating classes, capability decoding | How this specific receiver performs |
| `dataset` | Table and column definitions, layer boundaries, provenance fields, release content decisions | Conclusions drawn from the data |
| `analysis` | Prevalence series, entity resolution, congestion and capability findings | Anything the collector does at capture time |
| `documentation` | Standards, templates, tagging, style | Project subject matter |

A document about how the receiver fails to hear a 6 GHz AP is `instrument`. A
document about what a Reduced Neighbor Report element contains is `dot11`. A
document defining the `observations` table is `dataset`.

### Boundary Rules

- If a document spans two domains, use the primary one. Multi-value only when genuinely split.
- Define clear boundaries between similar domains (e.g., `deployment` is standing up a service; `infrastructure` is the VM it runs on).

---

## 5. Type Tags

| Tag | Use For |
|-----|---------|
| `project-root` | Repository root README |
| `directory-readme` | Interior README for any directory |
| `worklog` | Work log entries and milestone documentation |
| `brief` | Project brief: build, engagement, or advisory slant |
| `one-pager` | Ideation capture (portable context unit for AI handoffs) |
| `guide` | Step-by-step procedures and how-to documents |
| `reference` | Lookup information: inventories, schemas, API docs |
| `specification` | Service specs, deployment definitions, formal requirements |
| `report` | Analysis, findings, audit results, summaries |
| `runbook` | Operational procedures for incident response or maintenance |
| `policy` | Governance policies: commitments and principles |
| `procedure` | SOPs: how activities are carried out |

---

## 6. Status Tags

| Tag | Description |
|-----|-------------|
| `draft` | In development, not yet complete |
| `active` | Current, maintained, approved |
| `under-review` | Scheduled or triggered review in progress |
| `deprecated` | Superseded, avoid for new work |
| `archived` | Historical reference only |

---

## 7. Tech Tags

Use canonical names, lowercase, hyphenated. Build this list as your project's stack takes shape. Check for existing coverage before adding new tags.

```yaml
tech:
  - bash              # Collector and sweep orchestration
  - python            # Analysis and probe tooling
  - tcpdump           # Frame capture
  - tshark            # Offline PCAP dissection
  - parquet           # Machine-readable sweep artifacts
  - duckdb            # Local querying over sweep files
  - postgres          # Rebuildable observation projection
  - semaphore         # Scheduled sweep execution
```

---

## 8. Framework Tags

Compliance and governance framework references. Use only when a document directly implements or maps to a framework control. Skip this section entirely if your project doesn't involve compliance work.

This project has no compliance component and defines no framework tags. The
section is retained because a future dataset release may need to reference a
data-publication standard.

| Tag | Framework |
|-----|-----------|
| | |

---

## 9. Implementation

### Standard Frontmatter

```yaml
<!--
---
title: "Document Title"
description: "What this document covers"
author: "VintageDon (https://github.com/vintagedon/)"
date: "YYYY-MM-DD"
version: "1.0"
status: "Active"
tags:
  - type: guide
  - domain: [your-domain-tag]
  - tech: [relevant-tech]
related_documents:
  - "[Related Doc](path/to/doc.md)"
---
-->
```

### Conventions

- Use lowercase, hyphenated values (`ci-cd` not `CI/CD` or `cicd`)
- Tech tags use canonical names
- One value per line for readability, or array syntax for multi-value
- `related_documents` links use relative paths within the repo

---

## 10. Maintaining the Vocabulary

### Adding New Tags

1. Check if an existing tag covers the concept
2. If not, add the new tag with a boundary definition to this document
3. Backfill existing documents if the new tag applies retroactively

### Governance

- This document is the authoritative source for allowed tag values
- Prefer broader tags over proliferating specific ones
- Review additions for overlap with existing tags

---

## 11. References

| Resource | Description |
|----------|-------------|
| [Primary README Template](primary-readme-template.md) | Shows tag usage in repository root READMEs |
| [Interior README Template](interior-readme-template.md) | Shows tag usage in directory READMEs |
| [General KB Template](general-kb-template.md) | Shows tag usage for standalone docs |
| [Worklog README Template](worklog-readme-template.md) | Shows tag usage for work log entries |
| [One-Pager Template](one-pager-template.md) | Shows tag usage for ideation documents |
| [Project Brief Template](project-brief-template.md) | Shows tag usage for project briefs |
