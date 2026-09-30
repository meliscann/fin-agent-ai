"""
TCMB EVDS API istemcisi.
Vaka çalışmasındaki veri çekme mantığını modüler hale getirir.
"""

import json
import httpx
from datetime import datetime, timedelta
from pathlib import Path
from app.config import settings

# TCMB EVDS'yi eski "evds2.../service/evds" adresi artık boş bir yönlendirme
# dönüyor; gerçek API evds3'e taşınmış (bkz. PyPI 'evds' paketi kaynağı).
EVDS_BASE = "https://evds3.tcmb.gov.tr/igmevdsms-dis/"

# Vaka çalışmasında kullanılan seri kodları (veri_analizi.ipynb ile aynı)
SERIES = {
    "usd_try":  "TP.DK.USD.A.YTL",
    "eur_try":  "TP.DK.EUR.A.YTL",
    "gold_try": "TP.MK.KUL.YTL",  # TP.ALTIN.TRY.G artık geçerli bir EVDS serisi değil
    "cpi":      "TP.FG.J0",
}

# Politika faizi geçmişi — tek doğru kaynak: policy_rate_history.json
# (veri_analizi.ipynb'deki faiz_verileri ile aynı dosyayı okur; PPK basın
# duyurularından derlenmiştir. Güncellemek için tcmb_ppk_scraper.py kullanın.)
POLICY_RATE_JSON_PATH = Path(__file__).parent / "policy_rate_history.json"


def _load_policy_rate_history() -> list[dict]:
    """JSON'daki {tarih: yüzde} sözlüğünü, ondalık orana çevrilmiş, tarihe göre
    sıralı bir listeye dönüştürür (örn. 37.00 -> 0.37)."""
    with open(POLICY_RATE_JSON_PATH, encoding="utf-8") as f:
        raw = json.load(f)
    return [
        {"date": date, "rate": rate / 100}
        for date, rate in sorted(raw.items())
    ]


POLICY_RATE_HISTORY = _load_policy_rate_history()


async def fetch_series(
    series_key: str,
    start_date: str | None = None,
    end_date: str | None = None,
    frequency: int | None = None,
) -> list[dict]:
    """
    EVDS'den tek seri çeker.
    series_key: SERIES dict'indeki anahtar (örn. "usd_try")
    frequency: verilmezse EVDS'nin serinin kendi doğal frekansını döner —
    usd_try/eur_try gibi günlük seriler için bu, 2024 öncesine gidememe
    gibi bir sınırlamaya yol açabiliyor (EVDS'nin kendi davranışı). `5`
    (iş günü) vermek veri_analizi.ipynb'nin kullandığı ve 2020'ye kadar
    çalıştığı doğrulanmış değer — bkz. insights.py'deki canlı vaka
    çalışması hesaplamaları.
    """
    if not settings.tcmb_api_key:
        return _mock_series(series_key)

    if not start_date:
        start_date = (datetime.now() - timedelta(days=365 * 3)).strftime("%d-%m-%Y")
    if not end_date:
        end_date = datetime.now().strftime("%d-%m-%Y")

    series_code = SERIES[series_key]
    freq_str = str(frequency) if frequency is not None else ""
    # EVDS'nin yeni (evds3) API'si kimliği "key" query param değil, "key" HTTP
    # header'ı olarak bekliyor — ve query string'i, garip biçimde, başında "?"
    # OLMADAN kabul ediyor (httpx'in normal params= mekanizması "?" eklediği
    # için burada 404 döner; bu yüzden URL elle, "?" olmadan kuruluyor).
    query = (
        f"series={series_code}&startDate={start_date}&endDate={end_date}"
        f"&type=json&formulas=&frequency={freq_str}&aggregationTypes="
    )

    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            EVDS_BASE + query,
            headers={"key": settings.tcmb_api_key},
        )
        resp.raise_for_status()
        data = resp.json()

    # EVDS, değer alanının adında "." yerine "_" kullanıyor (örn. TP.FG.J0 -> TP_FG_J0)
    value_field = series_code.replace(".", "_")
    items = data.get("items", [])
    return [
        {
            "date": item.get("Tarih", ""),
            "value": float(item.get(value_field, 0) or 0),
        }
        for item in items
        if item.get(value_field)
    ]


async def fetch_latest_values() -> dict:
    """
    Tüm temel göstergelerin güncel değerlerini çeker.
    API anahtarı yoksa mock veri döner (geliştirme modu).
    """
    if not settings.tcmb_api_key:
        return _mock_latest()

    results = {}
    for key in SERIES:
        try:
            series = await fetch_series(key)
            if series:
                results[key] = series[-1]["value"]
        except Exception:
            results[key] = None

    results["policy_rate"] = get_current_policy_rate()
    return results


def get_current_policy_rate() -> float:
    """Tarihsel tablodan güncel politika faizini döner."""
    today = datetime.now().strftime("%Y-%m-%d")
    rate = POLICY_RATE_HISTORY[0]["rate"]
    for entry in POLICY_RATE_HISTORY:
        if entry["date"] <= today:
            rate = entry["rate"]
    return rate


# get_current_annual_inflation() sonucu bellek-içi kısa süreliğine önbelleğe
# alınır — EVDS zaten ayda bir güncellendiği için 1 saatlik önbellek "canlı"
# olma özelliğini bozmaz, ama /analyze, /compare, /scenario gibi sık çağrılan
# endpoint'lerin her isteği EVDS'ye vurmasını (gecikme + gereksiz yük) önler.
_inflation_cache: dict = {"value": None, "fetched_at": None}
_INFLATION_CACHE_TTL = timedelta(hours=1)


async def get_current_annual_inflation() -> float:
    """
    TÜFE endeksinden (TP.FG.J0) yıllık enflasyonu hesaplar: son değerin 12 ay
    önceki değere göre yüzde değişimi (ondalık oran, örn. %31 -> 0.31).
    EVDS'ye ulaşılamazsa veya 12 aylık geçmiş yoksa settings.inflation_rate
    (.env'deki INFLATION_RATE, son çare varsayımı) döner — bu fonksiyonu
    kullanan hiçbir endpoint bu yüzden çökmez.
    """
    now = datetime.now()
    cached_value = _inflation_cache["value"]
    fetched_at = _inflation_cache["fetched_at"]
    if cached_value is not None and fetched_at is not None:
        if now - fetched_at < _INFLATION_CACHE_TTL:
            return cached_value

    try:
        # Geniş pencere: EVDS'nin en güncel verisi "bugün"den geride kalabilir
        # (yayın gecikmesi) — 12 aylık karşılaştırma için en son noktadan
        # itibaren en az 13 ay geriye gidebilmemiz garanti olmalı.
        start_date = (now - timedelta(days=365 * 3)).strftime("%d-%m-%Y")
        series = await fetch_series("cpi", start_date=start_date)
    except Exception:
        return settings.inflation_rate

    if len(series) < 13:
        return settings.inflation_rate

    latest = series[-1]["value"]
    year_ago = series[-13]["value"]
    if not year_ago:
        return settings.inflation_rate

    result = round(latest / year_ago - 1, 4)
    _inflation_cache["value"] = result
    _inflation_cache["fetched_at"] = now
    return result


# ── Mock veri (API anahtarı olmadan geliştirme) ───────────────────────────────

def _mock_latest() -> dict:
    return {
        "usd_try":    38.50,
        "eur_try":    41.20,
        "gold_try":   4250.0,
        "policy_rate": 0.37,
        "fetched_at": datetime.now().isoformat(),
    }


def _mock_series(series_key: str) -> list[dict]:
    import numpy as np
    rng = np.random.default_rng(42)
    base_values = {"usd_try": 28.0, "eur_try": 30.0, "gold_try": 2800.0, "cpi": 100.0}
    base = base_values.get(series_key, 100.0)
    dates = [
        (datetime(2023, 1, 1) + timedelta(days=i * 30)).strftime("%Y-%m-%d")
        for i in range(36)
    ]
    values = base * np.cumprod(1 + rng.normal(0.03, 0.04, len(dates)))
    return [{"date": d, "value": round(float(v), 2)} for d, v in zip(dates, values)]
