<!--
---
title: "[Project Name]"
description: "One-line description"
author: "VintageDon (https://github.com/vintagedon/)"
date: "YYYY-MM-DD"
version: "1.0"
status: "Active"
tags:
  - type: project-root
  - domain: [primary-domain]
  - tech: [key-technologies]
related_documents:
  - "[Related Link](url)"
---
-->

<!--
FRONTMATTER: Always include. Domain and tech tags must use values
from docs/documentation-standards/tagging-strategy.md. Type is
always "project-root" for the repository root README.
-->

# [Project Name]

[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

<!--
TAGLINE + INTRO: The blockquote is a single sentence capturing the
project's essence. Follow with 2-3 sentences expanding on what the
project is, what it does, and why it exists. Source from the
one-pager's vision section and the brief's Why we're doing this
section.
-->

> One-line description that captures the essence of the project.

[2-3 sentences expanding on what this project is, what it does, and why it exists.]

---

<!--
OVERVIEW: 2-4 paragraphs of context, problem space, and motivation.
What gap does this project fill? Include domain-specific background
that newcomers need. Source from the one-pager's origin and vision
sections. Write for someone encountering the project cold.
-->

## Overview

[2-4 paragraphs explaining the context, problem space, and motivation.]

---

<!--
PROJECT STATUS: Table showing current state of each major area.
At hydration time, most areas will be "Planned." Update as work
progresses. Areas should map to the brief's Outcome and Phases.
-->

## Project Status

| Area | Status | Description |
|------|--------|-------------|
| [Area 1] | ✅ Complete | [Description] |
| [Area 2] | 🔄 In Progress | [Description] |
| [Area 3] | ⬜ Planned | [Description] |

---

<!--
ARCHITECTURE: Brief explanation of how the project is organized and
why. The component table maps technologies to their roles. Source
from the brief's Architecture section (build slant). For projects
without a clear architecture yet, describe the intended approach and
mark components as planned.
-->

## Architecture

[Brief explanation of how the project is organized and why.]

| Component | Implementation | Purpose |
|-----------|----------------|---------|
| [Component] | [Technology] | [What it does] |

---

<!--
REPOSITORY STRUCTURE: Tree view of the repo's top-level directories
with brief descriptions. Update the descriptions to reflect this
project's actual use of each directory. The structure itself is
standard from project-template-repository; only the descriptions
should be project-specific.
-->

## Repository Structure

```markdown
<repo-name>/
├── docs/              # Documentation
├── internal-files/    # Reference docs (gitignored by default; tracked in private repos)
├── shared/            # Cross-cutting utilities
├── spec/              # Specifications (gitignored by default; tracked in private repos)
├── staging/           # Pre-commit staging (gitignored by default; tracked in private repos)
├── work-logs/         # Development history
├── AGENTS.md          # Agent context loading
├── LICENSE
└── README.md          # This file
```

---

<!--
GETTING STARTED: Setup steps appropriate to the project's tech stack.
Include prerequisites, installation, and first-run commands. At
hydration time, this may be minimal ("project is in planning phase")
or populated if the stack is known. Match the commands to the actual
tech stack from the brief's Architecture section.
-->

## Getting Started

```bash
# Setup steps
command-1
command-2
```

---

## License

- **Code**: [MIT License](LICENSE)
- **Data/Content**: [CC-BY-4.0](LICENSE-DATA)

---

Last Updated: [Date] | Status: [Current Status]

<!--
TEMPLATE NOTES:

Required sections: Frontmatter, Title + badge, Tagline + intro,
Overview, Project Status, Architecture, Repository Structure,
Getting Started, License, Last Updated footer.

Optional sections (add as needed between Architecture and
Repository Structure, or after Getting Started):
- Target Audience table
- Domain-specific section (customize heading for project type)
- Related Work / Active Projects
- Acknowledgments

Repo URL pattern: https://github.com/radioastronomyio/<repo-name>
-->
