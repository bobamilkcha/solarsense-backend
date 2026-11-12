import pytest
from scripts.evaluate_nfr import accuracy_stats, latency_stats


def test_latency_skips_non_positive_and_computes_percentiles():
    stats = latency_stats([0.0, -1.0, 1.0, 2.0, 3.0, 4.0, 10.0], limit_s=5.0)
    assert stats is not None
    assert stats.count == 5
    assert stats.skipped == 2
    assert stats.median_s == 3.0
    assert stats.p95_s == 10.0
    assert stats.max_s == 10.0
    assert stats.within_limit_pct == pytest.approx(80.0)


def test_latency_none_when_no_usable_readings():
    assert latency_stats([0.0, -2.0], limit_s=5.0) is None


def test_accuracy_perfect_agreement():
    stats = accuracy_stats([(5.0, 5.0), (4.0, 4.0)])
    assert stats is not None
    assert stats.rmse == 0.0
    assert stats.nrmse_pct == 0.0
    assert stats.nmbe_pct == 0.0


def test_accuracy_nrmse_and_bias():
    # Errors +1 and -1 -> RMSE 1; mean satellite 5 -> nRMSE 20%, no bias.
    stats = accuracy_stats([(5.0, 4.0), (5.0, 6.0)])
    assert stats is not None
    assert stats.rmse == pytest.approx(1.0)
    assert stats.nrmse_pct == pytest.approx(20.0)
    assert stats.nmbe_pct == pytest.approx(0.0)

    over = accuracy_stats([(6.0, 5.0), (6.0, 5.0)])
    assert over is not None
    assert over.nmbe_pct == pytest.approx(20.0)


def test_accuracy_none_without_pairs():
    assert accuracy_stats([]) is None
