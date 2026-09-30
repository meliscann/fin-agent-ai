"""
Piyasa Analizi sekmesi — vaka çalışması verisi.

key_stats / normalized_performance / inflation_policy / backtest_100k /
real_vs_nominal CANLI hesaplanır — app/core/data'daki aynı fonksiyonları
(fetch_series, fetch_bist100, POLICY_RATE_HISTORY) kullanır; mantık
veri_analizi.ipynb'nin §7-9 hücrelerinin API'ye taşınmış hali.

decision_matrix ve portfolio_models ise öznel/editoryal puanlamalar —
hiçbir zaman "veriden türeyen" bir şey değildi, bilinçli olarak statik
kalıyor.

1 saatlik bellek-içi önbellek var (bkz. _CACHE_TTL) — her sayfa açılışında
4 EVDS + 1 Yahoo çağrısını tekrarlamamak için (aynı desen: tcmb.py'deki
_inflation_cache).
"""

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter

from app.core.data.tcmb import fetch_series, POLICY_RATE_HISTORY, get_current_annual_inflation, get_current_policy_rate
from app.core.data.yahoo import fetch_bist100

router = APIRouter(prefix="/insights", tags=["insights"])

ANALYSIS_START = "2020-01-01"   # normalize performans + reel getiri penceresi
BACKTEST_START = "2023-01-01"   # 100K TL backtest penceresi (bkz. notebook §8.1)

# Uygulama gerçek mevduat faizi verisi tutmuyor — veri_analizi.ipynb ile aynı
# sabit varsayım (%35 yıllık, %82,5 stopaj sonrası efektif oran).
MEVDUAT_YILLIK_FAIZ = 0.35
MEVDUAT_STOPAJ_SONRASI_ORAN = 0.825

# ── Öznel/editoryal puanlamalar — veriden türemez, bilinçli olarak statik ──────

DECISION_MATRIX = {
    "criteria": [
        "Enflasyon Koruması",
        "Likidite",
        "Reel Getiri Pot.",
        "Düşük Volatilite",
        "Kur Koruması",
    ],
    "instruments": ["TL Mevduat", "Altın", "Dolar/Euro", "BIST Hisse", "Nakit"],
    "scores": [
        [3, 5, 2, 5, 1],
        [5, 3, 5, 2, 5],
        [4, 4, 3, 3, 5],
        [3, 3, 5, 1, 2],
        [1, 5, 1, 5, 1],
    ],
    "profile_weights": {
        "temkinli": [0.30, 0.25, 0.15, 0.20, 0.10],
        "buyume":   [0.20, 0.15, 0.30, 0.15, 0.20],
    },
}

PORTFOLIO_MODELS = [
    {
        "name": "Temkinli Portföy",
        "profile": "temkinli",
        "slices": [
            {"name": "TL Mevduat & Tahvil", "value": 37.5, "color": "#4f8ef7"},
            {"name": "Döviz",               "value": 22.5, "color": "#E76F51"},
            {"name": "Altın",               "value": 22.5, "color": "#f5c842"},
            {"name": "BIST Hisse",          "value":  7.5, "color": "#3ecf8e"},
            {"name": "Uluslararası Hisse",  "value":  2.5, "color": "#6A994E"},
            {"name": "Nakit",               "value":  7.5, "color": "#6b6b8a"},
        ],
    },
    {
        "name": "Büyüme Odaklı Portföy",
        "profile": "buyume",
        "slices": [
            {"name": "TL Mevduat & Tahvil", "value": 17.5, "color": "#4f8ef7"},
            {"name": "Döviz",               "value": 22.5, "color": "#E76F51"},
            {"name": "Altın",               "value": 17.5, "color": "#f5c842"},
            {"name": "BIST Hisse",          "value": 27.5, "color": "#3ecf8e"},
            {"name": "Uluslararası Hisse",  "value": 12.5, "color": "#6A994E"},
            {"name": "Nakit",               "value":  2.5, "color": "#6b6b8a"},
        ],
    },
]

# ── Tarih yardımcıları ──────────────────────────────────────────────────────────
# fetch_series üç farklı biçimde tarih döndürebilir (EVDS'nin kendi seri
# frekansına göre): "YYYY-M" (aylık, sıfırsız ay — cpi/gold_try'nin doğal
# biçimi, ve usd/eur_try'ye frequency=5 verildiğinde), "DD-MM-YYYY" (günlük —
# usd/eur_try'ye frequency verilmezse). fetch_bist100 her zaman ISO
# "YYYY-MM-DD" döner. Aşağıdaki iki yardımcı bunları tekilleştirir.


def _to_iso(date_str: str) -> str:
    """Herhangi bir fetch_series/fetch_bist100 tarihini 'YYYY-MM-DD'ye çevirir."""
    parts = date_str.split("-")
    if len(parts[0]) == 4:
        if len(parts) == 2:  # "YYYY-M"
            y, m = parts
            return f"{int(y):04d}-{int(m):02d}-01"
        return date_str  # zaten "YYYY-MM-DD"
    d, m, y = parts  # "DD-MM-YYYY"
    return f"{int(y):04d}-{int(m):02d}-{int(d):02d}"


def _month_key(date_str: str) -> str:
    iso = _to_iso(date_str)
    return iso[:7]  # "YYYY-MM"


def _to_monthly(points: list[dict], value_key: str = "value") -> dict[str, float]:
    """[{"date":..., value_key:...}] -> {"YYYY-MM": o ayın SON noktasının değeri}."""
    out: dict[str, float] = {}
    for p in sorted(points, key=lambda x: _to_iso(x["date"])):
        out[_month_key(p["date"])] = p[value_key]
    return out


def _rate_as_of(target_date_iso: str) -> float:
    """POLICY_RATE_HISTORY'den target_date_iso'ya kadar en son ilan edilen oranı döner."""
    rate = POLICY_RATE_HISTORY[0]["rate"]
    for entry in POLICY_RATE_HISTORY:
        if entry["date"] <= target_date_iso:
            rate = entry["rate"]
    return rate


def _first_last_in_range(points: list[dict], value_key: str, start_iso: str) -> tuple[float, float, str]:
    """start_iso'dan itibaren ilk ve son noktanın değerlerini (ve son tarihi) döner."""
    filtered = sorted(
        (p for p in points if _to_iso(p["date"]) >= start_iso),
        key=lambda x: _to_iso(x["date"]),
    )
    return filtered[0][value_key], filtered[-1][value_key], _to_iso(filtered[-1]["date"])


# ── Canlı hesaplama ──────────────────────────────────────────────────────────────

async def _compute_case_study() -> dict[str, Any]:
    usd = await fetch_series("usd_try", start_date="01-01-2020", frequency=5)
    eur = await fetch_series("eur_try", start_date="01-01-2020", frequency=5)
    gold = await fetch_series("gold_try", start_date="01-01-2020")
    cpi = await fetch_series("cpi", start_date="01-01-2020")
    bist_raw = await fetch_bist100(period_years=7)
    bist = [{"date": p["date"], "value": p["close"]} for p in bist_raw]

    usd_m, eur_m, gold_m, cpi_m, bist_m = (
        _to_monthly(usd), _to_monthly(eur), _to_monthly(gold), _to_monthly(cpi), _to_monthly(bist)
    )

    # ── 1) Normalize performans: tüm serilerde ortak olan aylar, ilk ortak aya göre 100 bazlı ──
    common_months = sorted(set(usd_m) & set(eur_m) & set(gold_m) & set(cpi_m) & set(bist_m))
    normalized_performance = []
    if common_months:
        base = common_months[0]
        for m in common_months:
            normalized_performance.append({
                "date": m,
                "gold": round(gold_m[m] / gold_m[base] * 100, 1),
                "usd": round(usd_m[m] / usd_m[base] * 100, 1),
                "eur": round(eur_m[m] / eur_m[base] * 100, 1),
                "bist100": round(bist_m[m] / bist_m[base] * 100, 1),
                "tufe": round(cpi_m[m] / cpi_m[base] * 100, 1),
            })

    # ── 2) Enflasyon vs politika faizi: YoY TÜFE + o aya kadarki en son politika faizi ──
    cpi_months = sorted(cpi_m)
    inflation_policy = []
    for i, m in enumerate(cpi_months):
        if i < 12:
            continue
        year_ago_value = cpi_m[cpi_months[i - 12]]
        if not year_ago_value:
            continue
        inflation_pct = round((cpi_m[m] / year_ago_value - 1) * 100, 2)
        policy_pct = round(_rate_as_of(f"{m}-28") * 100, 1)
        inflation_policy.append({"date": m, "inflation": inflation_pct, "policy": policy_pct})

    # ── 3) 100.000 TL backtest (Ocak 2023 -> bugün) ──
    yatirim = 100_000.0
    gold_ilk, gold_son, _ = _first_last_in_range(gold, "value", BACKTEST_START)
    usd_ilk, usd_son, _ = _first_last_in_range(usd, "value", BACKTEST_START)
    eur_ilk, eur_son, _ = _first_last_in_range(eur, "value", BACKTEST_START)
    bist_ilk, bist_son, son_tarih = _first_last_in_range(bist, "value", BACKTEST_START)
    cpi_ilk_bt, cpi_son_bt, _ = _first_last_in_range(cpi, "value", BACKTEST_START)

    backtest_yil = (datetime.fromisoformat(son_tarih) - datetime.fromisoformat(BACKTEST_START)).days / 365.25
    mevduat_deger_bt = yatirim * (1 + MEVDUAT_YILLIK_FAIZ) ** backtest_yil
    nakit_deger_bt = yatirim * (cpi_ilk_bt / cpi_son_bt)

    def _backtest_entry(name: str, deger: float, color: str) -> dict:
        return {"name": name, "value": round(deger, 0), "gain": round((deger / yatirim - 1) * 100, 1), "color": color}

    backtest_100k = [
        _backtest_entry("Altın", yatirim * (gold_son / gold_ilk), "#f5c842"),
        _backtest_entry("Euro", yatirim * (eur_son / eur_ilk), "#a78bfa"),
        _backtest_entry("Mevduat", mevduat_deger_bt, "#6b8aa8"),
        _backtest_entry("Dolar", yatirim * (usd_son / usd_ilk), "#4f8ef7"),
        _backtest_entry("BIST 100", yatirim * (bist_son / bist_ilk), "#3ecf8e"),
        _backtest_entry("Nakit", nakit_deger_bt, "#f76f6f"),
    ]

    # ── 4) Nominal vs reel getiri (2020-01 -> bugün) ──
    gold_ilk_r, gold_son_r, _ = _first_last_in_range(gold, "value", ANALYSIS_START)
    usd_ilk_r, usd_son_r, _ = _first_last_in_range(usd, "value", ANALYSIS_START)
    eur_ilk_r, eur_son_r, _ = _first_last_in_range(eur, "value", ANALYSIS_START)
    bist_ilk_r, bist_son_r, son_tarih_r = _first_last_in_range(bist, "value", ANALYSIS_START)
    cpi_ilk_r, cpi_son_r, _ = _first_last_in_range(cpi, "value", ANALYSIS_START)

    toplam_enflasyon = (cpi_son_r / cpi_ilk_r - 1) * 100
    analiz_yil = (datetime.fromisoformat(son_tarih_r) - datetime.fromisoformat(ANALYSIS_START)).days / 365.25
    mevduat_nominal = ((1 + MEVDUAT_YILLIK_FAIZ * MEVDUAT_STOPAJ_SONRASI_ORAN) ** analiz_yil - 1) * 100

    def _reel(nominal_pct: float) -> float:
        return ((1 + nominal_pct / 100) / (1 + toplam_enflasyon / 100) - 1) * 100

    nominal_getiriler = {
        "Altın": (gold_son_r / gold_ilk_r - 1) * 100,
        "BIST 100": (bist_son_r / bist_ilk_r - 1) * 100,
        "Dolar": (usd_son_r / usd_ilk_r - 1) * 100,
        "Euro": (eur_son_r / eur_ilk_r - 1) * 100,
        "Mevduat": mevduat_nominal,
        "Nakit": 0.0,
    }
    real_vs_nominal = [
        {"name": ad, "nominal": round(nominal, 1), "real": round(_reel(nominal), 1)}
        for ad, nominal in nominal_getiriler.items()
    ]
    real_vs_nominal.sort(key=lambda x: x["real"], reverse=True)

    en_iyi = real_vs_nominal[0]
    deposit_entry = next(r for r in real_vs_nominal if r["name"] == "Mevduat")
    cash_entry = next(r for r in real_vs_nominal if r["name"] == "Nakit")

    key_stats = {
        "total_inflation_pct": round(toplam_enflasyon, 1),
        "best_asset": en_iyi["name"],
        "best_real_return_pct": en_iyi["real"],
        "cash_loss_pct": round(-cash_entry["real"], 1),
        "deposit_real_return_pct": deposit_entry["real"],
        "analysis_period": f"{ANALYSIS_START[:7]} → {son_tarih_r[:7]}",
        "backtest_period": f"{BACKTEST_START[:7]} → {son_tarih[:7]}",
        # Aynı kaynak uygulamanın geri kalanının (market-data ticker'ı,
        # /analyze vb.) kullandığıyla birebir aynı — burada yeniden
        # hesaplamak yerine doğrudan çağırıyoruz (DRY + son-çare fallback'i
        # bedava gelir).
        "current_inflation": round(await get_current_annual_inflation() * 100, 2),
        "current_policy_rate": round(get_current_policy_rate() * 100, 1),
    }

    return {
        "key_stats": key_stats,
        "normalized_performance": normalized_performance,
        "inflation_policy": inflation_policy,
        "backtest_100k": backtest_100k,
        "real_vs_nominal": real_vs_nominal,
        "decision_matrix": DECISION_MATRIX,
        "portfolio_models": PORTFOLIO_MODELS,
    }


_cache: dict[str, Any] = {"value": None, "fetched_at": None}
_CACHE_TTL = timedelta(hours=1)


@router.get("/case-study")
async def get_case_study() -> dict[str, Any]:
    now = datetime.now()
    if _cache["value"] is not None and _cache["fetched_at"] is not None:
        if now - _cache["fetched_at"] < _CACHE_TTL:
            return _cache["value"]

    result = await _compute_case_study()
    _cache["value"] = result
    _cache["fetched_at"] = now
    return result
