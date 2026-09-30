"""
Veri endpoint'leri.

GET /api/data/historical/{series}  → Tarihsel zaman serisi
GET /api/data/bist100              → BIST 100 tarihsel veri
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Literal

from app.core.data.tcmb import fetch_series, SERIES
from app.core.data.yahoo import fetch_bist100

router = APIRouter(prefix="/data", tags=["data"])


@router.get("/historical/{series_key}")
async def get_historical(
    series_key: Literal["usd_try", "eur_try", "gold_try", "cpi"],
    years: int = Query(default=3, ge=1, le=10),
):
    """
    TCMB EVDS tarihsel veri.
    series_key: usd_try | eur_try | gold_try | cpi
    """
    if series_key not in SERIES:
        raise HTTPException(status_code=400, detail=f"Geçersiz seri: {series_key}")

    try:
        data = await fetch_series(series_key)
        return {"series": series_key, "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"EVDS hatası: {e}")


@router.get("/bist100")
async def get_bist100(years: int = Query(default=3, ge=1, le=10)):
    """BIST 100 tarihsel kapanış fiyatları."""
    try:
        data = await fetch_bist100(period_years=years)
        return {"series": "bist100", "data": data, "count": len(data)}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Yahoo Finance hatası: {e}")
