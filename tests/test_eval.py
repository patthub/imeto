from imeto.obs.eval import (
    ExpectedFact,
    PredictedFact,
    aggregate,
    load_golden,
    score,
)


def test_perfect_match():
    pred = [PredictedFact("direct", ["trained 128 people"])]
    exp = [ExpectedFact("direct", ["128 people"])]
    m = score(pred, exp)
    assert (m.recall, m.precision, m.kind_accuracy) == (1.0, 1.0, 1.0)


def test_missed_fact_lowers_recall():
    exp = [ExpectedFact("direct", ["something missing"])]
    m = score([], exp)
    assert m.recall == 0.0 and m.matched == 0


def test_false_positive_lowers_precision():
    pred = [PredictedFact("direct", ["fabricated"])]
    m = score(pred, [])
    assert m.precision == 0.0


def test_kind_mismatch():
    pred = [PredictedFact("direct", ["the cat sat on the mat"])]
    exp = [ExpectedFact("inferred", ["cat sat on the mat"])]
    m = score(pred, exp)
    assert m.matched == 1 and m.kind_accuracy == 0.0


def test_matching_folds_typography():
    pred = [PredictedFact("direct", ["the „School” project"])]
    exp = [ExpectedFact("direct", ['the "School" project'])]
    assert score(pred, exp).matched == 1


def test_aggregate_averages():
    a = score([PredictedFact("direct", ["x"])], [ExpectedFact("direct", ["x"])])
    b = score([], [ExpectedFact("direct", ["y"])])
    agg = aggregate([a, b])
    assert agg.recall == 0.5
    assert agg.n_expected == 2


def test_golden_files_present_and_valid():
    from imeto.core.span import _fold

    cases = load_golden("tests/golden")
    assert len(cases) >= 15
    for c in cases:
        assert c["work_type"] and c["text"] and c["expected"]
        hay = _fold(c["text"]).lower()
        for e in c["expected"]:
            # every expected fact must have at least one substring present in the text
            assert any(_fold(s).lower() in hay for s in e["quote_substrings"]), (
                f"{c['name']}: not in text {e['quote_substrings']}"
            )
