'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import {
  analyzePortfolio, getMarketData, runScenario, comparePortfolios, checkAlerts, getRecommendation, generateReport, getPortfolioConfig,
  PortfolioRequest, AnalysisResponse, MarketData, ScenarioResponse, Shocks,
  CompareResponse, AlertItem, RecommendationResult, PortfolioConfig,
} from '@/lib/api'
import dynamic from 'next/dynamic'
import ChatPanel from './components/ChatPanel'
import InfoTooltip from './components/InfoTooltip'

const MonteCarloChart  = dynamic(() => import('./components/MonteCarloChart'),  { ssr: false })
const InsightsPanel    = dynamic(() => import('./components/InsightsPanel'),    { ssr: false })

// ── Sabitler ──────────────────────────────────────────────────────────────────

const ASSETS = [
  { id: 'gold',      name: 'Gram Altın',    color: '#f5c842' },
  { id: 'usd',       name: 'USD/TRY',       color: '#4f8ef7' },
  { id: 'bist100',   name: 'BIST 100',      color: '#3ecf8e' },
  { id: 'bond',      name: 'Tahvil',        color: '#a78bfa' },
  { id: 'tufe_bond', name: 'TÜFE Tahvili',  color: '#22d3ee' },
  { id: 'deposit',   name: 'Mevduat',       color: '#6b6b8a' },
] as const

// Hızlı senaryolar — mevcut portföye gerçek bir makro şok uygulayıp
// /api/portfolio/scenario üzerinden önce/sonra karşılaştırması gösterir.
// Şok büyüklükleri gösterim amaçlı seçilmiş makul stres testi değerleridir.
const SCENARIOS: Record<string, { shocks: Shocks; desc: string }> = {
  'Güvenli Liman':     { shocks: { usd_shock: 0.25 },         desc: 'Kriz senaryosu: Dolar %25 daha güçlü' },
  'Enflasyon Kalkanı':  { shocks: { inflation_delta: 0.15 },  desc: 'Enflasyon beklenenden 15 puan yüksek çıkarsa' },
  'Büyüme Odaklı':      { shocks: { policy_rate_delta: -0.10 }, desc: 'TCMB politika faizini 10 puan indirirse' },
  'BIST Ağırlıklı':     { shocks: { bist_shock: 0.20 },       desc: 'BIST 100 %20 daha güçlü performans gösterirse' },
}

const HORIZONS: (1 | 3 | 5 | 10)[] = [1, 3, 5, 10]
const RISK_OPTIONS = [
  { id: 'temkinli', label: 'Temkinli', color: '#3ecf8e' },
  { id: 'dengeli',  label: 'Dengeli',  color: '#f5c842' },
  { id: 'buyume',   label: 'Büyüme',   color: '#f76f6f' },
] as const

// Backend çöküyse veya /config henüz gelmediyse kullanılan son-çare
// kopyası — TEK doğru kaynak artık backend (bkz. lib/api.ts: getPortfolioConfig,
// app/agents/__init__.py: RISK_PRESETS). Normal koşullarda page açılışında
// çekilen değerlerle (riskPresets state'i) ezilir.
const RISK_ALLOCATIONS_FALLBACK = {
  temkinli: { gold: 25, usd: 15, bist100:  5, bond: 20, tufe_bond: 15, deposit: 20 },
  dengeli:  { gold: 30, usd: 25, bist100: 20, bond:  8, tufe_bond:  7, deposit: 10 },
  buyume:   { gold: 20, usd: 15, bist100: 50, bond:  5, tufe_bond:  5, deposit:  5 },
} as const

const IPS_THRESHOLDS_FALLBACK = { weak: 75, strong: 92 }

// ── Yardımcı ──────────────────────────────────────────────────────────────────

function fmt(n: number) {
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(2) + 'M ₺'
  if (n >= 1_000)     return (n / 1_000).toFixed(0) + 'K ₺'
  return n.toFixed(0) + ' ₺'
}

// Eşik değerleri artık backend'den gelir (bkz. IPS_THRESHOLDS_FALLBACK
// yorumu ve app/core/analysis/monte_carlo.py: IPS_THRESHOLDS — kalibrasyon
// geçmişi ve gerekçesi orada belgeli). Buradaki parametre varsayılanı
// sadece config henüz gelmediyse/backend çöktüyse devreye girer.
function ipsColor(score: number, thresholds = IPS_THRESHOLDS_FALLBACK) {
  if (score >= thresholds.strong) return '#3ecf8e'
  if (score >= thresholds.weak) return '#f5c842'
  return '#f76f6f'
}

function ipsLabel(score: number, thresholds = IPS_THRESHOLDS_FALLBACK) {
  if (score >= thresholds.strong) return 'Güçlü koruma'
  if (score >= thresholds.weak) return 'Kısmi koruma'
  return 'Zayıf koruma'
}

// ── Ana Bileşen ───────────────────────────────────────────────────────────────

export default function Home() {
  // Aktif sekme
  const [activeTab, setActiveTab]   = useState<'simulator' | 'analiz'>('simulator')

  // Portföy state
  const [allocation, setAllocation] = useState({ gold: 30, usd: 25, bist100: 20, bond: 15, tufe_bond: 0, deposit: 10 })
  const [amount, setAmount]         = useState(500_000)
  const [horizon, setHorizon]       = useState<1|3|5|10>(3)
  const [risk, setRisk]             = useState<'temkinli'|'dengeli'|'buyume'>('dengeli')

  // Sonuçlar
  const [analysis, setAnalysis]     = useState<AnalysisResponse | null>(null)
  const [loading, setLoading]       = useState(false)
  const [market, setMarket]         = useState<MarketData | null>(null)
  const [chatOpen, setChatOpen]     = useState(false)

  // Risk preset'leri + IPS eşikleri — sayfa açılışında backend'den çekilir,
  // gelene kadar/başarısız olursa yukarıdaki fallback sabitleri kullanılır.
  const [riskPresets, setRiskPresets]     = useState<PortfolioConfig['risk_presets']>(RISK_ALLOCATIONS_FALLBACK)
  const [ipsThresholds, setIpsThresholds] = useState(IPS_THRESHOLDS_FALLBACK)

  // Hızlı senaryo (what-if) sonucu
  const [scenarioResult, setScenarioResult]         = useState<ScenarioResponse | null>(null)
  const [scenarioLoading, setScenarioLoading]       = useState(false)
  const [activeScenarioName, setActiveScenarioName] = useState<string | null>(null)

  // Karşılaştırma, öneri, uyarı, rapor
  const [compareResult, setCompareResult]   = useState<CompareResponse | null>(null)
  const [compareLoading, setCompareLoading] = useState(false)
  const [compareTarget, setCompareTarget]   = useState<'temkinli'|'dengeli'|'buyume'|null>(null)

  const [recommendation, setRecommendation]   = useState<RecommendationResult | null>(null)
  const [recommendLoading, setRecommendLoading] = useState(false)

  const [alerts, setAlerts]               = useState<AlertItem[] | null>(null)
  const [alertsLoading, setAlertsLoading] = useState(false)

  const [reportLoading, setReportLoading] = useState(false)
  const [reportError, setReportError]     = useState<string | null>(null)

  const debounceRef = useRef<ReturnType<typeof setTimeout>>()
  const total = Object.values(allocation).reduce((s, v) => s + v, 0)
  const isValid = Math.abs(total - 100) < 0.01

  // Portfolio request nesnesi
  const portfolioReq: PortfolioRequest = { amount, horizon_years: horizon, risk_profile: risk, allocation }

  // Analiz çağrısı (debounced)
  const runAnalysis = useCallback(async () => {
    if (!isValid) return
    setLoading(true)
    try {
      const res = await analyzePortfolio(portfolioReq)
      setAnalysis(res)
    } catch (e) { console.error(e) }
    finally { setLoading(false) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [amount, horizon, risk, allocation, isValid])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(runAnalysis, 700)
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [runAnalysis])

  // Piyasa verisi + risk preset'leri/IPS eşikleri (sayfa açılışında bir kez)
  useEffect(() => { getMarketData().then(setMarket).catch(console.error) }, [])
  useEffect(() => {
    getPortfolioConfig()
      .then(cfg => { setRiskPresets(cfg.risk_presets); setIpsThresholds(cfg.ips_thresholds) })
      .catch(console.error)
  }, [])

  // Portföy değişince eski senaryo/karşılaştırma/öneri/uyarı sonuçları geçersiz kalır — temizle
  useEffect(() => {
    setScenarioResult(null)
    setActiveScenarioName(null)
    setCompareResult(null)
    setCompareTarget(null)
    setRecommendation(null)
    setAlerts(null)
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [amount, horizon, risk, allocation])

  const handleSlider = (id: string, val: number) =>
    setAllocation(p => {
      const others = Object.entries(p)
        .filter(([k]) => k !== id)
        .reduce((s, [, v]) => s + v, 0)
      return { ...p, [id]: Math.max(0, Math.min(val, 100 - others)) }
    })

  const runQuickScenario = async (name: string, shocks: Shocks) => {
    if (!isValid) return
    setScenarioLoading(true)
    setActiveScenarioName(name)
    try {
      const res = await runScenario(portfolioReq, shocks)
      setScenarioResult(res)
    } catch (e) { console.error(e) }
    finally { setScenarioLoading(false) }
  }

  const clearScenario = () => {
    setScenarioResult(null)
    setActiveScenarioName(null)
  }

  const runCompare = async (targetRisk: 'temkinli'|'dengeli'|'buyume') => {
    if (!isValid) return
    setCompareLoading(true)
    setCompareTarget(targetRisk)
    try {
      const portfolioB: PortfolioRequest = {
        amount, horizon_years: horizon, risk_profile: targetRisk,
        allocation: riskPresets[targetRisk],
      }
      const label = RISK_OPTIONS.find(r => r.id === targetRisk)!.label
      const res = await comparePortfolios(portfolioReq, portfolioB, 'Portföyüm', label)
      setCompareResult(res)
    } catch (e) { console.error(e) }
    finally { setCompareLoading(false) }
  }

  const clearCompare = () => {
    setCompareResult(null)
    setCompareTarget(null)
  }

  const runRecommendation = async () => {
    if (!isValid) return
    setRecommendLoading(true)
    try { setRecommendation(await getRecommendation(portfolioReq)) }
    catch (e) { console.error(e) }
    finally { setRecommendLoading(false) }
  }

  const runAlertCheck = async () => {
    if (!isValid) return
    setAlertsLoading(true)
    try {
      const res = await checkAlerts(portfolioReq)
      setAlerts(res.alerts)
    } catch (e) { console.error(e) }
    finally { setAlertsLoading(false) }
  }

  const runDownloadReport = async () => {
    if (!isValid) return
    setReportLoading(true)
    setReportError(null)
    try {
      const { filename, pdf_base64 } = await generateReport(portfolioReq)
      const byteChars = atob(pdf_base64)
      const bytes = new Uint8Array(byteChars.length)
      for (let i = 0; i < byteChars.length; i++) bytes[i] = byteChars.charCodeAt(i)
      const blob = new Blob([bytes], { type: 'application/pdf' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = filename
      a.click()
      URL.revokeObjectURL(url)
    } catch (e) {
      console.error(e)
      setReportError('Rapor oluşturulamadı.')
    } finally { setReportLoading(false) }
  }

  const m = analysis?.metrics

  // ── JSX ─────────────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-bg text-[#e8e8f0]">

      {/* ── Header ── */}
      <header className="border-b border-white/8 px-6 py-3 flex items-center gap-4 justify-between">
        <div className="flex items-center gap-3 shrink-0">
          <div>
            <span className="font-syne font-bold text-lg tracking-tight">Fin</span>
            <span className="font-syne font-bold text-lg text-gold ml-1">Agent</span>
          </div>
        </div>

        {/* Tab switcher */}
        <div className="flex items-center gap-0.5 bg-bg3 border border-white/8 rounded-lg p-0.5 mx-auto">
          {(['simulator', 'analiz'] as const).map(tab => (
            <button
              key={tab}
              onClick={() => { setActiveTab(tab); if (tab === 'simulator') setChatOpen(false) }}
              className={`px-4 py-1.5 rounded-md text-xs font-semibold transition-all ${
                activeTab === tab
                  ? 'bg-bg2 text-[#e8e8f0] shadow-sm'
                  : 'text-[#6b6b8a] hover:text-[#e8e8f0]'
              }`}
            >
              {tab === 'simulator' ? 'Portföy Simülatörü' : 'Piyasa Analizi'}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-4 shrink-0">
          {/* Market ticker — sadece simülatörde */}
          {activeTab === 'simulator' && market && (
            <div className="hidden lg:flex items-center gap-5 font-mono text-xs text-[#6b6b8a]">
              <span>USD/TRY <span className="text-[#e8e8f0]">{market.usd_try.toFixed(2)}</span></span>
              <span>Altın <span className="text-gold">{market.gold_try.toFixed(0)} ₺</span></span>
              <span>BIST <span className="text-[#3ecf8e]">{market.bist100.toFixed(0)}</span></span>
              <span>TÜFE <span className="text-[#f76f6f]">%{(market.inflation_annual * 100).toFixed(0)}</span></span>
            </div>
          )}
          {/* AI Asistan butonu — sadece simülatörde */}
          {activeTab === 'simulator' && (
            <button
              onClick={() => setChatOpen(o => !o)}
              className="flex items-center gap-2 px-3 py-1.5 rounded-lg border border-white/8
                         text-xs font-semibold hover:border-gold/40 transition-colors"
            >
              <span className="w-1.5 h-1.5 rounded-full bg-[#a78bfa]" style={{
                animation: 'pulse-dot 2s ease-in-out infinite'
              }} />
              {chatOpen ? 'Grafikler' : 'AI Asistan'}
            </button>
          )}
        </div>
      </header>

      <main className="flex h-[calc(100vh-57px)]">

        {/* ── SOL PANEL: Kontroller (sadece simülatörde) ── */}
        {activeTab === 'simulator' && (
        <aside className="w-80 flex-shrink-0 border-r border-white/8 overflow-y-auto p-5 space-y-5">

          {/* Yatırım miktarı */}
          <section>
            <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase mb-2">
              Yatırım miktarı
            </p>
            <div className="flex items-center gap-2 bg-bg3 border border-white/8 rounded-xl px-4 py-2.5">
              <span className="font-mono text-xs text-[#6b6b8a] border-r border-white/10 pr-3">TRY</span>
              <input
                type="number"
                value={amount}
                onChange={e => setAmount(Number(e.target.value))}
                className="bg-transparent outline-none font-mono text-lg w-full text-[#e8e8f0]"
                min={1000} step={10000}
              />
            </div>
          </section>

          {/* Zaman ufku */}
          <section>
            <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase mb-2">
              Zaman ufku
            </p>
            <div className="grid grid-cols-4 gap-1.5">
              {HORIZONS.map(h => (
                <button
                  key={h}
                  onClick={() => setHorizon(h)}
                  className={`py-2 rounded-lg text-sm font-semibold transition-all ${
                    horizon === h
                      ? 'bg-gold/15 border border-gold text-gold'
                      : 'bg-bg3 border border-white/8 text-[#6b6b8a] hover:border-white/20'
                  }`}
                >
                  {h}y
                </button>
              ))}
            </div>
          </section>

          {/* Risk profili */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase">
                Risk profili
              </p>
              <span className="text-[10px] text-[#6b6b8a]">dağılımı otomatik ayarlar</span>
            </div>
            <div className="grid grid-cols-3 gap-1.5">
              {RISK_OPTIONS.map(r => (
                <button
                  key={r.id}
                  onClick={() => {
                    setRisk(r.id)
                    setAllocation({ ...riskPresets[r.id] })
                  }}
                  className={`py-2 rounded-lg text-xs font-semibold transition-all ${
                    risk === r.id
                      ? 'border'
                      : 'bg-bg3 border border-white/8 text-[#6b6b8a] hover:border-white/20'
                  }`}
                  style={risk === r.id ? {
                    background: r.color + '18',
                    borderColor: r.color,
                    color: r.color,
                  } : {}}
                >
                  {r.label}
                </button>
              ))}
            </div>
          </section>

          {/* Varlık dağılımı */}
          <section>
            <div className="flex justify-between items-center mb-3">
              <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase">
                Varlık dağılımı
              </p>
              <span className={`font-mono text-xs px-2 py-0.5 rounded-md ${
                isValid
                  ? 'bg-[#3ecf8e]/10 text-[#3ecf8e]'
                  : 'bg-[#f76f6f]/10 text-[#f76f6f]'
              }`}>
                %{total}
              </span>
            </div>

            {/* Stacked bar */}
            <div className="flex h-1.5 rounded-full overflow-hidden gap-0.5 mb-4">
              {ASSETS.map(a => (
                <div
                  key={a.id}
                  style={{
                    flex: allocation[a.id as keyof typeof allocation],
                    background: a.color,
                    opacity: 0.8,
                    transition: 'flex 0.3s',
                    borderRadius: 2,
                  }}
                />
              ))}
            </div>

            <div className="space-y-3">
              {ASSETS.map(a => {
                const val = allocation[a.id as keyof typeof allocation]
                return (
                  <div key={a.id}>
                    <div className="flex justify-between mb-1.5">
                      <span className="flex items-center gap-2 text-sm font-medium">
                        <span className="w-2 h-2 rounded-full flex-shrink-0"
                              style={{ background: a.color }} />
                        {a.name}
                      </span>
                      <span className="font-mono text-sm text-gold bg-gold/10 px-2 py-0.5 rounded-md">
                        %{val}
                      </span>
                    </div>
                    <input
                      type="range" min={0} max={100} value={val}
                      onChange={e => handleSlider(a.id, Number(e.target.value))}
                      style={{
                        width: '100%',
                        background: `linear-gradient(to right, ${a.color} ${val}%, #18181f ${val}%)`,
                      }}
                    />
                  </div>
                )
              })}
            </div>
          </section>

          {/* Hızlı senaryolar */}
          <section>
            <div className="flex items-center justify-between mb-2">
              <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase">
                Hızlı senaryolar
              </p>
              <span className="text-[10px] text-[#6b6b8a]">şok uygular</span>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              {Object.entries(SCENARIOS).map(([name, { shocks, desc }]) => (
                <button
                  key={name}
                  onClick={() => runQuickScenario(name, shocks)}
                  disabled={!isValid || scenarioLoading}
                  title={desc}
                  className={`py-2 px-2 border rounded-lg text-xs transition-all text-left
                             disabled:opacity-40 disabled:cursor-not-allowed ${
                    activeScenarioName === name
                      ? 'bg-gold/15 border-gold text-gold'
                      : 'bg-bg3 border-white/8 text-[#6b6b8a] hover:border-gold/40 hover:text-gold'
                  }`}
                >
                  {scenarioLoading && activeScenarioName === name ? 'Hesaplanıyor...' : name}
                </button>
              ))}
            </div>
          </section>

          {/* Araçlar: karşılaştırma, öneri, uyarı, rapor */}
          <section>
            <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase mb-2">
              Araçlar
            </p>

            <p className="text-xs text-[#6b6b8a] mb-1.5">Karşılaştır</p>
            <div className="grid grid-cols-2 gap-1.5 mb-3">
              {RISK_OPTIONS.filter(r => r.id !== risk).map(r => (
                <button
                  key={r.id}
                  onClick={() => runCompare(r.id)}
                  disabled={!isValid || compareLoading}
                  className={`py-2 px-2 border rounded-lg text-xs transition-all
                             disabled:opacity-40 disabled:cursor-not-allowed ${
                    compareTarget === r.id
                      ? 'bg-gold/15 border-gold text-gold'
                      : 'bg-bg3 border-white/8 text-[#6b6b8a] hover:border-gold/40 hover:text-gold'
                  }`}
                >
                  {compareLoading && compareTarget === r.id ? 'Hesaplanıyor...' : `vs ${r.label}`}
                </button>
              ))}
            </div>

            <div className="grid grid-cols-3 gap-1.5">
              <button
                onClick={runRecommendation}
                disabled={!isValid || recommendLoading}
                className="py-2 px-1.5 bg-bg3 border border-white/8 rounded-lg text-[11px] text-[#6b6b8a]
                           hover:border-gold/40 hover:text-gold transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {recommendLoading ? '...' : 'Öneri Al'}
              </button>
              <button
                onClick={runAlertCheck}
                disabled={!isValid || alertsLoading}
                className="py-2 px-1.5 bg-bg3 border border-white/8 rounded-lg text-[11px] text-[#6b6b8a]
                           hover:border-gold/40 hover:text-gold transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {alertsLoading ? '...' : 'Uyarılar'}
              </button>
              <button
                onClick={runDownloadReport}
                disabled={!isValid || reportLoading}
                className="py-2 px-1.5 bg-bg3 border border-white/8 rounded-lg text-[11px] text-[#6b6b8a]
                           hover:border-gold/40 hover:text-gold transition-all disabled:opacity-40 disabled:cursor-not-allowed"
              >
                {reportLoading ? '...' : 'PDF İndir'}
              </button>
            </div>
            {reportError && <p className="text-[11px] text-[#f76f6f] mt-1.5">{reportError}</p>}
          </section>

        </aside>
        )}

        {/* ── SAĞ PANEL ── */}
        <div className="flex-1 overflow-y-auto">

          {/* Piyasa Analizi sekmesi */}
          {activeTab === 'analiz' && <InsightsPanel />}

          {/* Portföy Simülatörü sekmesi */}
          {activeTab === 'simulator' && (chatOpen ? (
            <div className="h-full flex flex-col">
              <div className="px-6 py-4 border-b border-white/8">
                <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase">
                  AI Asistan — Açıklama Ajanı
                </p>
              </div>
              <div className="flex-1 min-h-0">
                <ChatPanel portfolio={isValid ? portfolioReq : undefined} />
              </div>
            </div>
          ) : (
            <div className="p-6 space-y-5">

              {/* Geçersiz dağılım uyarısı */}
              {!isValid && (
                <div className="bg-[#f76f6f]/10 border border-[#f76f6f]/30 rounded-xl px-4 py-3 text-sm text-[#f76f6f]">
                  Toplam dağılım %{total} — analiz için %100 olmalı.
                </div>
              )}

              {/* Uyarı banner'ı */}
              {alerts !== null && (
                <div className="bg-bg2 border border-white/8 rounded-xl p-4 fade-in">
                  <div className="flex justify-between items-start mb-2">
                    <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase">
                      Uyarılar
                    </p>
                    <button
                      onClick={() => setAlerts(null)}
                      className="text-[#6b6b8a] hover:text-[#e8e8f0] text-xs font-semibold shrink-0"
                    >
                      ✕ Kapat
                    </button>
                  </div>
                  {alerts.length === 0 ? (
                    <p className="text-xs text-[#3ecf8e]">✓ Uyarı yok</p>
                  ) : (
                    <div className="space-y-2">
                      {alerts.map((a, i) => (
                        <p key={i} className="text-sm flex items-start gap-2" style={{
                          color: a.level === 'warning' ? '#f76f6f' : '#4f8ef7',
                        }}>
                          <span className="mt-1.5 w-1.5 h-1.5 rounded-full shrink-0" style={{
                            background: a.level === 'warning' ? '#f76f6f' : '#4f8ef7',
                          }} />
                          {a.message}
                        </p>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {/* Portföy karşılaştırması */}
              {compareResult && (
                <div className="bg-bg2 border border-gold/30 rounded-xl p-4 fade-in">
                  <div className="flex justify-between items-start mb-3">
                    <p className="text-[10px] font-semibold tracking-widest text-gold uppercase">
                      Karşılaştırma: {compareResult.label_a} vs {compareResult.label_b}
                    </p>
                    <button
                      onClick={clearCompare}
                      className="text-[#6b6b8a] hover:text-[#e8e8f0] text-xs font-semibold shrink-0"
                    >
                      ✕ Kapat
                    </button>
                  </div>

                  <div className="grid grid-cols-2 gap-3 mb-3">
                    {[
                      { label: compareResult.label_a, metrics: compareResult.metrics_a },
                      { label: compareResult.label_b, metrics: compareResult.metrics_b },
                    ].map(side => (
                      <div key={side.label} className="bg-bg3 rounded-lg p-3">
                        <p className="text-[10px] text-[#6b6b8a] uppercase mb-2">{side.label}</p>
                        <p className="font-mono text-lg font-medium" style={{
                          color: side.metrics.real_return_pct >= 0 ? '#3ecf8e' : '#f76f6f',
                        }}>
                          {side.metrics.real_return_pct > 0 ? '+' : ''}
                          {side.metrics.real_return_pct.toFixed(1)}% reel
                        </p>
                        <p className="text-xs text-[#6b6b8a] mt-1">
                          IPS {side.metrics.inflation_protection_score.toFixed(0)}/100 · {fmt(side.metrics.expected_value)}
                        </p>
                      </div>
                    ))}
                  </div>

                  <p className="text-xs text-[#6b6b8a] mb-2">
                    Reel getiride kazanan: <span className="text-[#e8e8f0] font-semibold">{compareResult.winner_by_real_return}</span> ·
                    {' '}IPS'te kazanan: <span className="text-[#e8e8f0] font-semibold">{compareResult.winner_by_ips}</span>
                  </p>
                  <p className="text-sm text-[#e8e8f0] leading-relaxed">{compareResult.ai_comparison}</p>
                </div>
              )}

              {/* Senaryo karşılaştırması */}
              {scenarioResult && activeScenarioName && (
                <div className="bg-bg2 border border-gold/30 rounded-xl p-4 fade-in">
                  <div className="flex justify-between items-start mb-3">
                    <div>
                      <p className="text-[10px] font-semibold tracking-widest text-gold uppercase">
                        Senaryo: {activeScenarioName}
                      </p>
                      <p className="text-xs text-[#6b6b8a] mt-0.5">{SCENARIOS[activeScenarioName].desc}</p>
                    </div>
                    <button
                      onClick={clearScenario}
                      className="text-[#6b6b8a] hover:text-[#e8e8f0] text-xs font-semibold shrink-0"
                    >
                      ✕ Kapat
                    </button>
                  </div>

                  <div className="grid grid-cols-2 gap-3 mb-3">
                    <div className="bg-bg3 rounded-lg p-3">
                      <p className="text-[10px] text-[#6b6b8a] uppercase mb-2">Şimdi</p>
                      <p className="font-mono text-lg font-medium" style={{
                        color: scenarioResult.base_metrics.real_return_pct >= 0 ? '#3ecf8e' : '#f76f6f',
                      }}>
                        {scenarioResult.base_metrics.real_return_pct > 0 ? '+' : ''}
                        {scenarioResult.base_metrics.real_return_pct.toFixed(1)}% reel
                      </p>
                      <p className="text-xs text-[#6b6b8a] mt-1">
                        IPS {scenarioResult.base_metrics.inflation_protection_score.toFixed(0)}/100 · {fmt(scenarioResult.base_metrics.expected_value)}
                      </p>
                    </div>
                    <div className="bg-bg3 rounded-lg p-3 border border-gold/20">
                      <p className="text-[10px] text-gold uppercase mb-2">Senaryo Sonrası</p>
                      <p className="font-mono text-lg font-medium" style={{
                        color: scenarioResult.shocked_metrics.real_return_pct >= 0 ? '#3ecf8e' : '#f76f6f',
                      }}>
                        {scenarioResult.shocked_metrics.real_return_pct > 0 ? '+' : ''}
                        {scenarioResult.shocked_metrics.real_return_pct.toFixed(1)}% reel
                      </p>
                      <p className="text-xs text-[#6b6b8a] mt-1">
                        IPS {scenarioResult.shocked_metrics.inflation_protection_score.toFixed(0)}/100 · {fmt(scenarioResult.shocked_metrics.expected_value)}
                      </p>
                    </div>
                  </div>

                  <p className="text-sm text-[#e8e8f0] leading-relaxed">{scenarioResult.impact_summary}</p>
                </div>
              )}

              {/* Metrik kartları */}
              <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
                {[
                  {
                    label: 'Beklenen Değer',
                    value: m ? fmt(m.expected_value) : '—',
                    sub: `${horizon} yıl sonunda`,
                    color: '#f5c842',
                    highlight: true,
                    tip: '1000 olası gelecek senaryosunun ortalaması — garanti bir sonuç değil, gerçek sonuç daha yüksek veya düşük çıkabilir.',
                    tipAlign: 'left' as const,
                  },
                  {
                    label: 'Reel Getiri',
                    value: m ? `${m.real_return_pct > 0 ? '+' : ''}${m.real_return_pct.toFixed(1)}%` : '—',
                    sub: 'Enflasyon düzeltmeli',
                    color: m && m.real_return_pct >= 0 ? '#3ecf8e' : '#f76f6f',
                    tip: 'Enflasyon düşüldükten sonraki gerçek kazancınız. Nominal getiriniz pozitif olsa bile enflasyon daha yüksekse reel getiri negatif olabilir — alım gücünüz azalmış demektir.',
                    tipAlign: 'right' as const,
                  },
                  {
                    label: 'En Kötü Senaryo',
                    value: m ? fmt(m.monte_carlo.percentile_10) : '—',
                    sub: '%10 ihtimal',
                    color: '#f76f6f',
                    tip: "1000 simüle edilen senaryonun en kötü %10'u bu seviyenin altında kaldı — \"%10 ihtimalle olur\" değil, \"1000 senaryonun %10'u bundan kötü çıktı\" demek.",
                    // grid-cols-2'de bu kart satır başına (sol kenara) düşer,
                    // lg:grid-cols-4'te ortaya doğru kayar — bkz. InfoTooltip'in
                    // flip-lg açıklaması.
                    tipAlign: 'flip-lg' as const,
                  },
                  {
                    label: 'En İyi Senaryo',
                    value: m ? fmt(m.monte_carlo.percentile_90) : '—',
                    sub: '%10 ihtimal',
                    color: '#3ecf8e',
                    tip: "1000 simüle edilen senaryonun en iyi %10'u bu seviyenin üstüne çıktı — \"%10 ihtimalle olur\" değil, \"1000 senaryonun %10'u bundan iyi çıktı\" demek.",
                    tipAlign: 'right' as const,
                  },
                ].map(card => (
                  <div
                    key={card.label}
                    className={`bg-bg2 rounded-xl p-4 border transition-all ${
                      card.highlight ? 'border-gold/30' : 'border-white/8'
                    } ${loading ? 'opacity-60' : 'opacity-100'}`}
                  >
                    <p className="flex items-center gap-1 text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase mb-1">
                      {card.label}
                      <InfoTooltip text={card.tip} align={card.tipAlign} />
                    </p>
                    <p className="font-mono text-2xl font-medium leading-none" style={{ color: card.color }}>
                      {loading ? '...' : card.value}
                    </p>
                    <p className="text-xs text-[#6b6b8a] mt-1">{card.sub}</p>
                  </div>
                ))}
              </div>

              {/* Enflasyon Koruma Skoru */}
              {m && (
                <div className="bg-bg2 border border-white/8 rounded-xl p-4">
                  <div className="flex justify-between items-center mb-3">
                    <p className="flex items-center gap-1 text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase">
                      Enflasyon Koruma Skoru
                      <InfoTooltip
                        text="1000 simüle edilen senaryodan kaçında portföyünüzün enflasyonu yendiğinin yüzdesi. 100 = her senaryoda enflasyonu yendiniz, 0 = hiçbirinde yenemediniz."
                        align="left"
                      />
                    </p>
                    <span className="font-mono text-2xl font-medium" style={{ color: ipsColor(m.inflation_protection_score, ipsThresholds) }}>
                      {m.inflation_protection_score.toFixed(0)}<span className="text-sm text-[#6b6b8a]">/100</span>
                    </span>
                  </div>
                  <div className="h-1.5 bg-bg3 rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full transition-all duration-500"
                      style={{
                        width: `${m.inflation_protection_score}%`,
                        background: ipsColor(m.inflation_protection_score, ipsThresholds),
                      }}
                    />
                  </div>
                  <p className="text-xs text-[#6b6b8a] mt-2">{ipsLabel(m.inflation_protection_score, ipsThresholds)}</p>
                </div>
              )}

              {/* Ek metrikler */}
              {m && (
                <div className="grid grid-cols-3 gap-3">
                  {[
                    {
                      label: 'Volatilite', value: `%${m.annualized_volatility.toFixed(1)}`, color: '#f5c842',
                      tip: 'Portföyünüzün değerinin ne kadar iniş çıkış yapabileceğinin ölçüsü. Yüksek volatilite büyük kazanç da büyük kayıp da olabileceği anlamına gelir.',
                      tipAlign: 'left' as const,
                    },
                    {
                      label: 'Sharpe Oranı', value: m.sharpe_ratio.toFixed(2), color: '#a78bfa',
                      tip: "Aldığınız riske karşılık ne kadar getiri kazandığınızın ölçüsü. Yüksek Sharpe iyidir — genelde 1'in üzeri iyi kabul edilir, 0'ın altı riskin karşılığını alamadığınızı gösterir.",
                      tipAlign: 'right' as const,
                    },
                    {
                      label: 'Maks. Düşüş Est.', value: `%${m.max_drawdown_estimate.toFixed(1)}`, color: '#f76f6f',
                      tip: 'Portföyünüzün zirveden en düşük noktaya ne kadar değer kaybedebileceğinin kaba bir tahmini — simülasyonun kendisinden değil, volatiliteden hesaplanan bir yaklaşık değer.',
                      tipAlign: 'right' as const,
                    },
                  ].map(c => (
                    <div key={c.label} className="bg-bg2 border border-white/8 rounded-xl p-3 text-center">
                      <p className="flex items-center justify-center gap-1 text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase mb-1">
                        {c.label}
                        <InfoTooltip text={c.tip} align={c.tipAlign} />
                      </p>
                      <p className="font-mono text-lg font-medium" style={{ color: c.color }}>{c.value}</p>
                    </div>
                  ))}
                </div>
              )}

              {/* Monte Carlo Grafiği */}
              <div className="bg-bg2 border border-white/8 rounded-xl p-4">
                <div className="flex justify-between items-center mb-4">
                  <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase">
                    Monte Carlo Simülasyonu
                  </p>
                  <div className="flex gap-4 text-[10px] font-mono text-[#6b6b8a]">
                    <span className="flex items-center gap-1.5">
                      <span className="w-3 h-0.5 bg-[#3ecf8e] inline-block rounded" />Medyan
                    </span>
                    <span className="flex items-center gap-1.5">
                      <span className="w-3 h-0.5 bg-[#f76f6f] inline-block rounded" style={{ borderTop: '1px dashed #f76f6f', background: 'transparent' }} />Enflasyon
                    </span>
                  </div>
                </div>
                {m ? (
                  <MonteCarloChart
                    mc={m.monte_carlo}
                    amount={amount}
                    inflationRate={analysis!.inflation_rate_used}
                    horizonYears={horizon}
                  />
                ) : (
                  <div className="h-[220px] flex items-center justify-center text-[#6b6b8a] text-sm">
                    {isValid ? 'Yükleniyor...' : 'Geçerli bir dağılım girin'}
                  </div>
                )}
              </div>

              {/* AI Yorumu */}
              {analysis?.ai_insight && (
                <div className="bg-bg2 border border-white/8 rounded-xl p-4 fade-in">
                  <div className="flex items-center gap-2 mb-3">
                    <span
                      className="w-2 h-2 rounded-full bg-[#a78bfa]"
                      style={{ animation: 'pulse-dot 2s ease-in-out infinite' }}
                    />
                    <p className="text-[10px] font-semibold tracking-widest text-[#a78bfa] uppercase">
                      AI Analizi
                    </p>
                  </div>
                  <p className="text-sm text-[#e8e8f0] leading-relaxed">{analysis.ai_insight}</p>
                </div>
              )}

              {/* Öneri kartı */}
              {recommendation && (
                <div className="bg-bg2 border border-white/8 rounded-xl p-4 fade-in">
                  <div className="flex justify-between items-start mb-3">
                    <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase">
                      Önerilen Dağılım — {RISK_OPTIONS.find(r => r.id === recommendation.risk_profile)?.label ?? recommendation.risk_profile}
                    </p>
                    <button
                      onClick={() => setRecommendation(null)}
                      className="text-[#6b6b8a] hover:text-[#e8e8f0] text-xs font-semibold shrink-0"
                    >
                      ✕ Kapat
                    </button>
                  </div>

                  <div className="flex h-1.5 rounded-full overflow-hidden gap-0.5 mb-3">
                    {ASSETS.map(a => (
                      <div
                        key={a.id}
                        style={{
                          flex: recommendation.suggested_allocation[a.id as keyof typeof recommendation.suggested_allocation],
                          background: a.color,
                          opacity: 0.8,
                          borderRadius: 2,
                        }}
                      />
                    ))}
                  </div>
                  <div className="flex flex-wrap gap-x-4 gap-y-1 mb-3">
                    {ASSETS.map(a => (
                      <span key={a.id} className="flex items-center gap-1.5 text-xs text-[#6b6b8a]">
                        <span className="w-2 h-2 rounded-full" style={{ background: a.color }} />
                        {a.name} <span className="font-mono text-[#e8e8f0]">
                          %{recommendation.suggested_allocation[a.id as keyof typeof recommendation.suggested_allocation]}
                        </span>
                      </span>
                    ))}
                  </div>

                  {recommendation.projected_metrics && (
                    <p className="text-xs text-[#6b6b8a] mb-2">
                      Projeksiyon: {fmt(recommendation.projected_metrics.expected_value)} · IPS {recommendation.projected_metrics.inflation_protection_score.toFixed(0)}/100 ·
                      {' '}reel getiri {recommendation.projected_metrics.real_return_pct > 0 ? '+' : ''}{recommendation.projected_metrics.real_return_pct.toFixed(1)}%
                    </p>
                  )}

                  <p className="text-sm text-[#e8e8f0] leading-relaxed mb-3">{recommendation.rationale}</p>

                  <button
                    onClick={() => setAllocation({ ...recommendation.suggested_allocation })}
                    className="px-3 py-1.5 bg-gold text-bg text-xs font-semibold rounded-lg hover:bg-gold2 transition-colors"
                  >
                    Bu dağılımı uygula
                  </button>
                </div>
              )}

            </div>
          ))}
        </div>
      </main>
    </div>
  )
}
