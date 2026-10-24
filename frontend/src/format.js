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
  return `第${row}行第${col}列`
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
    quantity: item.quantity || 0,
    box_id: item.box_id ?? null,
    row: item.row ?? null,
    col: item.col ?? null,
    datasheet_url: item.datasheet_url || '',
    image_url: item.image_url || '',
    remark: item.remark || '',
    ...extra,
  }
}
