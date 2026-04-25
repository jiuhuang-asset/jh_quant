<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'

const STORAGE_KEY = 'jh_quant.signalgateway.dashboard.settings'
const CRON_PRESET_GROUPS = [
  {
    label: 'A股时段模板',
    items: [
      { label: '盘前准备', value: '25 9 * * 1-5', hint: '工作日 09:25，开盘前准备' },
      { label: '开盘调度', value: '30 9 * * 1-5', hint: '工作日 09:30，开盘触发' },
      { label: '午后开盘', value: '0 13 * * 1-5', hint: '工作日 13:00，午后恢复交易' },
      { label: '收盘复盘', value: '0 15 * * 1-5', hint: '工作日 15:00，收盘后触发' },
    ],
  },
  {
    label: '盘中节奏模板',
    items: [
      { label: '15分钟轮询', value: '*/15 9-15 * * 1-5', hint: '交易时段内每15分钟触发' },
      { label: '30分钟轮询', value: '*/30 9-15 * * 1-5', hint: '交易时段内每30分钟触发' },
      { label: '整点扫描', value: '0 10-15 * * 1-5', hint: '10:00 到 15:00 每个整点触发' },
    ],
  },
]

const loading = ref(true)
const actionLoading = ref(false)
const activeSection = ref('overview')
const errorText = ref('')
const lastUpdatedAt = ref('')
const savingConnection = ref(false)
const savingSchedule = ref(false)
const scheduleValidationError = ref('')

const runtimeConfig = reactive({
  host: '127.0.0.1',
  port: 8000,
  protocol: 'http',
  apiBase: 'http://127.0.0.1:8000',
  title: 'SignalGateway 量化控制台',
  refreshIntervalMs: 15000,
})

const settingsForm = reactive({
  apiBase: '',
  refreshIntervalMs: 15000,
  cronEnabled: false,
  cronExpression: '',
  intervalSeconds: 300,
  timezone: 'Asia/Shanghai',
  autoStart: false,
})

const endpointLatency = reactive({})
const state = reactive({
  health: null,
  status: null,
  runtime: null,
  performance: null,
  analytics: null,
  config: null,
})

const equityChartEl = ref(null)
const activityChartEl = ref(null)
const exposureChartEl = ref(null)

let equityChart
let activityChart
let exposureChart
let refreshTimer

const navigationItems = [
  { key: 'overview', label: '总览', caption: '运行脉冲' },
  { key: 'positions', label: '持仓', caption: '实时 OMS 状态' },
  { key: 'performance', label: '绩效', caption: '收益与换手' },
  { key: 'config', label: '配置', caption: '策略栈配置' },
  { key: 'settings', label: '设置', caption: '连接与调度' },
  { key: 'diagnostics', label: '诊断', caption: '延迟与原始载荷' },
]

const summaryCards = computed(() => {
  const status = state.status || {}
  const perf = state.performance || {}
  const lastResult = status.last_result || {}
  const latestPortfolio = perf.latest_portfolio || {}
  const positionExposure = perf.position_exposure || {}

  return [
    {
      label: '服务模式',
      value: formatMode(status.mode),
      tone: status.running ? 'good' : 'neutral',
      detail: status.running ? '调度器运行中' : '调度器已暂停',
    },
    {
      label: '组合市值',
      value: formatNumber(latestPortfolio.portfolio_value),
      tone: 'neutral',
      detail: '最新资产快照',
    },
    {
      label: '现金占比',
      value: formatPercent(latestPortfolio.cash_ratio),
      tone: 'neutral',
      detail: '当前流动性',
    },
    {
      label: '持仓数量',
      value: positionExposure.position_count ?? '-',
      tone: 'neutral',
      detail: '当前持仓标的',
    },
    {
      label: '本轮买入',
      value: lastResult.executed_buy_count ?? 0,
      tone: 'good',
      detail: '最近一次交易周期',
    },
    {
      label: '本轮卖出',
      value: lastResult.executed_sell_count ?? 0,
      tone: 'warn',
      detail: '最近一次交易周期',
    },
  ]
})

const statusRows = computed(() => {
  const status = state.status || {}
  return [
    ['会话 ID', status.session_id || '-'],
    ['运行中', status.running ? '是' : '否'],
    ['Cron 表达式', status.scheduler?.cron_expression || '-'],
    ['轮询间隔', status.scheduler?.interval_seconds ?? '-'],
    ['时区', status.scheduler?.timezone || '-'],
    ['最近错误', status.last_error || '-'],
  ]
})

const strategyRows = computed(() => (state.config?.strategies || []).map((item) => ({
  name: item.alias || item.name,
  source: item.name,
  weight: item.weight,
  params: JSON.stringify(item.params || {}),
})))

const positionsRows = computed(() => {
  const raw = state.runtime?.positions
  if (!raw) return []
  if (Array.isArray(raw)) return raw
  if (Array.isArray(raw.positions)) return raw.positions
  if (Array.isArray(raw.holdings)) return raw.holdings
  if (typeof raw === 'object') {
    return Object.entries(raw).map(([symbol, payload]) => ({
      symbol,
      ...((payload && typeof payload === 'object') ? payload : { value: payload }),
    }))
  }
  return []
})

const holdingRows = computed(() => state.performance?.holding_returns || [])
const turnoverRows = computed(() => state.performance?.turnover || [])
const tradeActivityRows = computed(() => state.performance?.trade_activity || [])

const currentSectionMeta = computed(() => navigationItems.find((item) => item.key === activeSection.value) || navigationItems[0])
const connectionSummary = computed(() => {
  if (loading.value) {
    return {
      text: '连接检测中',
      detail: '正在拉取服务状态',
      tone: 'pending',
    }
  }
  if (errorText.value) {
    return {
      text: '连接异常',
      detail: errorText.value,
      tone: 'error',
    }
  }
  if (state.health?.status === 'ok') {
    return {
      text: '连接正常',
      detail: runtimeConfig.apiBase,
      tone: 'ok',
    }
  }
  return {
    text: '状态未知',
    detail: runtimeConfig.apiBase,
    tone: 'pending',
  }
})

const schedulerSummary = computed(() => {
  const scheduler = state.status?.scheduler || {}
  if (scheduler.schedule_type === 'cron') {
    return {
      mode: 'Cron 调度',
      detail: scheduler.cron_expression || '-',
      nextRun: scheduler.next_run_at ? formatDateTime(scheduler.next_run_at) : '等待预览',
      countdown: scheduler.next_run_in_seconds ?? null,
      nextRuns: (scheduler.next_runs || []).map((item) => formatDateTime(item)),
    }
  }
  return {
    mode: '固定间隔调度',
    detail: `${scheduler.interval_seconds ?? '-'} 秒`,
    nextRun: scheduler.next_run_at ? formatDateTime(scheduler.next_run_at) : '下一轮运行后开始预估',
    countdown: scheduler.next_run_in_seconds ?? null,
    nextRuns: (scheduler.next_runs || []).map((item) => formatDateTime(item)),
  }
})

function formatNumber(value) {
  if (value === null || value === undefined || value === '') return '-'
  const num = Number(value)
  if (Number.isNaN(num)) return String(value)
  return new Intl.NumberFormat('zh-CN', {
    maximumFractionDigits: Math.abs(num) >= 1000 ? 0 : 2,
  }).format(num)
}

function formatPercent(value) {
  if (value === null || value === undefined || value === '') return '-'
  const num = Number(value)
  if (Number.isNaN(num)) return String(value)
  return `${(num * 100).toFixed(2)}%`
}

function formatMode(value) {
  if (value === 'paper') return '模拟盘'
  if (value === 'live') return '实盘'
  return value || '-'
}

function formatHealth(value) {
  if (value === 'ok') return '正常'
  return value || '未知'
}

function formatDateTime(value) {
  if (!value) return '-'
  const dt = new Date(value)
  return Number.isNaN(dt.getTime()) ? String(value) : dt.toLocaleString('zh-CN')
}

function loadPersistedSettings() {
  try {
    const saved = localStorage.getItem(STORAGE_KEY)
    return saved ? JSON.parse(saved) : null
  } catch {
    return null
  }
}

function persistSettings() {
  localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({
      apiBase: runtimeConfig.apiBase,
      refreshIntervalMs: runtimeConfig.refreshIntervalMs,
    }),
  )
}

async function resolveRuntimeConfig() {
  const search = new URLSearchParams(window.location.search)
  const queryApiBase = search.get('apiBase')
  const queryPort = search.get('port')

  if (window.pywebview?.api?.get_runtime_config) {
    try {
      const config = await window.pywebview.api.get_runtime_config()
      Object.assign(runtimeConfig, config || {})
    } catch (error) {
      console.warn('读取 pywebview 配置失败', error)
    }
  }

  if (window.__SIGNALGATEWAY_CONFIG__) {
    Object.assign(runtimeConfig, window.__SIGNALGATEWAY_CONFIG__)
  }

  const persisted = loadPersistedSettings()
  if (persisted?.apiBase) {
    runtimeConfig.apiBase = persisted.apiBase
  }
  if (persisted?.refreshIntervalMs) {
    runtimeConfig.refreshIntervalMs = Number(persisted.refreshIntervalMs)
  }

  if (queryPort) {
    runtimeConfig.port = Number(queryPort)
  }

  if (queryApiBase) {
    runtimeConfig.apiBase = queryApiBase
  } else if (!runtimeConfig.apiBase) {
    runtimeConfig.apiBase = `${runtimeConfig.protocol}://${runtimeConfig.host}:${runtimeConfig.port}`
  }

  runtimeConfig.apiBase = String(runtimeConfig.apiBase).replace(/\/$/, '')
  settingsForm.apiBase = runtimeConfig.apiBase
  settingsForm.refreshIntervalMs = runtimeConfig.refreshIntervalMs
}

function applySchedulerStateToForm() {
  const scheduler = state.status?.scheduler || {}
  settingsForm.cronExpression = scheduler.cron_expression || ''
  settingsForm.cronEnabled = Boolean(scheduler.cron_expression)
  settingsForm.intervalSeconds = scheduler.interval_seconds || 300
  settingsForm.timezone = scheduler.timezone || 'Asia/Shanghai'
  settingsForm.autoStart = Boolean(state.config?.service?.auto_start)
}

async function request(path, options = {}) {
  const startedAt = performance.now()
  const method = (options.method || 'GET').toUpperCase()
  const headers = method === 'GET' ? {} : { 'Content-Type': 'application/json' }
  const response = await fetch(`${runtimeConfig.apiBase}${path}`, {
    headers,
    ...options,
  })
  endpointLatency[path] = Math.round(performance.now() - startedAt)
  if (!response.ok) {
    const text = await response.text()
    throw new Error(text || `${response.status} ${response.statusText}`)
  }
  if (response.status === 204) return {}
  const text = await response.text()
  return text ? JSON.parse(text) : {}
}

async function refreshAll() {
  loading.value = true
  errorText.value = ''
  try {
    const [health, status, runtime, performanceData, analytics, config] = await Promise.all([
      request('/health'),
      request('/service/status'),
      request('/service/runtime'),
      request('/service/performance'),
      request('/service/analytics'),
      request('/service/config'),
    ])

    state.health = health
    state.status = status
    state.runtime = runtime
    state.performance = performanceData
    state.analytics = analytics
    state.config = config
    lastUpdatedAt.value = new Date().toISOString()
    applySchedulerStateToForm()

    await nextTick()
    renderCharts()
  } catch (error) {
    errorText.value = error instanceof Error ? error.message : String(error)
  } finally {
    loading.value = false
  }
}

async function callAction(path) {
  actionLoading.value = true
  try {
    const payload = await request(path, {
      method: 'POST',
      body: JSON.stringify({}),
    })
    ElMessage.success('操作已完成')
    await refreshAll()
    return payload
  } catch (error) {
    const text = error instanceof Error ? error.message : String(error)
    ElMessage.error(text)
    throw error
  } finally {
    actionLoading.value = false
  }
}

function validateCronExpression(value) {
  if (!value) return '启用 Cron 调度时必须填写表达式。'
  const normalized = value.trim().replace(/\s+/g, ' ')
  const parts = normalized.split(' ')
  if (parts.length !== 5) {
    return '请使用标准 5 段 Cron 表达式，例如 `0 9 * * 1-5`。'
  }
  const allowed = /^[\d*/,.\-]+$/
  const invalid = parts.some((part) => !allowed.test(part))
  if (invalid) {
    return 'Cron 含有不支持的字符，只允许数字、`*`、`/`、`,`、`-`。'
  }
  return ''
}

function applyCronPreset(value) {
  settingsForm.cronEnabled = true
  settingsForm.cronExpression = value
  scheduleValidationError.value = ''
}

async function saveConnectionSettings() {
  savingConnection.value = true
  try {
    runtimeConfig.apiBase = settingsForm.apiBase.trim().replace(/\/$/, '')
    runtimeConfig.refreshIntervalMs = Number(settingsForm.refreshIntervalMs) || 15000
    persistSettings()
    startAutoRefresh()
    await refreshAll()
    ElMessage.success('连接设置已生效')
  } catch (error) {
    ElMessage.error(error instanceof Error ? error.message : String(error))
  } finally {
    savingConnection.value = false
  }
}

async function saveScheduleSettings() {
  scheduleValidationError.value = ''

  const cronExpression = settingsForm.cronEnabled ? settingsForm.cronExpression.trim() : null
  const cronError = settingsForm.cronEnabled ? validateCronExpression(cronExpression) : ''
  if (cronError) {
    scheduleValidationError.value = cronError
    return
  }

  if (!settingsForm.intervalSeconds || Number(settingsForm.intervalSeconds) <= 0) {
    scheduleValidationError.value = '轮询间隔必须大于 0。'
    return
  }

  savingSchedule.value = true
  try {
    await request('/service/scheduler-config', {
      method: 'POST',
      body: JSON.stringify({
        interval_seconds: Number(settingsForm.intervalSeconds),
        cron_expression: cronExpression,
        timezone: settingsForm.timezone.trim(),
        auto_start: Boolean(settingsForm.autoStart),
      }),
    })
    ElMessage.success('调度设置已更新')
    await refreshAll()
  } catch (error) {
    const text = error instanceof Error ? error.message : String(error)
    scheduleValidationError.value = text
    ElMessage.error(text)
  } finally {
    savingSchedule.value = false
  }
}

function ensureChart(instance, el) {
  if (!el) return null
  if (!instance) return echarts.init(el)
  return instance
}

function renderEquityChart() {
  const rows = state.performance?.equity_curve || []
  equityChart = ensureChart(equityChart, equityChartEl.value)
  if (!equityChart) return

  const labels = rows.map((item) => item.trade_date || item.date || item.generated_at || '')
  const values = rows.map((item) => Number(item.portfolio_value ?? item.equity ?? item.value ?? 0))

  equityChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: 16, right: 20, top: 28, bottom: 18, containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      boundaryGap: false,
      axisLabel: { color: '#8fa7c7' },
      axisLine: { lineStyle: { color: '#29415f' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#8fa7c7' },
      splitLine: { lineStyle: { color: 'rgba(120, 150, 190, 0.12)' } },
    },
    series: [{
      name: '权益曲线',
      type: 'line',
      smooth: true,
      symbol: 'none',
      data: values,
      lineStyle: { width: 3, color: '#4dd0a8' },
      areaStyle: {
        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
          { offset: 0, color: 'rgba(77, 208, 168, 0.45)' },
          { offset: 1, color: 'rgba(77, 208, 168, 0.02)' },
        ]),
      },
    }],
  })
}

function renderActivityChart() {
  const rows = state.performance?.trade_activity || []
  activityChart = ensureChart(activityChart, activityChartEl.value)
  if (!activityChart) return

  const labels = rows.map((item) => item.trade_date || item.date || '')
  const buyData = rows.map((item) => Number(item.buy_count ?? item.executed_buy_count ?? 0))
  const sellData = rows.map((item) => Number(item.sell_count ?? item.executed_sell_count ?? 0))

  activityChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    legend: { textStyle: { color: '#d9e4f5' } },
    grid: { left: 16, right: 20, top: 36, bottom: 18, containLabel: true },
    xAxis: {
      type: 'category',
      data: labels,
      axisLabel: { color: '#8fa7c7' },
      axisLine: { lineStyle: { color: '#29415f' } },
    },
    yAxis: {
      type: 'value',
      axisLabel: { color: '#8fa7c7' },
      splitLine: { lineStyle: { color: 'rgba(120, 150, 190, 0.12)' } },
    },
    series: [
      { name: '买入', type: 'bar', data: buyData, itemStyle: { color: '#4dd0a8' }, barMaxWidth: 18 },
      { name: '卖出', type: 'bar', data: sellData, itemStyle: { color: '#f97373' }, barMaxWidth: 18 },
    ],
  })
}

function renderExposureChart() {
  const topPositions = state.performance?.position_exposure?.top_positions || []
  exposureChart = ensureChart(exposureChart, exposureChartEl.value)
  if (!exposureChart) return

  const chartRows = topPositions.slice(0, 8).map((item) => ({
    name: item.symbol || item.name || '未知',
    value: Number(item.market_value ?? item.weight ?? item.position_value ?? 0),
  }))

  exposureChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item' },
    series: [{
      type: 'pie',
      radius: ['44%', '72%'],
      center: ['50%', '54%'],
      label: { color: '#d9e4f5' },
      itemStyle: { borderColor: '#0f1d33', borderWidth: 3 },
      data: chartRows.length ? chartRows : [{ name: '暂无数据', value: 1, itemStyle: { color: '#38506f' } }],
    }],
  })
}

function renderCharts() {
  renderEquityChart()
  renderActivityChart()
  renderExposureChart()
}

function resizeCharts() {
  equityChart?.resize()
  activityChart?.resize()
  exposureChart?.resize()
}

function startAutoRefresh() {
  stopAutoRefresh()
  refreshTimer = window.setInterval(() => {
    refreshAll().catch(() => {})
  }, runtimeConfig.refreshIntervalMs)
}

function stopAutoRefresh() {
  if (refreshTimer) {
    window.clearInterval(refreshTimer)
    refreshTimer = undefined
  }
}

watch(activeSection, async () => {
  await nextTick()
  resizeCharts()
})

onMounted(async () => {
  await resolveRuntimeConfig()
  await refreshAll()
  startAutoRefresh()
  window.addEventListener('resize', resizeCharts)
})

onBeforeUnmount(() => {
  stopAutoRefresh()
  window.removeEventListener('resize', resizeCharts)
  equityChart?.dispose()
  activityChart?.dispose()
  exposureChart?.dispose()
})
</script>

<template>
  <div class="workspace-shell">
    <aside class="sidebar-panel">
      <div class="brand-block">
        <p class="eyebrow">量化运维</p>
        <h1>{{ runtimeConfig.title }}</h1>
        <p class="brand-copy">面向 A 股量化场景的执行、持久化与调度控制面板。</p>
      </div>

      <nav class="side-nav">
        <button
          v-for="item in navigationItems"
          :key="item.key"
          class="nav-item"
          :class="{ active: activeSection === item.key }"
          @click="activeSection = item.key"
        >
          <strong>{{ item.label }}</strong>
          <span>{{ item.caption }}</span>
        </button>
      </nav>

      <div class="side-footer">
        <div class="meta-row">
          <span>健康状态</span>
          <strong :class="{ good: state.health?.status === 'ok' }">{{ formatHealth(state.health?.status) }}</strong>
        </div>
        <div class="meta-row">
          <span>接口地址</span>
          <strong>{{ runtimeConfig.apiBase }}</strong>
        </div>
        <div class="meta-row">
          <span>最近刷新</span>
          <strong>{{ formatDateTime(lastUpdatedAt) }}</strong>
        </div>
      </div>
    </aside>

    <main class="content-shell">
      <section class="top-banner">
        <div>
          <p class="eyebrow">{{ currentSectionMeta.caption }}</p>
          <h2>{{ currentSectionMeta.label }}</h2>
        </div>
        <div class="connection-badge" :class="`tone-${connectionSummary.tone}`">
          <span>连接状态</span>
          <strong>{{ connectionSummary.text }}</strong>
          <small>{{ connectionSummary.detail }}</small>
        </div>
        <div class="toolbar-actions">
          <el-button type="success" :loading="actionLoading" @click="callAction('/service/start')">启动</el-button>
          <el-button type="danger" plain :loading="actionLoading" @click="callAction('/service/stop')">停止</el-button>
          <el-button type="warning" plain :loading="actionLoading" @click="callAction('/service/run-once')">运行一次</el-button>
          <el-button type="primary" plain :loading="loading" @click="refreshAll">刷新</el-button>
        </div>
      </section>

      <el-alert
        v-if="errorText"
        type="error"
        :closable="false"
        show-icon
        class="error-banner"
        :title="`请求失败：${errorText}`"
      />

      <template v-if="activeSection === 'overview'">
        <section class="card-grid">
          <article
            v-for="card in summaryCards"
            :key="card.label"
            class="metric-card"
            :class="`tone-${card.tone}`"
          >
            <span>{{ card.label }}</span>
            <strong>{{ card.value }}</strong>
            <small>{{ card.detail }}</small>
          </article>
        </section>

        <div class="two-col section-gap">
          <section class="panel-card">
            <div class="panel-heading">
              <div>
                <h3>执行状态</h3>
                <p>展示当前会话、运行状态与调度概况。</p>
              </div>
            </div>
            <div class="kv-grid">
              <div v-for="[label, value] in statusRows" :key="label" class="kv-item">
                <span>{{ label }}</span>
                <strong>{{ value }}</strong>
              </div>
              <div class="kv-item">
                <span>调度模式</span>
                <strong>{{ schedulerSummary.mode }}</strong>
              </div>
              <div class="kv-item">
                <span>下一次触发</span>
                <strong>{{ schedulerSummary.nextRun }}</strong>
              </div>
            </div>
          </section>

          <section class="panel-card">
            <div class="panel-heading">
              <div>
                <h3>重点暴露</h3>
                <p>最新组合快照中的主要持仓暴露。</p>
              </div>
            </div>
            <div ref="exposureChartEl" class="chart-block"></div>
          </section>
        </div>

        <div class="two-col section-gap">
          <section class="panel-card">
            <div class="panel-heading">
              <div>
                <h3>权益曲线</h3>
                <p>持久化记录下的组合市值变化。</p>
              </div>
            </div>
            <div ref="equityChartEl" class="chart-block"></div>
          </section>

          <section class="panel-card">
            <div class="panel-heading">
              <div>
                <h3>交易活跃度</h3>
                <p>展示买卖次数与交易节奏。</p>
              </div>
            </div>
            <div ref="activityChartEl" class="chart-block"></div>
          </section>
        </div>
      </template>

      <template v-else-if="activeSection === 'positions'">
        <section class="panel-card">
          <div class="panel-heading">
            <div>
              <h3>当前持仓</h3>
              <p>来自 `/service/runtime` 的标准化 OMS 状态。</p>
            </div>
          </div>
          <el-table :data="positionsRows" stripe height="640" empty-text="暂无持仓">
            <el-table-column prop="symbol" label="代码" min-width="140" />
            <el-table-column prop="quantity" label="数量" min-width="120" />
            <el-table-column prop="market_value" label="市值" min-width="140" />
            <el-table-column prop="avg_price" label="持仓均价" min-width="120" />
            <el-table-column prop="pnl" label="盈亏" min-width="120" />
            <el-table-column prop="pnl_pct" label="盈亏率" min-width="120" />
          </el-table>
        </section>
      </template>

      <template v-else-if="activeSection === 'performance'">
        <div class="stack-grid">
          <section class="panel-card">
            <div class="panel-heading">
              <div>
                <h3>持仓收益</h3>
                <p>展示最新持仓层面的盈亏、市值与收益率。</p>
              </div>
            </div>
            <el-table :data="holdingRows" stripe height="260" empty-text="暂无持仓收益数据">
              <el-table-column prop="symbol" label="代码" min-width="140" />
              <el-table-column prop="pnl" label="盈亏" min-width="120" />
              <el-table-column prop="pnl_pct" label="盈亏率" min-width="120" />
              <el-table-column prop="market_value" label="市值" min-width="140" />
              <el-table-column prop="latest_date" label="最新日期" min-width="160" />
            </el-table>
          </section>

          <section class="panel-card">
            <div class="panel-heading">
              <div>
                <h3>换手情况</h3>
                <p>按日展示成交额与换手率变化。</p>
              </div>
            </div>
            <el-table :data="turnoverRows" stripe height="260" empty-text="暂无换手数据">
              <el-table-column prop="trade_date" label="交易日期" min-width="160" />
              <el-table-column prop="turnover_ratio" label="换手率" min-width="140" />
              <el-table-column prop="trade_amount" label="成交额" min-width="160" />
              <el-table-column prop="portfolio_value" label="组合市值" min-width="160" />
            </el-table>
          </section>

          <section class="panel-card">
            <div class="panel-heading">
              <div>
                <h3>交易明细汇总</h3>
                <p>按交易日展示操作频次。</p>
              </div>
            </div>
            <el-table :data="tradeActivityRows" stripe height="260" empty-text="暂无交易活跃度数据">
              <el-table-column prop="trade_date" label="交易日期" min-width="160" />
              <el-table-column prop="buy_count" label="买入次数" min-width="120" />
              <el-table-column prop="sell_count" label="卖出次数" min-width="120" />
              <el-table-column prop="trade_count" label="交易总数" min-width="120" />
            </el-table>
          </section>
        </div>
      </template>

      <template v-else-if="activeSection === 'config'">
        <div class="two-col">
          <section class="panel-card">
            <div class="panel-heading">
              <div>
                <h3>策略配置</h3>
                <p>当前 SignalGateway 使用的策略栈。</p>
              </div>
            </div>
            <el-table :data="strategyRows" stripe height="460" empty-text="暂无策略配置">
              <el-table-column prop="name" label="别名" min-width="140" />
              <el-table-column prop="source" label="策略来源" min-width="180" />
              <el-table-column prop="weight" label="权重" min-width="100" />
              <el-table-column prop="params" label="参数" min-width="320" show-overflow-tooltip />
            </el-table>
          </section>

          <section class="panel-card">
            <div class="panel-heading">
              <div>
                <h3>服务配置载荷</h3>
                <p>来自 `/service/config` 的分组配置数据。</p>
              </div>
            </div>
            <pre class="json-panel">{{ JSON.stringify(state.config?.service || {}, null, 2) }}</pre>
          </section>
        </div>
      </template>

      <template v-else-if="activeSection === 'settings'">
        <div class="two-col">
          <section class="panel-card">
            <div class="panel-heading">
              <div>
                <h3>连接设置</h3>
                <p>修改目标 API 地址和当前面板的自动刷新频率。</p>
              </div>
            </div>

            <el-form label-position="top">
              <el-form-item label="API 地址">
                <el-input v-model="settingsForm.apiBase" placeholder="http://127.0.0.1:8000" />
              </el-form-item>
              <el-form-item label="刷新间隔（毫秒）">
                <el-input-number v-model="settingsForm.refreshIntervalMs" :min="2000" :step="1000" controls-position="right" />
              </el-form-item>
              <el-button type="primary" :loading="savingConnection" @click="saveConnectionSettings">应用连接设置</el-button>
            </el-form>
          </section>

          <section class="panel-card">
            <div class="panel-heading">
              <div>
                <h3>调度设置</h3>
                <p>通过调度配置接口动态更新 Cron、间隔、时区和自动启动参数。</p>
              </div>
            </div>

            <div class="schedule-preview">
              <div class="preview-card">
                <span>当前模式</span>
                <strong>{{ schedulerSummary.mode }}</strong>
                <small>{{ schedulerSummary.detail }}</small>
              </div>
              <div class="preview-card">
                <span>下一次触发</span>
                <strong>{{ schedulerSummary.nextRun }}</strong>
                <small v-if="schedulerSummary.countdown !== null">约 {{ schedulerSummary.countdown }} 秒后</small>
                <small v-else>刷新后显示预览</small>
              </div>
            </div>

            <el-form label-position="top">
              <el-form-item label="启用 Cron 调度">
                <el-switch v-model="settingsForm.cronEnabled" />
              </el-form-item>
              <el-form-item label="Cron 模板">
                <div class="preset-groups">
                  <section v-for="group in CRON_PRESET_GROUPS" :key="group.label" class="preset-section">
                    <div class="preset-section-title">{{ group.label }}</div>
                    <div class="preset-grid">
                      <button
                        v-for="preset in group.items"
                        :key="preset.value"
                        type="button"
                        class="preset-chip"
                        @click="applyCronPreset(preset.value)"
                      >
                        <strong>{{ preset.label }}</strong>
                        <span>{{ preset.hint }}</span>
                        <code>{{ preset.value }}</code>
                      </button>
                    </div>
                  </section>
                </div>
              </el-form-item>
              <el-form-item label="Cron 表达式">
                <el-input
                  v-model="settingsForm.cronExpression"
                  :disabled="!settingsForm.cronEnabled"
                  placeholder="0 9 * * 1-5"
                />
              </el-form-item>
              <el-form-item label="轮询间隔（秒）">
                <el-input-number v-model="settingsForm.intervalSeconds" :min="1" :step="60" controls-position="right" />
              </el-form-item>
              <el-form-item label="时区">
                <el-input v-model="settingsForm.timezone" placeholder="Asia/Shanghai" />
              </el-form-item>
              <el-form-item label="自动启动调度器">
                <el-switch v-model="settingsForm.autoStart" />
              </el-form-item>

              <el-alert
                v-if="scheduleValidationError"
                type="warning"
                :closable="false"
                class="inline-alert"
                :title="scheduleValidationError"
              />

              <div class="helper-copy">
                常用示例：`0 9 * * 1-5` 表示工作日固定时点触发，`*/15 9-15 * * 1-5` 表示盘中每 15 分钟触发。
              </div>

              <div v-if="schedulerSummary.nextRuns.length" class="upcoming-block">
                <div class="upcoming-title">未来 3 次触发</div>
                <div class="upcoming-list">
                  <div v-for="item in schedulerSummary.nextRuns" :key="item" class="upcoming-item">{{ item }}</div>
                </div>
              </div>

              <el-button type="primary" :loading="savingSchedule" @click="saveScheduleSettings">应用调度设置</el-button>
            </el-form>
          </section>
        </div>
      </template>

      <template v-else-if="activeSection === 'diagnostics'">
        <div class="two-col">
          <section class="panel-card">
            <div class="panel-heading">
              <div>
                <h3>接口延迟</h3>
                <p>客户端采集的各接口请求耗时。</p>
              </div>
            </div>
            <div class="kv-grid">
              <div v-for="(value, key) in endpointLatency" :key="key" class="kv-item">
                <span>{{ key }}</span>
                <strong>{{ value }} ms</strong>
              </div>
            </div>
          </section>

          <section class="panel-card">
            <div class="panel-heading">
              <div>
                <h3>分析快照</h3>
                <p>用于审计和排障的完整合并载荷。</p>
              </div>
            </div>
            <pre class="json-panel">{{ JSON.stringify(state.analytics || {}, null, 2) }}</pre>
          </section>
        </div>
      </template>
    </main>
  </div>
</template>

<style scoped>
.workspace-shell {
  min-height: 100vh;
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
  padding: 18px;
  color: #d9e4f5;
}

.sidebar-panel,
.top-banner,
.metric-card,
.panel-card {
  border: 1px solid rgba(120, 150, 190, 0.16);
  background: linear-gradient(180deg, rgba(14, 27, 48, 0.94), rgba(11, 22, 39, 0.94));
  box-shadow: 0 18px 50px rgba(0, 0, 0, 0.28);
  backdrop-filter: blur(18px);
}

.sidebar-panel {
  border-radius: 28px;
  padding: 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.eyebrow {
  margin: 0 0 12px;
  color: #6eb7ff;
  text-transform: uppercase;
  letter-spacing: 0.16em;
  font-size: 12px;
}

.brand-block h1,
.top-banner h2,
.panel-heading h3 {
  margin: 0;
}

.brand-block h1 {
  font-size: 34px;
  line-height: 1.08;
}

.brand-copy,
.panel-heading p,
.helper-copy {
  margin: 10px 0 0;
  color: #8fa7c7;
  line-height: 1.6;
}

.side-nav {
  display: grid;
  gap: 10px;
}

.nav-item {
  width: 100%;
  text-align: left;
  padding: 16px;
  border-radius: 18px;
  border: 1px solid rgba(125, 158, 205, 0.08);
  background: rgba(125, 158, 205, 0.04);
  color: #d9e4f5;
  cursor: pointer;
  transition: 160ms ease;
}

.nav-item strong,
.nav-item span {
  display: block;
}

.nav-item span {
  margin-top: 6px;
  color: #8fa7c7;
  font-size: 13px;
}

.nav-item.active {
  border-color: rgba(77, 208, 168, 0.36);
  background: linear-gradient(180deg, rgba(77, 208, 168, 0.14), rgba(31, 76, 69, 0.12));
  transform: translateX(4px);
}

.side-footer {
  margin-top: auto;
  display: grid;
  gap: 10px;
}

.meta-row,
.kv-item {
  padding: 14px 16px;
  border-radius: 16px;
  background: rgba(125, 158, 205, 0.05);
  border: 1px solid rgba(125, 158, 205, 0.08);
}

.meta-row span,
.metric-card span,
.kv-item span {
  display: block;
  color: #8fa7c7;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.meta-row strong,
.kv-item strong {
  display: block;
  margin-top: 8px;
  word-break: break-word;
}

.meta-row strong.good {
  color: #4dd0a8;
}

.content-shell {
  display: grid;
  align-content: start;
  gap: 18px;
}

.top-banner {
  border-radius: 24px;
  padding: 20px 24px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
}

.top-banner h2 {
  font-size: 32px;
}

.connection-badge {
  min-width: 220px;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid rgba(125, 158, 205, 0.12);
  background: rgba(125, 158, 205, 0.05);
}

.connection-badge span,
.connection-badge small {
  display: block;
}

.connection-badge span {
  color: #8fa7c7;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.connection-badge strong {
  display: block;
  margin-top: 6px;
}

.connection-badge small {
  margin-top: 6px;
  color: #8fa7c7;
  word-break: break-all;
}

.connection-badge.tone-ok strong {
  color: #4dd0a8;
}

.connection-badge.tone-error strong {
  color: #ff8b8b;
}

.toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.error-banner,
.inline-alert {
  margin-top: 12px;
}

.card-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 14px;
}

.metric-card {
  padding: 18px;
  border-radius: 22px;
}

.metric-card strong {
  display: block;
  margin-top: 14px;
  font-size: 28px;
}

.metric-card small {
  display: block;
  margin-top: 10px;
  color: #89a0bf;
}

.tone-good strong {
  color: #4dd0a8;
}

.tone-warn strong {
  color: #ff8b8b;
}

.two-col {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.stack-grid {
  display: grid;
  gap: 18px;
}

.section-gap {
  margin-top: 0;
}

.panel-card {
  border-radius: 24px;
  padding: 20px;
}

.panel-heading {
  display: flex;
  justify-content: space-between;
  gap: 16px;
  align-items: start;
  margin-bottom: 16px;
}

.chart-block {
  height: 340px;
}

.kv-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
}

.json-panel {
  margin: 0;
  max-height: 520px;
  overflow: auto;
  border-radius: 18px;
  padding: 16px;
  background: #091320;
  color: #cfe0ff;
  border: 1px solid rgba(120, 150, 190, 0.12);
}

.schedule-preview {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.preview-card {
  padding: 14px 16px;
  border-radius: 16px;
  background: rgba(125, 158, 205, 0.05);
  border: 1px solid rgba(125, 158, 205, 0.08);
}

.preview-card span,
.preview-card small {
  display: block;
}

.preview-card span {
  color: #8fa7c7;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.preview-card strong {
  display: block;
  margin-top: 8px;
}

.preview-card small {
  margin-top: 8px;
  color: #8fa7c7;
}

.preset-groups {
  display: grid;
  gap: 12px;
  width: 100%;
}

.preset-section {
  display: grid;
  gap: 8px;
}

.preset-section-title,
.upcoming-title {
  color: #8fa7c7;
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.preset-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  width: 100%;
}

.preset-chip {
  text-align: left;
  padding: 12px 14px;
  border-radius: 16px;
  border: 1px solid rgba(125, 158, 205, 0.12);
  background: rgba(9, 19, 32, 0.86);
  color: #d9e4f5;
  cursor: pointer;
}

.preset-chip strong,
.preset-chip span,
.preset-chip code {
  display: block;
}

.preset-chip span {
  margin-top: 6px;
  color: #8fa7c7;
  font-size: 13px;
}

.preset-chip code {
  margin-top: 8px;
  color: #6eb7ff;
  font-size: 12px;
}

.upcoming-block {
  margin: 12px 0 16px;
  display: grid;
  gap: 10px;
}

.upcoming-list {
  display: grid;
  gap: 8px;
}

.upcoming-item {
  padding: 10px 12px;
  border-radius: 14px;
  background: rgba(9, 19, 32, 0.86);
  border: 1px solid rgba(125, 158, 205, 0.12);
  color: #d9e4f5;
}

:deep(.el-form-item__label) {
  color: #cfe0ff !important;
}

:deep(.el-input__wrapper),
:deep(.el-textarea__inner),
:deep(.el-input-number),
:deep(.el-input-number .el-input__wrapper) {
  background: rgba(7, 17, 30, 0.88);
  box-shadow: 0 0 0 1px rgba(125, 158, 205, 0.12) inset !important;
}

:deep(.el-input__inner),
:deep(.el-textarea__inner) {
  color: #e8f2ff;
}

:deep(.el-table) {
  --el-table-bg-color: transparent;
  --el-table-tr-bg-color: transparent;
  --el-table-header-bg-color: rgba(125, 158, 205, 0.08);
  --el-table-border-color: rgba(125, 158, 205, 0.12);
  --el-text-color-regular: #d9e4f5;
  --el-fill-color-light: rgba(125, 158, 205, 0.06);
  --el-table-row-hover-bg-color: rgba(8, 19, 35, 0.96);
  color: #d9e4f5;
}

:deep(.el-table th.el-table__cell),
:deep(.el-table tr),
:deep(.el-table td.el-table__cell) {
  background: transparent;
}

:deep(.el-table__body tr:hover > td.el-table__cell) {
  background: rgba(8, 19, 35, 0.96) !important;
  box-shadow: inset 0 1px 0 rgba(110, 183, 255, 0.16), inset 0 -1px 0 rgba(110, 183, 255, 0.16);
  color: #f7fbff !important;
}

:deep(.el-table__body tr:hover > td.el-table__cell .cell) {
  color: #f7fbff !important;
  text-shadow: none !important;
}

:deep(.el-table__body tr.el-table__row:hover > td.el-table__cell),
:deep(.el-table__body tr.hover-row > td.el-table__cell),
:deep(.el-table--enable-row-hover .el-table__body tr:hover > td.el-table__cell) {
  background-color: rgba(8, 19, 35, 0.96) !important;
}

:deep(.el-table__body tr.el-table__row:hover > td.el-table__cell .cell),
:deep(.el-table__body tr.hover-row > td.el-table__cell .cell),
:deep(.el-table--enable-row-hover .el-table__body tr:hover > td.el-table__cell .cell) {
  color: #f7fbff !important;
}

:deep(.el-table--striped .el-table__body tr.el-table__row--striped:hover > td.el-table__cell) {
  background: rgba(8, 19, 35, 0.96) !important;
}

@media (max-width: 1280px) {
  .workspace-shell {
    grid-template-columns: 1fr;
  }

  .card-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 860px) {
  .workspace-shell {
    padding: 12px;
  }

  .two-col,
  .kv-grid,
  .card-grid,
  .schedule-preview,
  .preset-grid {
    grid-template-columns: 1fr;
  }

  .top-banner {
    align-items: start;
    flex-direction: column;
  }
}
</style>
