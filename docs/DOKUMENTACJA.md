# IMeTo — Dokumentacja projektu

> Ten dokument opisuje **co już zbudowaliśmy, jak to działa i dlaczego tak**.
> Jest napisany tak, by zrozumiała go także osoba mniej techniczna — pojęcia
> fachowe tłumaczymy przy pierwszym użyciu, a na końcu jest [słownik](#slownik-pojec).
>
> Dokumenty pokrewne: `TECHNICZNY.md` (szczegółowy plan techniczny) i `CLAUDE.md`
> (instrukcja dla asystenta AI pracującego nad kodem).

---

## Spis treści

1. [Po co jest IMeTo (w jednym akapicie)](#1-po-co-jest-imeto)
2. [Główna idea: cytat musi mieć pokrycie](#2-glowna-idea-cytat-musi-miec-pokrycie)
3. [Jak system jest pomyślany jako całość](#3-jak-system-jest-pomyslany-jako-calosc)
4. [Co już zbudowaliśmy — moduł po module](#4-co-juz-zbudowalismy)
5. [Jak dokładnie wyciągane są fakty — krok po kroku](#5-jak-wyciagane-sa-fakty)
6. [Model danych i zgodność ze standardami](#6-model-danych-i-zgodnosc-ze-standardami)
7. [Jak to uruchomić i sprawdzić samemu](#7-jak-to-uruchomic-i-sprawdzic)
8. [Co jest dalej w planie](#8-co-jest-dalej-w-planie)
9. [Słownik pojęć](#slownik-pojec)

---

## 1. Po co jest IMeTo

IMeTo to narzędzie, które **czyta dokumenty** (np. sprawozdania, publikacje w formacie
PDF lub Word) i **wyławia z nich fakty**, przy czym każdy fakt musi być **poparty
dosłownym cytatem** ze źródła. Docelowo pomaga człowiekowi ocenić dorobek lub wpływ
opisany w dokumentach — ale robi to w sposób, w którym **niczego nie zmyśla**: każde
zdanie, które system wyprodukuje, da się cofnąć do konkretnego miejsca w oryginalnym
dokumencie.

Kluczowe ograniczenia, które kształtują cały projekt:

- **Dla jednego użytkownika, lokalnie.** To nie jest usługa w chmurze dla tysięcy osób.
  Ma działać na jednym komputerze („on-premise", czyli u siebie, bez wysyłania danych na
  zewnątrz).
- **Człowiek decyduje.** System proponuje kandydatów na fakty; to człowiek akceptuje lub
  odrzuca. System nigdy nie „przepycha" wniosków sam.
- **Minimum zależności, nudne technologie.** Im mniej egzotyki, tym mniej rzeczy się psuje.

---

## 2. Główna idea: cytat musi mieć pokrycie

Największym ryzykiem przy używaniu modeli językowych (sztucznej inteligencji typu
ChatGPT) jest **halucynacja** — model potrafi napisać zdanie, które brzmi wiarygodnie,
ale jest zmyślone albo przekręcone. W ocenie dorobku to byłoby katastrofalne.

IMeTo rozwiązuje to jedną żelazną zasadą:

> **Żaden fakt nie trafia do bazy, dopóki jego cytat nie zostanie znaleziony
> *dosłownie* w tekście źródłowym.**

W praktyce działa to tak: model wskazuje fragment dokumentu jako dowód (np. „Rada gminy
przyjęła uchwałę nr 12"). Zanim IMeTo to zapisze, **sprawdza znak po znaku**, czy ten
fragment naprawdę występuje w oryginale. Jeśli model przekręcił choćby cyfrę („nr 13"
zamiast „nr 12") — fakt zostaje **odrzucony**. Tolerujemy wyłącznie różnice w tzw.
białych znakach (spacje, przejścia do nowej linii), bo model często „zwija" tekst — ale
treść musi się zgadzać co do znaku.

Ta weryfikacja to serce systemu. Wszystko inne jest wokół niej zbudowane.

---

## 3. Jak system jest pomyślany jako całość

Docelowo IMeTo to **potok** (ang. *pipeline*) — ciąg etapów, przez które przechodzi
dokument:

```
dokument  →  [ekstrakcja faktów]  →  [propozycje tropów]  →  [rozbiór ZA/PRZECIW]
          →  [asystent redakcyjny]  →  [eksport dossier]
```

Po każdym etapie może być **próg** — moment, w którym system zatrzymuje się i czeka na
decyzję człowieka (akceptuj / odrzuć), zanim ruszy dalej.

**Ważne:** na dziś zbudowaliśmy fundamenty i pierwszy etap (ekstrakcja). Kolejne etapy
(propozycje tropów, rozbiór, redakcja, eksport) są zaplanowane, ale jeszcze nie powstały.
Ten dokument opisuje **stan faktyczny**, nie plany.

Architektura dzieli kod na dwie warstwy, których granica jest twarda:

- **Rdzeń (`core/`)** — wspólne, ogólne klocki: weryfikacja cytatu, kontrakt danych,
  baza, klient AI. Rdzeń nie wie nic o konkretnej dziedzinie (ocenie dorobku).
- **Fazy (`phases/`)** — logika poszczególnych etapów potoku. Fazy korzystają z rdzenia,
  **nigdy odwrotnie**. Dzięki temu rdzeń jest stabilny, a etapy można wymieniać.

---

## 4. Co już zbudowaliśmy

Budujemy krok po kroku. Każdy krok zostawia **działający, przetestowany** system —
nie ma momentu, w którym „nic nie działa, bo przepisujemy całość". Poniżej każdy
zbudowany element: najpierw prostym językiem, potem nota techniczna.

### Krok 0 — Szkielet projektu (rusztowanie)

**Prosto:** zanim powstał jakikolwiek właściwy kod, przygotowaliśmy „warsztat" — pliki,
które mówią, z czego projekt się składa, jakich narzędzi używa i jak sprawdzić, że
wszystko się spina. Sam w sobie nic nie liczy, ale bez niego nie da się pracować.

**Technicznie:**
- `pyproject.toml` — jedno miejsce z listą zależności (bibliotek) i konfiguracją
  narzędzi do sprawdzania jakości kodu.
- `.gitignore` — lista rzeczy, których nie zapisujemy do historii projektu (m.in.
  sekrety i lokalna baza danych).
- `.env.example` — wzór pliku z ustawieniami (bez prawdziwych haseł).
- `imeto/__init__.py` — pusty na razie pakiet główny.
- `tests/test_smoke.py` — najprostszy możliwy test: „czy projekt w ogóle się ładuje".

### Krok 1 — Weryfikacja cytatu (`imeto/core/span.py`)

**Prosto:** funkcja, która odpowiada na jedno pytanie: *„czy ten cytat naprawdę
występuje w tym dokumencie, dosłownie?"*. Jeśli tak — mówi, w którym dokładnie miejscu
(od którego do którego znaku). Jeśli nie — mówi „nie". To jest ta żelazna zasada z
punktu 2, zamieniona w kod.

**Technicznie:** funkcja `find_span(full_text, quote)` zwraca parę liczb `(start, end)`
— pozycję cytatu w tekście — albo `None`. Znaki niebiałe muszą pasować co do znaku
(wielkość liter, cyfry, interpunkcja). Ciągi białych znaków w cytacie dopasowują dowolne
białe znaki w źródle, więc zwrócona pozycja wskazuje **oryginał**, nawet jeśli model
zwinął spacje czy przejścia do nowej linii. To odpowiada „poziomowi 3" kotwiczenia z
planu technicznego. Zero sztucznej inteligencji, zero bazy danych — czysta, przewidywalna
logika, w pełni testowalna.

### Krok 2 — Kontrakt odpowiedzi modelu (`imeto/core/schemas.py`)

**Prosto:** ustalenie, w jakiej *dokładnie* formie model AI ma zwracać wyniki. To jak
formularz z rubrykami: model musi wypełnić dokładnie te pola i żadnych innych. Jeśli
spróbuje dopisać coś od siebie — odpowiedź jest odrzucana.

**Technicznie:** modele danych `ExtractedFact` (pojedynczy fakt: `quote` — dosłowny
cytat, oraz `statement` — treść faktu, który cytat popiera) i `Extraction` (lista
faktów). Zbudowane w bibliotece Pydantic, z ustawieniem „zabroń dodatkowych pól"
(`extra="forbid"`) i wymogiem, że teksty nie mogą być puste. Uwaga projektowa: model
**nie** podaje pozycji cytatu w tekście — pozycję liczymy sami (krok 1), bo modelowi w tej
sprawie nie ufamy.

### Krok 3 — Baza z pochodzeniem danych (`imeto/core/provenance.py`)

**Prosto:** to jest „archiwum z metrykami". Przechowuje źródła (dokumenty) i dowody
(zweryfikowane cytaty), ale co ważne — **przy zapisie dowodu ponownie sprawdza cytat**.
Nie da się wcisnąć do archiwum czegoś, co nie ma pokrycia w źródle. Dodatkowo przy każdym
dowodzie zapisuje „metrykę": kiedy powstał, który proces go wytworzył i który model AI za
niego odpowiada — żeby zawsze dało się odtworzyć, skąd dany fakt się wziął.

**Technicznie:** dwie tabele — `Source` (dokument) i `Evidence` (zweryfikowany cytat) —
zbudowane na bibliotece SQLModel nad bazą SQLite (lekka baza w jednym pliku, bez serwera).
Cały dostęp do bazy idzie przez klasę `ProvenanceStore` — żaden inny moduł nie dotyka
bazy bezpośrednio, dzięki czemu w przyszłości można wymienić silnik (na Postgres) bez
przepisywania reszty. Metoda `add_evidence` egzekwuje niezmiennik: woła `find_span` z
kroku 1 i albo zapisuje dowód z policzonymi pozycjami, albo zgłasza błąd `SpanNotVerified`.
Nazwy kolumn i typy są zgodne z międzynarodowymi standardami opisu danych — o tym
szczegółowo w [rozdziale 6](#6-model-danych-i-zgodnosc-ze-standardami).

### Krok 4 — Ustawienia (`imeto/config.py`)

**Prosto:** jedno miejsce na wszystkie ustawienia programu — adres modelu AI, nazwa
modelu, ścieżka do bazy itd. Zamiast rozsiewać te wartości po całym kodzie, trzymamy je w
jednym miejscu i wczytujemy z pliku ustawień. Hasła i klucze **nigdy** nie są w kodzie.

**Technicznie:** klasa `Settings` na bibliotece pydantic-settings, wczytująca wartości z
pliku `.env` lub zmiennych środowiskowych, z typowaniem (np. liczby są liczbami, a
prawda/fałsz — wartościami logicznymi). Pole `db_url` jest zarazem przełącznikiem silnika
bazy (SQLite ↔ Postgres).

### Krok 5 — Klient modelu AI (`imeto/core/llm.py`)

**Prosto:** to „tłumacz" między IMeTo a modelem sztucznej inteligencji. Wysyła do modelu
polecenie, odbiera odpowiedź i **pilnuje, żeby odpowiedź miała właściwą formę**. Jeśli
model odpowie bałaganem zamiast wypełnionego formularza — klient pokazuje mu błąd i prosi
o poprawkę, i tak kilka razy, aż dostanie coś poprawnego (albo się podda i zgłosi błąd).
Jest „model-agnostyczny", czyli obojętny na to, jaki konkretnie model jest pod spodem —
można go wymienić, zmieniając tylko adres i nazwę, bez ruszania kodu.

**Technicznie:** klasa `LLMClient` używa biblioteki `openai` (standard komunikacji z
modelami zgodnymi z API OpenAI — obsługuje też modele lokalne). Metoda `structured`
realizuje pętlę: wywołanie modelu → parsowanie i walidacja odpowiedzi względem schematu z
kroku 2 → w razie niezgodności doklejenie komunikatu błędu i ponowna próba, do limitu.
Ponawianie sieciowe (gdy serwer chwilowo nie odpowiada) obsługuje samo SDK — nie
dublujemy tego. Klient został przetestowany **bez łączenia się z siecią**: w testach
podstawiamy atrapę odpowiedzi (biblioteka respx), dzięki czemu sprawdzamy naszą logikę
niezależnie od tego, czy jakiś model akurat działa.

### Krok 6 — Wczytywanie dokumentów (`imeto/ingest/parsing.py`)

**Prosto:** funkcja, która bierze plik PDF lub Word i zamienia go na zwykły tekst, na
którym można dalej pracować (m.in. szukać cytatów). Jeśli ktoś poda plik w nieobsługiwanym
formacie — funkcja grzecznie odmawia.

**Technicznie:** `parse_document(path)` rozpoznaje format po rozszerzeniu: `.docx` czyta
biblioteką python-docx (łączy akapity), `.pdf` biblioteką pdfplumber (łączy strony), inne
rozszerzenia odrzuca. Zwraca jeden ciągły tekst (`full_text`). Ważne uproszczenie: pozycje
cytatów to po prostu numery znaków w tym tekście, więc nie budujemy osobnej „mapy" pozycji
na strony — to samo, na czym operuje weryfikacja cytatu z kroku 1. Testy tworzą plik Word
„w locie", więc nie zależą od żadnego zewnętrznego pliku przykładowego.

### Krok 7 — Pierwsza faza potoku (`imeto/phases/extract.py`)

**Prosto:** to pierwszy prawdziwy „etap pracy", który spina wszystko dotychczasowe w jeden
przepływ: bierze dokument, wyciąga z niego tekst, prosi model o fakty, **sprawdza każdy
cytat** i zapisuje do archiwum tylko te fakty, które mają pokrycie. Fakty z przekręconym
lub zmyślonym cytatem są po cichu odrzucane i zliczane. Na koniec faza mówi: „tyle a tyle
zapisałem, tyle odrzuciłem, teraz potrzebna decyzja człowieka".

**Technicznie:** definiujemy kontrakt fazy (`Phase`, `PhaseContext`, `PhaseResult` w
`phases/base.py`) i pierwszą jego realizację — `ExtractPhase`. Przepływ: `parse_document`
→ zapis źródła → `llm.structured(...)` z instrukcją wydobycia faktów → dla każdego faktu
`store.add_evidence` (który weryfikuje cytat); wyjątek `SpanNotVerified` jest łapany i
liczony jako odrzucony. Wynik (`PhaseResult`) niesie listę zapisanych dowodów i flagę
`needs_human=True` (kandydaci czekają na próg). Faza jest w pełni testowalna z atrapą
modelu i tymczasową bazą.

### Krok 8 — Uruchomienie z wiersza poleceń (`imeto/cli.py`)

**Prosto:** polecenie `imeto run <dokument>`, które uruchamia cały przepływ jednym
strzałem i wypisuje wynik: ile faktów zapisano, ile odrzucono, oraz treść każdego faktu z
jego cytatem. To domyka pierwszy działający, kompletny etap projektu (nazywamy go POC-1).

**Technicznie:** cienka warstwa na bibliotece Typer. To tutaj **konfiguracja (krok 4)
wpina się w rdzeń**: adres i nazwa modelu budują `LLMClient`, `db_url` buduje bazę, a
`ExtractPhase` przetwarza dokument. CLI nie zawiera żadnej logiki — tylko wywołuje rdzeń i
wypisuje wynik (zasada „interfejs to cienka skórka"). Jeśli model nie jest skonfigurowany,
polecenie kończy się czytelnym komunikatem, zamiast niejasnym błędem.

### Krok 9 — Próg człowieka (`imeto/core/provenance.py`)

**Prosto:** do tej pory każdy zweryfikowany cytat był po prostu zapisywany. Teraz
wprowadzamy decyzję człowieka: każdy taki cytat zaczyna życie jako **kandydat**, a człowiek
go **akceptuje** albo **odrzuca**. System zapamiętuje nie tylko decyzję, ale i jej autora
oraz moment — żeby zawsze było wiadomo, kto co zatwierdził. To realizacja zasady „człowiek
decyduje".

**Technicznie:** dowód (`Evidence`) dostaje pola `status` (candidate / accepted /
rejected), `approved_by` (kto zdecydował) i `decided_at` (kiedy). Store zyskuje metody
`accept_evidence` i `reject_evidence` oraz filtrowanie dowodów po statusie. W języku
standardu PROV-O akceptacja to przypisanie do osoby (`wasAttributedTo`), a odrzucenie —
unieważnienie (`wasInvalidatedBy`). Uwaga: pełny „dyrygent" wielu faz (sekwencer) świadomie
odłożyliśmy — przy jednej fazie byłby przedwczesny; wejdzie przy POC-2, gdy faz będzie
więcej.

### Krok 10 — Interfejs graficzny (`imeto/ui/app.py`)

**Prosto:** klikalny interfejs w przeglądarce. Wgrywasz dokument, klikasz „Wydobądź
fakty", widzisz listę kandydatów, zaznaczasz te, które chcesz zaakceptować, i klikasz
„Zatwierdź". To ten sam przepływ co w wierszu poleceń, ale wygodny do przeglądania i
podejmowania decyzji — czyli praktyczna realizacja progu z kroku 9.

**Technicznie:** interfejs zbudowany w bibliotece Gradio, uruchamiany poleceniem
`imeto ui`. Trzymamy się zasady „interfejs to cienka skórka": logika (uruchomienie
ekstrakcji, zastosowanie decyzji) jest w osobnych, **testowalnych** funkcjach
(`extract_candidates`, `apply_decisions`), a warstwa Gradio tylko je spina z widżetami.
Samą bibliotekę Gradio wczytujemy dopiero przy uruchomieniu interfejsu, więc nie obciąża
reszty programu ani testów. Adres i nazwę modelu można podać wprost w interfejsie.

---

## 5. Jak dokładnie wyciągane są fakty — krok po kroku
<a id="5-jak-wyciagane-sa-fakty"></a>

To jest serce działania IMeTo. Poniżej cały przebieg od momentu, gdy podajesz dokument, aż
do zapisania zweryfikowanego faktu — najpierw w skrócie, potem każdy etap szczegółowo, a na
końcu **konkretny przykład** pokazujący, jak prawdziwy cytat przechodzi, a zmyślony wypada.

### 5.0. Przebieg w skrócie

```
dokument → [1] tekst → [2] zapis źródła → [3] pytanie do modelu → [4] sprawdzenie formy
        → [5] weryfikacja każdego cytatu → [6] zapis kandydatów → [7] decyzja człowieka
```

Cała ta sekwencja to jedno „naciśnięcie guzika": polecenie `imeto run <dokument>` albo
przycisk **Wydobądź fakty** w interfejsie. Uruchamia ona fazę `ExtractPhase`
(`imeto/phases/extract.py`), która dyryguje pozostałymi klockami.

### 5.1. Etap 1 — z dokumentu na czysty tekst

Plik (PDF lub Word) trafia do funkcji `parse_document`. Dla Worda skleja treść wszystkich
akapitów, dla PDF-a — tekst wszystkich stron, wstawiając między nie znak nowej linii.
Powstaje **jeden ciągły napis** (`full_text`). To ważne, bo wszystkie dalsze pozycje
cytatów to po prostu numery znaków w tym napisie — nie ma osobnej „mapy stron".

### 5.2. Etap 2 — zapis źródła do archiwum

Zanim cokolwiek wyciągniemy, dokument zostaje zapisany jako **źródło** (`Source`) w bazie:
jego pełny tekst plus identyfikator (na razie ścieżka do pliku). Źródło dostaje swój numer
(`source_id`). Dzięki temu każdy przyszły fakt będzie miał do czego się „przykleić" i
zawsze będzie wiadomo, z którego dokładnie dokumentu pochodzi.

### 5.3. Etap 3 — pytanie do modelu AI

Do modelu wysyłamy dwie rzeczy:

- **Instrukcję** (stały tekst `EXTRACT_SYSTEM`): „wydobądź fakty; zwróć wyłącznie JSON w
  formacie `{"facts": [{"quote": "...", "statement": "..."}]}`; **quote musi być dosłownym
  fragmentem tekstu, skopiowanym znak w znak**; nie zmyślaj cytatów; jeśli nie ma faktów,
  zwróć pustą listę".
- **Treść dokumentu** (`full_text`) jako materiał do przeczytania.

Model ma zwrócić listę faktów, gdzie **`quote`** to dosłowny fragment ze źródła (dowód), a
**`statement`** to ten sam fakt ujęty własnymi słowami (streszczenie). Rozdzielenie tych
dwóch jest celowe: `quote` służy do weryfikacji, `statement` do czytania przez człowieka.

Ważne, czego tu **nie** ma: model **nie** podaje, w którym miejscu tekstu cytat się
znajduje. Pozycję wyliczymy sami (etap 5), bo to jedyny sposób, by nie dać się oszukać.

### 5.4. Etap 4 — sprawdzenie, czy odpowiedź ma właściwą formę

Odpowiedź modelu przechodzi przez `LLMClient.structured`:

1. Jeśli model owinął JSON w blok ```` ```json … ``` ```` — zdejmujemy tę otoczkę (małe
   modele często to robią).
2. Próbujemy odczytać i **zwalidować** wynik względem schematu (`Extraction`): czy to
   poprawny JSON, czy są dokładnie pola `quote` i `statement`, czy nie są puste, czy nie
   ma pól-śmieci.
3. Jeśli walidacja się nie uda — doklejamy do rozmowy komunikat błędu („poprzednia
   odpowiedź nie spełniła schematu, popraw") i **pytamy model ponownie**, do ustalonego
   limitu prób. Po wyczerpaniu prób zgłaszamy czytelny błąd.

To pierwsza z dwóch siatek bezpieczeństwa: pilnuje **formy** odpowiedzi. Druga (etap 5)
pilnuje jej **prawdziwości**.

### 5.5. Etap 5 — weryfikacja każdego cytatu (serce anty-halucynacji)

Dla **każdego** faktu z listy wykonujemy `add_evidence`, które nie ufa modelowi na słowo,
tylko sprawdza cytat w oryginale funkcją `find_span`:

1. Bierzemy `quote` i pomijamy otaczające spacje.
2. Dzielimy go na słowa i budujemy wzorzec „słowo — dowolne białe znaki — słowo — …".
   Dzięki temu **znaki niebiałe (litery, cyfry, interpunkcja) muszą pasować co do znaku**,
   ale różnice w spacjach czy przejściach do nowej linii są tolerowane (model często zwija
   tekst).
3. Szukamy tego wzorca w `full_text` źródła.
   - **Znaleziono** → zwracamy pozycję `(start, end)` w oryginale. Fakt ma pokrycie.
   - **Nie znaleziono** → funkcja zwraca „brak", a `add_evidence` zgłasza `SpanNotVerified`.

Jeśli cytat ma pokrycie, tworzymy **dowód** (`Evidence`): dosłowny cytat, jego pozycja
`start`/`end`, `statement`, oraz „metryczkę" pochodzenia (jaki proces go wytworzył, jaki
model, kiedy). Jeśli cytatu nie ma w tekście — dowód **nie powstaje**; faza łapie ten
wyjątek i **zlicza fakt jako odrzucony**. Halucynacja fizycznie nie może wejść do bazy.

### 5.6. Etap 6 — zapis kandydatów i podsumowanie

Zweryfikowane dowody trafiają do archiwum ze statusem **`candidate`** (kandydat). Faza
zwraca podsumowanie: ile faktów zapisano jako kandydatów, ile odrzucono z braku pokrycia,
oraz sygnał „potrzebna decyzja człowieka" (`needs_human`). W wierszu poleceń widzisz tę
listę od razu; w interfejsie pojawia się jako lista do zaznaczenia.

### 5.7. Etap 7 — decyzja człowieka (próg)

Kandydat to jeszcze nie fakt zatwierdzony. Człowiek przegląda listę i **akceptuje** lub
**odrzuca** każdy z osobna. Decyzja zmienia status dowodu na `accepted` albo `rejected` i
zapisuje, **kto** i **kiedy** ją podjął. Dopiero zaakceptowane dowody uznajemy za
potwierdzone. To realizacja zasady „człowiek decyduje" (system nigdy nie przepycha
wniosków sam).

### 5.8. Konkretny przykład

Załóżmy, że w dokumencie jest zdanie:

> `Rada gminy przyjęła uchwałę nr 12 w sprawie budżetu na rok 2025.`

Model zwraca dwa fakty:

| # | `quote` (dowód) | `statement` (streszczenie) | Wynik weryfikacji |
|---|---|---|---|
| A | `przyjęła uchwałę nr 12` | Rada przyjęła uchwałę. | **Znaleziono** w tekście → zapis jako kandydat, pozycja np. (11, 33) |
| B | `przyjęła uchwałę nr 13` | Rada przyjęła uchwałę nr 13. | **Nie znaleziono** (12 ≠ 13) → `SpanNotVerified` → odrzucone, brak zapisu |

Fakt A ma pokrycie znak w znak, więc wchodzi do archiwum jako kandydat. Fakt B wygląda
równie wiarygodnie, ale model przekręcił numer — w oryginale nie ma „nr 13", więc **wypada
automatycznie**, zanim ktokolwiek go zobaczy jako potwierdzony. To właśnie ta różnica
chroni przed halucynacją. Sytuacja odwrotna — model zwija spacje albo zamienia przejście do
nowej linii na spację — jest tolerowana, bo treść (znaki niebiałe) się zgadza.

Ten przykład jest jednocześnie realnym testem w kodzie
(`tests/test_span_verification.py`, `tests/test_extract_phase.py`).

---

## 6. Model danych i zgodność ze standardami
<a id="6-model-danych-i-zgodnosc-ze-standardami"></a>

To jest świadoma i ważna decyzja projektowa. Zamiast wymyślać własny, prywatny sposób
opisu danych, **opisujemy dane językiem uznanych, międzynarodowych standardów**. Dzięki
temu to, co IMeTo wyprodukuje, jest zrozumiałe dla innych systemów naukowych i daje się
wymieniać, cytować i audytować.

**Prosto:** to trochę jak używanie ISO do dat albo standardu bibliograficznego w
bibliotece — nie wymyślamy własnego formatu, tylko trzymamy się tego, co świat już
ustalił. Nasza baza dalej jest zwykłą, prostą bazą, ale **nazwy pól i typy odpowiadają
tym standardom**, a docelowo dane da się wyeksportować do formatu, który inne systemy
naukowe od razu rozumieją.

Cztery standardy, każdy odpowiada za inną warstwę (nie konkurują ze sobą):

| Standard | Za co odpowiada w IMeTo | Przykład |
|---|---|---|
| **PROV-O** (W3C) | **Pochodzenie danych** — kto/co/kiedy wytworzyło dany fakt | dowód „został zacytowany ze" źródła, „został wytworzony przez" dany proces |
| **Web Annotation** (W3C) | **Zakotwiczenie cytatu** w tekście | „ten cytat to znaki od 120 do 145 w dokumencie" |
| **FaBiO** (SPAR) | **Typ dokumentu** źródłowego | raport, artykuł naukowy, praca dyplomowa, zbiór danych |
| **SKG-IF** | **Format wymiany** metadanych naukowych | identyfikatory (DOI, ORCID), autorzy, czasopisma |
| **SKOS** | **Słowniki dziedzinowe** (planowane) | lista typów dowodów, kryteria oceny |
| **CiTO** (SPAR) | **Relacje argumentacyjne** (planowane, POC-2) | ten dowód „popiera" / „podważa" to twierdzenie |

Jak to wygląda konkretnie w bazie (krok 3):

- **`Source`** (dokument) jest opisany jako „byt" w rozumieniu PROV-O, otypowany klasą
  FaBiO (np. „raport"), z polami bibliograficznymi ze standardu Dublin Core (tytuł,
  język) oraz listą identyfikatorów w modelu SKG-IF (np. DOI).
- **`Evidence`** (zweryfikowany cytat) łączy dwa standardy naraz: jest „bytem"
  PROV-O, który „został zacytowany ze" źródła (`prov:wasQuotedFrom`), a zarazem
  „adnotacją" w rozumieniu Web Annotation — dokładny cytat to selektor tekstu
  (`exact`), a pozycja od-do to selektor pozycji (`start`/`end`). Do tego pola
  pochodzenia: kiedy powstał, jaki proces i jaki model go wytworzył.

**Decyzja o przechowywaniu:** zostajemy przy zwykłej bazie relacyjnej (SQLite), a
zgodność ze standardami realizujemy przez **nazewnictwo pól** i przez **eksport do
formatu JSON-LD** (planowany na późniejszy etap). Nie budujemy specjalnej „bazy grafowej"
ani magazynu trójek RDF — dla jednego użytkownika lokalnie byłby to zbędny narzut.
Ciekawostka: nasze dane *są* grafem (PROV-O to model grafowy), a eksport do JSON-LD *jest*
grafem — więc kto zechce analiz grafowych, załaduje sobie wyeksportowane dossier do
narzędzia grafowego u siebie. Graf dostajemy „na wejściu" (model) i „na wyjściu"
(eksport), bez silnika grafowego w środku.

---

## 7. Jak to uruchomić i sprawdzić
<a id="7-jak-to-uruchomic-i-sprawdzic"></a>

Wszystkie polecenia wykonuje się w katalogu projektu
(`/Users/patrykhubar/Desktop/imeto_2_0`). Używamy narzędzia `uv` do zarządzania
środowiskiem — `uv run` uruchamia polecenie w środowisku projektu.

**Zainstaluj środowisko (raz):**
```bash
uv sync --extra dev
```

**Uruchom wszystkie testy** — to jest „dowód, że wszystko działa":
```bash
uv run pytest -v
```
Zobaczysz listę testów zakończonych `PASSED`. Pliki testów w katalogu `tests/` czyta się
jak specyfikację — każdy test to jeden opisany przypadek.

**Sprawdź jakość kodu** (styl i typy):
```bash
uv run ruff check imeto tests   # styl i częste błędy
uv run mypy imeto               # zgodność typów
```

**Pobaw się weryfikacją cytatu na żywo:**
```bash
uv run python
```
a potem w interaktywnej konsoli:
```python
from imeto.core.span import find_span
src = "Rada gminy przyjęła uchwałę nr 12\nw sprawie budżetu."
find_span(src, "przyjęła uchwałę nr 12")   # -> (11, 33)  znaleziono
find_span(src, "przyjęła uchwałę nr 13")   # -> None      (przekręcona cyfra)
```

**Uruchom cały przepływ na dokumencie (POC-1):** potrzebny jest działający model AI
(lokalny, zgodny z API OpenAI). Wskazujemy go w ustawieniach, po czym:
```bash
export LLM_BASE_URL="http://localhost:8888/v1"   # adres Twojego modelu
export LLM_MODEL="<nazwa modelu>"                # np. z Unsloth Studio / vLLM
uv run imeto run data/sprawozdanie_test.docx
```
Program wypisze podsumowanie (ile faktów zapisano, ile odrzucono jako bez pokrycia) oraz
treść każdego zapisanego faktu z jego dosłownym cytatem i pozycją. Bez skonfigurowanego
modelu polecenie zgłosi czytelny komunikat „llm_model nie ustawiony" — to poprawne
zachowanie, nie błąd.

---

## 8. Co jest dalej w planie
<a id="8-co-jest-dalej-w-planie"></a>

Zbudowane: **kroki 0–10** — cały przepływ POC-1 z progiem człowieka i interfejsem
graficznym: szkielet, weryfikacja cytatu, kontrakt danych, baza z pochodzeniem,
ustawienia, klient AI, wczytywanie dokumentów, faza ekstrakcji, wiersz poleceń, próg
człowieka (akceptuj/odrzuć) oraz GUI Gradio.

Uruchomienie interfejsu:
```bash
uv sync --extra ui          # doinstaluj Gradio (raz)
uv run imeto ui             # otwórz interfejs w przeglądarce
```

Następne kroki (POC-2 i dalej): propozycje tropów, rozbiór argumentacyjny ZA/PRZECIW,
asystent redakcyjny, eksport dossier (m.in. do formatu JSON-LD zgodnego ze standardami),
mapa twierdzeń. Warunkowo, gdy zajdzie realna potrzeba: „dyrygent" wielu faz (sekwencer),
przeniesienie na bazę Postgres, prawdziwe API oraz pobieranie metadanych naukowych
(OpenAlex / ORCID / Crossref).

Dalej (POC-2 i POC-3): propozycje tropów, rozbiór argumentacyjny ZA/PRZECIW, asystent
redakcyjny, eksport dossier oraz mapa twierdzeń. Warunkowo, gdy zajdzie realna potrzeba:
przeniesienie na bazę Postgres, dodanie prawdziwego API i pobieranie metadanych naukowych
(OpenAlex/ORCID/Crossref).

---

## Słownik pojęć

- **AI / model językowy (LLM)** — program, który generuje tekst na podstawie poleceń
  (jak ChatGPT). Potężny, ale bywa niewiarygodny — stąd cała nasza ostrożność.
- **Halucynacja** — sytuacja, gdy model podaje informację brzmiącą wiarygodnie, ale
  zmyśloną lub przekręconą.
- **Cytat / span** — dosłowny fragment tekstu źródłowego. „Span" to jego pozycja: od
  którego do którego znaku występuje w dokumencie.
- **Kotwiczenie (anchoring)** — powiązanie cytatu z jego dokładnym miejscem w źródle.
- **Provenance (pochodzenie danych)** — informacja o tym, skąd dany fakt się wziął: z
  jakiego źródła, w jakim procesie, przez jaki model, kiedy. Pozwala odtworzyć i
  zaudytować każdą informację.
- **Niezmiennik** — reguła, która musi być zawsze spełniona. U nas: „dowód tylko po
  weryfikacji cytatu".
- **Structured output (wynik strukturalny)** — wymóg, by model odpowiadał w ściśle
  określonej formie (formularzu), a nie dowolnym tekstem.
- **Schemat / kontrakt danych** — opis dozwolonej formy danych: jakie pola, jakich typów,
  co obowiązkowe.
- **Walidacja** — sprawdzenie, czy dane spełniają schemat.
- **Ontologia / standard opisu danych** — uzgodniony przez społeczność sposób nazywania i
  łączenia pojęć, żeby różne systemy rozumiały te same dane tak samo. PROV-O, FaBiO,
  SKOS, Web Annotation, SKG-IF to takie standardy.
- **JSON-LD** — format zapisu danych, który jest jednocześnie zwykłym plikiem danych i
  grafem zgodnym z ontologiami. Nasz planowany format eksportu.
- **Baza relacyjna / SQLite** — sposób przechowywania danych w tabelach. SQLite to jej
  najprostsza odmiana: cała baza to jeden plik, bez osobnego serwera.
- **Potok (pipeline)** — ciąg etapów, przez które przechodzi dokument.
- **Próg (human-in-the-loop)** — moment, w którym system czeka na decyzję człowieka.
- **Rdzeń vs fazy** — rdzeń to wspólne klocki (ogólne), fazy to konkretne etapy potoku
  (dziedzinowe). Fazy używają rdzenia, nigdy odwrotnie.
- **Test** — mały program sprawdzający, że dany fragment kodu robi to, co ma. „Zielone
  testy" znaczą, że wszystko przeszło.
- **on-premise (on-prem)** — działanie na własnym sprzęcie, bez chmury i wysyłania danych
  na zewnątrz.
- **`uv`, `ruff`, `mypy`, `pytest`** — narzędzia pracy: `uv` zarządza środowiskiem,
  `ruff` pilnuje stylu kodu, `mypy` sprawdza zgodność typów, `pytest` uruchamia testy.
