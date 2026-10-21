export const TIMEZONE = 'Asia/Omsk'
export const statusLabels = {
  uploaded: 'В очереди',
  preprocessing: 'Подготовка фото',
  ocr_processing: 'Распознавание',
  parsing: 'Разбор товаров',
  need_review: 'Нужна проверка',
  completed: 'Подтверждён',
  failed: 'Ошибка обработки',
} as const
export const isProcessing = (status: string) =>
  ['uploaded', 'preprocessing', 'ocr_processing', 'parsing'].includes(status)
export const money = (value: string | number | null | undefined) =>
  value == null
    ? 'Нет суммы'
    : new Intl.NumberFormat('ru-RU', {
        style: 'currency',
        currency: 'RUB',
        maximumFractionDigits: 2,
      }).format(Number(value))
export const dateTime = (value: string | null) =>
  value
    ? new Intl.DateTimeFormat('ru-RU', {
        timeZone: TIMEZONE,
        dateStyle: 'medium',
        timeStyle: 'short',
      }).format(new Date(value))
    : 'Дата не определена'
export const shortDate = (value: string) =>
  new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', timeZone: 'UTC' }).format(
    new Date(value),
  )
export function monthNow() {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TIMEZONE,
    year: 'numeric',
    month: '2-digit',
  }).formatToParts(new Date())
  return `${parts.find((p) => p.type === 'year')!.value}-${parts.find((p) => p.type === 'month')!.value}`
}
export function localDateTime(value: string | null) {
  if (!value) return ''
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: TIMEZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(new Date(value))
  const get = (type: string) => parts.find((p) => p.type === type)!.value
  return `${get('year')}-${get('month')}-${get('day')}T${get('hour')}:${get('minute')}`
}
export const omskToIso = (value: string) =>
  value ? new Date(`${value}+06:00`).toISOString() : null

export function decimal(value: string, places = 2, positive = false): string {
  const normalized = value.trim().replace(',', '.')
  if (
    !new RegExp(`^\\d{1,${places === 3 ? 12 : 10}}(?:\\.\\d{1,${places}})?$`).test(normalized) ||
    (positive && Number(normalized) <= 0)
  ) {
    throw new Error(
      places === 3
        ? 'Количество должно быть больше нуля, до 3 знаков после запятой.'
        : 'Укажите неотрицательную сумму, до 2 знаков после запятой.',
    )
  }
  return normalized
}
export function cents(value: string): bigint {
  const [whole, fraction = ''] = decimal(value).split('.')
  return BigInt(whole) * 100n + BigInt(fraction.padEnd(2, '0'))
}
export function centsString(value: bigint) {
  return `${value / 100n}.${String(value % 100n).padStart(2, '0')}`
}
export function lineTotal(quantity: string, price: string) {
  const [whole, fraction = ''] = decimal(quantity, 3, true).split('.')
  const units = BigInt(whole) * 1000n + BigInt(fraction.padEnd(3, '0'))
  return centsString((units * cents(price) + 500n) / 1000n)
}
