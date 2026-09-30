"""
Monte Carlo simülasyon motoru.
Vaka çalışmasındaki 1000 senaryo analizini API'ye taşır.
"""

import numpy as np
from app.models.portfolio import AssetAllocation, MonteCarloResult, PortfolioMetrics, PortfolioRequest

# Vaka çalışmasından alınan varlık parametreleri (yıllık). `ret`, aşağıdaki
# GBM'e sürekli bileşik (log) drift olarak besleniyor (bkz. run_monte_carlo),
# yani buraya konan değer *doğrudan* simülasyondaki efektif büyümeyi belirler.
#
# bist100.ret, notebook'un kendi 100.000 TL backtest penceresiyle (Ocak 2023 —
# 2026-03-27, veri_analizi.ipynb §8.1, ~3,23 yıl) tutarlı olacak şekilde 0.52'den
# 0.25'e düzeltildi: o pencerede BIST100 gerçekte ~%25 log-CAGR (~%28 basit CAGR)
# getirmiş — halbuki eski 0.52 hiçbir hesaplanmış kaynağa dayanmıyordu ve BIST100'ü
# (en riskli varlık) yapay olarak en yüksek beklenen getiriye sahip gösteriyordu.
# Diğer dördü (gold/usd/bond/deposit) aynı yöntemle henüz doğrulanmadı.
ASSET_PARAMS = {
    "gold":    {"ret": 0.42, "vol": 0.18},
    "usd":     {"ret": 0.35, "vol": 0.14},
    "bist100": {"ret": 0.25, "vol": 0.38},
    "bond":    {"ret": 0.34, "vol": 0.08},
    "deposit": {"ret": 0.28, "vol": 0.02},
}

# TÜFE'ye endeksli tahvilin getirisi diğer varlıklar gibi ASSET_PARAMS'ta
# SABİT bir sayı değil — tanımı gereği canlı enflasyona bağlı (kuponu TÜFE'ye
# endeksli). Bu yüzden compute_portfolio_params() içinde `inflation_rate +
# TUFE_BOND_REAL_SPREAD` olarak DİNAMİK hesaplanıyor (bkz. o fonksiyonun
# docstring'i) — sabit bir sayı yazmak, bist100.ret/IPS eşiği için düzelttiğimiz
# türden bir "bayat değer" hatasını bilerek yeniden üretirdi.
# NOT: %2 ilk tahmindir, gerçek Hazine ihale sonuçlarıyla çapraz kontrol
# edilmedi — ASSET_PARAMS'taki diğer sayılar gibi (bkz. yukarıdaki not).
TUFE_BOND_REAL_SPREAD = 0.02
TUFE_BOND_VOL = 0.04

def compute_portfolio_params(
    allocation: AssetAllocation,
    asset_params: dict | None = None,
    inflation_rate: float | None = None,
) -> dict:
    """
    Portföyün ağırlıklı getiri ve volatilitesini hesaplar.
    asset_params: verilirse global ASSET_PARAMS yerine kullanılır — what-if
    şok senaryolarında (bkz. apply_shocks_to_asset_params) geçici olarak
    değiştirilmiş getiri varsayımlarını simülasyona sokmak için gerekli.
    inflation_rate: tufe_bond ağırlığı >0 olan bir tahsis için ZORUNLU — bu
    varlığın getirisi buradan (+ TUFE_BOND_REAL_SPREAD) dinamik hesaplanır
    (bkz. TUFE_BOND_REAL_SPREAD notu). tufe_bond ağırlığı 0 ise kullanılmaz.

    Not: risk_profile burada volatiliteyi ayrıca çarpmaz — tahsisin kendisi
    (ASSET_PARAMS × allocation) riski zaten taşır, ve frontend'de risk
    profili butonları zaten farklı tahsis preset'leri seçtiriyor. Ayrı bir
    volatilite çarpanı, tahsisten bağımsızlaştığında (kullanıcı slider'ı
    preset sonrası elle değiştirdiğinde) aynı tahsis için "daha büyümeci"
    profilin skoru düşürmesi gibi bir çelişkiye yol açıyordu.
    """
    params_source = asset_params if asset_params is not None else ASSET_PARAMS
    alloc_dict = allocation.model_dump()
    total = sum(alloc_dict.values())

    weighted_ret = 0.0
    weighted_vol = 0.0

    for asset, weight_pct in alloc_dict.items():
        if weight_pct == 0:
            continue
        w = weight_pct / total
        if asset == "tufe_bond":
            if inflation_rate is None:
                raise ValueError(
                    "tufe_bond ağırlığı >0 iken inflation_rate zorunludur "
                    "(bu varlığın getirisi dinamik olarak ondan hesaplanır)."
                )
            ret = inflation_rate + TUFE_BOND_REAL_SPREAD
            vol = TUFE_BOND_VOL
        else:
            ret = params_source[asset]["ret"]
            vol = params_source[asset]["vol"]
        weighted_ret += w * ret
        weighted_vol += w * vol

    return {"ret": weighted_ret, "vol": weighted_vol}


def apply_shocks_to_asset_params(shocks: dict[str, float]) -> dict:
    """
    Makro şokları ASSET_PARAMS'ın bir KOPYASINA uygular ve döner (global
    ASSET_PARAMS'ı değiştirmez). Sonuç, run_monte_carlo/compute_portfolio_params'a
    asset_params= olarak geçirilmek üzere tasarlanmıştır.

    Desteklenen şoklar:
      usd_shock         → ASSET_PARAMS["usd"]["ret"] üzerine eklenir
      policy_rate_delta → ASSET_PARAMS["bond"] ve ["deposit"]["ret"] üzerine eklenir
      bist_shock        → ASSET_PARAMS["bist100"]["ret"] üzerine eklenir

    inflation_delta burada uygulanmaz — o, enflasyon oranının kendisine
    eklenir (bkz. çağıran kodun compute_inflation_adjusted_metrics'e verdiği
    inflation_rate parametresi), varlık getirilerine değil.

    tufe_bond da burada YOK — ASSET_PARAMS'ta hiç bulunmuyor (getirisi
    compute_portfolio_params içinde inflation_rate'ten dinamik hesaplanıyor,
    bkz. TUFE_BOND_REAL_SPREAD). Bunun güzel bir sonucu: inflation_delta
    şoku uygulandığında tufe_bond'un getirisi otomatik ve doğru şekilde
    değişir (şoklu inflation_rate zaten build_portfolio_metrics'e geçiyor) —
    burada ekstra kod gerekmez. Diğer şoklar (usd_shock/policy_rate_delta/
    bist_shock) tufe_bond'u bilerek etkilemez — gerçek hayatta da bu
    enstrümanın kuponu politika faizine değil TÜFE'ye bağlıdır.
    """
    from copy import deepcopy

    shocked = deepcopy(ASSET_PARAMS)
    if "usd_shock" in shocks:
        shocked["usd"]["ret"] += shocks["usd_shock"]
    if "policy_rate_delta" in shocks:
        shocked["bond"]["ret"] += shocks["policy_rate_delta"]
        shocked["deposit"]["ret"] += shocks["policy_rate_delta"]
    if "bist_shock" in shocks:
        shocked["bist100"]["ret"] += shocks["bist_shock"]
    return shocked


def run_monte_carlo(
    amount: float,
    horizon_years: int,
    allocation: AssetAllocation,
    n_simulations: int = 1000,
    sample_paths: int = 50,
    asset_params: dict | None = None,
    seed: int | None = None,
    inflation_rate: float | None = None,
) -> tuple[MonteCarloResult, np.ndarray]:
    """
    GBM (Geometric Brownian Motion) ile Monte Carlo simülasyonu.
    n_simulations: toplam senaryo sayısı
    sample_paths:  grafik için döndürülecek örnek yol sayısı
    asset_params:  verilirse global ASSET_PARAMS yerine kullanılır (what-if
                   şok senaryoları için — bkz. apply_shocks_to_asset_params)
    seed:          verilirse rastgele sayı üretecini bu değerle başlatır.
                   Base/shocked karşılaştırmalarında ikisine de AYNI seed
                   geçirilerek "ortak rastgele sayılar" (common random
                   numbers) sağlanır — böylece iki sonuç arasındaki tek fark
                   uygulanan şok olur, örnekleme gürültüsü karışmaz.
                   Verilmezse (varsayılan) her çağrı işletim sisteminden yeni
                   entropi alır — /analyze gibi tek seferlik çağrılar için
                   istenen budur, davranışları bu parametreden etkilenmez.
    inflation_rate: tufe_bond ağırlığı >0 olan bir tahsis için ZORUNLU —
                   bkz. compute_portfolio_params.

    Dönüş: (MonteCarloResult, final_values). final_values, her senaryonun ham
    (enflasyon düzeltilmemiş) son değerini içeren dizi — IPS ve reel getirinin
    AYNI simülasyondan türetilebilmesi için `compute_inflation_adjusted_metrics`'e
    geçirilir (bkz. o fonksiyonun docstring'i).
    """
    params = compute_portfolio_params(allocation, asset_params=asset_params, inflation_rate=inflation_rate)
    mu = params["ret"]
    sigma = params["vol"]

    steps = horizon_years * 12  # aylık adımlar
    mu_m = mu / 12
    sigma_m = sigma / np.sqrt(12)

    rng = np.random.default_rng(seed)

    # (n_simulations, steps) boyutunda rastgele şoklar
    z = rng.standard_normal((n_simulations, steps))
    log_returns = (mu_m - 0.5 * sigma_m**2) + sigma_m * z

    # GBM kapalı-form: S_t = S_0 * exp(kümülatif log getiri). (cumprod(1+x) bir
    # yaklaşıklıktı — volatilite arttıkça ortalama değeri yapay şekilde
    # aşağı çekiyordu; exp(cumsum(x)) GBM'in "ortalama volatiliteden
    # bağımsızdır" özelliğini doğru şekilde korur.)
    cum = np.exp(np.cumsum(log_returns, axis=1))
    final_values = amount * cum[:, -1]

    # Tam yollar (grafik için küçük örneklem)
    path_indices = rng.choice(n_simulations, size=min(sample_paths, n_simulations), replace=False)
    sample_matrix = amount * cum[path_indices]  # (sample_paths, steps)

    # Adım başına tam zaman serisi ekliyoruz (başlangıç değeriyle)
    start_col = np.full((sample_matrix.shape[0], 1), amount)
    full_paths = np.concatenate([start_col, sample_matrix], axis=1)
    paths_list = [path.tolist() for path in full_paths]

    result = MonteCarloResult(
        percentile_10=float(np.percentile(final_values, 10)),
        percentile_25=float(np.percentile(final_values, 25)),
        percentile_50=float(np.percentile(final_values, 50)),
        percentile_75=float(np.percentile(final_values, 75)),
        percentile_90=float(np.percentile(final_values, 90)),
        expected=float(final_values.mean()),
        worst=float(final_values.min()),
        best=float(final_values.max()),
        paths_sample=paths_list,
    )
    return result, final_values


# IPS'in "zayıf/kısmi/güçlü koruma" bantları — page.tsx'in ipsColor/ipsLabel'i
# ve alert_agent_run'ın varsayılan ips_floor'u TEK kaynak olarak burayı okur
# (bkz. GET /api/portfolio/config). Enflasyon varsayımı sabit %48'den EVDS'nin
# canlı ~%30,65 değerine geçince IPS dağılımı 100'e doğru sıkıştı (144 örnek
# portföy/ufuk/risk-profili kombinasyonunda ölçülen gerçek dağılım: %16 <75,
# %42 [75,92), %42 >=92 — bkz. ips.md). Eski 25/50 eşikleri bu dağılımda hemen
# hemen her şeyi "Güçlü koruma" gösterirdi.
IPS_THRESHOLDS = {"weak": 75.0, "strong": 92.0}


def compute_inflation_adjusted_metrics(
    final_values: np.ndarray,
    amount: float,
    inflation_rate: float,
    horizon_years: int,
) -> tuple[float, float]:
    """
    Enflasyon Koruma Skoru (IPS) ve reel getiriyi AYNI Monte Carlo
    simülasyonundan türetir — ikisi de aynı enflasyon-düzeltmeli (deflate
    edilmiş) sonuç dizisine dayandığı için birbiriyle çelişemez (eski
    formülde IPS varlıkları tek tek eşik testinden geçiriyordu, reel getiri
    ise harmanlanmış tek bir sayı kullanıyordu — bu ikisini ayırıyordu).

    IPS: başlangıç tutarını reel olarak koruyan/aşan senaryoların yüzdesi (0-100).
    real_return_pct: deflate edilmiş sonuçların medyanından hesaplanan getiri (%).

    Not: IPS > 50 ⟺ medyan real_value >= amount ⟺ real_return_pct >= 0 — bu
    ilişki matematiksel olarak garantidir (aynı diziden türetildikleri için),
    rastgele değil. Bkz. tests/test_ips_consistency.py.

    Dönüş: (inflation_protection_score, real_return_pct)
    """
    deflator = (1 + inflation_rate) ** horizon_years
    real_values = final_values / deflator

    ips = float((real_values >= amount).mean() * 100)
    real_median = float(np.median(real_values))
    real_return_pct = (real_median / amount - 1) * 100

    return round(ips, 1), round(real_return_pct, 1)


def compute_sharpe(ret: float, vol: float, risk_free: float = 0.28) -> float:
    """Basitleştirilmiş Sharpe oranı. Risk-free = mevduat faizi."""
    if vol == 0:
        return 0.0
    return round((ret - risk_free) / vol, 2)


def build_portfolio_metrics(
    portfolio: PortfolioRequest,
    inflation_rate: float,
    asset_params: dict | None = None,
    seed: int | None = None,
) -> PortfolioMetrics:
    """
    Bir portföy için TEK doğru kaynak: Monte Carlo → IPS/reel getiri → Sharpe
    zincirini çalıştırıp PortfolioMetrics döner. `/api/portfolio/*` route'ları
    ve `app/agents/__init__.py`'deki analysis/report/alert/recommendation
    ajanlarının hepsi bu fonksiyonu çağırır — aynı hesabı bağımsız kopyalamazlar.

    asset_params: verilirse global ASSET_PARAMS yerine kullanılır (what-if
    şok senaryolarında, bkz. apply_shocks_to_asset_params).
    seed: verilirse Monte Carlo'yu bu tohumla çalıştırır — base/shocked
    karşılaştırmalarında ikisine aynı seed geçirilir (bkz. what_if_scenario).
    """
    mc, final_values = run_monte_carlo(
        amount=portfolio.amount,
        horizon_years=portfolio.horizon_years,
        allocation=portfolio.allocation,
        n_simulations=1000,
        asset_params=asset_params,
        seed=seed,
        inflation_rate=inflation_rate,
    )

    params = compute_portfolio_params(portfolio.allocation, asset_params=asset_params, inflation_rate=inflation_rate)
    nominal_ret_pct = (mc.expected / portfolio.amount - 1) * 100
    ips, real_ret_pct = compute_inflation_adjusted_metrics(
        final_values, portfolio.amount, inflation_rate, portfolio.horizon_years
    )

    return PortfolioMetrics(
        expected_value=round(mc.expected, 2),
        nominal_return_pct=round(nominal_ret_pct, 1),
        real_return_pct=real_ret_pct,
        inflation_protection_score=ips,
        annualized_volatility=round(params["vol"] * 100, 1),
        sharpe_ratio=compute_sharpe(params["ret"], params["vol"]),
        max_drawdown_estimate=round(params["vol"] * 2.5 * 100, 1),
        monte_carlo=mc,
    )
