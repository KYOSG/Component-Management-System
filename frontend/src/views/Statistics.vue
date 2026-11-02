<script setup>
import { nextTick, onBeforeUnmount, onMounted, ref, shallowRef } from 'vue'
import * as echarts from 'echarts'
import http from '../api'

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

function option(title, points, kind) {
  return {
    title: { text: title, left: 8, textStyle: { fontSize: 15, fontWeight: 650, color: '#1f2430' } },
    tooltip: { trigger: 'axis' },
    grid: { left: 56, right: 20, top: 48, bottom: 32 },
    xAxis: { type: 'category', data: points.map((point) => point.date.slice(5)), boundaryGap: kind === 'bar' },
    yAxis: { type: 'value', minInterval: kind === 'line-count' || kind === 'bar' ? 1 : 0 },
    series: [
      {
        type: kind === 'bar' ? 'bar' : 'line',
        smooth: kind !== 'bar',
        showSymbol: false,
        data: points.map((point) => point.value),
        itemStyle: { color: kind === 'bar' ? '#f59e0b' : '#3f51b5' },
        areaStyle: kind === 'bar' ? undefined : { color: 'rgba(63, 81, 181, 0.12)' },
      },
    ],
  }
}

function render(chart, el, title, points, kind) {
  if (!el) return chart
  const instance = chart || echarts.init(el)
  instance.setOption(option(title, points, kind), true)
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
    const next = []
    next[0] = render(charts.value[0], valueEl.value, '库存总价值', valueRes.data.points, 'line')
    next[1] = render(charts.value[1], countEl.value, '库存元件数', countRes.data.points, 'line-count')
    next[2] = render(charts.value[2], consumptionEl.value, '消耗元件数', usedRes.data.points, 'bar')
    charts.value = next
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
      <div class="toolbar">
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
      <p class="muted">默认最近一个月。消耗只统计项目 BOM 的一键出库、单行出库，以及物料盒里的出库。流转不会改变这三条曲线。</p>
    </div>
    <div class="page-card chart-card"><div ref="valueEl" class="chart"></div></div>
    <div class="page-card chart-card"><div ref="countEl" class="chart"></div></div>
    <div class="page-card chart-card"><div ref="consumptionEl" class="chart"></div></div>
  </div>
</template>

<style scoped>
.chart {
  height: 280px;
}

.chart-card {
  padding-bottom: 8px;
}
</style>
