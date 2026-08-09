"""
tests/unit/test_formulas.py

Known-input -> known-output tests for core/formulas.py, per acceptance
criteria: "Decay and S_final exist as pure functions in core/formulas.py
with unit tests".
"""

import math

import pytest

from backend.core.formulas import (
    W_TICKER,
    blend_s_final,
    recency_weight,
    time_weighted_average,
)

# ============================================================
# recency_weight
# ============================================================


class TestRecencyWeight:
    def test_zero_age_gives_full_weight(self):
        assert recency_weight(age_hours=0, lambda_=0.1) == pytest.approx(1.0)

    def test_known_value(self):
        # W_time = e^(-0.1 * 10) = e^-1
        assert recency_weight(age_hours=10, lambda_=0.1) == pytest.approx(
            math.exp(-1), rel=1e-9
        )

    def test_weight_strictly_decreases_with_age(self):
        w_1h = recency_weight(age_hours=1, lambda_=0.1)
        w_24h = recency_weight(age_hours=24, lambda_=0.1)
        w_48h = recency_weight(age_hours=48, lambda_=0.1)
        assert w_1h > w_24h > w_48h

    def test_larger_lambda_decays_faster(self):
        slow = recency_weight(age_hours=24, lambda_=0.05)
        fast = recency_weight(age_hours=24, lambda_=0.2)
        assert fast < slow

    def test_negative_age_raises(self):
        with pytest.raises(ValueError):
            recency_weight(age_hours=-1, lambda_=0.1)


# ============================================================
# time_weighted_average
# ============================================================


class TestTimeWeightedAverage:
    def test_empty_list_returns_none(self):
        assert time_weighted_average([]) is None

    def test_single_event_equals_its_own_score(self):
        assert time_weighted_average([(0.8, 1.0)]) == pytest.approx(0.8)

    def test_recent_event_dominates_older_event(self):
        # event A: score=1.0, weight=1.0 (just published)
        # event B: score=-1.0, weight=0.1 (heavily decayed)
        result = time_weighted_average([(1.0, 1.0), (-1.0, 0.1)])
        assert result == pytest.approx((1.0 * 1.0 + -1.0 * 0.1) / (1.0 + 0.1))
        assert result > 0  # recent positive event should win out

    def test_all_zero_weights_returns_none(self):
        # every event decayed to (numerically) zero weight -> no
        # signal left to average, must be None not a division by zero
        assert time_weighted_average([(0.5, 0.0), (-0.3, 0.0)]) is None


# ============================================================
# blend_s_final
# ============================================================


class TestBlendSFinal:
    def test_empty_state_when_nothing_valid(self):
        result = blend_s_final(
            ticker_avg=None,
            concept_avgs={"STEEL": None},
            concept_weights={"STEEL": 1.0},
        )
        assert result.is_empty is True
        assert result.score == 0.0

    def test_empty_state_is_distinct_type_from_real_zero(self):
        # a genuinely neutral score (real news, averages to exactly 0)
        # must NOT be confused with the empty state
        neutral = blend_s_final(
            ticker_avg=0.0, concept_avgs={}, concept_weights={}
        )
        empty = blend_s_final(
            ticker_avg=None, concept_avgs={}, concept_weights={}
        )
        assert neutral.score == 0.0 and neutral.is_empty is False
        assert empty.score == 0.0 and empty.is_empty is True

    def test_ticker_only_no_concepts(self):
        result = blend_s_final(ticker_avg=0.5, concept_avgs={}, concept_weights={})
        assert result.is_empty is False
        assert result.score == pytest.approx(0.5)

    def test_ticker_plus_one_concept_matches_hand_calc(self):
        # S_final = (W_ticker*0.5 + wi*1.0) / (W_ticker + wi)
        #         = (1.0*0.5 + 1.0*1.0) / (1.0 + 1.0) = 1.5 / 2 = 0.75
        result = blend_s_final(
            ticker_avg=0.5,
            concept_avgs={"STEEL": 1.0},
            concept_weights={"STEEL": 1.0},
        )
        assert result.score == pytest.approx(0.75)

    def test_concept_with_no_news_is_excluded_not_zeroed(self):
        """
        Critical case from the formula's own I_Ci definition: a
        concept with NO news this window must vanish from BOTH
        numerator and denominator — it must not be treated as
        "weight wi, score 0", which would incorrectly drag S_final
        toward neutral just because an unrelated sector was quiet.
        """
        # STEEL has news (avg=1.0), REAL_ESTATE has none (None)
        with_excluded = blend_s_final(
            ticker_avg=None,
            concept_avgs={"STEEL": 1.0, "REAL_ESTATE": None},
            concept_weights={"STEEL": 1.0, "REAL_ESTATE": 0.3},
        )
        # If REAL_ESTATE were wrongly zeroed-in: (1.0*1.0 + 0.3*0) / (1.0+0.3) = 0.769
        # Correct (excluded): (1.0*1.0) / (1.0) = 1.0
        assert with_excluded.score == pytest.approx(1.0)
        assert with_excluded.score != pytest.approx(1.0 / 1.3)

    def test_ticker_weight_dominates_over_low_weight_concept(self):
        # ticker mention (W=1.0, very negative) vs a low-weight
        # concept (wi=0.1, very positive) — ticker should dominate
        # the blend since its weight is much larger
        result = blend_s_final(
            ticker_avg=-1.0,
            concept_avgs={"AGRICULTURE": 1.0},
            concept_weights={"AGRICULTURE": 0.1},
        )
        expected = (W_TICKER * -1.0 + 0.1 * 1.0) / (W_TICKER + 0.1)
        assert result.score == pytest.approx(expected)
        assert result.score < 0

    def test_multiple_concepts_sum_correctly(self):
        result = blend_s_final(
            ticker_avg=None,
            concept_avgs={"STEEL": 0.5, "CONSTRUCTION": -0.2, "MACRO": 0.1},
            concept_weights={"STEEL": 1.0, "CONSTRUCTION": 0.5, "MACRO": 0.3},
        )
        expected_num = 1.0 * 0.5 + 0.5 * -0.2 + 0.3 * 0.1
        expected_den = 1.0 + 0.5 + 0.3
        assert result.score == pytest.approx(expected_num / expected_den)

    def test_unknown_concept_defaults_to_zero_weight(self):
        # concept present in concept_avgs but missing from
        # concept_weights (shouldn't normally happen if the caller
        # reads both from the same static_ontology query, but the
        # function must not crash if it does)
        result = blend_s_final(
            ticker_avg=0.5, concept_avgs={"UNKNOWN": 0.9}, concept_weights={}
        )
        # UNKNOWN gets wi=0.0 -> contributes 0 to both num and denom,
        # equivalent to being excluded
        assert result.score == pytest.approx(0.5)