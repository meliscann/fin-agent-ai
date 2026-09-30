'use client'

import { useEffect, useState } from 'react'
import {
  LineChart, Line, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, ResponsiveContainer, CartesianGrid,
  ReferenceLine,
} from 'recharts'
import {
  getCaseStudyData, CaseStudyData,
  NormalizedPoint, BacktestAsset, RealVsNominalAsset, PortfolioModel,
} from '@/lib/api'

// ── Stil sabitleri ─────────────────────────────────────────────────────────────
const TICK  = { fontSize: 10, fill: '#6b6b8a', fontFamily: 'var(--font-mono)' }
const GRID  = { stroke: 'rgba(255,255,255,0.04)' }
const CARD  = 'bg-bg2 border border-white/8 rounded-xl p-4'

// ── Tooltip bileşenleri ────────────────────────────────────────────────────────

function NormTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-bg2 border border-white/10 rounded-xl p-3 text-xs font-mono min-w-[160px]">
      <p className="text-[#6b6b8a] mb-2">{label}</p>
      {payload
        .slice()
        .sort((a: any, b: any) => b.value - a.value)
        .map((e: any) => (
          <p key={e.name} style={{ color: e.color }} className="my-0.5">
            {e.name}: <span className="font-semibold">{e.value}x</span>
          </p>
        ))}
    </div>
  )
}

function InflTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-bg2 border border-white/10 rounded-xl p-3 text-xs font-mono">
      <p className="text-[#6b6b8a] mb-2">{label}</p>
      {payload.map((e: any) => (
        <p key={e.name} style={{ color: e.color }} className="my-0.5">
          {e.name}: <span className="font-semibold">%{e.value.toFixed(1)}</span>
        </p>
      ))}
    </div>
  )
}

// ── Yardımcı ──────────────────────────────────────────────────────────────────

function ScoreCell({ score }: { score: number }) {
  const cfg: Record<number, { bg: string; text: string; label: string }> = {
    1: { bg: 'rgba(247,111,111,0.25)', text: '#f76f6f', label: '1' },
    2: { bg: 'rgba(247,111,111,0.12)', text: '#f7a06f', label: '2' },
    3: { bg: 'rgba(245,200,66,0.18)',  text: '#f5c842', label: '3' },
    4: { bg: 'rgba(62,207,142,0.15)',  text: '#3ecf8e', label: '4' },
    5: { bg: 'rgba(62,207,142,0.30)',  text: '#3ecf8e', label: '5' },
  }
  const c = cfg[score] ?? cfg[3]
  return (
    <div
      className="flex items-center justify-center rounded-lg text-sm font-bold font-mono h-10"
      style={{ background: c.bg, color: c.text }}
    >
      {c.label}
    </div>
  )
}

// ── Backtest çubukları ─────────────────────────────────────────────────────────

function BacktestBars({ data }: { data: BacktestAsset[] }) {
  const max = Math.max(...data.map(d => d.value))
  return (
    <div className="space-y-2.5">
      {data.map(item => {
        const pct = (item.value / max) * 100
        const positive = item.gain > 0
        return (
          <div key={item.name} className="flex items-center gap-3">
            <span className="w-20 text-xs font-mono text-right text-[#6b6b8a] shrink-0">
              {item.name}
            </span>
            <div className="flex-1 h-8 bg-bg3 rounded-lg overflow-hidden relative">
              <div
                className="h-full rounded-lg transition-all duration-700"
                style={{ width: `${pct}%`, background: item.color + 'bb' }}
              />
              <div className="absolute inset-0 flex items-center justify-between px-3">
                <span className="text-xs font-mono text-[#e8e8f0] font-semibold">
                  {item.value.toLocaleString('tr-TR')} ₺
                </span>
              </div>
            </div>
            <span
              className="w-16 text-xs font-mono text-right shrink-0 font-semibold"
              style={{ color: positive ? '#3ecf8e' : '#f76f6f' }}
            >
              {positive ? '+' : ''}{item.gain}%
            </span>
          </div>
        )
      })}
      {/* Başlangıç referansı */}
      <div className="flex items-center gap-3 pt-1 border-t border-white/8">
        <span className="w-20 text-xs font-mono text-right text-[#6b6b8a] shrink-0">Başlangıç</span>
        <div className="flex-1 h-px bg-[#f76f6f]/40 relative">
          <div
            className="absolute top-1/2 -translate-y-1/2 h-2.5 w-px bg-[#f76f6f]/60"
            style={{ left: `${(100_000 / max) * 100}%` }}
          />
        </div>
        <span className="w-16 text-xs font-mono text-right text-[#6b6b8a] shrink-0">100.000 ₺</span>
      </div>
    </div>
  )
}

// ── Reel getiri çubukları ──────────────────────────────────────────────────────

function RealReturnBars({ data }: { data: RealVsNominalAsset[] }) {
  const absMax = Math.max(...data.map(d => Math.abs(d.real)), 100)
  return (
    <div className="space-y-2.5">
      {data.map(item => {
        const positive = item.real >= 0
        const barPct = (Math.abs(item.real) / absMax) * 100
        const color = positive ? '#3ecf8e' : '#f76f6f'
        return (
          <div key={item.name} className="flex items-center gap-3">
            <span className="w-20 text-xs font-mono text-right text-[#6b6b8a] shrink-0">
              {item.name}
            </span>
            <div className="flex-1 flex items-center gap-1.5">
              {/* sıfır referansı için orta çizgi */}
              {positive ? (
                <>
                  <div className="w-1 h-8 bg-white/5 rounded-sm shrink-0" />
                  <div
                    className="h-8 rounded-r-lg transition-all duration-700 flex items-center pl-2"
                    style={{ width: `${barPct}%`, minWidth: 4, background: color + 'aa' }}
                  >
                    <span className="text-xs font-mono text-[#e8e8f0] font-semibold whitespace-nowrap">
                      +{item.real.toFixed(1)}%
                    </span>
                  </div>
                </>
              ) : (
                <>
                  <div
                    className="h-8 rounded-l-lg transition-all duration-700 flex items-center justify-end pr-2 ml-auto"
                    style={{ width: `${barPct}%`, minWidth: 4, background: color + 'aa' }}
                  >
                    <span className="text-xs font-mono text-[#e8e8f0] font-semibold whitespace-nowrap">
                      {item.real.toFixed(1)}%
                    </span>
                  </div>
                  <div className="w-1 h-8 bg-white/5 rounded-sm shrink-0" />
                </>
              )}
            </div>
            <span className="w-20 text-xs font-mono text-right text-[#6b6b8a] shrink-0">
              nominal {item.nominal >= 1000
                ? `+${(item.nominal / 100).toFixed(0)}x`
                : `+${item.nominal.toFixed(0)}%`}
            </span>
          </div>
        )
      })}
    </div>
  )
}

// ── Portföy pasta grafiği ──────────────────────────────────────────────────────

function ModelPie({ model }: { model: PortfolioModel }) {
  const [active, setActive] = useState<number | null>(null)
  return (
    <div className={CARD}>
      <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase mb-3">
        {model.name}
      </p>
      <ResponsiveContainer width="100%" height={180}>
        <PieChart>
          <Pie
            data={model.slices}
            dataKey="value"
            nameKey="name"
            cx="50%"
            cy="50%"
            innerRadius={48}
            outerRadius={76}
            paddingAngle={2}
            onMouseEnter={(_, i) => setActive(i)}
            onMouseLeave={() => setActive(null)}
          >
            {model.slices.map((s, i) => (
              <Cell
                key={s.name}
                fill={s.color}
                fillOpacity={active === null || active === i ? 0.85 : 0.3}
                stroke="transparent"
              />
            ))}
          </Pie>
          <Tooltip
            content={({ active: a, payload: p }) => {
              if (!a || !p?.length) return null
              const item = p[0].payload as typeof model.slices[0]
              return (
                <div className="bg-bg2 border border-white/10 rounded-xl p-2.5 text-xs font-mono">
                  <p style={{ color: item.color }} className="font-semibold">{item.name}</p>
                  <p className="text-[#e8e8f0]">%{item.value}</p>
                </div>
              )
            }}
          />
        </PieChart>
      </ResponsiveContainer>
      {/* Legend */}
      <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 mt-2">
        {model.slices.map(s => (
          <div key={s.name} className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-sm shrink-0" style={{ background: s.color }} />
            <span className="text-[10px] text-[#6b6b8a] truncate">{s.name}</span>
            <span className="text-[10px] font-mono text-[#e8e8f0] ml-auto">%{s.value}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Ana bileşen ────────────────────────────────────────────────────────────────

export default function InsightsPanel() {
  const [data, setData] = useState<CaseStudyData | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getCaseStudyData()
      .then(setData)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full text-[#6b6b8a] text-sm">
        Veri yükleniyor…
      </div>
    )
  }

  if (error || !data) {
    return (
      <div className="flex items-center justify-center h-full text-[#f76f6f] text-sm">
        Veri alınamadı — backend çalışıyor mu?
      </div>
    )
  }

  const { key_stats: ks, normalized_performance, inflation_policy,
          backtest_100k, real_vs_nominal, decision_matrix, portfolio_models } = data

  // "2020-01 → 2026-09" -> "2020–2026" (başlıklardaki kısa yıl aralığı için)
  const analysisYearRange = ks.analysis_period.split(' → ').map(s => s.slice(0, 4)).join('–')

  // Normalize veriyi "x katı" olarak göster (100 → 1.0x, 1748 → 17.48x)
  const normData = normalized_performance.map(p => ({
    ...p,
    gold:   +(p.gold   / 100).toFixed(2),
    usd:    +(p.usd    / 100).toFixed(2),
    eur:    +(p.eur    / 100).toFixed(2),
    bist100:+(p.bist100/ 100).toFixed(2),
    tufe:   +(p.tufe   / 100).toFixed(2),
  }))

  return (
    <div className="p-6 space-y-5 fade-in">

      {/* ── Başlık ── */}
      <div className="flex items-baseline justify-between">
        <div>
          <h2 className="font-syne font-bold text-base">
            Vaka Çalışması
            <span className="ml-2 text-[#6b6b8a] font-normal text-sm">{analysisYearRange}</span>
          </h2>
          <p className="text-[10px] text-[#6b6b8a] mt-0.5">
            Yüksek Enflasyon Ortamında Portföy Analizi · TCMB EVDS & Yahoo Finance
          </p>
        </div>
        <span className="text-[10px] font-mono text-[#6b6b8a]">{ks.analysis_period}</span>
      </div>

      {/* ── Anahtar metrikler ── */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          {
            label: 'Toplam Enflasyon',
            value: `%${ks.total_inflation_pct.toFixed(0)}`,
            sub: analysisYearRange,
            color: '#f76f6f',
          },
          {
            label: `${ks.best_asset} Reel Getiri`,
            value: `${ks.best_real_return_pct > 0 ? '+' : ''}%${ks.best_real_return_pct.toFixed(0)}`,
            sub: 'En yüksek reel getiri',
            color: '#f5c842',
          },
          {
            label: 'Mevduat Reel Kaybı',
            value: `%${ks.deposit_real_return_pct.toFixed(0)}`,
            sub: 'Enflasyon düzeltmeli',
            color: '#f76f6f',
          },
          {
            label: 'Nakit Değer Kaybı',
            value: `-%${ks.cash_loss_pct.toFixed(0)}`,
            sub: 'Alım gücü eriyor',
            color: '#f76f6f',
          },
        ].map(c => (
          <div key={c.label} className={CARD}>
            <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase mb-1">
              {c.label}
            </p>
            <p className="font-mono text-2xl font-medium leading-none" style={{ color: c.color }}>
              {c.value}
            </p>
            <p className="text-xs text-[#6b6b8a] mt-1">{c.sub}</p>
          </div>
        ))}
      </div>

      {/* ── Normalize performans ── */}
      <div className={CARD}>
        <div className="flex items-center justify-between mb-4">
          <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase">
            Varlık Performansı (2020 = 1×)
          </p>
          <div className="hidden md:flex items-center gap-4 text-[10px] font-mono">
            {[
              { key: 'gold',    label: 'Altın',     color: '#f5c842' },
              { key: 'bist100', label: 'BIST 100',  color: '#3ecf8e' },
              { key: 'usd',     label: 'Dolar',     color: '#4f8ef7' },
              { key: 'eur',     label: 'Euro',      color: '#a78bfa' },
              { key: 'tufe',    label: 'Enflasyon', color: '#f76f6f' },
            ].map(l => (
              <span key={l.key} className="flex items-center gap-1.5" style={{ color: l.color }}>
                <span className="w-3 h-0.5 rounded inline-block" style={{ background: l.color }} />
                {l.label}
              </span>
            ))}
          </div>
        </div>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={normData} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="date" tick={TICK} axisLine={false} tickLine={false} interval={2} />
            <YAxis
              tick={TICK} axisLine={false} tickLine={false} width={40}
              tickFormatter={v => v + 'x'}
            />
            <Tooltip content={<NormTooltip />} />
            <Line dataKey="gold"    stroke="#f5c842" strokeWidth={2.5} dot={false} name="Altın" />
            <Line dataKey="bist100" stroke="#3ecf8e" strokeWidth={2}   dot={false} name="BIST 100" />
            <Line dataKey="usd"     stroke="#4f8ef7" strokeWidth={1.5} dot={false} name="Dolar" />
            <Line dataKey="eur"     stroke="#a78bfa" strokeWidth={1.5} dot={false} name="Euro" />
            <Line dataKey="tufe"    stroke="#f76f6f" strokeWidth={2}   dot={false} name="Enflasyon"
                  strokeDasharray="5 3" />
          </LineChart>
        </ResponsiveContainer>
        <p className="text-[10px] text-[#6b6b8a] mt-2">
          Altın {analysisYearRange.split('–')[0]} başından bu yana yaklaşık{' '}
          <span className="text-[#f5c842]">{normData[normData.length - 1]?.gold.toFixed(1)}×</span> büyürken,
          nakit tutan yatırımcı alım gücünün <span className="text-[#f76f6f]">%{ks.cash_loss_pct.toFixed(0)}'ini</span> kaybetti.
        </p>
      </div>

      {/* ── Enflasyon vs Politika Faizi ── */}
      <div className={CARD}>
        <div className="flex items-center justify-between mb-4">
          <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase">
            Enflasyon vs Politika Faizi ({inflation_policy[0]?.date.slice(0, 4)}–{analysisYearRange.split('–')[1]})
          </p>
          <div className="flex items-center gap-4 text-[10px] font-mono">
            <span className="flex items-center gap-1.5 text-[#f76f6f]">
              <span className="w-3 h-0.5 bg-[#f76f6f] rounded inline-block" />Enflasyon
            </span>
            <span className="flex items-center gap-1.5 text-[#4f8ef7]">
              <span className="w-3 h-px inline-block" style={{
                borderTop: '1px dashed #4f8ef7'
              }} />Politika Faizi
            </span>
          </div>
        </div>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={inflation_policy} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
            <CartesianGrid {...GRID} />
            <XAxis dataKey="date" tick={TICK} axisLine={false} tickLine={false} interval={4} />
            <YAxis
              tick={TICK} axisLine={false} tickLine={false} width={38}
              tickFormatter={v => '%' + v}
            />
            <Tooltip content={<InflTooltip />} />
            <ReferenceLine y={5} stroke="rgba(62,207,142,0.25)" strokeDasharray="3 3" />
            <Line dataKey="inflation" stroke="#f76f6f" strokeWidth={2}
                  dot={false} name="Enflasyon" />
            <Line dataKey="policy"    stroke="#4f8ef7" strokeWidth={2}
                  dot={false} name="Politika Faizi" strokeDasharray="6 3" />
          </LineChart>
        </ResponsiveContainer>
        <p className="text-[10px] text-[#6b6b8a] mt-2">
          Politika faizi 2022'de <span className="text-[#f76f6f]">enflasyonun çok altında</span> kaldı.
          2023 sonunda tırmanan faiz ile mücadele başladı; güncel oran{' '}
          <span className="text-[#4f8ef7]">%{ks.current_policy_rate}</span>,
          enflasyon <span className="text-[#f76f6f]">%{ks.current_inflation}</span>.
        </p>
      </div>

      {/* ── 100K Backtest + Reel Getiri ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">

        {/* Backtest */}
        <div className={CARD}>
          <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase mb-1">
            100.000 ₺ Yatırsaydın
          </p>
          <p className="text-[10px] text-[#6b6b8a] mb-4">{ks.backtest_period}</p>
          <BacktestBars data={backtest_100k} />
        </div>

        {/* Reel Getiri */}
        <div className={CARD}>
          <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase mb-1">
            Reel Getiri Analizi
          </p>
          <p className="text-[10px] text-[#6b6b8a] mb-4">
            {analysisYearRange} · Enflasyon düzeltmeli · Toplam enflasyon:{' '}
            <span className="text-[#f76f6f]">%{ks.total_inflation_pct}</span>
          </p>
          <RealReturnBars data={real_vs_nominal} />
          <p className="text-[10px] text-[#6b6b8a] mt-4 leading-relaxed">
            Nominal getiriler yanıltıcı —{' '}
            <span className="text-[#f5c842]">sadece altın</span> enflasyonu geçerek
            reel kazanç sağladı.
          </p>
        </div>
      </div>

      {/* ── Karar Matrisi ── */}
      <div className={CARD}>
        <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase mb-4">
          Karar Matrisi — 5 Kriter × 5 Araç (1=Zayıf · 5=Güçlü)
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr>
                <th className="text-left text-[#6b6b8a] font-semibold pb-2 pr-4 font-mono min-w-[100px]">
                  Araç
                </th>
                {decision_matrix.criteria.map(c => (
                  <th
                    key={c}
                    className="text-center text-[#6b6b8a] font-semibold pb-2 px-1 font-mono text-[10px] leading-tight min-w-[80px]"
                  >
                    {c}
                  </th>
                ))}
                <th className="text-center text-[#6b6b8a] font-semibold pb-2 pl-4 font-mono text-[10px] min-w-[72px]">
                  Temkinli
                </th>
                <th className="text-center text-[#6b6b8a] font-semibold pb-2 pl-1 font-mono text-[10px] min-w-[72px]">
                  Büyüme
                </th>
              </tr>
            </thead>
            <tbody>
              {decision_matrix.instruments.map((inst, i) => {
                const scores = decision_matrix.scores[i]
                const wT = decision_matrix.profile_weights.temkinli
                const wB = decision_matrix.profile_weights.buyume
                const scoreT = scores.reduce((s, v, j) => s + v * wT[j], 0)
                const scoreB = scores.reduce((s, v, j) => s + v * wB[j], 0)
                return (
                  <tr key={inst} className="border-t border-white/5">
                    <td className="py-1.5 pr-4 font-mono text-[#e8e8f0] font-medium">{inst}</td>
                    {scores.map((score, j) => (
                      <td key={j} className="py-1.5 px-1">
                        <ScoreCell score={score} />
                      </td>
                    ))}
                    <td className="py-1.5 pl-4 text-center font-mono font-bold text-[#3ecf8e]">
                      {scoreT.toFixed(2)}
                    </td>
                    <td className="py-1.5 pl-1 text-center font-mono font-bold text-[#f5c842]">
                      {scoreB.toFixed(2)}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        <div className="flex gap-4 mt-3 text-[10px] font-mono text-[#6b6b8a]">
          {[1, 2, 3, 4, 5].map(s => (
            <ScoreLabel key={s} score={s} />
          ))}
        </div>
      </div>

      {/* ── Portföy Modelleri ── */}
      <div>
        <p className="text-[10px] font-semibold tracking-widest text-[#6b6b8a] uppercase mb-3">
          Önerilen Portföy Dağılım Modelleri
        </p>
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
          {portfolio_models.map(m => <ModelPie key={m.name} model={m} />)}
        </div>
      </div>

      {/* ── Footer ── */}
      <div className="text-[10px] text-[#6b6b8a] font-mono pt-2 border-t border-white/5">
        Kaynak: TCMB EVDS API · Yahoo Finance (yfinance) · Analiz: Melis CAN · veriler saatlik canlı güncellenir
      </div>

    </div>
  )
}

function ScoreLabel({ score }: { score: number }) {
  const cfg: Record<number, { color: string; label: string }> = {
    1: { color: '#f76f6f', label: '1 Zayıf' },
    2: { color: '#f7a06f', label: '2 Düşük' },
    3: { color: '#f5c842', label: '3 Orta' },
    4: { color: '#3ecf8e', label: '4 İyi' },
    5: { color: '#3ecf8e', label: '5 Güçlü' },
  }
  const c = cfg[score]
  return (
    <span className="flex items-center gap-1">
      <span
        className="w-3 h-3 rounded-sm"
        style={{ background: c.color + (score >= 4 ? '50' : '30') }}
      />
      {c.label}
    </span>
  )
}
