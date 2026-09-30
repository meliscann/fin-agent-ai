from pydantic import BaseModel, Field, field_validator
from typing import Literal


# ── İstek modelleri ───────────────────────────────────────────────────────────

class AssetAllocation(BaseModel):
    """Varlık dağılımı. Toplamı 100 olmalı."""
    gold: float = Field(ge=0, le=100, description="Gram altın yüzdesi")
    usd: float = Field(ge=0, le=100, description="USD/TRY yüzdesi")
    bist100: float = Field(ge=0, le=100, description="BIST 100 yüzdesi")
    bond: float = Field(ge=0, le=100, description="Tahvil/TL yüzdesi")
    tufe_bond: float = Field(ge=0, le=100, description="TÜFE'ye endeksli tahvil yüzdesi")
    deposit: float = Field(ge=0, le=100, description="Mevduat yüzdesi")

    @field_validator("deposit")
    @classmethod
    def total_must_be_100(cls, v, info):
        values = info.data
        total = sum([
            values.get("gold", 0),
            values.get("usd", 0),
            values.get("bist100", 0),
            values.get("bond", 0),
            values.get("tufe_bond", 0),
            v,
        ])
        if abs(total - 100) > 0.01:
            raise ValueError(f"Toplam dağılım %100 olmalı, şu an: %{total:.1f}")
        return v


class PortfolioRequest(BaseModel):
    amount: float = Field(gt=0, description="Yatırım miktarı (TL)")
    horizon_years: Literal[1, 3, 5, 10] = Field(description="Zaman ufku (yıl)")
    risk_profile: Literal["temkinli", "dengeli", "buyume"] = "dengeli"
    allocation: AssetAllocation


class ScenarioRequest(BaseModel):
    """What-if senaryo motoru isteği."""
    base_portfolio: PortfolioRequest
    shocks: dict[str, float] = Field(
        description="Makro şoklar: {'inflation_delta': 0.10, 'usd_shock': 0.20, 'policy_rate_delta': -0.05, 'bist_shock': 0.15}"
    )


class ChatRequest(BaseModel):
    """Ajan diyaloğu isteği."""
    message: str = Field(min_length=1, max_length=2000)
    history: list[dict] = Field(default=[], description="Önceki mesajlar")
    portfolio_context: PortfolioRequest | None = None


class CompareRequest(BaseModel):
    """Portföy karşılaştırma isteği."""
    portfolio_a: PortfolioRequest
    portfolio_b: PortfolioRequest
    label_a: str = "Portföy A"
    label_b: str = "Portföy B"


# ── Yanıt modelleri ───────────────────────────────────────────────────────────

class MonteCarloResult(BaseModel):
    percentile_10: float
    percentile_25: float
    percentile_50: float
    percentile_75: float
    percentile_90: float
    expected: float
    worst: float
    best: float
    paths_sample: list[list[float]] = Field(default=[], description="Grafik için 50 örnek yol")


class PortfolioMetrics(BaseModel):
    expected_value: float
    nominal_return_pct: float
    real_return_pct: float
    inflation_protection_score: float = Field(ge=0, le=100)
    annualized_volatility: float
    sharpe_ratio: float
    max_drawdown_estimate: float
    monte_carlo: MonteCarloResult


class AnalysisResponse(BaseModel):
    request: PortfolioRequest
    metrics: PortfolioMetrics
    ai_insight: str = ""
    inflation_rate_used: float
    computed_at: str


class MarketData(BaseModel):
    """Anlık piyasa verisi."""
    usd_try: float
    gold_try: float
    bist100: float
    inflation_annual: float
    policy_rate: float
    fetched_at: str


class ScenarioResponse(BaseModel):
    base_metrics: PortfolioMetrics
    shocked_metrics: PortfolioMetrics
    impact_summary: str
    shocks_applied: dict[str, float]


class CompareResponse(BaseModel):
    label_a: str
    label_b: str
    metrics_a: PortfolioMetrics
    metrics_b: PortfolioMetrics
    winner_by_real_return: str
    winner_by_ips: str
    ai_comparison: str


class PortfolioConfigResponse(BaseModel):
    """
    Risk preset'leri ve IPS eşikleri için TEK doğru kaynak — frontend bunu
    sayfa açılışında çeker, kendi kopyasını hardcode etmez (bkz.
    app/agents/__init__.py: RISK_PRESETS, app/core/analysis/monte_carlo.py:
    IPS_THRESHOLDS).
    """
    risk_presets: dict[Literal["temkinli", "dengeli", "buyume"], AssetAllocation]
    ips_thresholds: dict[Literal["weak", "strong"], float]
