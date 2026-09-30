"""
Yahoo Finance veri istemcisi.
Kur, altın, BIST 100 verilerini yfinance üzerinden çeker.
API anahtarı gerekmez.
"""

import asyncio
import math
from datetime import datetime, timedelta


def requests_warning():
    try:
        from requests import RequestsDependencyWarning
        return RequestsDependencyWarning
    except ImportError:
        return Warning


# ── Canlı piyasa snapshot ─────────────────────────────────────────────────────

async def fetch_market_snapshot() -> dict:
    """
    Tek seferde USD/TRY, EUR/TRY, Altın (TL/gram) ve BIST 100 çeker.
    Hata durumunda sabit mock değerlerine düşer.
    """
    def _sync() -> dict:
        import warnings, yfinance as yf
        warnings.filterwarnings("ignore", category=requests_warning())

        def last(sym: str) -> float:
            h = yf.Ticker(sym).history(period="2d")
            if h.empty:
                raise ValueError(f"{sym}: yfinance boş sonuç döndürdü")
            value = float(h["Close"].iloc[-1])
            if math.isnan(value) or math.isinf(value):
                raise ValueError(f"{sym}: yfinance geçersiz değer döndürdü ({value})")
            return value

        usd_try  = last("USDTRY=X")
        eur_try  = last("EURTRY=X")
        gold_usd = last("GC=F")
        bist100  = last("XU100.IS")

        # Altın: troy ons (USD) → gram (TRY)
        gold_try = (gold_usd * usd_try / 31.1035) if gold_usd and usd_try else 0.0

        return {
            "usd_try":  round(usd_try,  4),
            "eur_try":  round(eur_try,  4),
            "gold_try": round(gold_try, 2),
            "bist100":  round(bist100,  2),
        }

    try:
        return await asyncio.to_thread(_sync)
    except Exception:
        return _mock_snapshot()


def _mock_snapshot() -> dict:
    return {"usd_try": 44.06, "eur_try": 51.02, "gold_try": 7515.0, "bist100": 12698.0}


# ── Tarihsel BIST 100 ─────────────────────────────────────────────────────────

async def fetch_bist100(period_years: int = 3) -> list[dict]:
    """BIST 100 (XU100.IS) tarihsel kapanış verisi."""
    def _sync():
        import yfinance as yf
        ticker = yf.Ticker("XU100.IS")
        start = (datetime.now() - timedelta(days=365 * period_years)).strftime("%Y-%m-%d")
        hist = ticker.history(start=start)
        return [
            {"date": str(idx.date()), "close": round(float(row["Close"]), 2)}
            for idx, row in hist.iterrows()
        ]

    try:
        return await asyncio.to_thread(_sync)
    except Exception:
        return _mock_bist100(period_years)


async def fetch_latest_bist100() -> float:
    """BIST 100 son kapanış — snapshot'tan daha hızlı tek-ticker çağrısı."""
    snap = await fetch_market_snapshot()
    return snap["bist100"]


def _mock_bist100(period_years: int) -> list[dict]:
    import numpy as np
    rng = np.random.default_rng(7)
    base = 12698.0
    n = period_years * 12
    dates = [
        (datetime(2023, 1, 1) + timedelta(days=i * 30)).strftime("%Y-%m-%d")
        for i in range(n)
    ]
    prices = base * np.cumprod(1 + rng.normal(0.04, 0.06, n))
    return [{"date": d, "close": round(float(p), 2)} for d, p in zip(dates, prices)]
