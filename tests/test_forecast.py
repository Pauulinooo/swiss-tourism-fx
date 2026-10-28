"""Forecast safeguards and metrics: no look-ahead, WAPE, FX placebo shifts, DM test, Holm."""

import numpy as np
import pandas as pd
import pytest
from scipy import stats
from statsmodels.stats.multitest import multipletests

import forecast as fc

ORIGIN = pd.Timestamp("2018-06-01")


# --- No look-ahead -----------------------------------------------------------
@pytest.mark.parametrize("h", [1, 6])
def test_scramble_future_does_not_change_forecast(panel, fx_yoy, h):
    assert fc.check_no_lookahead(panel, fx_yoy, h, ORIGIN) == 0.0


def test_scramble_catches_a_leaking_feature(panel, fx_yoy, monkeypatch):
    """The check must have teeth: a feature that peeks at the target month is caught."""
    real = fc.build_features

    def leaky(panel, fx_yoy, h):
        f = real(panel, fx_yoy, h)
        f["y_t"] = f["y_target"]            # value at t + h, unknown at the origin
        return f

    monkeypatch.setattr(fc, "build_features", leaky)
    with pytest.raises(AssertionError, match="look-ahead"):
        fc.check_no_lookahead(panel, fx_yoy, 3, ORIGIN)


def test_training_rows_end_at_origin(panel, fx_yoy):
    feats = fc.build_features(panel, fx_yoy, 3)
    out = fc.fit_predict(feats, ORIGIN, use_fx=True)
    assert (out["origin_date"] == ORIGIN).all()
    assert (out["target_date"] == ORIGIN + pd.DateOffset(months=3)).all()
    assert len(out) == panel["series_id"].nunique()


def test_fx_feature_is_the_currency_at_the_origin(panel, fx_yoy):
    feats = fc.build_features(panel, fx_yoy, 4)
    row = feats[(feats["origin_date"] == ORIGIN) & (feats["origin"] == "Germany")].iloc[0]
    eur = fx_yoy[(fx_yoy["currency"] == "EUR") & (fx_yoy["date"] == ORIGIN)]["fx_yoy"].item()
    assert row["fx_yoy"] == eur
    swiss = feats[feats["origin"] == "Switzerland"]["fx_yoy"]
    assert (swiss == 0).all()


# --- WAPE --------------------------------------------------------------------
def test_wape_known_value():
    actual, forecast = pd.Series([100.0, 200.0, 300.0]), pd.Series([110.0, 180.0, 300.0])
    assert fc.wape(actual, forecast) == pytest.approx(100 * 30 / 600)


def test_wape_ignores_small_months_unlike_mape():
    actual, forecast = pd.Series([1.0, 1000.0]), pd.Series([3.0, 1000.0])
    assert fc.wape(actual, forecast) == pytest.approx(100 * 2 / 1001)
    assert fc.mape(actual, forecast) == pytest.approx(100.0)


def test_wape_aggregates_from_sums_not_from_group_averages():
    """Pooled WAPE = sum of group |errors| / sum of group actuals (how the dashboard rebuilds it)."""
    res = pd.DataFrame({"g": ["a", "a", "b", "b"], "actual": [100.0, 100.0, 10.0, 10.0],
                        "naive": [90.0, 110.0, 15.0, 5.0], "gb_no_fx": [100.0, 100.0, 10.0, 10.0],
                        "gb_fx": [95.0, 105.0, 10.0, 10.0]})
    by_group = fc.wape_table(res, ["g"])
    pooled = fc.wape_table(res, [])
    sums = res.assign(err=(res["actual"] - res["naive"]).abs()).groupby("g")[["err", "actual"]].sum()
    assert pooled["naive"].item() == pytest.approx(100 * sums["err"].sum() / sums["actual"].sum())
    assert pooled["naive"].item() == pytest.approx(100 * 30 / 220)
    assert pooled["naive"].item() != pytest.approx(by_group["naive"].mean())   # 10% and 50% -> not 30%
    assert pooled["fx_gain"].item() == pytest.approx(pooled["gb_no_fx"].item() - pooled["gb_fx"].item())
    assert by_group["n"].tolist() == [2, 2]


# --- FX placebo: circular shift ----------------------------------------------
def _wide(df):
    return df.pivot(index="date", columns="currency", values="fx_yoy").sort_index()


@pytest.mark.parametrize("seed", range(20))
def test_shift_fx_is_circular_and_at_least_24_months(fx_yoy, seed):
    out, k = fc.shift_fx(fx_yoy, seed)
    n = fx_yoy["date"].nunique()
    assert fc.MIN_SHIFT == 24 and 24 <= k <= n - 24
    before, after = _wide(fx_yoy), _wide(out)
    # Every currency moves by the same k, and values wrap around the end
    np.testing.assert_array_equal(after.to_numpy(), np.roll(before.to_numpy(), k, axis=0))
    assert len(out) == len(fx_yoy)
    for cur in before:
        assert sorted(after[cur]) == sorted(before[cur])


def test_shift_fx_is_reproducible_and_varies_by_seed(fx_yoy):
    assert fc.shift_fx(fx_yoy, 3)[1] == fc.shift_fx(fx_yoy, 3)[1]
    assert len({fc.shift_fx(fx_yoy, s)[1] for s in range(20)}) > 1


def test_shift_fx_rejects_unaligned_currencies(fx_yoy):
    with pytest.raises(AssertionError, match="same months"):
        fc.shift_fx(fx_yoy.drop(index=0), 0)


# --- Diebold-Mariano and Holm ------------------------------------------------
def test_dm_at_h1_equals_a_one_sample_t_test():
    """With h = 1 there are no autocovariance terms and the HLN factor is (T-1)/T: DM is a plain t-test."""
    d = np.random.default_rng(2).normal(0.3, 1.0, 40)
    stat, p = fc.dm_test(d, h=1)
    t = stats.ttest_1samp(d, 0.0)
    assert stat == pytest.approx(t.statistic) and p == pytest.approx(t.pvalue)


def test_dm_is_symmetric_and_zero_for_zero_mean():
    d = np.random.default_rng(3).normal(0.5, 1.0, 43)
    s1, p1 = fc.dm_test(d, h=6)
    s2, p2 = fc.dm_test(-d, h=6)
    assert s1 == pytest.approx(-s2) and p1 == pytest.approx(p2)
    stat, p = fc.dm_test(np.tile([1.0, -1.0], 20), h=2)
    assert stat == pytest.approx(0.0) and p == pytest.approx(1.0)


def test_dm_needs_enough_months():
    with pytest.raises(AssertionError, match="too few"):
        fc.dm_test(np.ones(12), h=6)


def test_holm_known_case():
    p = pd.Series([0.01, 0.04, 0.03, 0.005], index=list("abcd"))
    adj = fc.holm(p)
    # Sorted: d 0.005*4, a 0.01*3, c 0.03*2, b 0.04*1 -> running max keeps b at 0.06
    assert adj.round(10).to_dict() == {"a": 0.03, "b": 0.06, "c": 0.06, "d": 0.02}
    np.testing.assert_allclose(adj, multipletests(p, method="holm")[1])


def test_holm_caps_at_one():
    assert (fc.holm(pd.Series([0.5, 0.6, 0.9])) == 1.0).all()
