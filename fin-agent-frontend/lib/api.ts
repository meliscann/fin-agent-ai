const BASE = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

export interface Allocation {
  gold: number; usd: number; bist100: number; bond: number; tufe_bond: number; deposit: number
}

export interface PortfolioRequest {
  amount: number
  horizon_years: 1 | 3 | 5 | 10
  risk_profile: 'temkinli' | 'dengeli' | 'buyume'
  allocation: Allocation
}

export interface MonteCarloResult {
  percentile_10: number; percentile_25: number; percentile_50: number
  percentile_75: number; percentile_90: number
  expected: number; worst: number; best: number
  paths_sample: number[][]
}

export interface PortfolioMetrics {
  expected_value: number
  nominal_return_pct: number
  real_return_pct: number
  inflation_protection_score: number
  annualized_volatility: number
  sharpe_ratio: number
  max_drawdown_estimate: number
  monte_carlo: MonteCarloResult
}

export interface AnalysisResponse {
  metrics: PortfolioMetrics
  ai_insight: string
  inflation_rate_used: number
  computed_at: string
}

export interface MarketData {
  usd_try: number; gold_try: number; bist100: number
  inflation_annual: number; policy_rate: number; fetched_at: string
}

export async function analyzePortfolio(req: PortfolioRequest): Promise<AnalysisResponse> {
  const res = await fetch(`${BASE}/api/portfolio/analyze`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface Shocks {
  inflation_delta?: number
  usd_shock?: number
  policy_rate_delta?: number
  bist_shock?: number
}

export interface ScenarioResponse {
  base_metrics: PortfolioMetrics
  shocked_metrics: PortfolioMetrics
  impact_summary: string
  shocks_applied: Shocks
}

export async function runScenario(
  basePortfolio: PortfolioRequest,
  shocks: Shocks
): Promise<ScenarioResponse> {
  const res = await fetch(`${BASE}/api/portfolio/scenario`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ base_portfolio: basePortfolio, shocks }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function chatWithAgent(
  message: string,
  history: { role: string; content: string }[],
  portfolio?: PortfolioRequest
) {
  const res = await fetch(`${BASE}/api/agents/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, history, portfolio_context: portfolio ?? null }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface CompareResponse {
  label_a: string; label_b: string
  metrics_a: PortfolioMetrics; metrics_b: PortfolioMetrics
  winner_by_real_return: string; winner_by_ips: string
  ai_comparison: string
}

export async function comparePortfolios(
  portfolioA: PortfolioRequest,
  portfolioB: PortfolioRequest,
  labelA: string,
  labelB: string
): Promise<CompareResponse> {
  const res = await fetch(`${BASE}/api/portfolio/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ portfolio_a: portfolioA, portfolio_b: portfolioB, label_a: labelA, label_b: labelB }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface AlertItem {
  level: 'warning' | 'info'
  code: string
  message: string
}

export interface RecommendationResult {
  risk_profile: string
  suggested_allocation: Allocation
  projected_metrics: {
    expected_value: number
    inflation_protection_score: number
    real_return_pct: number
  } | null
  rationale: string
}

export interface ReportResult {
  filename: string
  pdf_base64: string
  content_type: string
}

async function orchestrate(
  message: string,
  portfolio: PortfolioRequest,
  runAgents: string[],
  extra?: Record<string, unknown>
): Promise<{ agent_results: Record<string, any> }> {
  const res = await fetch(`${BASE}/api/agents/orchestrate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, portfolio, run_agents: runAgents, ...extra }),
  })
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export async function generateReport(portfolio: PortfolioRequest): Promise<ReportResult> {
  const { agent_results } = await orchestrate('PDF rapor oluştur', portfolio, ['report'])
  return agent_results.report
}

export async function checkAlerts(portfolio: PortfolioRequest): Promise<{ alerts: AlertItem[] }> {
  // Eşik gönderilmez — backend'in kendi varsayılanı (IPS_THRESHOLDS["weak"])
  // zaten tek doğru kaynaktan geliyor, burada tekrar hardcode etmeye gerek yok.
  const { agent_results } = await orchestrate('Uyarıları kontrol et', portfolio, ['alert'])
  return agent_results.alert
}

export async function getRecommendation(portfolio: PortfolioRequest): Promise<RecommendationResult> {
  const { agent_results } = await orchestrate('Risk profilime göre öneri ver', portfolio, ['recommendation'])
  return agent_results.recommendation
}

export async function getMarketData(): Promise<MarketData> {
  const res = await fetch(`${BASE}/api/portfolio/market-data`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

export interface PortfolioConfig {
  risk_presets: Record<'temkinli' | 'dengeli' | 'buyume', Allocation>
  ips_thresholds: { weak: number; strong: number }
}

// Risk preset'leri ve IPS eşikleri için tek kaynak backend'dir (bkz.
// app/core/analysis/monte_carlo.py: IPS_THRESHOLDS, app/agents/__init__.py:
// RISK_PRESETS) — page.tsx bunu hardcode etmek yerine sayfa açılışında çeker.
export async function getPortfolioConfig(): Promise<PortfolioConfig> {
  const res = await fetch(`${BASE}/api/portfolio/config`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}

// ── Case Study / Insights ─────────────────────────────────────────────────────

export interface NormalizedPoint {
  date: string; gold: number; usd: number; eur: number; bist100: number; tufe: number
}

export interface InflationPolicyPoint {
  date: string; inflation: number; policy: number
}

export interface BacktestAsset {
  name: string; value: number; gain: number; color: string
}

export interface RealVsNominalAsset {
  name: string; nominal: number; real: number
}

export interface DecisionMatrix {
  criteria: string[]
  instruments: string[]
  scores: number[][]
  profile_weights: { temkinli: number[]; buyume: number[] }
}

export interface PortfolioSlice {
  name: string; value: number; color: string
}

export interface PortfolioModel {
  name: string; profile: string; slices: PortfolioSlice[]
}

export interface KeyStats {
  total_inflation_pct: number
  best_asset: string
  best_real_return_pct: number
  cash_loss_pct: number
  deposit_real_return_pct: number
  analysis_period: string
  backtest_period: string
  current_inflation: number
  current_policy_rate: number
}

export interface CaseStudyData {
  key_stats: KeyStats
  normalized_performance: NormalizedPoint[]
  inflation_policy: InflationPolicyPoint[]
  backtest_100k: BacktestAsset[]
  real_vs_nominal: RealVsNominalAsset[]
  decision_matrix: DecisionMatrix
  portfolio_models: PortfolioModel[]
}

export async function getCaseStudyData(): Promise<CaseStudyData> {
  const res = await fetch(`${BASE}/api/insights/case-study`)
  if (!res.ok) throw new Error(await res.text())
  return res.json()
}
