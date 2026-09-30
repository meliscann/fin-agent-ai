"""
Route katmanı için HTTP entegrasyon testleri.

Alttaki saf fonksiyonlar (Monte Carlo, ajanlar) ayrı dosyalarda test
ediliyor — buradaki amaç route wiring'inin (response_model, request body
doğrulama, JSON şekli) doğru olduğunu doğrulamak. TestClient(app) gerçek
FastAPI uygulamasını ayağa kaldırdığı için main.py'nin lifespan hook'unu
(arka planda TCMB PPK taraması tetikler) sahte bir no-op ile değiştiriyoruz
— testler ağa gitmemeli, dosya sistemindeki `.policy_rate_last_check`
cooldown dosyasının varlığına bağımlı kalmamalı.
"""

import pytest
from fastapi.testclient import TestClient

from app.core import llm as llm_module
from app.core.data import tcmb as tcmb_module

TEST_INFLATION = 0.30

PORTFOLIO = {
    "amount": 500_000,
    "horizon_years": 3,
    "risk_profile": "dengeli",
    "allocation": {"gold": 30, "usd": 25, "bist100": 20, "bond": 15, "tufe_bond": 0, "deposit": 10},
}


@pytest.fixture(autouse=True)
def mock_llm(monkeypatch):
    async def fake_chat(user_message, system=None, temperature=0.3, max_tokens=1500):
        return "Sahte LLM yanıtı (test)."
    monkeypatch.setattr(llm_module.llm, "chat", fake_chat)
    yield


@pytest.fixture(autouse=True)
def mock_inflation(monkeypatch):
    async def fake_inflation():
        return TEST_INFLATION
    monkeypatch.setattr(tcmb_module, "get_current_annual_inflation", fake_inflation)
    yield


@pytest.fixture
def client(monkeypatch):
    import app.main as main_module

    async def noop_policy_check():
        return None
    # Lifespan hook'un arka plan TCMB taramasını devre dışı bırak — testler
    # `.policy_rate_last_check` dosyasının cooldown durumuna bağımlı olmasın.
    monkeypatch.setattr(main_module, "_check_policy_rate_updates", noop_policy_check)

    with TestClient(main_module.app) as c:
        yield c


class TestAnalyzeEndpoint:
    def test_returns_200_with_expected_shape(self, client):
        res = client.post("/api/portfolio/analyze", json=PORTFOLIO)
        assert res.status_code == 200
        body = res.json()
        assert "metrics" in body
        assert 0 <= body["metrics"]["inflation_protection_score"] <= 100
        assert body["inflation_rate_used"] == TEST_INFLATION

    def test_allocation_not_summing_to_100_returns_422(self, client):
        bad = {**PORTFOLIO, "allocation": {**PORTFOLIO["allocation"], "gold": 999}}
        res = client.post("/api/portfolio/analyze", json=bad)
        assert res.status_code == 422


class TestScenarioEndpoint:
    def test_returns_base_and_shocked_metrics(self, client):
        res = client.post("/api/portfolio/scenario", json={
            "base_portfolio": PORTFOLIO,
            "shocks": {"usd_shock": 0.20},
        })
        assert res.status_code == 200
        body = res.json()
        assert "base_metrics" in body
        assert "shocked_metrics" in body
        assert body["shocks_applied"] == {"usd_shock": 0.20}

    def test_inflation_delta_shock_moves_tufe_bond_heavy_portfolio(self, client):
        # tufe_bond'un getirisi enflasyona dinamik bağlı (bkz. monte_carlo.py:
        # TUFE_BOND_REAL_SPREAD) — bu, "Enflasyon Kalkanı" şokunun (inflation_delta)
        # bu varlığı OTOMATİK etkilediğinin uçtan uca kanıtı: apply_shocks_to_asset_params
        # tufe_bond'a hiç dokunmuyor, ama beklenen değer yine de değişmeli çünkü
        # şoklu inflation_rate build_portfolio_metrics'e akıyor.
        tufe_bond_heavy = {
            **PORTFOLIO,
            "allocation": {"gold": 0, "usd": 0, "bist100": 0, "bond": 0, "tufe_bond": 100, "deposit": 0},
        }
        res = client.post("/api/portfolio/scenario", json={
            "base_portfolio": tufe_bond_heavy,
            "shocks": {"inflation_delta": 0.15},
        })
        assert res.status_code == 200
        body = res.json()
        assert body["shocked_metrics"]["expected_value"] > body["base_metrics"]["expected_value"]


class TestConfigEndpoint:
    def test_returns_presets_and_thresholds(self, client):
        res = client.get("/api/portfolio/config")
        assert res.status_code == 200
        body = res.json()
        assert set(body["risk_presets"].keys()) == {"temkinli", "dengeli", "buyume"}
        assert body["ips_thresholds"] == {"weak": 75.0, "strong": 92.0}


class TestOrchestrateEndpoint:
    def test_force_agents_runs_only_requested_agent(self, client):
        res = client.post("/api/agents/orchestrate", json={
            "message": "uyarıları kontrol et",
            "portfolio": PORTFOLIO,
            "run_agents": ["alert"],
        })
        assert res.status_code == 200
        body = res.json()
        assert list(body["agent_results"].keys()) == ["alert"]
        assert "alerts" in body["agent_results"]["alert"]

    def test_thresholds_are_forwarded_to_alert_agent(self, client):
        res = client.post("/api/agents/orchestrate", json={
            "message": "uyarıları kontrol et",
            "portfolio": PORTFOLIO,
            "run_agents": ["alert"],
            "thresholds": {"ips_floor": -1},
        })
        assert res.status_code == 200
        codes = {a["code"] for a in res.json()["agent_results"]["alert"]["alerts"]}
        assert "low_ips" not in codes
