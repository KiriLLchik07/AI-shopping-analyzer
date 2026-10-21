export type Money = string
export type User = { user_id: string; user_name: string; user_surname: string; user_mail: string }
export type Page<T> = {
  items: T[]
  page: number
  page_size: number
  total: number
  total_pages: number
}
export type ReceiptStatus =
  | 'uploaded'
  | 'preprocessing'
  | 'ocr_processing'
  | 'parsing'
  | 'need_review'
  | 'completed'
  | 'failed'
export type Receipt = {
  receipt_id: string
  store_name: string | null
  purchase_datetime: string | null
  total_amount: Money | null
  status: ReceiptStatus
  created_at: string
  confirmed_at: string | null
  processing_error_message: string | null
  raw_ocr_text: string | null
  ocr_confidence: number | null
  parsing_report?: { warnings?: unknown[] } | null
}
export type ReceiptItem = {
  receipt_item_id: string
  raw_name: string
  normalized_name: string | null
  quantity: string | null
  unit: string | null
  unit_price: Money | null
  total_price: Money | null
  category_id: string | null
  confidence: number | null
}
export type ReceiptDetail = Receipt & { items: ReceiptItem[] }
export type Category = { category_id: string; category_name: string }
export type Period = { date_from: string; date_to: string; timezone: string }
export type Summary = { total_amount: Money; purchase_count: number; period: Period }
export type CategoryExpense = {
  category_id: string | null
  category_name: string
  total_amount: Money
  purchase_count: number
}
export type ProductExpense = { product_name: string; total_amount: Money; purchase_count: number }
export type StoreExpense = {
  store_name: string | null
  total_amount: Money
  purchase_count: number
}
export type TrendPoint = { bucket_start: string; total_amount: Money; purchase_count: number }
export type MonthComparison = {
  amount_change: string
  amount_change_percent: string | null
  current: { total_amount: Money }
  previous: { total_amount: Money }
}
export type ReportSummary = {
  report_id: string
  period_start: string
  period_end: string
  created_at: string
  timezone: string
  model_name: string
}
export type Report = ReportSummary & {
  report_data: {
    summary: string
    recommendations: { title: string; reason: string; action: string }[]
  }
  input_data: {
    current: { total_amount: Money; purchase_count: number }
    previous: { total_amount: Money }
  }
}
