---
name: extract-presentation
description: Fact extraction from a presentation / slides
metadata:
  work_type: presentation
  fabio: Presentation
  version: 1
---

## Role

You extract facts from a presentation (slides). The text is bulleted and abbreviated —
quote the content of the bullet points verbatim; do not paraphrase the slide.

## What is a fact

- a claim or result from a bullet point,
- a key number or datum from the slide,
- a conclusion/recommendation from the summary.

What a fact is NOT: slide titles, agenda, subheadings, section names.

## direct vs inferred

- "direct": a claim from a bullet point stated explicitly.
- "inferred": a conclusion assembled from several points or slides. Put the
  premises in `quotes`.

## Pitfalls of this type

- Bullet points are often mental shorthand — do not supply what is not there.
- Distinguish a slide title from a claim (a title is not a fact).
