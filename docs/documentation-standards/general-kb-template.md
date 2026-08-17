<!--
---
title: "[Document Title]"
description: "What this document covers"
author: "VintageDon (https://github.com/vintagedon/)"
date: "YYYY-MM-DD"
version: "1.0"
status: "Draft|Active|Archived"
tags:
  - type: [guide/reference/specification/report/runbook/policy/procedure]
  - domain: [see tagging-strategy.md for allowed values]
  - tech: [relevant-technologies]
related_documents:
  - "[Related Doc](path/to/doc.md)"
---
-->

<!--
FRONTMATTER: Always include. The type tag classifies the document
(guide, reference, specification, report, runbook, policy, procedure).
Domain and tech tags must use values from
docs/documentation-standards/tagging-strategy.md.
-->

# [Document Title]

<!--
LEAD-IN: 1-2 sentences stating what this document provides and why
it exists. This orients the reader before the wrapper sections.
-->

[1-2 sentences: What this document provides and why it exists.]

---

<!--
PURPOSE: What problem this document solves or what need it addresses.
2-3 sentences max. If the purpose is obvious from the title and
lead-in, this section can be omitted (preserve the number gap).
-->

## 1. Purpose

[What problem this document solves or what need it addresses.]

---

<!--
SCOPE: What's covered and, when useful, what's explicitly excluded.
Use a short list or 2-3 sentences. Omit if the document's boundaries
are self-evident; preserve the number gap.
-->

## 2. Scope

What's covered:

- [Item 1]
- [Item 2]
- [Item 3]

---

<!--
AUDIENCE: Who should read this and what background is assumed. 1-2
sentences. Omit if obvious from context; preserve the number gap.
-->

## 3. Audience

[Who should read this and what background is assumed.]

---

<!--
CONTENT SECTIONS: This is the body of the document. Name sections
appropriately for the subject matter. Add as many numbered sections
as needed (§4, §5, §6, ...). Each major topic gets its own section.
The wrapper above (Purpose, Scope, Audience) is thin framing; the
content sections are the point.
-->

## 4. [Content Section Title]

[Your actual content.]

---

<!--
REFERENCES: Include when external resources, related documents, or
source materials are cited. Use the N convention (always second-to-last
numbered section, regardless of how many content sections precede it).
Omit if no references exist.
-->

## N. References

| Resource | Description |
|----------|-------------|
| [Link](url) | What it provides |

---

<!--
DOCUMENT INFO: Always include as the final section. Use N+1 numbering
(always last, regardless of total section count).
-->

## N+1. Document Info

| | |
|---|---|
| Author | VintageDon |
| Created | YYYY-MM-DD |
| Updated | YYYY-MM-DD |
| Version | 1.0 |

---

<!--
TEMPLATE NOTES:

Sections §1-§3 (Purpose, Scope, Audience) are the wrapper. They
frame the document but should be thin. If you omit any, preserve
the number gap.

Sections §4+ are your content. Name them for your subject matter.

References and Document Info are always last, using N and N+1
notation so they float to the end regardless of content section count.

Semantic numbering: omitted sections preserve their number gap.
§1, §2, §4 is correct if §3 is omitted. Never renumber.

Keep it lean: the wrapper is framing, the content is the point.
Don't pad sections for completeness.
-->
