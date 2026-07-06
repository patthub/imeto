from imeto.obs.eval import (
    ExpectedFact,
    PredictedFact,
    aggregate,
    load_golden,
    score,
)


def test_perfect_match():
    pred = [PredictedFact("direct", ["przeszkolono 128 osób"])]
    exp = [ExpectedFact("direct", ["128 osób"])]
    m = score(pred, exp)
    assert (m.recall, m.precision, m.kind_accuracy) == (1.0, 1.0, 1.0)


def test_missed_fact_lowers_recall():
    exp = [ExpectedFact("direct", ["czegoś nie ma"])]
    m = score([], exp)
    assert m.recall == 0.0 and m.matched == 0


def test_false_positive_lowers_precision():
    pred = [PredictedFact("direct", ["zmyślone"])]
    m = score(pred, [])
    assert m.precision == 0.0


def test_kind_mismatch():
    pred = [PredictedFact("direct", ["ala ma kota"])]
    exp = [ExpectedFact("inferred", ["ma kota"])]
    m = score(pred, exp)
    assert m.matched == 1 and m.kind_accuracy == 0.0


def test_matching_folds_typography():
    pred = [PredictedFact("direct", ['projekt „Szkoła”'])]
    exp = [ExpectedFact("direct", ['projekt "Szkoła"'])]
    assert score(pred, exp).matched == 1


def test_aggregate_averages():
    a = score([PredictedFact("direct", ["x"])], [ExpectedFact("direct", ["x"])])
    b = score([], [ExpectedFact("direct", ["y"])])
    agg = aggregate([a, b])
    assert agg.recall == 0.5
    assert agg.n_expected == 2


def test_golden_files_present_and_valid():
    cases = load_golden("tests/golden")
    assert len(cases) >= 3
    for c in cases:
        assert c["work_type"] and c["text"] and c["expected"]
