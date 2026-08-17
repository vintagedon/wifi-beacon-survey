<!--
---
title: "Assets"
description: "Project images, banners, and visual resources"
author: "VintageDon (https://github.com/vintagedon/)"
date: "2026-08-16"
version: "1.1"
status: "Active"
tags:
  - type: directory-readme
  - domain: documentation
---
-->

# Assets

Project images, banners, diagrams, and visual resources. Files here are referenced by README files, documentation, and other project content. This directory holds binary and visual assets that don't belong inline with markdown documents.

---

## 1. Contents

```
assets/
├── background-section-infographic.jpg   # Section background graphic
├── icon.svg                             # Repository icon (README header)
├── repo-banner.jpg                      # Repository banner
└── README.md                            # This file
```

---

## 2. Files

| File | Description | Status |
|------|-------------|--------|
| `icon.svg` | Flat repository icon: receiver dot on a fixed baseline beneath three signal arcs, arcs fading outward. Rendered at 128 px in the README header | ✅ Active |
| `repo-banner.jpg` | Repository banner image | ✅ Active |
| `background-section-infographic.jpg` | Section background graphic | ✅ Active |

---

## 4. Related

| Document | Relationship |
|----------|--------------|
| [Repository Root](../README.md) | Parent directory; typically references banner images |

---

## 5. Conventions

**Naming:** Use descriptive, lowercase, hyphenated filenames: `architecture-diagram.png`, `project-banner.svg`.

**Formats:** Prefer SVG for diagrams and icons, PNG for screenshots and complex images. Avoid large uncompressed formats.

**Icon palette:** `#2F7D76` tile, white glyph. Flat fills only, no gradients or strokes beyond the glyph itself, so the icon stays legible at favicon size and on either GitHub theme.

**References:** Link assets from markdown using relative paths: `![Alt text](assets/filename.png)` from the repo root, or `![Alt text](../assets/filename.png)` from a subdirectory.
