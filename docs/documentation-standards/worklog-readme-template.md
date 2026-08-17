<!--
---
title: "[Brief Title of Work]"
description: "What was accomplished"
author: "VintageDon (https://github.com/vintagedon/)"
date: "YYYY-MM-DD"
version: "1.0"
status: "Complete|In Progress|Blocked"
tags:
  - type: worklog
  - domain: [see tagging-strategy.md for allowed values]
related_documents:
  - "[Related Doc](path/to/doc.md)"
---
-->

<!--
FRONTMATTER: Always include. Type is always "worklog." Domain tag
must use a value from docs/documentation-standards/tagging-strategy.md.

NAMING: Date-based by default.
  worklog-YYYY-MM-DD.md
  worklog-YYYY-MM-DD-brief-topic.md
Related entries get gathered into milestone directories as patterns
emerge organically. Do not pre-create milestone directory structures.
-->

# [Brief Title of Work]

<!--
SUMMARY: Quick orientation block. Objective states what the work set
out to accomplish. Outcome states what was achieved. Both are 1-2
sentences. The attributes table gives at-a-glance status.
-->

## Summary

| Attribute | Value |
|-----------|-------|
| Status | ✅ Complete / 🔄 In Progress / ⛔ Blocked |
| Sessions | N |
| Artifacts | N scripts, N configs, N docs |

Objective: [What this work set out to accomplish.]

Outcome: [What was achieved.]

---

<!--
WORK COMPLETED (required): Table of tasks performed, what was done,
and the result. This is the core record. Be specific about what
changed, not what was planned.
-->

## 1. Work Completed

| Task | Description | Result |
|------|-------------|--------|
| [Task 1] | What was done | Outcome |
| [Task 2] | What was done | Outcome |

---

<!--
FILES CHANGED: Include when repo files were created, modified, or
moved. Link each file. Omit if no repo files were touched; preserve
the number gap.
-->

## 2. Files Changed

| File | Change |
|------|--------|
| [path/to/file](path/to/file) | Added / Updated / Created |

---

<!--
ISSUES ENCOUNTERED: Include when problems arose worth documenting
for future reference. Omit if work proceeded without notable issues;
preserve the number gap.
-->

## 3. Issues Encountered

| Issue | Resolution |
|-------|------------|
| [Problem] | [How solved] |

---

<!--
NEXT STEPS: Include when follow-on work is identified. The handoff
line tells the next person (or agent) what's ready and where it lives.
Omit if work is fully complete with no follow-on; preserve the
number gap.
-->

## 4. Next Steps

Handoff: [What's ready for follow-on work and where it lives.]

1. [Immediate action]
2. [Immediate action]

---

<!--
TEMPLATE NOTES:

This documents work done, not work planned. Capture what matters
for understanding progress.

Source attribution: use an HTML comment at the bottom to note the
conversation source if the worklog was derived from a chat session.
Example: <!-- Source: Claude.ai project session, YYYY-MM-DD -- >

Semantic numbering: omitted sections preserve their number gap.
-->
