from imeto.core.span import find_span

SRC = "The council adopted resolution no. 12\nregarding the budget for 2025."


def test_exact_match_returns_offsets():
    span = find_span(SRC, "adopted resolution no. 12")
    assert span is not None
    assert SRC[span[0] : span[1]] == "adopted resolution no. 12"


def test_whitespace_collapsed_in_quote_still_matches():
    # model collapsed the newline and double spaces to single ones
    span = find_span(SRC, "no. 12 regarding the budget")
    assert span is not None
    # offsets point to the original (with newline), not the collapsed version
    assert SRC[span[0] : span[1]] == "no. 12\nregarding the budget"


def test_altered_non_whitespace_is_rejected():
    assert find_span(SRC, "adopted resolution no. 13") is None  # 12 -> 13


def test_case_sensitive():
    assert find_span(SRC, "the council") is None  # original has "The"


def test_joined_words_rejected():
    # space in the quote, none in the source = modification, not a whitespace difference
    assert find_span("thecouncil", "the council") is None


def test_empty_or_blank_quote_rejected():
    assert find_span(SRC, "") is None
    assert find_span(SRC, "   \n  ") is None


def test_surrounding_whitespace_in_quote_ignored():
    assert find_span(SRC, "  The council  ") is not None


def test_returns_first_occurrence():
    span = find_span("cat and cat", "cat")
    assert span == (0, 3)


def test_typographic_quotes_folded():
    # source has typographic quotes, quote has straight ones — same content
    src = "Project „School without barriers” started in 2025."
    span = find_span(src, 'Project "School without barriers" started')
    assert span is not None
    # offset points to the ORIGINAL (with typographic quotes)
    assert src[span[0] : span[1]] == "Project „School without barriers” started"


def test_dash_variants_folded():
    src = "the period 2020—2025 was crucial"  # em-dash in the source
    assert find_span(src, "the period 2020-2025 was") is not None  # hyphen in the quote


def test_fold_is_symmetric():
    # quote with typographic quotes, source with straight ones — must also match
    assert find_span('goal "X"', "goal „X”") is not None
