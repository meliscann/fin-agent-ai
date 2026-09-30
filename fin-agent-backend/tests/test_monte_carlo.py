"""
Monte Carlo motorunun ve ilgili hesaplama fonksiyonlarının birim testleri.
Ağ/LLM çağrısı yapmaz — sadece saf hesaplama mantığını doğrular.
"""

import numpy as np
import pytest

from app.models.portfolio import AssetAllocation
from app.core.analysis.monte_carlo import (
    ASSET_PARAMS,
    TUFE_BOND_REAL_SPREAD,
    TUFE_BOND_VOL,
    compute_portfolio_params,
    apply_shocks_to_asset_params,
    run_monte_carlo,
    compute_inflation_adjusted_metrics,
    compute_sharpe,
)


def _alloc(**kwargs) -> AssetAllocation:
    kwargs.setdefault("tufe_bond", 0)
    return AssetAllocation(**kwargs)


class TestComputePortfolioParams:
    def test_single_asset_matches_asset_params(self):
        params = compute_portfolio_params(_alloc(gold=100, usd=0, bist100=0, bond=0, deposit=0))
        assert params["ret"] == pytest.approx(ASSET_PARAMS["gold"]["ret"])
        assert params["vol"] == pytest.approx(ASSET_PARAMS["gold"]["vol"])

    def test_weighted_average_is_correct(self):
        params = compute_portfolio_params(_alloc(gold=50, usd=50, bist100=0, bond=0, deposit=0))
        expected_ret = 0.5 * ASSET_PARAMS["gold"]["ret"] + 0.5 * ASSET_PARAMS["usd"]["ret"]
        assert params["ret"] == pytest.approx(expected_ret)

    def test_asset_params_override_is_used_instead_of_global(self):
        shocked = apply_shocks_to_asset_params({"usd_shock": 0.50})
        params = compute_portfolio_params(
            _alloc(gold=0, usd=100, bist100=0, bond=0, deposit=0), asset_params=shocked
        )
        assert params["ret"] == pytest.approx(ASSET_PARAMS["usd"]["ret"] + 0.50)


class TestTufeBondDynamicReturn:
    """
    tufe_bond, diğer varlıklardan farklı olarak ASSET_PARAMS'ta sabit bir
    ret/vol'a sahip değil — getirisi inflation_rate'ten dinamik hesaplanır
    (bkz. monte_carlo.py'deki TUFE_BOND_REAL_SPREAD notu). Bu testler o
    dinamik bağın gerçekten çalıştığını doğrular.
    """

    def test_ret_tracks_inflation_rate_plus_spread(self):
        alloc = _alloc(gold=0, usd=0, bist100=0, bond=0, deposit=0, tufe_bond=100)
        params = compute_portfolio_params(alloc, inflation_rate=0.30)
        assert params["ret"] == pytest.approx(0.30 + TUFE_BOND_REAL_SPREAD)
        assert params["vol"] == pytest.approx(TUFE_BOND_VOL)

    def test_ret_changes_when_inflation_rate_changes(self):
        alloc = _alloc(gold=0, usd=0, bist100=0, bond=0, deposit=0, tufe_bond=100)
        low = compute_portfolio_params(alloc, inflation_rate=0.20)
        high = compute_portfolio_params(alloc, inflation_rate=0.50)
        assert high["ret"] > low["ret"]
        assert high["ret"] - low["ret"] == pytest.approx(0.30)

    def test_missing_inflation_rate_raises_when_weight_positive(self):
        alloc = _alloc(gold=0, usd=0, bist100=0, bond=0, deposit=0, tufe_bond=100)
        with pytest.raises(ValueError, match="inflation_rate"):
            compute_portfolio_params(alloc)

    def test_missing_inflation_rate_is_fine_when_weight_is_zero(self):
        # tufe_bond ağırlığı 0 ise hiç kullanılmıyor, inflation_rate
        # verilmemiş olması sorun olmamalı.
        alloc = _alloc(gold=100, usd=0, bist100=0, bond=0, deposit=0, tufe_bond=0)
        params = compute_portfolio_params(alloc)
        assert params["ret"] == pytest.approx(ASSET_PARAMS["gold"]["ret"])


class TestApplyShocksToAssetParams:
    def test_does_not_mutate_global_asset_params(self):
        original_usd_ret = ASSET_PARAMS["usd"]["ret"]
        apply_shocks_to_asset_params({"usd_shock": 0.99})
        assert ASSET_PARAMS["usd"]["ret"] == original_usd_ret

    def test_usd_shock_only_affects_usd(self):
        shocked = apply_shocks_to_asset_params({"usd_shock": 0.10})
        assert shocked["usd"]["ret"] == pytest.approx(ASSET_PARAMS["usd"]["ret"] + 0.10)
        assert shocked["gold"]["ret"] == pytest.approx(ASSET_PARAMS["gold"]["ret"])

    def test_policy_rate_delta_affects_bond_and_deposit_only(self):
        shocked = apply_shocks_to_asset_params({"policy_rate_delta": -0.05})
        assert shocked["bond"]["ret"] == pytest.approx(ASSET_PARAMS["bond"]["ret"] - 0.05)
        assert shocked["deposit"]["ret"] == pytest.approx(ASSET_PARAMS["deposit"]["ret"] - 0.05)
        assert shocked["bist100"]["ret"] == pytest.approx(ASSET_PARAMS["bist100"]["ret"])

    def test_bist_shock_affects_bist100_only(self):
        shocked = apply_shocks_to_asset_params({"bist_shock": 0.15})
        assert shocked["bist100"]["ret"] == pytest.approx(ASSET_PARAMS["bist100"]["ret"] + 0.15)
        assert shocked["usd"]["ret"] == pytest.approx(ASSET_PARAMS["usd"]["ret"])

    def test_no_shocks_returns_unchanged_copy(self):
        shocked = apply_shocks_to_asset_params({})
        assert shocked == ASSET_PARAMS
        assert shocked is not ASSET_PARAMS  # kopya olmalı, aynı obje değil

    def test_inflation_delta_is_ignored_here(self):
        # inflation_delta varlık getirilerine değil, enflasyon oranına eklenir —
        # bu fonksiyon onu görmezden gelmeli.
        shocked = apply_shocks_to_asset_params({"inflation_delta": 0.10})
        assert shocked == ASSET_PARAMS


class TestRunMonteCarlo:
    def test_percentiles_are_ordered(self):
        result, _ = run_monte_carlo(
            amount=100_000, horizon_years=3,
            allocation=_alloc(gold=20, usd=20, bist100=20, bond=20, deposit=20),
            n_simulations=500, seed=1,
        )
        assert result.percentile_10 <= result.percentile_25 <= result.percentile_50
        assert result.percentile_50 <= result.percentile_75 <= result.percentile_90
        assert result.worst <= result.percentile_10
        assert result.best >= result.percentile_90

    def test_final_values_length_matches_n_simulations(self):
        _, final_values = run_monte_carlo(
            amount=100_000, horizon_years=1,
            allocation=_alloc(gold=100, usd=0, bist100=0, bond=0, deposit=0),
            n_simulations=250, seed=1,
        )
        assert len(final_values) == 250
        assert np.all(final_values > 0)  # GBM: değerler asla negatif olamaz

    def test_paths_sample_starts_at_amount(self):
        result, _ = run_monte_carlo(
            amount=100_000, horizon_years=1,
            allocation=_alloc(gold=100, usd=0, bist100=0, bond=0, deposit=0),
            n_simulations=100, sample_paths=10, seed=1,
        )
        assert len(result.paths_sample) == 10
        for path in result.paths_sample:
            assert path[0] == pytest.approx(100_000)

    def test_same_seed_gives_identical_result(self):
        r1, f1 = run_monte_carlo(
            amount=100_000, horizon_years=3,
            allocation=_alloc(gold=30, usd=25, bist100=20, bond=15, deposit=10),
            n_simulations=200, seed=7,
        )
        r2, f2 = run_monte_carlo(
            amount=100_000, horizon_years=3,
            allocation=_alloc(gold=30, usd=25, bist100=20, bond=15, deposit=10),
            n_simulations=200, seed=7,
        )
        assert np.array_equal(f1, f2)
        assert r1.expected == r2.expected

    def test_no_seed_gives_different_results(self):
        _, f1 = run_monte_carlo(
            amount=100_000, horizon_years=3,
            allocation=_alloc(gold=30, usd=25, bist100=20, bond=15, deposit=10),
            n_simulations=200,
        )
        _, f2 = run_monte_carlo(
            amount=100_000, horizon_years=3,
            allocation=_alloc(gold=30, usd=25, bist100=20, bond=15, deposit=10),
            n_simulations=200,
        )
        assert not np.array_equal(f1, f2)

    def test_asset_params_override_changes_outcome(self):
        allocation = _alloc(gold=0, usd=100, bist100=0, bond=0, deposit=0)
        baseline, _ = run_monte_carlo(amount=100_000, horizon_years=5, allocation=allocation, n_simulations=300, seed=3)
        shocked_params = apply_shocks_to_asset_params({"usd_shock": 1.0})
        shocked, _ = run_monte_carlo(
            amount=100_000, horizon_years=5, allocation=allocation,
            n_simulations=300, seed=3, asset_params=shocked_params,
        )
        assert shocked.expected > baseline.expected


class TestComputeInflationAdjustedMetrics:
    def test_all_scenarios_beat_inflation_gives_ips_100(self):
        final_values = np.full(1000, 200_000.0)  # her senaryo aynı, yüksek değer
        ips, real_ret = compute_inflation_adjusted_metrics(
            final_values, amount=100_000, inflation_rate=0.10, horizon_years=1
        )
        assert ips == 100.0
        assert real_ret > 0

    def test_all_scenarios_lose_to_inflation_gives_ips_0(self):
        final_values = np.full(1000, 100_000.0)  # nominal sabit kaldı
        ips, real_ret = compute_inflation_adjusted_metrics(
            final_values, amount=100_000, inflation_rate=0.50, horizon_years=1
        )
        assert ips == 0.0
        assert real_ret < 0

    def test_direction_consistency_is_guaranteed(self):
        """IPS > 50 <=> real_return_pct > 0 — matematiksel garanti, rastgele
        girdilerle bile bozulmamalı (bkz. test_ips_consistency.py)."""
        rng = np.random.default_rng(0)
        for _ in range(20):
            final_values = 100_000 * rng.lognormal(mean=0.0, sigma=0.5, size=1000)
            ips, real_ret = compute_inflation_adjusted_metrics(
                final_values, amount=100_000, inflation_rate=0.30, horizon_years=2
            )
            if ips > 50:
                assert real_ret > 0
            elif ips < 50:
                assert real_ret < 0


class TestComputeSharpe:
    def test_zero_volatility_returns_zero(self):
        assert compute_sharpe(ret=0.40, vol=0.0) == 0.0

    def test_positive_excess_return_gives_positive_sharpe(self):
        assert compute_sharpe(ret=0.50, vol=0.10, risk_free=0.28) > 0

    def test_negative_excess_return_gives_negative_sharpe(self):
        assert compute_sharpe(ret=0.10, vol=0.10, risk_free=0.28) < 0
