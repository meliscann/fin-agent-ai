'use client'

import {
  ComposedChart, Area, Line, XAxis, YAxis,
  Tooltip, ResponsiveContainer, CartesianGrid,
} from 'recharts'
import { MonteCarloResult } from '@/lib/api'

interface Props {
  mc: MonteCarloResult
  amount: number
  inflationRate: number
  horizonYears: number
}

function fmt(v: number) {
  if (v >= 1_000_000) return (v / 1_000_000).toFixed(1) + 'M'
  if (v >= 1_000) return (v / 1_000).toFixed(0) + 'K'
  return v.toFixed(0)
}

function computeBands(paths: number[][]): {
  t: number; p10: number; p25: number; p50: number; p75: number; p90: number
}[] {
  if (!paths?.length) return []
  const steps = paths[0].length
  return Array.from({ length: steps }, (_, t) => {
    const vals = paths.map(p => p[t]).sort((a, b) => a - b)
    const p = (pct: number) => vals[Math.max(0, Math.floor(vals.length * pct / 100))]
    return { t, p10: p(10), p25: p(25), p50: p(50), p75: p(75), p90: p(90) }
  })
}

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null
  const months = Number(label)
  const label2 = months === 0 ? 'Bugün' : months % 12 === 0 ? `${months / 12}. yıl` : `${months}. ay`
  return (
    <div className="bg-bg2 border border-white/10 rounded-xl p-3 text-xs font-mono">
      <p className="text-[#6b6b8a] mb-2">{label2}</p>
      {payload.map((e: any) => (
        <p key={e.name} style={{ color: e.color }} className="my-0.5">
          {e.name}: {fmt(e.value)} ₺
        </p>
      ))}
    </div>
  )
}

export default function MonteCarloChart({ mc, amount, inflationRate, horizonYears }: Props) {
  const bands = computeBands(mc.paths_sample)
  const steps = bands.length

  // Enflasyon çizgisi
  const data = bands.map((b, i) => ({
    ...b,
    inflation: amount * Math.pow(1 + inflationRate / 12, i),
    range90: [b.p10, b.p90] as [number, number],
    range50: [b.p25, b.p75] as [number, number],
  }))

  const tickFormatter = (v: number) => {
    const months = Number(v)
    if (months === 0) return 'Bugün'
    if (months % 12 === 0) return `${months / 12}y`
    return ''
  }

  const yMax = Math.max(mc.percentile_90, amount * Math.pow(1 + inflationRate, horizonYears)) * 1.05

  return (
    <ResponsiveContainer width="100%" height={220}>
      <ComposedChart data={data} margin={{ top: 4, right: 8, left: 0, bottom: 0 }}>
        <CartesianGrid stroke="rgba(255,255,255,0.04)" strokeDasharray="0" />
        <XAxis
          dataKey="t"
          tickFormatter={tickFormatter}
          tick={{ fontSize: 10, fill: '#6b6b8a', fontFamily: 'var(--font-mono)' }}
          axisLine={false} tickLine={false}
        />
        <YAxis
          tickFormatter={v => fmt(v) + ' ₺'}
          tick={{ fontSize: 10, fill: '#6b6b8a', fontFamily: 'var(--font-mono)' }}
          axisLine={false} tickLine={false} width={58}
          domain={[0, yMax]}
        />
        <Tooltip content={<CustomTooltip />} />

        {/* %90-%10 band */}
        <Area
          dataKey="p90" stroke="transparent"
          fill="rgba(62,207,142,0.07)" name="%90"
        />
        <Area
          dataKey="p10" stroke="transparent"
          fill="rgba(62,207,142,0.07)" name="%10"
        />

        {/* %75-%25 band */}
        <Area
          dataKey="p75" stroke="transparent"
          fill="rgba(62,207,142,0.12)" name="%75"
        />
        <Area
          dataKey="p25" stroke="transparent"
          fill="rgba(62,207,142,0.12)" name="%25"
        />

        {/* Medyan */}
        <Line
          dataKey="p50" stroke="#3ecf8e" strokeWidth={2}
          dot={false} name="Medyan"
        />

        {/* Enflasyon */}
        <Line
          dataKey="inflation" stroke="rgba(247,111,111,0.6)"
          strokeWidth={1.5} strokeDasharray="4 4"
          dot={false} name="Enflasyon"
        />
      </ComposedChart>
    </ResponsiveContainer>
  )
}
