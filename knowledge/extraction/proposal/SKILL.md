---
name: extract-proposal
description: Ekstrakcja faktów z wniosku grantowego / projektowego
metadata:
  work_type: proposal
  fabio: ResearchProposal
  version: 1
---

## Rola

Wydobywasz fakty z wniosku (grantowego lub projektowego). To dokument o
ZAMIARACH: opisuje, co dopiero ma się wydarzyć.

## Co jest faktem

- deklarowany cel projektu,
- planowane działanie lub etap,
- wnioskowany budżet / zasoby,
- spodziewany rezultat, harmonogram, skład zespołu.

## KLUCZOWA ZASADA (specyfika wniosku)

Wniosek opisuje plany, nie dokonania. Pole `statement` MUSI oddawać, że to
plan/cel — używaj sformułowań "Planowany cel: ...", "Wnioskowana kwota: ...",
"Spodziewany rezultat: ...". Nigdy nie zapisuj planu jako faktu dokonanego
(NIE "przeszkolono 200 osób", lecz "Planowane przeszkolenie 200 osób").

## direct vs inferred

- "direct": cel, kwota lub działanie zadeklarowane wprost.
- "inferred": całkowity zakres wyliczony z kilku zadań (np. suma budżetów etapów).
  W `quotes` podaj wtedy przesłanki.

## Pułapki tego typu

- "Celem jest przeszkolenie 200 osób" to PLAN — nie "przeszkolono 200 osób".
- Nie traktuj spodziewanych rezultatów jak osiągniętych.
