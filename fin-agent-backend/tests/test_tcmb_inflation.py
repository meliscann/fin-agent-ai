"""
get_current_annual_inflation()'ın testleri: YoY hesaplama, önbellek ve
fallback davranışı. fetch_series mock'lanır — gerçek EVDS çağrısı yapılmaz.
"""

import pytest

from app.core.data import tcmb as tcmb_module
from app.config import settings


@pytest.fixture(autouse=True)
def reset_inflation_cache():
    """Her testten önce/sonra modül-seviyesi önbelleği temizler — testler
    birbirinden bağımsız kalsın diye (global state, testler arası sızabilir)."""
    tcmb_module._inflation_cache["value"] = None
    tcmb_module._inflation_cache["fetched_at"] = None
    yield
    tcmb_module._inflation_cache["value"] = None
    tcmb_module._inflation_cache["fetched_at"] = None


def _series(*values: float) -> list[dict]:
    """(tarih önemsiz) sadece 'value' alanları sırayla artan bir seri üretir."""
    return [{"date": f"2020-{i+1}", "value": v} for i, v in enumerate(values)]


@pytest.mark.asyncio
async def test_computes_yoy_change_from_index(monkeypatch):
    # 13 aylık seri: ilk (12 ay önce) = 100, son = 130 -> %30 YoY
    series = _series(*([100.0] * 12 + [130.0]))

    async def fake_fetch_series(series_key, start_date=None, end_date=None):
        return series

    monkeypatch.setattr(tcmb_module, "fetch_series", fake_fetch_series)

    result = await tcmb_module.get_current_annual_inflation()
    assert result == pytest.approx(0.30)


@pytest.mark.asyncio
async def test_falls_back_when_fetch_raises(monkeypatch):
    async def fake_fetch_series(series_key, start_date=None, end_date=None):
        raise ConnectionError("EVDS erişilemedi")

    monkeypatch.setattr(tcmb_module, "fetch_series", fake_fetch_series)

    result = await tcmb_module.get_current_annual_inflation()
    assert result == settings.inflation_rate


@pytest.mark.asyncio
async def test_falls_back_when_insufficient_history(monkeypatch):
    async def fake_fetch_series(series_key, start_date=None, end_date=None):
        return _series(100.0, 105.0, 110.0)  # sadece 3 kayıt, 13 gerekiyor

    monkeypatch.setattr(tcmb_module, "fetch_series", fake_fetch_series)

    result = await tcmb_module.get_current_annual_inflation()
    assert result == settings.inflation_rate


@pytest.mark.asyncio
async def test_second_call_within_ttl_uses_cache_not_network(monkeypatch):
    call_count = {"n": 0}

    async def fake_fetch_series(series_key, start_date=None, end_date=None):
        call_count["n"] += 1
        return _series(*([100.0] * 12 + [120.0]))

    monkeypatch.setattr(tcmb_module, "fetch_series", fake_fetch_series)

    first = await tcmb_module.get_current_annual_inflation()
    second = await tcmb_module.get_current_annual_inflation()

    assert first == second == pytest.approx(0.20)
    assert call_count["n"] == 1  # ikinci çağrı önbellekten geldi, ağa gitmedi


@pytest.mark.asyncio
async def test_cache_expires_after_ttl(monkeypatch):
    from datetime import datetime, timedelta

    call_count = {"n": 0}

    async def fake_fetch_series(series_key, start_date=None, end_date=None):
        call_count["n"] += 1
        return _series(*([100.0] * 12 + [120.0]))

    monkeypatch.setattr(tcmb_module, "fetch_series", fake_fetch_series)

    await tcmb_module.get_current_annual_inflation()
    assert call_count["n"] == 1

    # Önbellek zaman damgasını TTL'nin dışına manuel olarak it
    tcmb_module._inflation_cache["fetched_at"] = datetime.now() - timedelta(hours=2)

    await tcmb_module.get_current_annual_inflation()
    assert call_count["n"] == 2  # süre dolduğu için tekrar çekti
