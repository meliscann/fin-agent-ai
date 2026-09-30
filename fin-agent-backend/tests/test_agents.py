"""
Ajanların (Analiz, Öneri, Uyarı, Rapor) testleri. LLM çağrıları mock'lanır —
gerçek API isteği/maliyeti yok, testler hızlı ve tekrarlanabilir kalır.
"""

import base64

import pytest

from app.models.portfolio import PortfolioRequest, AssetAllocation
from app.agents import (
    RISK_PRESETS,
    analysis_agent_run,
    recommendation_agent_run,
    alert_agent_run,
    report_agent_run,
)
from app.core.analysis.monte_carlo import IPS_THRESHOLDS
from app.core import llm as llm_module
from app.core.data import tcmb as tcmb_module

# Enflasyon artık EVDS'den canlı çekiliyor (bkz. _resolve_inflation_rate) —
# testler gerçek zamanlı enflasyona göre "iyi/kötü portföy" beklemek yerine
# context'e açıkça bir inflation_rate vererek deterministik kalır. Genel
# amaçlı sabit değer (context'te override edilmemiş durumlar için):
TEST_INFLATION = 0.30


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    """Tüm testlerde llm.chat'i sahte, hızlı bir yanıtla değiştirir."""
    async def fake_chat(user_message, system=None, temperature=0.3, max_tokens=1500):
        return "Sahte LLM yanıtı (test)."
    monkeypatch.setattr(llm_module.llm, "chat", fake_chat)
    yield


@pytest.fixture(autouse=True)
def mock_inflation(monkeypatch):
    """
    get_current_annual_inflation'ı sabit bir değerle değiştirir — context'te
    açıkça inflation_rate verilmeyen testler bile gerçek EVDS'ye gitmez,
    hızlı ve tekrarlanabilir kalır (bkz. TEST_INFLATION).
    """
    async def fake_inflation():
        return TEST_INFLATION
    monkeypatch.setattr(tcmb_module, "get_current_annual_inflation", fake_inflation)
    yield


def _portfolio(risk_profile="dengeli", **allocation) -> PortfolioRequest:
    alloc = allocation or {"gold": 30, "usd": 25, "bist100": 20, "bond": 15, "tufe_bond": 0, "deposit": 10}
    alloc.setdefault("tufe_bond", 0)
    return PortfolioRequest(
        amount=500_000, horizon_years=3, risk_profile=risk_profile,
        allocation=AssetAllocation(**alloc),
    )


class TestAnalysisAgent:
    @pytest.mark.asyncio
    async def test_missing_portfolio_returns_error(self):
        result = await analysis_agent_run("analiz", None)
        assert "error" in result

    @pytest.mark.asyncio
    async def test_returns_expected_shape(self):
        result = await analysis_agent_run("analiz", {"portfolio": _portfolio()})
        assert "monte_carlo" in result
        assert 0 <= result["inflation_protection_score"] <= 100
        assert "sharpe_ratio" in result
        assert "annualized_vol" in result

    @pytest.mark.asyncio
    async def test_maps_shared_metrics_fields_correctly(self, monkeypatch):
        # analysis_agent_run artık kendi hesabını yapmıyor, build_portfolio_metrics()'i
        # çağırıp sonucu dict'e döküyor (bkz. agents/__init__.py) — build_portfolio_metrics'i
        # sahte/bilinen bir sonuçla değiştirip eşlemenin doğru olduğunu doğrularız
        # (gerçek Monte Carlo rastgele olduğu için iki bağımsız çağrı birebir eşleşmez).
        import app.core.analysis.monte_carlo as mc_module
        from app.models.portfolio import PortfolioMetrics, MonteCarloResult

        fake_mc = MonteCarloResult(
            percentile_10=1, percentile_25=2, percentile_50=3, percentile_75=4,
            percentile_90=5, expected=6, worst=7, best=8, paths_sample=[],
        )
        fake_metrics = PortfolioMetrics(
            expected_value=6, nominal_return_pct=12.3, real_return_pct=4.5,
            inflation_protection_score=66.6, annualized_volatility=17.7,
            sharpe_ratio=0.42, max_drawdown_estimate=44.0, monte_carlo=fake_mc,
        )
        monkeypatch.setattr(mc_module, "build_portfolio_metrics", lambda *a, **k: fake_metrics)

        result = await analysis_agent_run("analiz", {"portfolio": _portfolio()})

        assert result["inflation_protection_score"] == 66.6
        assert result["sharpe_ratio"] == 0.42
        assert result["annualized_vol"] == 17.7
        assert result["nominal_return_pct"] == 12.3
        assert result["real_return_pct"] == 4.5


class TestRecommendationAgent:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("risk_profile", ["temkinli", "dengeli", "buyume"])
    async def test_returns_correct_preset_for_risk_profile(self, risk_profile):
        result = await recommendation_agent_run("öner", {"risk_profile": risk_profile})
        assert result["suggested_allocation"] == RISK_PRESETS[risk_profile]

    @pytest.mark.asyncio
    async def test_defaults_to_dengeli_without_context(self):
        result = await recommendation_agent_run("öner", None)
        assert result["risk_profile"] == "dengeli"
        assert result["suggested_allocation"] == RISK_PRESETS["dengeli"]

    @pytest.mark.asyncio
    async def test_includes_projection_when_portfolio_given(self):
        result = await recommendation_agent_run("öner", {"portfolio": _portfolio(risk_profile="buyume")})
        assert result["risk_profile"] == "buyume"
        assert result["projected_metrics"] is not None
        assert "inflation_protection_score" in result["projected_metrics"]
        assert 0 <= result["projected_metrics"]["inflation_protection_score"] <= 100

    @pytest.mark.asyncio
    async def test_no_projection_without_amount(self):
        result = await recommendation_agent_run("öner", {"risk_profile": "temkinli"})
        assert result["projected_metrics"] is None

    @pytest.mark.asyncio
    async def test_suggested_allocation_sums_to_100(self):
        for risk_profile in RISK_PRESETS:
            result = await recommendation_agent_run("öner", {"risk_profile": risk_profile})
            assert sum(result["suggested_allocation"].values()) == 100


class TestAlertAgent:
    @pytest.mark.asyncio
    async def test_poor_portfolio_triggers_alerts(self):
        # Herhangi bir portföyün "kötü" sayılması güncel/canlı enflasyona
        # göre değişir (bkz. TEST_INFLATION notu) — bu yüzden burada yüksek
        # bir enflasyon açıkça veriliyor, böylece test gerçek piyasa
        # koşullarından bağımsız, deterministik kalıyor.
        poor = _portfolio(risk_profile="temkinli", gold=0, usd=0, bist100=0, bond=0, deposit=100)
        result = await alert_agent_run("uyarılar", {"portfolio": poor, "inflation_rate": 0.90})
        codes = {a["code"] for a in result["alerts"]}
        assert "low_ips" in codes
        assert "negative_real_return" in codes

    @pytest.mark.asyncio
    async def test_strong_portfolio_triggers_no_portfolio_alerts(self):
        # ips_floor artık gerçekçi kalibre edilmiş (75, bkz. IPS_THRESHOLDS) —
        # TEST_INFLATION (%30) altında "buyume" preset'i bu eşiği net geçmez
        # (75/92 bandı sınırında kalabilir). Testin amacı "güçlü bir portföy
        # uyarı tetiklemez" ilişkisini doğrulamak, eşiğin tam sınırını değil —
        # bu yüzden burada açıkça düşük bir enflasyon veriyoruz (poor testin
        # yüksek enflasyon verdiği mantığın simetriği).
        strong = _portfolio(risk_profile="buyume", **RISK_PRESETS["buyume"])
        result = await alert_agent_run("uyarılar", {"portfolio": strong, "inflation_rate": 0.05})
        codes = {a["code"] for a in result["alerts"]}
        assert "low_ips" not in codes
        assert "negative_real_return" not in codes

    @pytest.mark.asyncio
    async def test_default_ips_floor_catches_moderately_weak_portfolio(self):
        # Regresyon testi: bu turda ips_floor varsayılanı (25.0 -> 75.0,
        # bkz. IPS_THRESHOLDS) düzeltildi çünkü eski 25 değeri, IPS bantları
        # 92/75'e kalibre edildikten sonra unutulmuş bayat bir değerdi.
        # test_poor_portfolio_triggers_alerts bunu yakalayamazdı çünkü orada
        # kullanılan portföy o kadar aşırı kötü ki (100% mevduat, %90
        # enflasyon) IPS neredeyse 0 çıkıyor — hem eski 25 hem yeni 75 eşiği
        # bunu yakalardı, ikisini ayırt etmiyordu. Burada IPS'i bilerek
        # 25 ile 75 arasında (deneysel olarak ~50-54, bkz. commit mesajı)
        # bir "dengeli" portföy/enflasyon kombinasyonuyla tutuyoruz — thresholds
        # HİÇ verilmiyor (context'te "thresholds" yok), böylece gerçekten
        # varsayılan test ediliyor. Eski koddaki 25 eşiğiyle bu test
        # low_ips'i YAKALAYAMAZ ve kırmızı olurdu.
        moderate = _portfolio(risk_profile="dengeli", **RISK_PRESETS["dengeli"])
        result = await alert_agent_run("uyarılar", {"portfolio": moderate, "inflation_rate": 0.38})
        codes = {a["code"] for a in result["alerts"]}
        assert "low_ips" in codes

        # Varsayılanın gerçekten IPS_THRESHOLDS["weak"]'e bağlı olduğunu (başka
        # bir sabite değil) mesaj içeriğinden de doğrula.
        low_ips_alert = next(a for a in result["alerts"] if a["code"] == "low_ips")
        assert f"eşik: {IPS_THRESHOLDS['weak']}" in low_ips_alert["message"]

    @pytest.mark.asyncio
    async def test_custom_ips_floor_is_respected(self):
        poor = _portfolio(risk_profile="temkinli", gold=0, usd=0, bist100=0, bond=0, deposit=100)
        # Eşiği 0'a çekersek (imkansız bir eşik) low_ips tetiklenmemeli
        result = await alert_agent_run("uyarılar", {"portfolio": poor, "thresholds": {"ips_floor": -1}})
        codes = {a["code"] for a in result["alerts"]}
        assert "low_ips" not in codes

    @pytest.mark.asyncio
    async def test_no_portfolio_still_returns_valid_response(self):
        result = await alert_agent_run("uyarılar", None)
        assert "alerts" in result
        assert "checked_at" in result


class TestReportAgent:
    @pytest.mark.asyncio
    async def test_returns_valid_pdf_bytes(self):
        result = await report_agent_run("rapor", {"portfolio": _portfolio()})
        pdf_bytes = base64.b64decode(result["pdf_base64"])
        assert pdf_bytes[:5] == b"%PDF-"
        assert len(pdf_bytes) > 500  # boş/bozuk bir PDF olmadığını doğrula

    @pytest.mark.asyncio
    async def test_filename_has_pdf_extension(self):
        result = await report_agent_run("rapor", {"portfolio": _portfolio()})
        assert result["filename"].endswith(".pdf")

    @pytest.mark.asyncio
    async def test_missing_portfolio_returns_error(self):
        result = await report_agent_run("rapor", None)
        assert "error" in result
