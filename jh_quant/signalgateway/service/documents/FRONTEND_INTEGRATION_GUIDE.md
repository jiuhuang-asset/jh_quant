# SignalGateway Service Frontend Integration Guide v3

Document version: `v3`

This guide covers frontend integration patterns for the SignalGateway HTTP API. For the full endpoint reference, see [API_DOCUMENTATION.md](API_DOCUMENTATION.md).

## 1. Architecture Overview

The API uses a unified `/services/{session_id}/*` pattern. Every service — whether single or multi — is identified by its `session_id`. There is no separate `/service/*` namespace.

Single-service deployments still use the same `/services/{session_id}/*` paths. The frontend only needs to know the `session_id`, which you can get from the config or service creation response.

## 2. API Client Setup

```ts
const API_BASE = 'http://127.0.0.1:8000'

async function apiRequest<T = any>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options.headers },
    ...options,
  })
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `${response.status} ${response.statusText}`)
  }
  return response.json()
}
```

For file uploads (config import), use `FormData` without setting `Content-Type`:

```ts
async function uploadConfig(sessionId: string, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  const response = await fetch(
    `${API_BASE}/services/${sessionId}/config/import`,
    { method: 'POST', body: formData }
  )
  return response.json()
}
```

For config export, trigger a file download:

```ts
function downloadConfig(sessionId: string) {
  const link = document.createElement('a')
  link.href = `${API_BASE}/services/${sessionId}/config/export`
  link.download = `config_${sessionId}.json`
  link.click()
}
```

## 3. Loading Sequences

### 3.1 Single-Service Dashboard

On page load, fire these requests in parallel:

```ts
const [health, analytics, selectionCfg, strategyCfg, portfolioCfg] =
  await Promise.all([
    apiRequest('/health'),
    apiRequest(`/services/${sessionId}/analytics`),
    apiRequest(`/services/${sessionId}/selection-config`),
    apiRequest(`/services/${sessionId}/strategy-config`),
    apiRequest(`/services/${sessionId}/portfolio/config`),
  ])
```

`/analytics` bundles `status`, `runtime`, `performance`, and `config`. The three config endpoints provide `available_selections`, `available_strategies`, and `available_optimizers` for dynamic form rendering.

### 3.2 Multi-Service Dashboard

```ts
const [health, services, comparison, perfComparison] = await Promise.all([
  apiRequest('/health'),
  apiRequest('/services'),
  apiRequest('/services/compare'),
  apiRequest('/services/performance/compare'),
])

// Then load details for a selected service on demand
const analytics = await apiRequest(
  `/services/${selectedSessionId}/analytics`
)
```

### 3.3 Polling for Live Updates

```ts
const POLL_INTERVAL = 30_000 // 30 seconds

function startPolling(sessionId: string) {
  return setInterval(async () => {
    const status = await apiRequest(`/services/${sessionId}/status`)
    updateStatusUI(status)
  }, POLL_INTERVAL)
}
```

## 4. State Management

### 4.1 Recommended State Shape

```ts
interface DashboardState {
  // Connection
  health: HealthResponse | null
  sessionId: string

  // Read-only snapshots
  status: ServiceStatusResponse | null
  runtime: RuntimeSnapshotResponse | null
  performance: PerformanceSnapshotResponse | null
  config: ServiceConfigResponse | null

  // Configuration with schema
  selectionConfig: SelectionConfigSnapshotResponse | null
  strategyConfig: StrategyConfigSnapshotResponse | null
  portfolioConfig: PortfolioConfigSnapshotResponse | null

  // User edit forms (separate from read-only state)
  editSelection: SelectionSpec | null
  editStrategies: StrategySpec[]
  editPortfolio: PortfolioSpec | null
  editScheduler: Partial<SchedulerConfigUpdateRequest> | null
}
```

Keep read-only snapshots, edit forms, and schema definitions in separate state slices.

### 4.2 Multi-Service State

```ts
interface MultiServiceState {
  services: ServiceInfoResponse[]
  selectedSessionId: string | null
  comparison: ServiceComparisonResponse | null
  performanceComparison: PerformanceComparisonResponse | null
  // Per-service details loaded on demand
  serviceDetails: Record<string, DashboardState>
}
```

## 5. Schema-Driven Forms

### 5.1 Dynamic Form Rendering

Each config endpoint returns available components with JSON Schema definitions:

```ts
// From GET /services/{session_id}/selection-config
const { available_selections } = selectionConfig

// available_selections[i].params_schema:
// { type: "object", properties: { factor: { type: "string" }, ... } }
```

Render forms dynamically based on `params_schema`. Never hardcode parameter names or types.

### 5.2 Example: Rendering a Strategy Form

```ts
function renderStrategyParams(schema: Record<string, any>, values: Record<string, any>) {
  return Object.entries(schema.properties).map(([key, prop]: [string, any]) => {
    switch (prop.type) {
      case 'string':
        return `<input type="text" name="${key}" value="${values[key] ?? ''}" />`
      case 'number':
      case 'integer':
        return `<input type="number" name="${key}" value="${values[key] ?? ''}" />`
      case 'boolean':
        return `<input type="checkbox" name="${key}" ${values[key] ? 'checked' : ''} />`
      default:
        return `<input type="text" name="${key}" value="${JSON.stringify(values[key])}" />`
    }
  })
}
```

### 5.3 Preset Dropdowns (Convenience Only)

Some fields benefit from preset choices for UX, but always use schema validation as authority:

```ts
const OBJECTIVE_OPTIONS = ['Sharpe', 'MinRisk', 'MaxReturn', 'MaxSharpe']
const RISK_MEASURE_OPTIONS = ['MV', 'MAD', 'CVaR', 'CDaR', 'EVaR']
const MODEL_OPTIONS = ['Classic', 'FM', 'FM-MV', 'HRP']
const COVARIANCE_OPTIONS = ['ledoit', 'sample', 'shrink']
const REBALANCE_MODE_OPTIONS = [
  'disabled', 'initial_only', 'every_cycle',
  'drift_threshold', 'schedule', 'manual_only',
]
```

## 6. Config Management Patterns

### 6.1 Reading Config

Always initialize forms from the API response, not local defaults:

```ts
const config = await apiRequest(`/services/${sessionId}/config`)
// Use config.config_bundle.selection_spec.params as initial form values
// Use config.config_source to display config origin
```

### 6.2 Updating Individual Config Sections

```ts
// Update selection
await apiRequest(`/services/${sessionId}/selection-config`, {
  method: 'POST',
  body: JSON.stringify({ selection_spec: { name, params, alias } }),
})

// Replace all strategies
await apiRequest(`/services/${sessionId}/strategy-config`, {
  method: 'POST',
  body: JSON.stringify({ strategy_specs }),
})

// Update portfolio
await apiRequest(`/services/${sessionId}/portfolio/config`, {
  method: 'POST',
  body: JSON.stringify({ portfolio_spec }),
})

// Update scheduler
await apiRequest(`/services/${sessionId}/scheduler-config`, {
  method: 'POST',
  body: JSON.stringify({ interval_seconds, cron_expression, timezone, auto_start }),
})
```

After each update, re-fetch the relevant GET endpoint to confirm changes took effect.

### 6.3 Full Config Import/Export

```ts
// Export: triggers file download
function exportConfig(sessionId: string) {
  window.open(`${API_BASE}/services/${sessionId}/config/export`)
}

// Import: upload a JSON file
async function importConfig(sessionId: string, file: File) {
  const formData = new FormData()
  formData.append('file', file)
  const resp = await fetch(`${API_BASE}/services/${sessionId}/config/import`, {
    method: 'POST',
    body: formData,
  })
  return resp.json()
}

// Full config replacement (advanced)
await apiRequest(`/services/${sessionId}/config`, {
  method: 'PUT',
  body: JSON.stringify({ config_bundle: { ... } }),
})
```

## 7. Trading Operations

### 7.1 Run Once

```ts
const result = await apiRequest(`/services/${sessionId}/run-once`, {
  method: 'POST',
})
// Display: result.status, result.executed_buy_count, result.executed_sell_count
```

### 7.2 Close All Positions

```ts
const result = await apiRequest(`/services/${sessionId}/close-all-positions`, {
  method: 'POST',
  body: JSON.stringify({ slippage: 0.001 }),
})
// Display: result.closed_count
```

### 7.3 Single-Symbol Signals

```ts
await apiRequest(`/services/${sessionId}/signal-buy`, {
  method: 'POST',
  body: JSON.stringify({ symbol: '600519', target_qty: 100, slippage: 0.001 }),
})

await apiRequest(`/services/${sessionId}/signal-sell`, {
  method: 'POST',
  body: JSON.stringify({ symbol: '600519', target_qty: 100, slippage: 0.001 }),
})
```

## 8. Portfolio Operations

### 8.1 Optimize Preview

```ts
const result = await apiRequest(`/services/${sessionId}/portfolio/optimize`, {
  method: 'POST',
  body: JSON.stringify({
    as_of_date: '2026-04-28',
    preview_only: true,
    symbols: ['000001', '600519'],
  }),
})
// Display: result.weights
```

### 8.2 Rebalance (preview then execute)

Always preview first:

```ts
// Step 1: Preview
const preview = await apiRequest(`/services/${sessionId}/portfolio/rebalance`, {
  method: 'POST',
  body: JSON.stringify({
    as_of_date: '2026-04-28',
    preview_only: true,
  }),
})

// Show preview.should_rebalance, preview.reason, preview.target_allocations
// Let user review, then execute:

// Step 2: Execute (user confirms)
if (userConfirmed) {
  const result = await apiRequest(`/services/${sessionId}/portfolio/rebalance`, {
    method: 'POST',
    body: JSON.stringify({
      as_of_date: '2026-04-28',
      preview_only: false,
      force: false,
    }),
  })
}
```

## 9. Charts and Visualization

### 9.1 Equity Curve

```ts
const perf = await apiRequest(`/services/${sessionId}/performance`)

// ECharts line chart
const option = {
  xAxis: { type: 'time', data: perf.equity_curve.map(d => d.date) },
  yAxis: { type: 'value' },
  series: [{
    name: 'Portfolio Value',
    type: 'line',
    data: perf.equity_curve.map(d => [d.date, d.portfolio_value]),
  }],
}
```

### 9.2 Multi-Service Comparison Overlay

```ts
const { sessions } = await apiRequest(
  `/services/performance/compare?limit=8`
)

const series = sessions.map(s => ({
  name: `${s.session_id} (${s.strategy_names.join(', ')})`,
  type: 'line',
  data: s.equity_curve.map(row => [row.trade_date, row.cumulative_return]),
}))

// Render with ECharts multi-series line chart
```

### 9.3 Comparison Table

```ts
function buildComparisonTable(sessions: PerformanceComparisonItem[]) {
  return sessions
    .sort((a, b) => b.total_return_pct - a.total_return_pct)
    .map(s => ({
      session: s.session_id,
      strategies: s.strategy_names.join(', '),
      return: `${s.total_return_pct?.toFixed(2)}%`,
      maxDrawdown: `${s.max_drawdown?.toFixed(2)}%`,
      winRate: `${s.win_rate?.toFixed(2)}%`,
      totalPnl: s.total_pnl?.toFixed(2),
      trades: s.total_trades,
    }))
}
```

## 10. Scheduler Control

```ts
// Start/stop
await apiRequest(`/services/${sessionId}/scheduler/start`, { method: 'POST' })
await apiRequest(`/services/${sessionId}/scheduler/stop`, { method: 'POST' })

// Update schedule
await apiRequest(`/services/${sessionId}/scheduler-config`, {
  method: 'POST',
  body: JSON.stringify({
    interval_seconds: 300,
    cron_expression: '0 15 * * 1-5',
    timezone: 'Asia/Shanghai',
    auto_start: true,
  }),
})
```

Schedule UI should show:
- Current running state: `GET /services/{session_id}/status` → `scheduler.running`
- Next run time: `scheduler.next_run_at`, `scheduler.next_run_in_seconds`
- Upcoming runs: `scheduler.next_runs[]`

## 11. Error Handling

```ts
async function safeApiCall<T>(fn: () => Promise<T>): Promise<T | null> {
  try {
    return await fn()
  } catch (err) {
    console.error('API error:', err)
    // Show toast notification
    showErrorToast(err instanceof Error ? err.message : 'Unknown error')
    return null
  }
}
```

Common error cases to handle:
- 404: Invalid `session_id` — prompt user to check service list
- 500: Server error — show diagnostic info
- Network error: Service unreachable — show connection status indicator

## 12. Page Structure Recommendations

### 12.1 Dashboard Pages

| Page | Endpoints | Purpose |
|------|-----------|---------|
| Overview | `analytics`, `status` | High-level status, latest metrics |
| Performance | `performance`, `runtime` | Charts, equity curve, exposure |
| Portfolio | `portfolio/*` | Allocations, optimization, rebalancing |
| Strategy Config | `strategy-config` | Manage strategy list and params |
| Selection Config | `selection-config` | Manage selection provider and params |
| Service Config | `scheduler-config`, `config` | Scheduler, service-level settings |
| Events | `events` | Audit log, state history |
| Data Explorer | `/data/*` | Browse and query cached market data |

### 12.2 Multi-Service Pages

| Page | Endpoints | Purpose |
|------|-----------|---------|
| Service List | `/services`, `/services/compare` | All services overview |
| Comparison | `/services/performance/compare` | Overlay charts, comparison table |

## 13. Session ID Selection (Multi-Service)

When multiple services are running, provide a session selector:

```ts
// Load service list
const { services } = await apiRequest('/services')

// Render dropdown
const options = services.map(s => ({
  value: s.session_id,
  label: `${s.session_id} (${s.mode}, ${s.strategy_count} strategies)`,
}))

// On selection, load that service's data
async function onSessionSelected(sessionId: string) {
  const [status, analytics, selectionCfg, strategyCfg, portfolioCfg] =
    await Promise.all([
      apiRequest(`/services/${sessionId}/status`),
      apiRequest(`/services/${sessionId}/analytics`),
      apiRequest(`/services/${sessionId}/selection-config`),
      apiRequest(`/services/${sessionId}/strategy-config`),
      apiRequest(`/services/${sessionId}/portfolio/config`),
    ])
  // Update state
}
```

For performance comparison page, allow multi-select of sessions to pass to `?session_ids=A,B,C`.

## 14. Strategy Evaluation

```ts
const result = await apiRequest(`/services/${sessionId}/strategy-evaluate`, {
  method: 'POST',
  body: JSON.stringify({
    // evaluation parameters
  }),
})
```

## 15. Risk Management

```ts
// Get current risk config
const riskCfg = await apiRequest(`/services/${sessionId}/risk-management`)

// Update risk config
await apiRequest(`/services/${sessionId}/risk-management`, {
  method: 'PUT',
  body: JSON.stringify({
    // risk management params
  }),
})
```

## 16. Common Pitfalls

1. **Strategy config is a full replacement**, not an append. Always maintain the complete `strategy_specs[]` array in frontend state before submitting.

2. **`params_schema` is authoritative**. Even if you add preset dropdowns, always validate against the schema returned by the API.

3. **`active_selection_config` vs `selection_spec.params`**: Edit using `selection_spec.params` (user input). `active_selection_config` is the runtime-resolved version for display.

4. **Rebalance preview first**: Always default `preview_only=true`. Only set `preview_only=false` after the user confirms the preview results.

5. **Full config replacement is destructive**: `PUT /services/{session_id}/config` replaces everything. Gate this behind a confirmation dialog in advanced settings.

6. **Config export downloads a file**: Don't fetch it with XHR/fetch for JSON parsing — use a download link or `window.open()`.
