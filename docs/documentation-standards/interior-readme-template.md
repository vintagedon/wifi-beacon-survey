<!--
---
title: "[Directory Name]"
description: "What this directory contains and its role"
author: "VintageDon (https://github.com/vintagedon/)"
date: "YYYY-MM-DD"
version: "1.0"
status: "Active"
tags:
  - type: directory-readme
  - domain: [see tagging-strategy.md for allowed values]
---
-->

<!--
FRONTMATTER: Always include. Domain tag must use a value from
docs/documentation-standards/tagging-strategy.md. Type is always
"directory-readme" for interior READMEs.
-->

# [Directory Name]

<!--
1-3 sentences: what this directory contains and its organizational
role. A reader landing here should immediately know what lives here
and why. Draw from the project charter or AGENTS.md for context.
-->

[What this directory contains and its role in the repository.]

---

<!--
CONTENTS (required): Tree view of actual directory contents with
brief inline descriptions. Reflect what exists or what is planned.
Do not fabricate placeholder files.
-->

## 1. Contents

```
directory-name/
├── subdirectory-1/     # Brief description
│   └── README.md
├── subdirectory-2/     # Brief description
│   └── README.md
├── file-1.md           # Brief description
└── README.md           # This file
```

---

<!--
FILES: Include when directory has files worth listing individually.
Omit section if no files exist; preserve the number gap (next section
stays §3, not §2).
-->

## 2. Files

| File | Description | Status |
|------|-------------|--------|
| [filename](filename) | What it covers | ✅ Active / 🔄 In Progress / ⬜ Planned |

---

<!--
SUBDIRECTORIES: Include when subdirectories exist. Link each README.
Omit section if none exist; preserve the number gap.
-->

## 3. Subdirectories

| Directory | Description |
|-----------|-------------|
| [subdirectory/](subdirectory/README.md) | What it contains |

---

<!--
RELATED: Include when meaningful cross-references exist. Always link
the parent directory. Add siblings or related documents that aid
navigation. Omit if relationships are obvious from context.
-->

## 4. Related

| Document | Relationship |
|----------|--------------|
| [Parent](../README.md) | Parent directory |
| [Sibling](../sibling/README.md) | Related directory |

---

<!--
TEMPLATE NOTES:

Semantic numbering: omitted sections preserve their number gap.
§1, §2, §4 is correct if §3 is omitted. Never renumber.

Expansion: add sections (§5, §6, ...) for usage notes, security
considerations, conventions, or other directory-specific content.

Pending pattern: place an empty README-pending.md (gitignored via
*-pending.md glob) to mark directories needing a proper README later.

Keep it lean: add what's needed, skip what's not. Don't fill
sections for completeness.
-->
