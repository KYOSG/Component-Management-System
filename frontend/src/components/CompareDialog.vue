<script setup>
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import http, { reportRequestError } from '../api'
import { MATCH_STATUS, placeText } from '../format'

const props = defineProps({
  modelValue: Boolean,
  projectId: { type: [Number, String], default: null },
  line: { type: Object, default: () => ({}) },
  item: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'replaced'])

const picked = ref(null)
const query = ref('')
const results = ref([])
const searching = ref(false)
const saving = ref(false)
let searchTimer = null

const IDENTITY = [
  { key: 'lcsc_code', label: '立创编号' },
  { key: 'mpn', label: '型号' },
  { key: 'brand', label: '品牌' },
  { key: 'category', label: '类目' },
  { key: 'footprint', label: '封装' },
  { key: 'value', label: '标称值' },
]

function blank(value) {
  const text = String(value ?? '').trim()
  return !text || text === '-' || text === '—' || text === '无'
}

function show(value) {
  return blank(value) ? '' : String(value).trim()
}

function normKey(value) {
  return String(value || '')
    .replace(/\s+/g, '')
    .replace(/（/g, '(')
    .replace(/）/g, ')')
    .toLowerCase()
}

function normVal(value) {
  return show(value).replace(/\s+/g, '').toLowerCase()
}

function parseParams(text) {
  const source = String(text || '').trim()
  if (!source) return []
  const rows = []
  for (const chunk of source.split(/[;；]+/)) {
    const part = chunk.trim()
    if (!part) continue
    const marks = []
    const re = /(?:^|\s)([^:：\s][^:：]*?)[:：]\s*/g
    let match = re.exec(part)
    while (match) {
      const key = match[1].trim()
      if (key) marks.push({ key, valueAt: match.index + match[0].length, keyAt: match.index })
      match = re.exec(part)
    }
    if (!marks.length) {
      rows.push({ label: '说明', value: part })
      continue
    }
    marks.forEach((mark, index) => {
      const end = index + 1 < marks.length ? marks[index + 1].keyAt : part.length
      rows.push({ label: mark.key, value: part.slice(mark.valueAt, end).trim() })
    })
  }
  return rows
}

function stateOf(left, right) {
  const a = normVal(left)
  const b = normVal(right)
  if (a && b && a === b) return 'same'
  if (a && b) return 'diff'
  if (a || b) return 'missing'
  return ''
}

const status = computed(() => MATCH_STATUS[props.line?.match_status] || null)
const replacementReason = computed(() => (props.line?.reason === '立创编号一致' ? '' : props.line?.reason || ''))

const headline = computed(() => {
  const line = props.line || {}
  const title = show(line.value) || show(line.mpn) || show(line.product_name) || '未填写标称值'
  const bits = [show(line.category), show(line.mpn) && show(line.mpn) !== title ? show(line.mpn) : ''].filter(Boolean)
  return { title, bits: bits.join(' · ') }
})

const stockHeadline = computed(() => {
  const item = picked.value
  if (!item) return null
  const title = show(item.value) || show(item.mpn) || show(item.name) || '未命名物料'
  const bits = [show(item.category), show(item.mpn) && show(item.mpn) !== title ? show(item.mpn) : ''].filter(Boolean)
  return { title, bits: bits.join(' · ') }
})

function chips(record) {
  if (!record) return []
  return [
    show(record.lcsc_code) && record.lcsc_code,
    show(record.footprint) && record.footprint,
    show(record.brand) && record.brand,
  ].filter(Boolean)
}

const bomChips = computed(() => chips(props.line))
const stockChips = computed(() => chips(picked.value))

const place = computed(() => {
  const locs = picked.value?.locations || []
  if (!locs.length) return '未入盒'
  return locs.map((loc) => placeText(loc)).join('；')
})

const required = computed(() => props.line?.quantity_required ?? 0)
const stockEnough = computed(() => (picked.value?.quantity ?? 0) >= required.value)

const rows = computed(() => {
  const line = props.line || {}
  const item = picked.value
  const list = []
  IDENTITY.forEach((field) => {
    const left = line[field.key]
    const right = item?.[field.key]
    const state = item ? stateOf(left, right) : (show(left) ? 'bom' : '')
    if (!state) return
    list.push({ group: '基本信息', label: field.label, left: show(left), right: show(right), state })
  })
  const seen = new Map()
  parseParams(line.params).forEach((row) => {
    const key = normKey(row.label)
    if (!key) return
    seen.set(key, { label: row.label.replace(/\s+/g, ''), left: show(row.value), right: '' })
  })
  if (item) {
    parseParams(item.params).forEach((row) => {
      const key = normKey(row.label)
      if (!key) return
      const current = seen.get(key)
      if (current) current.right = show(row.value)
      else seen.set(key, { label: row.label.replace(/\s+/g, ''), left: '', right: show(row.value) })
    })
  }
  seen.forEach((row) => {
    const identity = list.find((itemRow) => normKey(itemRow.label) === normKey(row.label))
    if (identity && normVal(identity.left) === normVal(row.left) && normVal(identity.right) === normVal(row.right)) return
    const state = item ? stateOf(row.left, row.right) : (row.left ? 'bom' : '')
    if (!state) return
    list.push({ group: '参数', ...row, state })
  })
  return list
})

const groups = computed(() => {
  const order = ['基本信息', '参数']
  return order
    .map((name) => ({ name, rows: rows.value.filter((row) => row.group === name) }))
    .filter((group) => group.rows.length)
})

const summary = computed(() => {
  if (!picked.value) return ''
  const same = rows.value.filter((row) => row.state === 'same').length
  const diff = rows.value.filter((row) => row.state === 'diff').length
  const missing = rows.value.filter((row) => row.state === 'missing').length
  const parts = [`${same} 项一致`]
  if (diff) parts.push(`${diff} 项不同`)
  if (missing) parts.push(`${missing} 项只有一侧有`)
  return parts.join(' · ')
})

function mark(state) {
  if (state === 'same') return '一致'
  if (state === 'diff') return '不同'
  if (state === 'missing') return '缺项'
  return ''
}

const typedCode = computed(() => {
  const text = query.value.trim().toUpperCase()
  return /^C\d{3,}$/.test(text) ? text : ''
})

const codeAlreadyListed = computed(() =>
  results.value.some((row) => (row.lcsc_code || '').toUpperCase() === typedCode.value) ||
  (picked.value?.lcsc_code || '').toUpperCase() === typedCode.value
)

watch(
  () => props.modelValue,
  (open) => {
    if (!open) return
    picked.value = props.item || null
    query.value = ''
    results.value = []
  }
)

watch(
  () => props.item,
  (item) => {
    if (props.modelValue && !picked.value) picked.value = item
  }
)

function onQuery() {
  clearTimeout(searchTimer)
  searchTimer = setTimeout(searchLibrary, 250)
}

async function searchLibrary() {
  const text = query.value.trim()
  if (!text) {
    results.value = []
    return
  }
  searching.value = true
  try {
    const { data } = await http.get('/items', { params: { q: text, page: 1, page_size: 8 } })
    results.value = data.items || []
  } catch (error) {
    reportRequestError(error)
  } finally {
    searching.value = false
  }
}

function choose(row) {
  picked.value = row
}

async function createFromCode() {
  if (!typedCode.value) return false
  saving.value = true
  try {
    const { data } = await http.post('/items/from-lcsc', { lcsc_code: typedCode.value })
    picked.value = data
    ElMessage.success('已按立创编号放入物料库，确认后会写入这条 BOM')
    return true
  } catch (error) {
    reportRequestError(error)
    return false
  } finally {
    saving.value = false
  }
}

async function confirmReplace() {
  if (!props.line?.id || !props.projectId) return
  if (!picked.value && typedCode.value) {
    const created = await createFromCode()
    if (!created) return
  }
  if (!picked.value) {
    ElMessage.warning('请先从库中选择物料，或输入立创编号')
    return
  }
  saving.value = true
  try {
    const { data } = await http.post(`/projects/${props.projectId}/lines/${props.line.id}/replace`, {
      item_id: picked.value.id,
    })
    emit('replaced', data)
    emit('update:modelValue', false)
    ElMessage.success('已用库中物料替换这条 BOM')
  } catch (error) {
    reportRequestError(error)
  } finally {
    saving.value = false
  }
}
</script>

<template>
  <el-dialog
    :model-value="modelValue"
    width="980px"
    align-center
    append-to-body
    class="cmp-dialog"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <template #header>
      <div class="cmp-title">
        <div>
          <strong>物料对照</strong>
          <span v-if="line.designators">{{ line.designators }}</span>
          <span v-if="line.quantity_required != null">需求 {{ line.quantity_required }}</span>
        </div>
        <el-tag v-if="status" :type="status.type" effect="light">{{ status.label }}</el-tag>
      </div>
    </template>

    <div class="cmp-search">
      <el-input
        v-model="query"
        clearable
        placeholder="搜索库存，或输入立创编号新建"
        @input="onQuery"
      />
      <el-button v-if="typedCode && !codeAlreadyListed" :loading="saving" @click="createFromCode">
        用 {{ typedCode }} 新建
      </el-button>
    </div>
    <div v-loading="searching" class="cmp-results">
      <button
        v-for="row in results"
        :key="row.id"
        type="button"
        class="cmp-hit"
        :class="{ on: picked && picked.id === row.id }"
        @click="choose(row)"
      >
        <b>{{ row.lcsc_code || row.mpn || row.name || '未命名' }}</b>
        <span>{{ [row.category, row.value, row.footprint].filter(Boolean).join(' · ') || row.mpn || '—' }}</span>
        <em>库存 {{ row.quantity }}</em>
      </button>
    </div>

    <div class="cmp-cards">
      <section class="cmp-card bom">
        <div class="cmp-kicker">BOM 物料</div>
        <div class="cmp-name">{{ headline.title }}</div>
        <div v-if="headline.bits" class="cmp-sub">{{ headline.bits }}</div>
        <div v-if="bomChips.length" class="cmp-chips">
          <span v-for="chip in bomChips" :key="chip">{{ chip }}</span>
        </div>
      </section>
      <section v-if="picked" class="cmp-card lib">
        <div class="cmp-kicker">库存物料</div>
        <div class="cmp-name">{{ stockHeadline.title }}</div>
        <div v-if="stockHeadline.bits" class="cmp-sub">{{ stockHeadline.bits }}</div>
        <div v-if="stockChips.length" class="cmp-chips">
          <span v-for="chip in stockChips" :key="chip">{{ chip }}</span>
        </div>
        <div class="cmp-stock">
          <b :class="stockEnough ? 'ok' : 'low'">{{ picked.quantity }}</b>
          <span>库存 / 需求 {{ required }}</span>
          <em>{{ place }}</em>
        </div>
      </section>
      <section v-else class="cmp-empty">
        <strong>还没有选中库存物料</strong>
        <p>搜索库中的物料，或输入立创编号新建。确定后，会用选中的物料替换这条 BOM，物料库本身不会被 BOM 覆盖。</p>
      </section>
    </div>

    <div v-if="replacementReason" class="cmp-reason">
      <span>替换理由</span>
      <p>{{ replacementReason }}</p>
      <em v-for="risk in line.risks || []" :key="risk">{{ risk }}</em>
    </div>

    <div class="cmp-summary">{{ picked ? summary : 'BOM 参数' }}</div>
    <div class="cmp-table" :class="{ solo: !picked }">
      <div class="cmp-head">
        <span>字段</span>
        <span>BOM</span>
        <span v-if="picked">库存</span>
        <span v-if="picked"></span>
      </div>
      <template v-for="group in groups" :key="group.name">
        <div class="cmp-group">{{ group.name }}</div>
        <div v-for="row in group.rows" :key="group.name + row.label" class="cmp-row" :class="row.state">
          <span class="cmp-key">{{ row.label }}</span>
          <span class="cmp-val">{{ row.left || '—' }}</span>
          <span v-if="picked" class="cmp-val">{{ row.right || '—' }}</span>
          <span v-if="picked" class="cmp-mark">{{ mark(row.state) }}</span>
        </div>
      </template>
    </div>
    <template #footer>
      <div class="cmp-footer">
        <span>确定后，用右侧物料替换左侧这条 BOM，不会把 BOM 写回物料库。</span>
        <div>
          <el-button @click="emit('update:modelValue', false)">取消</el-button>
          <el-button type="primary" :loading="saving" @click="confirmReplace">确定</el-button>
        </div>
      </div>
    </template>
  </el-dialog>
</template>

<style>
/* 颜色统一取 theme.css 里的 --cms-* 变量 */
.cmp-dialog {
  border-radius: var(--cms-radius-lg);
  overflow: hidden;
}
.cmp-dialog .el-dialog__header {
  margin: 0;
  padding: 18px 22px 8px;
}
.cmp-dialog .el-dialog__body {
  padding: 8px 22px 12px;
}
.cmp-dialog .el-dialog__footer {
  padding: 0 22px 18px;
}
.cmp-search {
  display: flex;
  gap: 8px;
  margin-bottom: 10px;
}
.cmp-search .el-input {
  flex: 1;
}
.cmp-results {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 168px;
  overflow: auto;
  margin-bottom: 12px;
}
.cmp-results:empty {
  display: none;
}
.cmp-hit {
  display: grid;
  grid-template-columns: 140px minmax(0, 1fr) auto;
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--cms-border);
  border-radius: var(--cms-radius-sm);
  background: var(--cms-surface);
  text-align: left;
  cursor: pointer;
  color: inherit;
  transition: border-color 0.15s, background-color 0.15s;
}
.cmp-hit:hover {
  border-color: var(--cms-primary-line);
}
.cmp-hit.on {
  border-color: var(--cms-primary);
  background: var(--cms-primary-soft);
}
.cmp-hit b {
  font-size: 13px;
  font-family: var(--cms-mono);
}
.cmp-hit span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--cms-muted);
  font-size: 12px;
}
.cmp-hit em {
  font-style: normal;
  color: var(--cms-primary-strong);
  font-size: 12px;
  font-weight: 650;
}
.cmp-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.cmp-footer > span {
  color: var(--cms-muted);
  font-size: 12px;
  line-height: 1.5;
}
.cmp-footer > div {
  display: flex;
  gap: 8px;
  flex: 0 0 auto;
}
.cmp-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-right: 28px;
}
.cmp-title strong {
  font-size: 18px;
  color: var(--cms-text);
}
.cmp-title span {
  margin-left: 10px;
  color: var(--cms-muted);
  font-size: 13px;
}
.cmp-cards {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
}
.cmp-card,
.cmp-empty {
  min-height: 148px;
  border-radius: var(--cms-radius);
  padding: 16px 18px;
}
.cmp-card.bom {
  background: linear-gradient(180deg, var(--cms-surface) 0%, var(--cms-primary-soft) 100%);
  border: 1px solid var(--cms-primary-line);
}
.cmp-card.lib {
  background: linear-gradient(180deg, var(--cms-surface) 0%, color-mix(in srgb, var(--cms-success) 9%, var(--cms-surface)) 100%);
  border: 1px solid color-mix(in srgb, var(--cms-success) 28%, var(--cms-surface));
}
.cmp-kicker {
  font-size: 12px;
  font-weight: 650;
  letter-spacing: 0.06em;
  color: var(--cms-muted);
}
.cmp-name {
  margin-top: 8px;
  font-size: 22px;
  font-weight: 700;
  line-height: 1.3;
  color: var(--cms-text);
  word-break: break-word;
}
.cmp-sub {
  margin-top: 4px;
  color: var(--cms-text-2);
  font-size: 13px;
}
.cmp-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}
.cmp-chips span {
  padding: 3px 10px;
  border-radius: 999px;
  background: color-mix(in srgb, var(--cms-surface) 86%, transparent);
  color: var(--cms-primary-strong);
  font-size: 12px;
  font-weight: 650;
}
.cmp-stock {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-top: 14px;
  color: var(--cms-text-2);
  font-size: 13px;
}
.cmp-stock b {
  font-size: 26px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.cmp-stock b.ok {
  color: var(--cms-success-text);
}
.cmp-stock b.low {
  color: var(--cms-warning-text);
}
.cmp-stock em {
  margin-left: auto;
  font-style: normal;
  color: var(--cms-primary-strong);
  font-weight: 650;
}
.cmp-empty {
  display: flex;
  flex-direction: column;
  justify-content: center;
  border: 1px dashed var(--el-border-color);
  background: var(--cms-surface-muted);
  color: var(--cms-muted);
}
.cmp-empty strong {
  color: var(--cms-text);
  font-size: 16px;
}
.cmp-empty p {
  margin: 8px 0 0;
  line-height: 1.6;
}
.cmp-reason {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: var(--cms-radius);
  background: var(--cms-surface-muted);
  border: 1px solid var(--cms-border);
}
.cmp-reason span {
  color: var(--cms-muted);
  font-size: 12px;
}
.cmp-reason p {
  margin: 4px 0 0;
  line-height: 1.6;
  color: var(--cms-text);
}
.cmp-reason em {
  display: inline-block;
  margin: 8px 8px 0 0;
  padding: 2px 8px;
  border-radius: 999px;
  background: var(--cms-warning-soft);
  color: var(--cms-warning-text);
  font-style: normal;
  font-size: 12px;
}
.cmp-summary {
  margin: 16px 0 8px;
  color: var(--cms-muted);
  font-size: 13px;
}
.cmp-table {
  border: 1px solid var(--cms-border);
  border-radius: var(--cms-radius);
  overflow: hidden;
  max-height: min(36vh, 360px);
  overflow: auto;
}
.cmp-head,
.cmp-row {
  display: grid;
  grid-template-columns: 200px minmax(0, 1fr) minmax(0, 1fr) 56px;
  gap: 12px;
  align-items: start;
  padding: 10px 14px;
}
.cmp-table.solo .cmp-head,
.cmp-table.solo .cmp-row {
  grid-template-columns: 200px minmax(0, 1fr);
}
.cmp-head {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--cms-surface-muted);
  color: var(--cms-muted);
  font-size: 12px;
  font-weight: 650;
}
.cmp-group {
  padding: 8px 14px;
  background: var(--cms-surface);
  border-top: 1px solid var(--cms-border-soft);
  color: var(--cms-faint);
  font-size: 12px;
  font-weight: 650;
}
.cmp-row {
  border-top: 1px solid var(--cms-border-soft);
  background: var(--cms-surface);
}
.cmp-row.diff {
  background: var(--cms-warning-soft);
}
.cmp-row.missing {
  background: var(--cms-surface-muted);
}
.cmp-key {
  color: var(--cms-muted);
  font-size: 13px;
  line-height: 1.5;
}
.cmp-val {
  color: var(--cms-text);
  font-size: 13px;
  line-height: 1.55;
  word-break: break-word;
}
.cmp-row.diff .cmp-val {
  font-weight: 700;
}
.cmp-mark {
  font-size: 12px;
  line-height: 1.5;
  text-align: right;
  color: var(--cms-faint);
}
.cmp-row.same .cmp-mark {
  color: var(--cms-success-text);
}
.cmp-row.diff .cmp-mark,
.cmp-row.missing .cmp-mark {
  color: var(--cms-warning-text);
}
</style>
