<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import http, { reportRequestError } from '../api'
import { FORMAT_LABEL, MATCH_STATUS, formatDate } from '../format'
import CompareDialog from '../components/CompareDialog.vue'
import ItemDrawer from '../components/ItemDrawer.vue'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const savingSets = ref(false)
const recommending = ref(false)
const committedSets = ref(null)
let recommendAbort = null
let recommendTicket = 0
const project = ref(null)
const boxes = ref([])
const drawer = ref(false)
const draft = ref(null)
const compareVisible = ref(false)
const compareLine = ref({})
const compareItem = ref(null)
const recommendNow = sessionStorage.getItem('recommend-project') === String(route.params.id)
if (recommendNow) sessionStorage.removeItem('recommend-project')
let pageAlive = true

async function load() {
  loading.value = true
  try {
    const [{ data }, boxRes] = await Promise.all([
      http.get(`/projects/${route.params.id}`),
      http.get('/boxes'),
    ])
    committedSets.value = data.purchase_sets
    project.value = data
    boxes.value = boxRes.data
  } catch (error) {
    reportRequestError(error)
  } finally {
    loading.value = false
  }
}

async function removeProject() {
  if (!project.value) return
  try {
    await ElMessageBox.confirm(`删除 ${project.value.name}？明细会一起删除，物料库不受影响。`, '删除 BOM', { type: 'warning' })
  } catch {
    return
  }
  try {
    await http.delete(`/projects/${project.value.id}`)
    ElMessage.success('已删除')
    await router.push('/projects')
  } catch (error) {
    reportRequestError(error)
  }
}

function needsRecommend(data) {
  return Boolean(data?.ai_enabled && data.lines?.some((line) => line.match_status === ''))
}

function applyLine(line) {
  const rows = project.value?.lines
  if (!rows) return
  const index = rows.findIndex((item) => item.id === line.id)
  if (index >= 0) rows.splice(index, 1, line)
}

function stopRecommend() {
  recommendAbort?.abort()
}

async function startRecommend() {
  if (!needsRecommend(project.value)) return
  stopRecommend()
  const ticket = ++recommendTicket
  const controller = new AbortController()
  recommendAbort = controller
  recommending.value = true
  try {
    const response = await fetch(`/api/projects/${route.params.id}/recommend`, {
      credentials: 'include',
      headers: { Accept: 'text/event-stream' },
      signal: controller.signal,
    })
    if (!response.ok || !response.body) throw new Error('recommend failed')
    const reader = response.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buffer += decoder.decode(value, { stream: true })
      const parts = buffer.split('\n\n')
      buffer = parts.pop() || ''
      for (const part of parts) {
        const dataLine = part.split('\n').find((item) => item.startsWith('data:'))
        if (!dataLine) continue
        const payload = JSON.parse(dataLine.slice(5).trim())
        if (payload?.id) applyLine(payload)
      }
    }
  } catch (error) {
    if (error?.name !== 'AbortError') ElMessage.error('Ai推荐中断')
  } finally {
    if (ticket === recommendTicket) {
      recommending.value = false
      recommendAbort = null
    }
  }
}

async function rematch() {
  stopRecommend()
  try {
    const { data } = await http.post(`/projects/${route.params.id}/match`)
    committedSets.value = data.purchase_sets
    project.value = data
    if (needsRecommend(data)) startRecommend()
    else ElMessage.success('已重新匹配')
  } catch (error) {
    reportRequestError(error)
  }
}

async function saveSets(value) {
  if (!project.value || value == null || value < 1 || value === committedSets.value) return
  stopRecommend()
  savingSets.value = true
  try {
    const { data } = await http.put(`/projects/${route.params.id}`, { purchase_sets: value })
    committedSets.value = data.purchase_sets
    project.value = data
    if (needsRecommend(data)) startRecommend()
    else ElMessage.success('已更新套数')
  } catch (error) {
    reportRequestError(error)
    await load()
  } finally {
    savingSets.value = false
  }
}

async function adopt(row) {
  if (!row.lcsc_code) {
    draft.value = {
      lcsc_code: '',
      mpn: row.mpn || '',
      name: row.product_name || '',
      brand: row.brand || '',
      footprint: row.footprint || '',
      category: row.category || '',
      value: row.value || '',
      params: row.params || '',
      specs: {},
      quantity: 0,
    }
    drawer.value = true
    ElMessage.info('已用 BOM 中的字段预填，请核对后填写自有库存和物料盒再保存')
    return
  }
  try {
    const { data } = await http.post(`/projects/${route.params.id}/lines/${row.id}/adopt`)
    if (data.warning) ElMessage.warning(data.warning)
    else ElMessage.info(`商城库存 ${data.mall_stock ?? '—'}，参考价格 ${data.mall_price || '—'}，请填写自有库存和物料盒后再保存`)
    draft.value = data
    drawer.value = true
  } catch (error) {
    reportRequestError(error)
  }
}

function replacementReason(row) {
  return row?.reason === '立创编号一致' ? '' : (row?.reason || '')
}

function canAdopt(row) {
  return row.match_status === 'not_found' || row.match_status === 'suggested'
}

function canAccept(row) {
  return row.match_status === 'suggested' && !!row.matched_item_id
}

function canCheckout(row) {
  return !!row.matched_item_id && ['matched', 'insufficient'].includes(row.match_status)
}

async function addAll() {
  try {
    await ElMessageBox.confirm(
      '会按每一行的需求数量入库：物料库里已有的物料增加库存，没有的新建物料。可以重复执行，每执行一次就再入库一次。',
      '全部加入物料库',
      { type: 'warning', confirmButtonText: '确认入库', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  stopRecommend()
  try {
    const { data } = await http.post(`/projects/${route.params.id}/add-all`)
    ElMessage.success(`已加入 ${data.added} 个，增量 ${data.incremented} 个`)
    await load()
  } catch (error) {
    reportRequestError(error)
  }
}

async function checkoutLine(row) {
  const name = row.mpn || row.lcsc_code || row.value || '该物料'
  try {
    await ElMessageBox.confirm(`出库 ${row.quantity_required} 个「${name}」？会计入消耗统计。`, '出库', { type: 'warning' })
  } catch {
    return
  }
  try {
    const { data } = await http.post(`/projects/${route.params.id}/lines/${row.id}/checkout`)
    applyLine(data)
    ElMessage.success('已出库')
  } catch (error) {
    reportRequestError(error)
  }
}

async function checkout() {
  try {
    await ElMessageBox.confirm('将按需求数量扣减已匹配物料的库存，库存可以为负数，会计入消耗统计。未入库的行和还没点“使用替换器件”确认的替换建议会跳过。可以重复执行，每执行一次就再扣一次。', '一键出库', { type: 'warning' })
  } catch {
    return
  }
  stopRecommend()
  try {
    const { data } = await http.post(`/projects/${route.params.id}/checkout`)
    ElMessage.success(`已出库 ${data.deducted} 行，跳过 ${data.skipped} 行`)
    await load()
  } catch (error) {
    reportRequestError(error)
  }
}

async function acceptSuggestion(row) {
  try {
    const { data } = await http.post(`/projects/${route.params.id}/lines/${row.id}/accept`)
    applyLine(data)
  } catch (error) {
    reportRequestError(error)
  }
}

async function stockDelta(row, delta) {
  try {
    const { data } = await http.post(`/projects/${route.params.id}/lines/${row.id}/stock-delta`, { delta })
    applyLine(data)
  } catch (error) {
    reportRequestError(error)
  }
}

async function openCompare(row) {
  compareLine.value = row
  compareItem.value = null
  try {
    if (row.matched_item_id) {
      const { data } = await http.get(`/items/${row.matched_item_id}`)
      compareItem.value = data
    }
    compareVisible.value = true
  } catch (error) {
    reportRequestError(error)
  }
}

function onPageHide() {
  stopRecommend()
}

onMounted(async () => {
  window.addEventListener('pagehide', onPageHide)
  await load()
  if (pageAlive && recommendNow) startRecommend()
})

onBeforeUnmount(() => {
  pageAlive = false
  window.removeEventListener('pagehide', onPageHide)
  stopRecommend()
})
</script>

<template>
  <div v-loading="loading" class="stack">
    <div v-if="project" class="page-card">
      <div class="toolbar">
        <el-button icon="ArrowLeft" @click="router.push('/projects')">返回列表</el-button>
        <el-button icon="Grid" @click="router.push({ path: '/map', query: { project: project.id } })">在物料盒地图中查看</el-button>
        <span class="spacer" />
        <el-button type="danger" plain icon="Delete" @click="removeProject">删除</el-button>
        <el-button type="warning" plain @click="checkout">一键出库</el-button>
        <el-button type="success" plain @click="addAll">全部加入物料库</el-button>
        <el-button type="primary" icon="Refresh" :loading="recommending" @click="rematch">重新匹配</el-button>
      </div>
      <el-alert
        v-if="!project.ai_enabled"
        title="未配置辅助Ai，未启用智能建议"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 16px"
      />
      <el-descriptions :column="3" border>
        <el-descriptions-item label="名称">{{ project.name }}</el-descriptions-item>
        <el-descriptions-item label="格式">{{ FORMAT_LABEL[project.format] || project.format }}</el-descriptions-item>
        <el-descriptions-item label="来源文件">{{ project.source_filename }}</el-descriptions-item>
        <el-descriptions-item label="套数">
          <el-input-number
            v-model="project.purchase_sets"
            :min="1"
            :step="1"
            :precision="0"
            :disabled="savingSets"
            @change="saveSets"
          />
        </el-descriptions-item>
        <el-descriptions-item label="配单编号">{{ project.order_no || '—' }}</el-descriptions-item>
        <el-descriptions-item label="导入时间">{{ formatDate(project.imported_at) }}</el-descriptions-item>
      </el-descriptions>
    </div>
    <div v-if="project" class="page-card">
      <el-alert
        v-if="recommending"
        title="Ai推荐中"
        type="info"
        show-icon
        :closable="false"
        style="margin-bottom: 16px"
      />
      <el-table :data="project.lines">
        <el-table-column label="位号" min-width="120">
          <template #default="{ row }">{{ row.designators || '—' }}</template>
        </el-table-column>
        <el-table-column label="用量" min-width="150">
          <template #default="{ row }">单板 {{ row.quantity_per_board }} / 需求 {{ row.quantity_required }}</template>
        </el-table-column>
        <el-table-column label="立创编号" width="120">
          <template #default="{ row }"><span class="mono">{{ row.lcsc_code || '—' }}</span></template>
        </el-table-column>
        <el-table-column label="类型 / 标称值" min-width="160">
          <template #default="{ row }">
            <span v-if="row.category">{{ row.category }}</span>
            <span v-if="row.category && row.value"> · </span>
            <span v-if="row.value">{{ row.value }}</span>
            <span v-if="!row.category && !row.value">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="footprint" label="封装" min-width="140" show-overflow-tooltip />
        <el-table-column label="料库状态" width="110">
          <template #default="{ row }">
            <el-tag v-if="MATCH_STATUS[row.match_status]" :type="MATCH_STATUS[row.match_status].type" effect="light" round>
              {{ MATCH_STATUS[row.match_status].label }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="库中位置" min-width="240">
          <template #default="{ row }">
            <div v-for="place in row.locations" :key="place">{{ place }}</div>
            <span v-if="!row.locations.length" class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="库存/需求" width="120">
          <template #default="{ row }">{{ row.stock ?? '—' }} / {{ row.quantity_required }}</template>
        </el-table-column>
        <el-table-column label="替换理由" min-width="220">
          <template #default="{ row }">
            <div>{{ replacementReason(row) || '—' }}</div>
            <el-tag v-for="risk in row.risks" :key="risk" size="small" type="warning" style="margin: 4px 4px 0 0">{{ risk }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <div class="ops">
              <el-button size="small" @click="openCompare(row)">替换</el-button>
              <el-button v-if="canAccept(row)" size="small" type="primary" @click="acceptSuggestion(row)">使用替换器件</el-button>
              <el-button v-if="canAdopt(row)" size="small" type="primary" plain @click="adopt(row)">
                {{ row.lcsc_code ? '按编号加入' : '加入物料库' }}
              </el-button>
              <el-button v-if="canCheckout(row)" size="small" type="warning" plain @click="checkoutLine(row)">出库</el-button>
              <el-button v-if="canCheckout(row)" size="small" type="success" plain @click="stockDelta(row, row.quantity_required)">补充库存</el-button>
              <el-button v-if="canCheckout(row)" size="small" type="danger" plain @click="stockDelta(row, -row.quantity_required)">减扣库存</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </div>
    <ItemDrawer v-model="drawer" :draft="draft" :boxes="boxes" @saved="rematch" />
    <CompareDialog
      v-model="compareVisible"
      :project-id="project && project.id"
      :line="compareLine"
      :item="compareItem"
      @replaced="applyLine"
    />
  </div>
</template>

<style scoped>
.ops {
  display: flex;
  flex-direction: column;
  align-items: stretch;
  gap: 4px;
}
.ops :deep(.el-button) {
  margin-left: 0;
}
</style>
