---
name: extract-poster
description: Fact extraction from a conference poster
metadata:
  work_type: poster
  fabio: ConferencePoster
  version: 1
---

## Role

You extract facts from a conference poster. A poster is concise and telegraphic —
the text is often in sentence fragments; stick to the literal wording in quotes.

## What is a fact

- the poster's main result or thesis,
- the method used, in brief,
- a key number (sample, effect),
- the final conclusion.

What a fact is NOT: section headings ("Results", "Methods").

## KEY RULE (about the result, not the poster)

A fact is a substantive finding. Statements about handling the work are NOT facts: funding
information ("funded from...", "NCN grant"), affiliations, acknowledgments,
contact details, place/date of presentation. Skip them.

## direct vs inferred

- "direct": a result or thesis stated explicitly (even if telegraphic).
- "inferred": a conclusion composed from several poster fields. Put the premises in `quotes`.

## Pitfalls of this type

- Telegraphic style: quote exactly as on the poster (often without full sentences).
- Do not supply context that is not on the poster.
