import { useQuery } from '@tanstack/react-query'
import { Link, useSearchParams } from 'react-router-dom'
import { Button } from '@radix-ui/themes'
import { PlusIcon, ArrowUpRightIcon, ReceiptIcon, MagnifyingGlassIcon } from '@phosphor-icons/react'
import { useEffect, useState } from 'react'
import { apiRequest } from '../api/client'
import type { Page, Receipt } from '../api/types'
import { dateTime, isProcessing, money, statusLabels } from '../lib/format'
import { Empty, ErrorNotice, Loading } from '../components/Feedback'
import { StatusBadge } from '../components/StatusBadge'
import { Pagination } from '../components/Pagination'

export function ReceiptsPage() {
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Number(params.get('page')) || 1)
  const status = params.get('status') ?? ''
  const store = params.get('store') ?? ''
  const [search, setSearch] = useState(store)
  useEffect(() => setSearch(store), [store])
  const query = new URLSearchParams({ page: String(page), page_size: '15' })
  if (status in statusLabels) query.set('status', status)
  if (store) query.set('store_name', store)
  const receipts = useQuery({
    queryKey: ['receipts', query.toString()],
    queryFn: ({ signal }) => apiRequest<Page<Receipt>>(`/api/receipts?${query}`, { signal }),
    refetchInterval: (q) =>
      q.state.data?.items.some((r) => isProcessing(r.status)) ? 3000 : false,
  })
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params)
    if (value) next.set(key, value)
    else next.delete(key)
    next.delete('page')
    setParams(next)
  }
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Ваши чеки</h1>
          <p>От фотографии до понятных расходов.</p>
        </div>
        <Button asChild size="3">
          <Link to="/upload">
            <PlusIcon size={19} />
            Добавить чек
          </Link>
        </Button>
      </header>
      <section className="surface receipts-surface" aria-label="Список чеков">
        <div className="list-toolbar">
          <form
            className="search-form"
            onSubmit={(e) => {
              e.preventDefault()
              filter('store', search.trim())
            }}
          >
            <MagnifyingGlassIcon size={20} aria-hidden="true" />
            <input
              aria-label="Название магазина"
              placeholder="Найти магазин"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              maxLength={100}
            />
            <Button type="submit" variant="ghost" color="gray">
              Найти
            </Button>
          </form>
          <label className="inline-label">
            Статус
            <select
              aria-label="Статус"
              value={status}
              onChange={(e) => filter('status', e.target.value)}
            >
              <option value="">Все чеки</option>
              {Object.entries(statusLabels).map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        {receipts.isPending ? (
          <Loading />
        ) : receipts.isError ? (
          <ErrorNotice error={receipts.error} retry={() => void receipts.refetch()} />
        ) : (
          <>
            <div className="list-caption">
              <span>{receipts.data.total} чеков</span>
              <span>Сначала новые</span>
            </div>
            {receipts.data.items.length === 0 ? (
              <Empty
                title={store || status ? 'Чеки не найдены' : 'Здесь будут ваши покупки'}
                description={
                  store || status
                    ? 'Попробуйте изменить фильтры.'
                    : 'Добавьте фотографию чека. После распознавания проверьте товары и подтвердите результат.'
                }
                action={
                  store || status ? (
                    <Button
                      variant="soft"
                      onClick={() => {
                        setParams({})
                        setSearch('')
                      }}
                    >
                      Сбросить фильтры
                    </Button>
                  ) : (
                    <Button asChild>
                      <Link to="/upload">Добавить чек</Link>
                    </Button>
                  )
                }
              />
            ) : (
              <div className="receipt-list">
                {receipts.data.items.map((receipt) => (
                  <Link
                    className="receipt-row"
                    to={`/receipts/${receipt.receipt_id}`}
                    key={receipt.receipt_id}
                  >
                    <span className="receipt-glyph">
                      <ReceiptIcon size={25} weight="duotone" />
                    </span>
                    <div className="receipt-name">
                      <strong>{receipt.store_name || 'Магазин не определён'}</strong>
                      <small>{dateTime(receipt.purchase_datetime || receipt.created_at)}</small>
                    </div>
                    <div className="receipt-row-status">
                      <StatusBadge status={receipt.status} />
                    </div>
                    <strong className="amount">{money(receipt.total_amount)}</strong>
                    <ArrowUpRightIcon className="row-arrow" size={19} />
                  </Link>
                ))}
              </div>
            )}
            <Pagination
              page={page}
              pages={receipts.data.total_pages}
              onChange={(next) => {
                const p = new URLSearchParams(params)
                p.set('page', String(next))
                setParams(p)
              }}
            />
          </>
        )}
      </section>
      <p className="footnote">В аналитику включаются только подтверждённые чеки.</p>
    </>
  )
}
