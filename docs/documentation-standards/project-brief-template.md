<!--
---
title: "[Project Name]"
type: brief
slant: "build | engagement | advisory"
status: "DRAFT v1, [what is locked]"
owner: "[Account or project owner]"
created: YYYY-MM-DD
tags:
  - type: brief
  - domain: [see tagging-strategy.md for allowed values]
---
-->

<!--
WHAT THIS IS: Every project gets a brief. The brief is the single
project-definition artifact. It replaces the older charter, which is
now the "build" slant of this template.

SLANT: One brief, three starting profiles, selected by who you are
pitching and what the data is. Slant is a frontmatter field.

  - build       Internal build that freezes scope and feeds specs.
  - engagement  Client or delivery work with a timeline and risks.
  - advisory    Research or recommendation work for a requestor.

The section set follows the slant the way a Diataxis-typed article
follows its type. The invariant core below is present in every brief
regardless of slant. The slant blocks attach the rest.

HOW TO USE:
  1. Set the slant field in frontmatter.
  2. Fill the invariant core.
  3. Keep the one matching SLANT block, delete the other two.
  4. Add or drop sections as the data dictates. The profiles are
     starting sets, not gates. Borrow a section from another slant
     when the work needs it.

A new audience that does not fit these three gets a new slant
profile, not a new document type. The axis stays open; the
vocabulary stays at one word: brief.

FRONTMATTER BY SLANT: the fields above are common to all slants.
  - engagement adds: client, division, tier, pm, account_owner
  - advisory adds:   requestor, distribution
  - build adds:      repository

STYLE: Follow writing-style-guide.md. No em dashes anywhere,
including this template's examples. This template adds brief
structure and rhetoric; the style guide owns prose mechanics.
-->

# [Project Name] — Brief

<!--
WHY WE'RE DOING THIS: Plain problem framing. State the current
broken or absent state in direct sentences. Then name what makes
this non-trivial, the constraint or boundary that the rest of the
brief has to work around. Source from the intake conversation.
Invariant: present in every slant.
-->

## Why we're doing this

[What is broken or missing today, in plain declarative sentences.]

[What makes this non-trivial: the constraint, boundary, or
architecture fact that shapes everything downstream.]

---

<!--
OUTCOME: The concrete end-state, not the process to reach it.
Describe what exists when this is done. Use a table for anything
enumerable (deliverables, targets, endpoints). Invariant.
-->

## Outcome

[The end-state in one or two sentences.]

| [Item] | [Attribute] | [Attribute] |
|--------|-------------|-------------|
| [Row]  | [Value]     | [Value]     |

---

<!--
LOCKED DECISIONS: Decision-first. Lock what is settled in a register
before describing any build. State explicitly that these are closed.
Handle dormant or conditional decisions with a note rather than
leaving them ambiguous. Invariant.
-->

## Locked decisions

| # | Decision | Value |
|---|----------|-------|
| 1 | [Decision] | [Value] |
| 2 | [Decision] | [Value] |

These are no longer open. Implementation locks them in.

[Optional note on any decision that is dormant or conditional: why
it is dormant, what reactivates it, where it is tracked.]

---

<!--
SCOPE: In and Out. Every Out item carries a reason and a pointer to
where it is handled instead, so a reader never wonders whether it
was forgotten. Invariant.
-->

## Scope

**In:**

- [Included item]
- [Included item]

**Out:**

- [Excluded item]. [Reason, and where it is handled instead.]
- [Excluded item]. [Reason, and where it is handled instead.]

---

<!--
CRITICAL DESIGN DECISION: Name the single most load-bearing choice
and give it its own section. Recommendation, then numbered
justification, then what you explicitly defer. If there is genuinely
more than one load-bearing choice, add a second subsection; do not
inflate ordinary choices to fill the slot. Invariant.
-->

## Critical design decision: [the choice]

**Recommendation:** [The decision, stated plainly.]

[Why, as numbered reasons. Each reason stands on its own.]

1. [Reason.]
2. [Reason.]

**Deferred:** [What this decision explicitly does not settle, and
which later effort owns it.]

---

<!-- SLANT:BUILD — keep this block only when slant is build; delete the engagement and advisory blocks.
The build slant freezes the WHAT and WHY and feeds specs. It carries
no durations: sequence is expressed as dependencies, and the HOW and
WHEN of execution live in specs, not here. Source from the one-pager
and any GDR outputs.
-->

## Architecture

<!-- Structural design with a component table and rationale. As
detailed as the project's complexity requires, no more. -->

[How the system is organized and why.]

| Component | Implementation | Purpose |
|-----------|----------------|---------|
| [Component] | [Technology] | [What it does] |

## Acceptance criteria

<!-- Testable pass/fail conditions grouped by category. Concrete
enough that a reviewer can verify each without ambiguity. -->

**[Category]:**

- [Testable criterion]
- [Testable criterion]

## Phases

<!-- Dependency-ordered, not date-ordered. Each phase should be
independently specifiable as one or more specs. -->

1. **[Phase].** [Deliverables. What this phase produces.]
2. **[Phase].** [Deliverables. Depends on phase 1.]

<!-- /SLANT:BUILD -->

<!-- SLANT:ENGAGEMENT — keep this block only when slant is engagement; delete the build and advisory blocks.
The engagement slant plans bounded delivery work with a timeline and
risk posture. Source from the intake conversation and the delivery
runbook.
-->

## Tier and approach

<!-- Classify the engagement and justify the tier against an explicit
intake pre-check rather than asserting it. State what would promote
the tier if discovery surfaces complexity. -->

[Tier and the artifacts it calls for.]

Per the intake pre-check:

1. [Pre-check question?] **[Answer.]**
2. [Pre-check question?] **[Answer.]**

[Tier justification. What promotes it if discovery surfaces
complexity.]

## Stakeholder roster

<!-- Who is involved and how to reach them. Roles that the work
depends on (approvers, moderators, tenant contacts). -->

| Name | Role | Contact |
|------|------|---------|
| [Name] | [Role] | [Contact] |

## Phases

<!-- Sequenced delivery with duration estimates. Each phase names the
concrete work, not just a label. -->

1. **[Phase] ([duration]).** [Concrete work.]
2. **[Phase] ([duration]).** [Concrete work.]

## Risks

<!-- Register table. Mitigations are specific and testable. Never
"monitor closely"; name the control that catches the failure. -->

| Risk | Severity | Mitigation |
|------|----------|------------|
| [Risk] | [High/Med/Low] | [Specific, testable control] |

## Mechanism trace

<!-- Optional. Include only when the control path is not obvious from
prose. A short trace of how the design behaves on each path. Drop the
section if the design is self-evident. -->

```
[Trigger] -> [control] -> [outcome]
[Trigger] -> [control] -> [outcome]
```

<!-- /SLANT:ENGAGEMENT -->

<!-- SLANT:ADVISORY — keep this block only when slant is advisory; delete the build and engagement blocks.
The advisory slant frames research or recommendation work for a
requestor. It is neither an internal build nor a billed engagement.
Source from the request and the requestor's framing.
-->

## Research questions

<!-- The bounded questions this work answers. Specific enough that an
answer is recognizable. State what is out of question scope. -->

1. [Question.]
2. [Question.]

## Methodology and sources

<!-- How the investigation proceeds and what it draws on. Name source
classes and any access constraints. -->

[Approach, and the source classes it relies on.]

## Findings structure

<!-- How findings will be organized when delivered, so the requestor
knows the shape of the output before it lands. -->

[The structure the findings document will take.]

## Recommendations

<!-- The advisory output. State recommendations plainly with the
reasoning that supports each. -->

- [Recommendation.] [Reasoning.]

## Distribution note

<!-- Who receives this, handling or classification constraints, and
any caveat on how far it travels. -->

[Recipients and handling constraints.]

<!-- /SLANT:ADVISORY -->

---

<!--
NEXT STEPS: Action items, with owners where the action belongs to a
specific person. Invariant.
-->

## Next steps

1. [Action.] [Owner, if specific.]
2. [Action.] [Owner, if specific.]

---

<!--
REFERENCES: Source documents, conversation logs, and related
projects. For the build slant, this is also where provenance lives:
extend it with a source-documents and multi-model contribution table
when the brief draws on a one-pager and GDR passes. Invariant.
-->

## References

- [Source document or conversation log]
- [Related or downstream project]

---

*v[N] [date]. [Slant] brief. [What is locked.] To move to Active when
[promotion condition].*

<!--
TEMPLATE NOTES:

NUMBERING: Unlike the fixed-address charter this replaces, the brief
uses narrative named sections. The section set flexes by slant, so a
fixed 1-to-N numbering cannot stay stable across slants. Section
names are stable within a slant, which gives retrieval the
predictable structure it needs.

SLANT IS THE AXIS: build, engagement, advisory are starting profiles,
not an enum to defend. The data dictates the section set. A new
audience earns a new profile here, never a new document type.

LEAN: Start with the invariant core and the matching slant block.
Add sections as content requires. Do not fill sections for
completeness; the wrapper is thin, the content is the point.

SOURCES: build draws from the one-pager and GDR outputs; engagement
from the intake conversation and delivery runbook; advisory from the
request itself.
-->
