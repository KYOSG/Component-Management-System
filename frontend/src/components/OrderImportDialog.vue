<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import http, { reportRequestError } from '../api'

const props = defineProps({
  modelValue: Boolean,
})
const emit = defineEmits(['update:modelValue', 'done'])

const parsing = ref(false)
const committing = ref(false)
const refreshing = ref(false)
const preview = ref(null)
const selected = ref([])
const queuedCodes = ref([])
const pendingCodes = ref([])

const open = computed({
  get: () => props.modelValue,
  set: (value) => emit('update:modelValue', value),
})
const busy = computed(() => parsing.value || committing.value || refreshing.value)
const loadingText = computed(() => {
  if (committing.value) return '正在入库'
  if (refreshing.value) return '正在安排更新'
  return '正在解析订单'
})
const shippable = computed(() => (preview.value?.create_count || 0) + (preview.value?.stock_count || 0))

watch(
  () => props.modelValue,
  (shown) => {
    if (!shown) return
    preview.value = null
    selected.value = []
    queuedCodes.value = []
    pendingCodes.value = []
  },
)

function beforeClose(done) {
  if (!committing.value && !refreshing.value) done()
}

function codeOf(row) {
  return String(row?.lcsc_code || '').trim().toUpperCase()
}

function canRefresh(row) {
  return Boolean(codeOf(row)) && row.action !== 'skip'
}

function codeState(row) {
  const code = codeOf(row)
  if (queuedCodes.value.includes(code)) return '更新中'
  if (pendingCodes.value.includes(code)) return '入库后更新'
  return ''
}

function onSelect(rows) {
  selected.value = rows
}

function remember(list, incoming) {
  return [...new Set([...list, ...incoming.map((code) => String(code || '').trim().toUpperCase()).filter(Boolean)])]
}

function priceText(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (Number.isNaN(number)) return '—'
  return `¥${number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`
}

function rowClass({ row }) {
  return row.action === 'skip' ? 'is-skip' : ''
}

async function upload(option) {
  if (option.file.size > 10 * 1024 * 1024) {
    ElMessage.error('文件不能超过 10MB')
    return
  }
  const body = new FormData()
  body.append('file', option.file)
  parsing.value = true
  preview.value = null
  selected.value = []
  queuedCodes.value = []
  pendingCodes.value = []
  try {
    const { data } = await http.post('/items/order-preview', body)
    preview.value = data
  } catch (error) {
    reportRequestError(error)
  } finally {
    parsing.value = false
  }
}

async function queueRefresh() {
  const lines = selected.value.filter(canRefresh)
  if (!lines.length) {
    ElMessage.warning('请先勾选带有立创编号、并且会入库的明细')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将按立创编号查询并更新勾选的 ${lines.length} 条物料：型号、名称、品牌、封装、类目、标称值、参数、规格、数据手册和图片。已有单价、库存、存放位置、备注和低库存阈值会保留。已经在库里的马上开始；还没入库的，会在确认入库之后开始。查询大约每分钟不超过 30 条，两次之间随机间隔，可以先入库。每条物料更新结束前不能再次查询或编辑。`,
      '批量查询并更新',
      { type: 'warning', confirmButtonText: '开始更新', cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  refreshing.value = true
  try {
    const codes = [...new Set(lines.map(codeOf))]
    const { data } = await http.post('/items/lcsc-refresh', { lcsc_codes: codes })
    queuedCodes.value = remember(queuedCodes.value, data.queued_codes || [])
    pendingCodes.value = remember(pendingCodes.value, data.pending_codes || [])
    const parts = []
    if (data.queued) parts.push(`已开始更新 ${data.queued} 条`)
    if (data.pending_codes?.length) parts.push(`${data.pending_codes.length} 条会在确认入库后开始`)
    if (data.skipped_busy) parts.push(`${data.skipped_busy} 条正在更新`)
    const text = parts.join('，') || '没有可更新的物料'
    if (data.queued || data.pending_codes?.length) ElMessage.success(text)
    else ElMessage.warning(text)
  } catch (error) {
    reportRequestError(error)
  } finally {
    refreshing.value = false
  }
}

async function commit() {
  if (!preview.value || !shippable.value) return
  committing.value = true
  try {
    const refreshCodes = [
      ...new Set(
        preview.value.lines
          .filter((row) => row.action !== 'skip' && pendingCodes.value.includes(codeOf(row)))
          .map(codeOf),
      ),
    ]
    const { data } = await http.post('/items/order-commit', {
      order_no: preview.value.order_no,
      refresh_codes: refreshCodes,
      lines: preview.value.lines.map((row) => ({
        lcsc_code: row.lcsc_code,
        mpn: row.mpn,
        name: row.name,
        brand: row.brand,
        footprint: row.footprint,
        ship_qty: row.ship_qty,
        unit_price: row.unit_price,
        skip: row.action === 'skip',
      })),
    })
    const parts = []
    if (data.created) parts.push(`新建 ${data.created} 种`)
    if (data.stocked) parts.push(`追加 ${data.stocked} 种`)
    if (data.refresh_queued) parts.push(`后台更新 ${data.refresh_queued} 条`)
    ElMessage.success(`已入库 ${data.ship_total} 件${parts.length ? `，${parts.join('，')}` : ''}`)
    open.value = false
    emit('done')
  } catch (error) {
    reportRequestError(error)
  } finally {
    committing.value = false
  }
}

function close() {
  if (committing.value || refreshing.value) return
  open.value = false
}
</script>

<template>
  <el-dialog
    v-model="open"
    :title="preview ? '确认订单入库' : '订单入库'"
    width="92%"
    top="6vh"
    :close-on-click-modal="!preview && !busy"
    :close-on-press-escape="!busy"
    :show-close="!committing"
    :before-close="beforeClose"
  >
    <div v-loading="busy" :element-loading-text="loadingText">
      <el-upload
        v-if="!preview"
        drag
        :show-file-list="false"
        accept=".xls,.xlsx"
        :http-request="upload"
        :disabled="parsing"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">将立创商城订单详情拖到此处，或<em>点击上传</em></div>
        <div class="el-upload__tip">支持 .xls / .xlsx。确认后按发货数量入库，库里没有的物料会新建。</div>
      </el-upload>

      <template v-else>
        <el-alert
          v-if="preview.already_imported"
          class="order-alert"
          type="warning"
          show-icon
          :closable="false"
          title="这个订单之前已经入过库，再次确认会再次增加库存"
        />
        <div class="order-meta">
          <span>订单编号 <strong>{{ preview.order_no || '—' }}</strong></span>
          <span>下单日期 <strong>{{ preview.ordered_at || '—' }}</strong></span>
          <span>发货合计 <strong>{{ preview.ship_total }}</strong></span>
          <span>新建 {{ preview.create_count }} · 追加 {{ preview.stock_count }} · 跳过 {{ preview.skip_count }}</span>
        </div>
        <p class="order-note">已有物料只按发货数量增加库存。新建物料会写入订单里的型号、封装和单价，标称值和类目按商品名称识别。数量先记在未入库，之后可以再放入物料盒。发货数量和订购数量不一致时会标出。勾选明细后可以批量查询立创资料，查询在后台进行，可以先入库。</p>
        <el-table :data="preview.lines" :row-class-name="rowClass" height="460" table-layout="auto" @selection-change="onSelect">
          <el-table-column type="selection" width="42" align="center" :selectable="canRefresh" />
          <el-table-column prop="line_no" label="序号" width="64" align="center" />
          <el-table-column label="商品编号" min-width="120" align="center">
            <template #default="{ row }"><span class="mono">{{ row.lcsc_code || '—' }}</span></template>
          </el-table-column>
          <el-table-column prop="mpn" label="厂家型号" min-width="160" show-overflow-tooltip>
            <template #default="{ row }">{{ row.mpn || '—' }}</template>
          </el-table-column>
          <el-table-column prop="name" label="商品名称" min-width="220" show-overflow-tooltip>
            <template #default="{ row }">{{ row.name || '—' }}</template>
          </el-table-column>
          <el-table-column prop="footprint" label="封装" width="120" align="center" show-overflow-tooltip>
            <template #default="{ row }">{{ row.footprint || '—' }}</template>
          </el-table-column>
          <el-table-column label="类目" width="90" align="center">
            <template #default="{ row }">{{ row.category || '—' }}</template>
          </el-table-column>
          <el-table-column label="标称值" width="100" align="center">
            <template #default="{ row }"><strong v-if="row.value">{{ row.value }}</strong><span v-else>—</span></template>
          </el-table-column>
          <el-table-column prop="ordered_qty" label="订购" width="72" align="center" />
          <el-table-column label="发货" width="72" align="center">
            <template #default="{ row }">
              <strong :class="{ 'ship-diff': row.ordered_qty !== row.ship_qty }">{{ row.ship_qty }}</strong>
            </template>
          </el-table-column>
          <el-table-column label="单价" width="110" align="center">
            <template #default="{ row }">{{ priceText(row.unit_price) }}</template>
          </el-table-column>
          <el-table-column label="处理" width="168" align="center">
            <template #default="{ row }">
              <el-tag v-if="row.action === 'create'" type="success" effect="light">新建并入库</el-tag>
              <el-tag v-else-if="row.action === 'stock'" type="primary" effect="light">追加，现有 {{ row.current_quantity }}</el-tag>
              <el-tag v-else type="info" effect="light">{{ row.skip_reason || '跳过' }}</el-tag>
              <div v-if="codeState(row)" class="refresh-mark">{{ codeState(row) }}</div>
            </template>
          </el-table-column>
        </el-table>
      </template>
    </div>
    <template #footer>
      <div class="order-footer">
        <el-upload
          v-if="preview"
          :show-file-list="false"
          accept=".xls,.xlsx"
          :http-request="upload"
          :disabled="busy"
        >
          <el-button :disabled="busy">重新选择</el-button>
        </el-upload>
        <span class="spacer" />
        <el-button
          v-if="preview"
          :disabled="busy || !selected.length"
          :loading="refreshing"
          @click="queueRefresh"
        >
          批量查询并更新
        </el-button>
        <el-button :disabled="committing || refreshing" @click="close">取消</el-button>
        <el-button v-if="preview" type="primary" :loading="committing" :disabled="!shippable || parsing" @click="commit">
          确认入库
        </el-button>
      </div>
    </template>
  </el-dialog>
</template>

<style scoped>
.order-alert {
  margin-bottom: 12px;
}

.order-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px 18px;
  margin-bottom: 8px;
  color: var(--cms-text-2);
}

.order-note {
  margin: 0 0 12px;
  color: var(--cms-muted);
  font-size: 13px;
}

.order-footer {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}

.refresh-mark {
  margin-top: 4px;
  color: var(--cms-text-2);
  font-size: 12px;
}

.order-footer :deep(.el-button) {
  margin-left: 0;
}

.ship-diff {
  color: var(--cms-warning-text);
}

:deep(.is-skip) {
  color: var(--cms-muted);
}
</style>
