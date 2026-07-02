---
name: extract-article
description: Ekstrakcja faktów z artykułu naukowego (recenzowanego)
metadata:
  work_type: article
  fabio: JournalArticle
  version: 1
---

## Rola

Wydobywasz fakty z artykułu naukowego. Interesuje Cię treść merytoryczna
(wyniki, metody, wkład), nie forma ani ozdobniki redakcyjne.

## Co jest faktem

- wynik badania (liczbowy lub jakościowy),
- zastosowana metoda, materiał, wielkość i charakterystyka próby,
- wniosek autorów, deklarowany wkład lub nowość pracy,
- konkretna dana (wartość z jednostką, przedział, istotność).

Czym fakt NIE jest: zwroty redakcyjne ("w niniejszej pracy przedstawiono"),
ogólniki bez treści, cudze wyniki przytoczone tylko jako tło w przeglądzie
literatury.

## direct vs inferred

- "direct": wynik lub metoda napisane w tekście wprost.
- "inferred": wniosek zestawiony z kilku zdań (np. przewaga metody A nad B na
  podstawie dwóch osobno podanych wyników). W `quotes` podaj wtedy przesłanki.

## Pułapki tego typu

- Nie myl deklaracji celu ("celem było zbadanie...") z uzyskanym wynikiem.
- Każdą liczbę wiąż z jej warunkiem (na jakim zbiorze, w jakiej grupie, z jaką
  jednostką) — liczba bez kontekstu bywa myląca.
- Nie przypisuj autorom cudzych wyników cytowanych z literatury.
