<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import * as echarts from 'echarts'
import http, { reportRequestError } from '../api'

const loading = ref(false)
const range = ref(defaultRange())
const valueEl = ref(null)
const countEl = ref(null)
const consumptionEl = ref(null)
const charts = shallowRef([])

function pad(number) {
  return String(number).padStart(2, '0')
}

function formatDay(date) {
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}`
}

function defaultRange() {
  const end = new Date()
  const start = new Date()
  start.setDate(end.getDate() - 29)
  return [formatDay(start), formatDay(end)]
}

// 图表颜色从 theme.css 读取，改主题时这里不用动
function cssVar(name, fallback) {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim()
  return value || fallback
}

function alpha(hex, opacity) {
  const match = /^#([0-9a-f]{6})$/i.exec(hex)
  if (!match) return hex
  const n = parseInt(match[1], 16)
  return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${opacity})`
}

function palette() {
  return {
    primary: cssVar('--cms-primary', '#4f46e5'),
    warning: cssVar('--cms-warning', '#d97706'),
    muted: cssVar('--cms-muted', '#64748b'),
    border: cssVar('--cms-border-soft', '#eef2f7'),
    font: cssVar('--cms-font', 'sans-serif'),
  }
}

function option(points, kind, colors) {
  const bar = kind === 'bar'
  const color = bar ? colors.warning : colors.primary
  return {
    textStyle: { fontFamily: colors.font },
    tooltip: { trigger: 'axis' },
    grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
    xAxis: {
      type: 'category',
      data: points.map((point) => point.date.slice(5)),
      boundaryGap: bar,
      axisLine: { lineStyle: { color: colors.border } },
      axisTick: { show: false },
      axisLabel: { color: colors.muted },
    },
    yAxis: {
      type: 'value',
      minInterval: kind === 'line-count' || bar ? 1 : 0,
      axisLabel: { color: colors.muted },
      splitLine: { lineStyle: { color: colors.border } },
    },
    series: [
      {
        type: bar ? 'bar' : 'line',
        smooth: !bar,
        showSymbol: false,
        barMaxWidth: 18,
        data: points.map((point) => point.value),
        itemStyle: { color, borderRadius: bar ? [4, 4, 0, 0] : 0 },
        lineStyle: { width: 2.5 },
        areaStyle: bar
          ? undefined
          : {
              color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                { offset: 0, color: alpha(color, 0.22) },
                { offset: 1, color: alpha(color, 0) },
              ]),
            },
      },
    ],
  }
}

function render(chart, el, points, kind, colors) {
  if (!el) return chart
  const instance = chart || echarts.init(el)
  instance.setOption(option(points, kind, colors), true)
  return instance
}

async function load() {
  if (!range.value || range.value.length !== 2) return
  loading.value = true
  try {
    const params = { start: range.value[0], end: range.value[1] }
    const [valueRes, countRes, usedRes] = await Promise.all([
      http.get('/statistics/value-trend', { params }),
      http.get('/statistics/count-trend', { params }),
      http.get('/statistics/consumption', { params }),
    ])
    await nextTick()
    const colors = palette()
    const next = []
    next[0] = render(charts.value[0], valueEl.value, valueRes.data.points, 'line', colors)
    next[1] = render(charts.value[1], countEl.value, countRes.data.points, 'line-count', colors)
    next[2] = render(charts.value[2], consumptionEl.value, usedRes.data.points, 'bar', colors)
    charts.value = next
  } catch (error) {
    reportRequestError(error)
  } finally {
    loading.value = false
  }
}

function resize() {
  charts.value.forEach((chart) => chart && chart.resize())
}

onMounted(async () => {
  window.addEventListener('resize', resize)
  await load()
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  charts.value.forEach((chart) => chart && chart.dispose())
})
</script>

<template>
  <div v-loading="loading" class="stack">
    <div class="page-card">
      <div class="card-head">
        <div>
          <h3>统计区间</h3>
          <p>默认最近一个月。消耗只统计项目 BOM 的一键出库、单行出库，以及物料盒里的出库。流转不会改变这三条曲线。</p>
        </div>
        <el-date-picker
          v-model="range"
          type="daterange"
          value-format="YYYY-MM-DD"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          :clearable="false"
          @change="load"
        />
      </div>
    </div>
    <div class="chart-grid">
      <section class="page-card chart-wide">
        <h3>库存总价值</h3>
        <div ref="valueEl" class="chart"></div>
      </section>
      <section class="page-card">
        <h3>库存元件数</h3>
        <div ref="countEl" class="chart"></div>
      </section>
      <section class="page-card">
        <h3>消耗元件数</h3>
        <div ref="consumptionEl" class="chart"></div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.card-head {
  flex-wrap: wrap;
}

.chart-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.chart-wide {
  grid-column: 1 / -1;
}

.chart {
  height: 260px;
}

.chart-wide .chart {
  height: 300px;
}

@media (max-width: 1100px) {
  .chart-grid {
    grid-template-columns: minmax(0, 1fr);
  }
}
</style>
