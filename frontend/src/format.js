import { ElMessage } from 'element-plus'

export const MATCH_STATUS = {
  matched: { label: '已匹配', type: 'success' },
  insufficient: { label: '库存不足', type: 'warning' },
  suggested: { label: '建议替换', type: 'primary' },
  not_found: { label: '未找到', type: 'info' },
}

export const FORMAT_LABEL = {
  easyeda_v131: '立创 EDA',
  lcsc_quote: '立创商城报价单',
}

export function formatDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  const pad = (number) => String(number).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}

export function cellText(row, col) {
  if (!row || !col) return '未入盒'
  return `${row}-${col}`
}

export function money(value) {
  if (value === null || value === undefined || value === '') return '—'
  const number = Number(value)
  if (Number.isNaN(number)) return '—'
  return `¥${number.toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`
}

export function placeText(loc) {
  if (!loc) return '未入库'
  const qty = loc.quantity ?? 0
  if (loc.location_type === 'tape_reel') {
    const label = loc.slot_index ? `卷${loc.slot_index}` : (loc.reel_label || '料卷')
    return `${loc.box_name || '料卷盒'} ${label} × ${qty}`
  }
  if (loc.location_type === 'box_cell') return `${loc.box_name || '物料盒'} ${loc.row}-${loc.col} × ${qty}`
  return `未入库 × ${qty}`
}

export function itemPayload(item, extra = {}) {
  return {
    lcsc_code: item.lcsc_code || '',
    mpn: item.mpn || '',
    name: item.name || '',
    brand: item.brand || '',
    footprint: item.footprint || '',
    category: item.category || '',
    value: item.value || '',
    params: item.params || '',
    specs: { ...(item.specs || {}) },
    quantity: item.quantity || 0,
    min_stock: item.min_stock || 0,
    unit_price: item.unit_price ?? null,
    datasheet_url: item.datasheet_url || '',
    image_url: item.image_url || '',
    remark: item.remark || '',
    ...extra,
  }
}

function pickFilename(header, fallback) {
  const text = header || ''
  const encoded = text.match(/filename\*=UTF-8''([^;]+)/i)
  if (encoded) return decodeURIComponent(encoded[1])
  const plain = text.match(/filename="?([^";]+)"?/i)
  return plain ? plain[1] : fallback
}

export async function downloadFile(http, url, params, fallback) {
  let response
  try {
    response = await http.get(url, { params, responseType: 'blob' })
  } catch (error) {
    const blob = error.response?.data
    if (blob instanceof Blob) {
      try {
        const detail = JSON.parse(await blob.text()).detail
        if (typeof detail === 'string') ElMessage.error(detail)
      } catch {
        // 响应不是 JSON，交给默认提示
      }
    }
    throw error
  }
  const link = document.createElement('a')
  link.href = URL.createObjectURL(response.data)
  link.download = pickFilename(response.headers['content-disposition'], fallback)
  document.body.appendChild(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(link.href), 1000)
}
