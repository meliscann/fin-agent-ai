"""
IPS (Enflasyon Koruma Skoru) ve real_return_pct'in iç tutarlılığını doğrulayan
regresyon testi.

Bağlam: Eski IPS formülü (`compute_inflation_protection_score`) her varlığı
enflasyona karşı AYRI AYRI eşik testinden geçirip ağırlıklı topluyordu; reel
getiri ise harmanlanmış TEK bir getiriyi enflasyonla karşılaştırıyordu. Bu iki
farklı yöntem, aynı portföy için birbirine zıt sonuç verebiliyordu (örn.
IPS=78 "Güçlü koruma" derken real_return_pct=-%10,5 — ips.md'de belgelenmiştir).

Yeni formülde ikisi de AYNI Monte Carlo simülasyonundan (`final_values`)
türetiliyor (bkz. `compute_inflation_adjusted_metrics`), bu yüzden şu ilişki
matematiksel olarak garantidir:
    IPS > 50  ⟺  medyan(real_value) >= amount  ⟺  real_return_pct >= 0

Bu test, formül gelecekte tekrar birbirinden bağımsız iki hesaba ayrılırsa
(regresyon) bunu hemen yakalasın diye var.
"""

import pytest

from app.models.portfolio import PortfolioRequest, AssetAllocation
from app.core.analysis.monte_carlo import build_portfolio_metrics


def _request(risk_profile: str = "dengeli", horizon_years: int = 3, **allocation) -> PortfolioRequest:
    allocation.setdefault("tufe_bond", 0)
    return PortfolioRequest(
        amount=500_000,
        horizon_years=horizon_years,
        risk_profile=risk_profile,
        allocation=AssetAllocation(**allocation),
    )


# Geniş bir portföy yelpazesi: tekil varlıklar, karma dağılımlar, farklı risk
# profilleri/ufuklar — hangisi IPS>50 hangisi IPS<50 tarafına düşerse düşsün,
# asıl test edilen şey ikisinin AYNI YÖNÜ göstermesi.
ALLOCATIONS = [
    dict(gold=0, usd=25, bist100=50, bond=15, deposit=10),   # ips.md'deki orijinal örnek
    dict(gold=0, usd=0, bist100=0, bond=0, deposit=100),      # tamamen mevduat
    dict(gold=100, usd=0, bist100=0, bond=0, deposit=0),      # tamamen altın
    dict(gold=0, usd=0, bist100=100, bond=0, deposit=0),      # tamamen BIST100
    dict(gold=20, usd=20, bist100=20, bond=20, deposit=20),   # eşit dağılım
    dict(gold=0, usd=0, bist100=0, bond=100, deposit=0),      # tamamen tahvil
]


@pytest.mark.parametrize("allocation", ALLOCATIONS)
@pytest.mark.parametrize("risk_profile", ["temkinli", "dengeli", "buyume"])
def test_ips_and_real_return_agree_on_direction(allocation, risk_profile):
    request = _request(risk_profile=risk_profile, **allocation)
    metrics = build_portfolio_metrics(request, inflation_rate=0.48)

    if metrics.inflation_protection_score > 50:
        assert metrics.real_return_pct > 0, (
            f"Tutarsızlık: IPS={metrics.inflation_protection_score} (>50) ama "
            f"real_return_pct={metrics.real_return_pct} (<=0) — allocation={allocation}, "
            f"risk_profile={risk_profile}"
        )
    elif metrics.inflation_protection_score < 50:
        assert metrics.real_return_pct < 0, (
            f"Tutarsızlık: IPS={metrics.inflation_protection_score} (<50) ama "
            f"real_return_pct={metrics.real_return_pct} (>=0) — allocation={allocation}, "
            f"risk_profile={risk_profile}"
        )
    # IPS tam 50.0 ise (nadir bir sınır durumu) yön testi atlanır.


def test_original_screenshot_example_no_longer_contradicts():
    """ips.md'de belgelenen orijinal çelişki örneği: IPS=78 "Güçlü koruma"
    derken real_return_pct=-%10,5 çıkıyordu. Artık ikisi aynı yönü göstermeli."""
    request = _request(
        risk_profile="dengeli", horizon_years=3,
        gold=0, usd=25, bist100=50, bond=15, deposit=10,
    )
    metrics = build_portfolio_metrics(request, inflation_rate=0.48)

    is_ips_positive = metrics.inflation_protection_score > 50
    is_real_return_positive = metrics.real_return_pct > 0
    assert is_ips_positive == is_real_return_positive, (
        f"IPS={metrics.inflation_protection_score}, "
        f"real_return_pct={metrics.real_return_pct} — yönleri hâlâ çelişiyor"
    )
