"""
Uzman Ajan Modülleri — FinAgent

Her ajan:
  - run(message, context) → dict arayüzüne sahip
  - LLM + gerekirse harici araç kullanır
  - Bağımsız çalışabilir, orkestratör koordine eder
"""

from app.core.llm import llm


async def _resolve_inflation_rate(context: dict | None) -> float:
    """
    context'te açıkça bir inflation_rate verilmişse onu kullanır (örn.
    what-if şok senaryosunda "şoklu" enflasyon), yoksa EVDS'den canlı
    enflasyon oranını çeker (bkz. tcmb.get_current_annual_inflation —
    kısa süreli önbelleklidir, her çağrı ağa gitmez).
    """
    if context and "inflation_rate" in context:
        return context["inflation_rate"]
    from app.core.data.tcmb import get_current_annual_inflation
    return await get_current_annual_inflation()


# ── Analiz Ajanı ──────────────────────────────────────────────────────────────

async def analysis_agent_run(message: str, context: dict | None = None) -> dict:
    """Monte Carlo analizi yapar ve yorumlar."""
    if not context or "portfolio" not in context:
        return {"error": "Portföy bağlamı eksik."}

    from app.core.analysis.monte_carlo import build_portfolio_metrics
    from app.models.portfolio import PortfolioRequest

    portfolio: PortfolioRequest = context["portfolio"]
    inflation_rate = await _resolve_inflation_rate(context)
    metrics = build_portfolio_metrics(portfolio, inflation_rate)

    return {
        "monte_carlo": metrics.monte_carlo.model_dump(),
        "nominal_return_pct": metrics.nominal_return_pct,
        "real_return_pct": metrics.real_return_pct,
        "inflation_protection_score": metrics.inflation_protection_score,
        "sharpe_ratio": metrics.sharpe_ratio,
        "annualized_vol": metrics.annualized_volatility,
    }


# ── Öneri Ajanı ───────────────────────────────────────────────────────────────

# Risk profili hazır ayarları — TEK kaynak burası. Frontend bunu sayfa
# açılışında GET /api/portfolio/config üzerinden çeker (bkz. page.tsx'teki
# riskPresets state'i), kendi kopyasını tutmaz.
RISK_PRESETS = {
    "temkinli": {"gold": 25, "usd": 15, "bist100": 5, "bond": 20, "tufe_bond": 15, "deposit": 20},
    "dengeli":  {"gold": 30, "usd": 25, "bist100": 20, "bond": 8, "tufe_bond": 7, "deposit": 10},
    "buyume":   {"gold": 20, "usd": 15, "bist100": 50, "bond": 5, "tufe_bond": 5, "deposit": 5},
}


async def recommendation_agent_run(message: str, context: dict | None = None) -> dict:
    """Risk profiline göre varlık dağılımı önerir, mümkünse projeksiyon ekler."""
    from app.models.portfolio import AssetAllocation, PortfolioRequest

    risk_profile = "dengeli"
    amount = None
    horizon_years = None

    if context and "portfolio" in context:
        portfolio = context["portfolio"]
        risk_profile = portfolio.risk_profile
        amount = portfolio.amount
        horizon_years = portfolio.horizon_years
    elif context and "risk_profile" in context:
        risk_profile = context["risk_profile"]

    preset = RISK_PRESETS.get(risk_profile, RISK_PRESETS["dengeli"])

    projected = None
    if amount and horizon_years:
        from app.core.analysis.monte_carlo import build_portfolio_metrics

        inflation_rate = await _resolve_inflation_rate(context)
        preset_portfolio = PortfolioRequest(
            amount=amount, horizon_years=horizon_years,
            risk_profile=risk_profile, allocation=AssetAllocation(**preset),
        )
        metrics = build_portfolio_metrics(preset_portfolio, inflation_rate)
        projected = {
            "expected_value": metrics.expected_value,
            "inflation_protection_score": metrics.inflation_protection_score,
            "real_return_pct": metrics.real_return_pct,
        }

    projection_text = ""
    if projected:
        projection_text = (
            f"Projeksiyon: beklenen değer {projected['expected_value']:,.0f} TL, "
            f"IPS {projected['inflation_protection_score']}/100, "
            f"reel getiri %{projected['real_return_pct']}"
        )

    rationale_prompt = f"""Risk profili "{risk_profile}" için önerilen varlık dağılımı:
{preset}
{projection_text}

Bu dağılımı 2-3 cümleyle gerekçelendir. Neden bu profile uygun? Türkçe, sade."""

    rationale = await llm.chat(rationale_prompt, temperature=0.4)

    return {
        "risk_profile": risk_profile,
        "suggested_allocation": preset,
        "projected_metrics": projected,
        "rationale": rationale,
    }


# ── Açıklama Ajanı ────────────────────────────────────────────────────────────

async def explanation_agent_run(message: str, context: dict | None = None) -> dict:
    """Türkçe doğal dil soru-cevap."""
    system = """Sen FinAgent'ın Türkçe finans asistanısın.
Türk yatırımcısına belirsizlik ortamında yol gösteriyorsun.
Yanıtların: net, pratik, Türkçe. Akademik dil kullanma.
Emin olmadığın şeylerde bunu belirt."""

    portfolio_info = ""
    if context and "portfolio" in context:
        p = context["portfolio"]
        alloc = p.allocation.model_dump()
        portfolio_info = f"\nKullanıcının portföyü: {alloc}, {p.amount} TL, {p.horizon_years} yıl"

    analysis_info = ""
    if context and "analysis" in context:
        a = context["analysis"]
        analysis_info = f"\nAnaliz sonuçları: {a}"

    full_message = f"{message}{portfolio_info}{analysis_info}"

    response = await llm.chat(full_message, system=system, temperature=0.5, max_tokens=800)

    return {"response": response}


# ── Rapor Ajanı ───────────────────────────────────────────────────────────────

_TURKISH_FONTS_REGISTERED = False


def _register_turkish_fonts() -> None:
    """DejaVu Sans'ı reportlab'e kaydeder.

    reportlab'in yerleşik "Helvetica"sı WinAnsiEncoding kullanıyor ve
    ı/ğ/ş/İ gibi Türkçe'ye özgü karakterleri içermiyor — PDF'te bunlar
    kutucuk (▪) olarak basılıyordu. DejaVu Sans bu karakterleri kapsıyor;
    dosyalar matplotlib'in paketinden alındı (bkz. app/assets/fonts/LICENSE_DEJAVU
    — serbestçe gömülebilir/dağıtılabilir bir lisans).
    """
    global _TURKISH_FONTS_REGISTERED
    if _TURKISH_FONTS_REGISTERED:
        return
    from pathlib import Path
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fonts_dir = Path(__file__).resolve().parent.parent / "assets" / "fonts"
    pdfmetrics.registerFont(TTFont("DejaVuSans", str(fonts_dir / "DejaVuSans.ttf")))
    pdfmetrics.registerFont(TTFont("DejaVuSans-Bold", str(fonts_dir / "DejaVuSans-Bold.ttf")))
    _TURKISH_FONTS_REGISTERED = True


async def report_agent_run(message: str, context: dict | None = None) -> dict:
    """Portföy analizini PDF rapor olarak üretir (base64 kodlanmış döner)."""
    if not context or "portfolio" not in context:
        return {"error": "Portföy bağlamı eksik."}

    import base64
    import io
    import textwrap
    from datetime import datetime as _dt
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import cm
    from reportlab.pdfgen import canvas
    from app.core.analysis.monte_carlo import build_portfolio_metrics

    _register_turkish_fonts()

    portfolio = context["portfolio"]
    inflation_rate = await _resolve_inflation_rate(context)
    metrics = build_portfolio_metrics(portfolio, inflation_rate)

    mc = metrics.monte_carlo
    ips = metrics.inflation_protection_score
    real_ret = metrics.real_return_pct
    sharpe = metrics.sharpe_ratio
    nominal_ret = metrics.nominal_return_pct

    insight = await llm.chat(
        f"""Portföy raporu için 3-4 cümlelik özet yorum yaz.
Tutar: {portfolio.amount:,.0f} TL, Vade: {portfolio.horizon_years} yıl
Beklenen değer: {mc.expected:,.0f} TL, Reel getiri: %{real_ret}, IPS: {ips}/100
Türkçe, sade.""",
        temperature=0.4,
    )

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    _, height = A4
    y = height - 2 * cm

    def line(text: str, size: int = 11, dy: float = 0.7 * cm, bold: bool = False):
        nonlocal y
        c.setFont("DejaVuSans-Bold" if bold else "DejaVuSans", size)
        c.drawString(2 * cm, y, text)
        y -= dy

    labels = {
        "gold": "Gram Altın", "usd": "USD/TRY", "bist100": "BIST 100", "bond": "Tahvil",
        "tufe_bond": "TÜFE'ye Endeksli Tahvil", "deposit": "Mevduat",
    }

    line("FinAgent — Portföy Analiz Raporu", size=16, bold=True)
    line(f"Oluşturulma: {_dt.now().strftime('%d.%m.%Y %H:%M')}", size=9)
    y -= 0.3 * cm
    line(f"Yatırım tutarı: {portfolio.amount:,.0f} TL", bold=True)
    line(f"Vade: {portfolio.horizon_years} yıl")
    line(f"Risk profili: {portfolio.risk_profile}")
    y -= 0.3 * cm
    line("Varlık Dağılımı:", bold=True)
    for k, v in portfolio.allocation.model_dump().items():
        line(f"  {labels.get(k, k)}: %{v:.0f}", size=10, dy=0.55 * cm)
    y -= 0.3 * cm
    line("Sonuçlar:", bold=True)
    line(f"  Beklenen değer: {mc.expected:,.0f} TL", size=10, dy=0.55 * cm)
    line(f"  Nominal getiri: %{nominal_ret:.1f}", size=10, dy=0.55 * cm)
    line(f"  Reel getiri: %{real_ret}", size=10, dy=0.55 * cm)
    line(f"  Enflasyon Koruma Skoru (IPS): {ips}/100", size=10, dy=0.55 * cm)
    line(f"  Sharpe oranı: {sharpe}", size=10, dy=0.55 * cm)
    y -= 0.3 * cm
    line("AI Değerlendirmesi:", bold=True)
    for wrapped in textwrap.wrap(insight, width=95):
        line(wrapped, size=10, dy=0.5 * cm)

    c.showPage()
    c.save()
    pdf_bytes = buf.getvalue()
    buf.close()

    return {
        "filename": f"finagent-rapor-{_dt.now().strftime('%Y%m%d-%H%M')}.pdf",
        "pdf_base64": base64.b64encode(pdf_bytes).decode("ascii"),
        "content_type": "application/pdf",
    }


# ── Uyarı Ajanı ───────────────────────────────────────────────────────────────

async def alert_agent_run(message: str, context: dict | None = None) -> dict:
    """
    Enflasyon koruması ve politika faizi hareketleri için eşik tabanlı
    uyarılar üretir. Uygulama içi — e-posta/push göndermez, sadece uyarı
    listesi döner; frontend bunu çekip gösterebilir.
    """
    from datetime import datetime as _dt

    from app.core.analysis.monte_carlo import IPS_THRESHOLDS

    alerts = []
    thresholds = (context or {}).get("thresholds", {})
    ips_floor = thresholds.get("ips_floor", IPS_THRESHOLDS["weak"])

    if context and "portfolio" in context:
        from app.core.analysis.monte_carlo import build_portfolio_metrics

        portfolio = context["portfolio"]
        inflation_rate = await _resolve_inflation_rate(context)
        metrics = build_portfolio_metrics(portfolio, inflation_rate)
        ips = metrics.inflation_protection_score
        real_ret = metrics.real_return_pct
        if ips < ips_floor:
            alerts.append({
                "level": "warning",
                "code": "low_ips",
                "message": f"Enflasyon Koruma Skoru düşük: {ips}/100 (eşik: {ips_floor}). Portföy enflasyona karşı zayıf korumalı.",
            })
        if real_ret < 0:
            alerts.append({
                "level": "warning",
                "code": "negative_real_return",
                "message": f"Reel getiri negatif: %{real_ret}. Portföy şu haliyle enflasyonu yenemiyor.",
            })

    # Politika faizi yakın zamanda (son 30 gün) değişti mi
    from app.core.data.tcmb import POLICY_RATE_HISTORY

    if POLICY_RATE_HISTORY:
        last = POLICY_RATE_HISTORY[-1]
        last_date = _dt.strptime(last["date"], "%Y-%m-%d")
        if (_dt.now() - last_date).days <= 30:
            alerts.append({
                "level": "info",
                "code": "policy_rate_changed",
                "message": f"TCMB politika faizi {last['date']} tarihinde %{last['rate']*100:.1f} olarak güncellendi.",
            })

    return {"alerts": alerts, "checked_at": _dt.now().isoformat()}


# ── Modül dışa aktarım ────────────────────────────────────────────────────────

# Her agent modülü için run fonksiyonu
class analysis_agent:
    run = staticmethod(analysis_agent_run)

class recommendation_agent:
    run = staticmethod(recommendation_agent_run)

class explanation_agent:
    run = staticmethod(explanation_agent_run)

class report_agent:
    run = staticmethod(report_agent_run)

class alert_agent:
    run = staticmethod(alert_agent_run)
