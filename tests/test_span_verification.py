from imeto.core.span import find_span

SRC = "Rada gminy przyjęła uchwałę nr 12\nw sprawie budżetu na rok 2025."


def test_exact_match_returns_offsets():
    span = find_span(SRC, "przyjęła uchwałę nr 12")
    assert span is not None
    assert SRC[span[0] : span[1]] == "przyjęła uchwałę nr 12"


def test_whitespace_collapsed_in_quote_still_matches():
    # model zwinął newline i podwójne spacje do pojedynczych
    span = find_span(SRC, "nr 12 w sprawie budżetu")
    assert span is not None
    # offsety wskazują na oryginał (z newline), nie na zwiniętą wersję
    assert SRC[span[0] : span[1]] == "nr 12\nw sprawie budżetu"


def test_altered_non_whitespace_is_rejected():
    assert find_span(SRC, "przyjęła uchwałę nr 13") is None  # 12 -> 13


def test_case_sensitive():
    assert find_span(SRC, "rada gminy") is None  # oryginał ma "Rada"


def test_joined_words_rejected():
    # spacja w cytacie, brak w źródle = modyfikacja, nie różnica białych znaków
    assert find_span("radagminy", "rada gminy") is None


def test_empty_or_blank_quote_rejected():
    assert find_span(SRC, "") is None
    assert find_span(SRC, "   \n  ") is None


def test_surrounding_whitespace_in_quote_ignored():
    assert find_span(SRC, "  Rada gminy  ") is not None


def test_returns_first_occurrence():
    span = find_span("ala ma ala", "ala")
    assert span == (0, 3)


def test_typographic_quotes_folded():
    # źródło ma cudzysłowy drukarskie, cytat proste — treść ta sama
    src = 'Projekt „Szkoła bez barier” ruszył w 2025.'
    span = find_span(src, 'Projekt "Szkoła bez barier" ruszył')
    assert span is not None
    # offset wskazuje ORYGINAŁ (z drukarskimi cudzysłowami)
    assert src[span[0] : span[1]] == 'Projekt „Szkoła bez barier” ruszył'


def test_dash_variants_folded():
    src = "okres 2020—2025 był kluczowy"  # em-dash w źródle
    assert find_span(src, "okres 2020-2025 był") is not None  # dywiz w cytacie


def test_fold_is_symmetric():
    # cytat z cudzysłowem drukarskim, źródło z prostym — też ma trafić
    assert find_span('cel "X"', "cel „X”") is not None
