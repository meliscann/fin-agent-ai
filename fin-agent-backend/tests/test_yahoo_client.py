"""
yahoo.py istemcisinin dayanıklılık testleri — yfinance'i mock'layarak,
gerçek ağ çağrısı yapmadan. Bu oturumda bulunan iki gerçek hatayı
(sessiz sıfır dönme, NaN'ın JSON'u çökertmesi) regresyona karşı korur.
"""

from unittest.mock import MagicMock

import pandas as pd
import pytest

from app.core.data import yahoo


def _fake_history(close_value):
    """yf.Ticker(...).history(...)'nin döneceği sahte DataFrame."""
    if close_value is None:
        return pd.DataFrame()
    return pd.DataFrame({"Close": [close_value, close_value]})


class _FakeTicker:
    def __init__(self, close_by_symbol: dict):
        self._close_by_symbol = close_by_symbol

    def __call__(self, symbol):
        self._current_symbol = symbol
        return self

    def history(self, period="2d"):
        return _fake_history(self._close_by_symbol.get(self._current_symbol))


@pytest.mark.asyncio
async def test_all_symbols_healthy_returns_real_values(monkeypatch):
    fake = _FakeTicker({
        "USDTRY=X": 48.0, "EURTRY=X": 55.0, "GC=F": 4400.0, "XU100.IS": 14000.0,
    })
    monkeypatch.setattr("yfinance.Ticker", fake)

    snap = await yahoo.fetch_market_snapshot()

    assert snap["usd_try"] == pytest.approx(48.0)
    assert snap["bist100"] == pytest.approx(14000.0)
    assert snap["gold_try"] > 0  # ons -> gram çevrimi yapılmış olmalı


@pytest.mark.asyncio
async def test_nan_close_falls_back_to_mock_not_zero(monkeypatch):
    """Bu oturumda bulunan gerçek hata: GC=F NaN dönünce tüm yanıt (JSON'a
    çevrilemediği için) çöküyordu. Artık mock veriye düşmeli, NaN veya 0
    döndürmemeli."""
    fake = _FakeTicker({
        "USDTRY=X": 48.0, "EURTRY=X": 55.0, "GC=F": float("nan"), "XU100.IS": 14000.0,
    })
    monkeypatch.setattr("yfinance.Ticker", fake)

    snap = await yahoo.fetch_market_snapshot()

    assert snap == yahoo._mock_snapshot()
    for value in snap.values():
        assert value == value  # NaN != NaN olduğu için bu, NaN olmadığını kanıtlar


@pytest.mark.asyncio
async def test_empty_history_falls_back_to_mock(monkeypatch):
    fake = _FakeTicker({
        "USDTRY=X": 48.0, "EURTRY=X": 55.0, "GC=F": 4400.0, "XU100.IS": None,
    })
    monkeypatch.setattr("yfinance.Ticker", fake)

    snap = await yahoo.fetch_market_snapshot()

    assert snap == yahoo._mock_snapshot()


@pytest.mark.asyncio
async def test_infinite_value_falls_back_to_mock(monkeypatch):
    fake = _FakeTicker({
        "USDTRY=X": float("inf"), "EURTRY=X": 55.0, "GC=F": 4400.0, "XU100.IS": 14000.0,
    })
    monkeypatch.setattr("yfinance.Ticker", fake)

    snap = await yahoo.fetch_market_snapshot()

    assert snap == yahoo._mock_snapshot()
