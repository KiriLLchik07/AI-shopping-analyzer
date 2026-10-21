import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import { Button } from '@radix-ui/themes'
import { ChartBarIcon, ArrowUpRightIcon, ReceiptIcon } from '@phosphor-icons/react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiRequest } from '../api/client'
import type {
  CategoryExpense,
  MonthComparison,
  ProductExpense,
  StoreExpense,
  Summary,
  TrendPoint,
} from '../api/types'
import { TIMEZONE, money, shortDate } from '../lib/format'
import { Empty, ErrorNotice, Loading } from '../components/Feedback'

const presets = [
  { value: 'current_month', label: 'Этот месяц' },
  { value: 'previous_month', label: 'Прошлый месяц' },
  { value: 'last_7_days', label: 'Последние 7 дней' },
  { value: 'last_30_days', label: 'Последние 30 дней' },
  { value: 'custom', label: 'Свой период' },
]
export function AnalyticsPage() {
  const [params, setParams] = useSearchParams()
  const preset = params.get('period') || 'current_month'
  const group = params.get('group_by') || 'day'
  const sort = params.get('sort_by') || 'amount'
  const [selected, setSelected] = useState(preset)
  const [from, setFrom] = useState(params.get('date_from') || '')
  const [to, setTo] = useState(params.get('date_to') || '')
  const [validation, setValidation] = useState('')
  const appliedFrom = params.get('date_from') || ''
  const appliedTo = params.get('date_to') || ''
  useEffect(() => {
    setSelected(preset)
    setFrom(appliedFrom)
    setTo(appliedTo)
    setValidation('')
  }, [preset, appliedFrom, appliedTo])
  const base = new URLSearchParams({ period: preset, timezone: TIMEZONE })
  if (preset === 'custom') {
    base.set('date_from', params.get('date_from') || '')
    base.set('date_to', params.get('date_to') || '')
  }
  const key = base.toString()
  const [summary, categories, trends, products, stores] = useQueries({
    queries: [
      {
        queryKey: ['analytics', 'summary', key],
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          apiRequest<Summary>(`/api/analytics/summary?${base}`, { signal }),
      },
      {
        queryKey: ['analytics', 'categories', key],
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          apiRequest<{ items: CategoryExpense[] }>(`/api/analytics/categories?${base}`, { signal }),
      },
      {
        queryKey: ['analytics', 'trends', key, group],
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          apiRequest<{ points: TrendPoint[] }>(
            `/api/analytics/trends?${base}&group_by=${encodeURIComponent(group)}`,
            { signal },
          ),
      },
      {
        queryKey: ['analytics', 'products', key, sort],
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          apiRequest<{ items: ProductExpense[] }>(
            `/api/analytics/products/top?${base}&limit=8&sort_by=${encodeURIComponent(sort)}`,
            { signal },
          ),
      },
      {
        queryKey: ['analytics', 'stores', key],
        queryFn: ({ signal }: { signal: AbortSignal }) =>
          apiRequest<{ items: StoreExpense[] }>(`/api/analytics/stores?${base}&limit=5`, {
            signal,
          }),
      },
    ],
  })
  const comparison = useQuery({
    queryKey: ['analytics', 'comparison'],
    queryFn: ({ signal }) =>
      apiRequest<MonthComparison>(`/api/analytics/month-comparison?timezone=${TIMEZONE}`, {
        signal,
      }),
  })
  function apply(event: FormEvent) {
    event.preventDefault()
    setValidation('')
    if (selected === 'custom') {
      if (!from || !to || from > to) {
        setValidation('Выберите начало и конец периода. Начало не должно быть позже конца.')
        return
      }
      if ((Date.parse(to) - Date.parse(from)) / 86400000 + 1 > 366) {
        setValidation('Выберите период не длиннее 366 дней.')
        return
      }
    }
    setParams({
      period: selected,
      ...(selected === 'custom' ? { date_from: from, date_to: to } : {}),
      group_by: group,
      sort_by: sort,
    })
  }
  function setOption(name: string, value: string) {
    const next = new URLSearchParams(params)
    next.set(name, value)
    setParams(next)
  }
  const maximum = Math.max(1, ...(trends.data?.points.map((p) => Number(p.total_amount)) ?? []))
  const categoryMax = Math.max(
    1,
    ...(categories.data?.items.map((c) => Number(c.total_amount)) ?? []),
  )
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Расходы без догадок</h1>
          <p>Только подтверждённые покупки. Часовой пояс: Омск.</p>
        </div>
        <Button asChild variant="soft">
          <Link to="/reports">
            Отчёт за месяц
            <ArrowUpRightIcon />
          </Link>
        </Button>
      </header>
      <form className="period-toolbar surface" onSubmit={apply}>
        <label>
          Период
          <select
            aria-label="Период"
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
          >
            {presets.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        {selected === 'custom' && (
          <>
            <label>
              С<input type="date" value={from} onChange={(e) => setFrom(e.target.value)} required />
            </label>
            <label>
              По
              <input type="date" value={to} onChange={(e) => setTo(e.target.value)} required />
            </label>
          </>
        )}
        <Button type="submit">Показать</Button>
      </form>
      {validation && <ErrorNotice error={validation} />}
      {summary.isPending ? (
        <Loading />
      ) : summary.isError ? (
        <ErrorNotice error={summary.error} retry={() => void summary.refetch()} />
      ) : (
        <>
          <section className="summary-strip" aria-label="Итоги периода">
            <div className="summary-primary">
              <span>Расходы за период</span>
              <strong>{money(summary.data.total_amount)}</strong>
              <small>
                {shortDate(summary.data.period.date_from)} -{' '}
                {shortDate(summary.data.period.date_to)}
              </small>
            </div>
            <div className="summary-secondary">
              <ReceiptIcon size={24} />
              <span>Покупок</span>
              <strong>{summary.data.purchase_count}</strong>
            </div>
            <div className="summary-comparison">
              <span>Текущий месяц к прошлому</span>
              {comparison.isPending ? (
                <span className="muted">Загружаем сравнение</span>
              ) : comparison.isError ? (
                <ErrorNotice error={comparison.error} retry={() => void comparison.refetch()} />
              ) : (
                <>
                  <strong>
                    {comparison.data.amount_change_percent == null
                      ? 'Нет базы для сравнения'
                      : `${Number(comparison.data.amount_change_percent) > 0 ? '+' : ''}${Number(comparison.data.amount_change_percent).toLocaleString('ru-RU')}%`}
                  </strong>
                  <small>Сравнение за одинаковую часть месяца.</small>
                </>
              )}
            </div>
          </section>
          {summary.data.purchase_count === 0 && (
            <Empty
              title="За этот период пока нет покупок"
              description="Подтвердите распознанные чеки или выберите другой период."
              action={
                <Button asChild variant="soft">
                  <Link to="/receipts">Проверить чеки</Link>
                </Button>
              }
            />
          )}
        </>
      )}
      <div className="analytics-grid">
        <section className="surface trend-panel">
          <div className="section-header">
            <h2>Динамика расходов</h2>
            <label className="inline-label">
              <span className="sr-only">Группировка</span>
              <select value={group} onChange={(e) => setOption('group_by', e.target.value)}>
                <option value="day">По дням</option>
                <option value="week">По неделям</option>
                <option value="month">По месяцам</option>
              </select>
            </label>
          </div>
          {trends.isPending ? (
            <Loading />
          ) : trends.isError ? (
            <ErrorNotice error={trends.error} retry={() => void trends.refetch()} />
          ) : trends.data.points.length === 0 ? (
            <p className="panel-empty">За выбранный период нет данных.</p>
          ) : (
            <div className="trend-scroll">
              <div
                className="trend-chart"
                role="img"
                aria-label="Расходы по интервалам. Точные суммы доступны в таблице ниже."
              >
                {trends.data.points.map((p) => (
                  <div
                    key={p.bucket_start}
                    className="trend-column"
                    title={`${shortDate(p.bucket_start)}: ${money(p.total_amount)}`}
                  >
                    <span className="trend-amount">{money(p.total_amount)}</span>
                    <div className="trend-bar-area">
                      <div
                        className="trend-bar"
                        style={{ height: `${(Number(p.total_amount) / maximum) * 100}%` }}
                      />
                    </div>
                    <small>{shortDate(p.bucket_start)}</small>
                  </div>
                ))}
              </div>
            </div>
          )}
          {trends.data && trends.data.points.length > 0 && (
            <details className="trend-values">
              <summary>Точные значения</summary>
              <table>
                <thead>
                  <tr>
                    <th>Начало интервала</th>
                    <th>Расходы</th>
                    <th>Покупок</th>
                  </tr>
                </thead>
                <tbody>
                  {trends.data.points.map((p) => (
                    <tr key={p.bucket_start}>
                      <td>{p.bucket_start}</td>
                      <td>{money(p.total_amount)}</td>
                      <td>{p.purchase_count}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </details>
          )}
        </section>
        <section className="surface category-panel">
          <div className="section-header">
            <h2>По категориям</h2>
            <ChartBarIcon size={22} />
          </div>
          {categories.isPending ? (
            <Loading />
          ) : categories.isError ? (
            <ErrorNotice error={categories.error} retry={() => void categories.refetch()} />
          ) : categories.data.items.length === 0 ? (
            <p className="panel-empty">Категории появятся после подтверждения чеков.</p>
          ) : (
            <div className="category-expenses">
              {categories.data.items.map((c) => (
                <div className="category-expense" key={c.category_id || c.category_name}>
                  <div>
                    <span>{c.category_name}</span>
                    <strong>{money(c.total_amount)}</strong>
                  </div>
                  <div
                    className="category-bar"
                    style={{ width: `${(Number(c.total_amount) / categoryMax) * 100}%` }}
                  />
                </div>
              ))}
            </div>
          )}
        </section>
        <section className="surface products-panel">
          <div className="section-header">
            <h2>Товары</h2>
            <label>
              <span className="sr-only">Сортировка товаров</span>
              <select value={sort} onChange={(e) => setOption('sort_by', e.target.value)}>
                <option value="amount">По расходам</option>
                <option value="frequency">По частоте</option>
              </select>
            </label>
          </div>
          {products.isPending ? (
            <Loading />
          ) : products.isError ? (
            <ErrorNotice error={products.error} retry={() => void products.refetch()} />
          ) : products.data.items.length === 0 ? (
            <p className="panel-empty">Пока нет товаров для сравнения.</p>
          ) : (
            <table className="ranking-table">
              <thead>
                <tr>
                  <th>Товар</th>
                  <th>Покупок</th>
                  <th>Расходы</th>
                </tr>
              </thead>
              <tbody>
                {products.data.items.map((p) => (
                  <tr key={p.product_name}>
                    <td>{p.product_name}</td>
                    <td>{p.purchase_count}</td>
                    <td>{money(p.total_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <section className="surface stores-panel">
          <div className="section-header">
            <h2>Магазины</h2>
          </div>
          {stores.isPending ? (
            <Loading />
          ) : stores.isError ? (
            <ErrorNotice error={stores.error} retry={() => void stores.refetch()} />
          ) : stores.data.items.length === 0 ? (
            <p className="panel-empty">Пока нет покупок в магазинах.</p>
          ) : (
            <table className="ranking-table">
              <thead>
                <tr>
                  <th>Магазин</th>
                  <th>Покупок</th>
                  <th>Расходы</th>
                </tr>
              </thead>
              <tbody>
                {stores.data.items.map((p) => (
                  <tr key={p.store_name || 'unknown'}>
                    <td>{p.store_name || 'Не определён'}</td>
                    <td>{p.purchase_count}</td>
                    <td>{money(p.total_amount)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </>
  )
}
