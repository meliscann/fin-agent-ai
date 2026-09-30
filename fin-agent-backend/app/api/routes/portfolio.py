"""
Portföy analiz endpoint'leri.

POST /api/portfolio/analyze      → Tam Monte Carlo analizi
POST /api/portfolio/compare      → İki portföy karşılaştırma
POST /api/portfolio/scenario     → What-if senaryo motoru
GET  /api/portfolio/market-data  → Güncel piyasa verisi
GET  /api/portfolio/config       → Risk preset'leri + IPS eşikleri (tek kaynak)
"""

from datetime import datetime
from fastapi import APIRouter, HTTPException

from app.models.portfolio import (
    PortfolioRequest,
    CompareRequest,
    ScenarioRequest,
    AnalysisResponse,
    CompareResponse,
    ScenarioResponse,
    MarketData,
    PortfolioConfigResponse,
)
from app.core.analysis.monte_carlo import (
    build_portfolio_metrics,
    apply_shocks_to_asset_params,
    IPS_THRESHOLDS,
)
from app.core.data.yahoo import fetch_market_snapshot
from app.core.data.tcmb import get_current_policy_rate, get_current_annual_inflation
from app.core.llm import llm
from app.agents import RISK_PRESETS

router = APIRouter(prefix="/portfolio", tags=["portfolio"])

# What-if senaryolarında base ve shocked simülasyonlarının AYNI rastgele
# örneklemi ("common random numbers") kullanması için sabit tohum — böylece
# iki sonuç arasındaki tek fark uygulanan şok olur, örnekleme gürültüsü
# karışmaz. /analyze gibi tek seferlik çağrılar bunu kullanmaz (seed=None).
SCENARIO_SEED = 42


@router.post("/analyze", response_model=AnalysisResponse)
async def analyze_portfolio(request: PortfolioRequest):
    """
    Portföy analizi — Monte Carlo + AI yorumu.

    Örnek istek:
    {
      "amount": 500000,
      "horizon_years": 3,
      "risk_profile": "dengeli",
      "allocation": {"gold": 30, "usd": 25, "bist100": 20, "bond": 15, "deposit": 10}
    }
    """
    inflation_rate = await get_current_annual_inflation()
    try:
        metrics = build_portfolio_metrics(request, inflation_rate)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Analiz hatası: {e}")

    # AI yorumu
    alloc = request.allocation.model_dump()
    ai_prompt = f"""Portföy analizi:
Dağılım: {alloc}
Tutar: {request.amount:,.0f} TL | Vade: {request.horizon_years} yıl | Profil: {request.risk_profile}
Beklenen değer: {metrics.expected_value:,.0f} TL
Reel getiri: {metrics.real_return_pct:.1f}%
Enflasyon koruma skoru: {metrics.inflation_protection_score}/100
Sharpe: {metrics.sharpe_ratio}

Bu portföyü 3-4 cümleyle değerlendir. Güçlü yönler, riskler, 1-2 somut öneri. Türkçe, sade."""

    ai_insight = await llm.chat(ai_prompt, temperature=0.4)

    return AnalysisResponse(
        request=request,
        metrics=metrics,
        ai_insight=ai_insight,
        inflation_rate_used=inflation_rate,
        computed_at=datetime.now().isoformat(),
    )


@router.post("/compare", response_model=CompareResponse)
async def compare_portfolios(request: CompareRequest):
    """İki portföyü yan yana karşılaştırır."""
    inflation_rate = await get_current_annual_inflation()
    try:
        metrics_a = build_portfolio_metrics(request.portfolio_a, inflation_rate)
        metrics_b = build_portfolio_metrics(request.portfolio_b, inflation_rate)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Karşılaştırma hatası: {e}")

    winner_rr = request.label_a if metrics_a.real_return_pct > metrics_b.real_return_pct else request.label_b
    winner_ips = request.label_a if metrics_a.inflation_protection_score > metrics_b.inflation_protection_score else request.label_b

    compare_prompt = f"""{request.label_a}: reel getiri {metrics_a.real_return_pct:.1f}%, IPS {metrics_a.inflation_protection_score}/100, Sharpe {metrics_a.sharpe_ratio}
{request.label_b}: reel getiri {metrics_b.real_return_pct:.1f}%, IPS {metrics_b.inflation_protection_score}/100, Sharpe {metrics_b.sharpe_ratio}

Hangisi daha iyi ve neden? 2-3 cümle, Türkçe."""

    ai_comparison = await llm.chat(compare_prompt, temperature=0.4)

    return CompareResponse(
        label_a=request.label_a,
        label_b=request.label_b,
        metrics_a=metrics_a,
        metrics_b=metrics_b,
        winner_by_real_return=winner_rr,
        winner_by_ips=winner_ips,
        ai_comparison=ai_comparison,
    )


@router.post("/scenario", response_model=ScenarioResponse)
async def what_if_scenario(request: ScenarioRequest):
    """
    What-if senaryo motoru.

    Örnek şoklar:
    {"inflation_delta": 0.10, "usd_shock": 0.15, "policy_rate_delta": -0.05, "bist_shock": 0.15}
    """
    try:
        base_inflation = await get_current_annual_inflation()
        shocked_inflation = base_inflation + request.shocks.get("inflation_delta", 0)
        shocked_asset_params = apply_shocks_to_asset_params(request.shocks)

        # base ve shocked AYNI seed'i kullanır ki tek fark uygulanan şok olsun
        base_metrics = build_portfolio_metrics(request.base_portfolio, base_inflation, seed=SCENARIO_SEED)
        shocked_metrics = build_portfolio_metrics(
            request.base_portfolio, shocked_inflation,
            asset_params=shocked_asset_params, seed=SCENARIO_SEED,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Senaryo hatası: {e}")

    impact_prompt = f"""Makro şok senaryosu:
{request.shocks}
Baz reel getiri: {base_metrics.real_return_pct:.1f}% → Şok sonrası: {shocked_metrics.real_return_pct:.1f}%
Baz IPS: {base_metrics.inflation_protection_score}/100 → Şok sonrası: {shocked_metrics.inflation_protection_score}/100

Bu şokun portföye etkisini 2-3 cümleyle açıkla. Türkçe."""

    impact = await llm.chat(impact_prompt, temperature=0.3)

    return ScenarioResponse(
        base_metrics=base_metrics,
        shocked_metrics=shocked_metrics,
        impact_summary=impact,
        shocks_applied=request.shocks,
    )


@router.get("/config", response_model=PortfolioConfigResponse)
async def get_portfolio_config():
    """
    Risk preset'leri ve IPS eşikleri — frontend bunu sayfa açılışında çeker
    ki kendi kopyasını hardcode etmesin (bkz. PortfolioConfigResponse).
    """
    return PortfolioConfigResponse(
        risk_presets=RISK_PRESETS,
        ips_thresholds=IPS_THRESHOLDS,
    )


@router.get("/market-data", response_model=MarketData)
async def get_market_data():
    """Güncel piyasa verisi: kur, altın, BIST — Yahoo Finance canlı verisi."""
    try:
        snap = await fetch_market_snapshot()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Veri çekme hatası: {e}")

    inflation_annual = await get_current_annual_inflation()

    return MarketData(
        usd_try=snap.get("usd_try", 0),
        gold_try=snap.get("gold_try", 0),
        bist100=snap.get("bist100", 0),
        inflation_annual=inflation_annual,
        policy_rate=get_current_policy_rate(),
        fetched_at=datetime.now().isoformat(),
    )
