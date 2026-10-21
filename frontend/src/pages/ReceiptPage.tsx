import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertDialog, Button, Callout } from '@radix-ui/themes'
import { ArrowLeftIcon, CheckCircleIcon, ArrowClockwiseIcon } from '@phosphor-icons/react'
import { apiJson, apiRequest } from '../api/client'
import type { ReceiptDetail } from '../api/types'
import { cents, centsString, dateTime, isProcessing, money, statusLabels } from '../lib/format'
import { ErrorNotice, Loading } from '../components/Feedback'
import { StatusBadge } from '../components/StatusBadge'
import { ReceiptImage } from '../components/ReceiptImage'
import { ReceiptItems, ReceiptMetadata } from '../components/ReceiptEditor'

export function ReceiptPage() {
  const { receiptId = '' } = useParams()
  return <ReceiptContent key={receiptId} id={receiptId} />
}
function ReceiptContent({ id }: { id: string }) {
  const client = useQueryClient()
  const [dirty, setDirty] = useState<Set<string>>(new Set())
  const onDirty = useCallback(
    (key: string, changed: boolean) =>
      setDirty((old) => {
        const next = new Set(old)
        if (changed) next.add(key)
        else next.delete(key)
        return next
      }),
    [],
  )
  const receipt = useQuery({
    queryKey: ['receipt', id],
    queryFn: ({ signal }) => apiRequest<ReceiptDetail>(`/api/receipts/${id}`, { signal }),
    refetchOnWindowFocus: false,
    refetchInterval: (query) =>
      query.state.data && isProcessing(query.state.data.status) ? 2500 : false,
  })
  const refresh = useCallback(async () => {
    await client.invalidateQueries({ queryKey: ['receipt', id] })
    void client.invalidateQueries({ queryKey: ['receipts'] })
    void client.invalidateQueries({ queryKey: ['analytics'] })
  }, [client, id])
  const confirm = useMutation({
    mutationFn: () => apiJson(`/api/receipts/${id}/confirm`, 'POST'),
    onSuccess: refresh,
  })
  const reprocess = useMutation({
    mutationFn: (replace: boolean) =>
      apiJson(`/api/receipts/${id}/reprocess`, 'POST', { replace_items: replace }),
    onSuccess: async () => {
      setDirty(new Set())
      await refresh()
    },
    onError: refresh,
  })
  if (receipt.isPending) return <Loading label="Открываем чек" />
  if (receipt.isError)
    return <ErrorNotice error={receipt.error} retry={() => void receipt.refetch()} />
  const data = receipt.data
  const processing = isProcessing(data.status)
  const editable =
    data.status === 'need_review' || data.status === 'completed' || data.status === 'failed'
  const totalsComplete =
    data.items.length > 0 && data.items.every((item) => item.total_price != null)
  const sum = totalsComplete
    ? data.items.reduce((total, item) => total + cents(item.total_price!), 0n)
    : null
  const mismatch =
    sum != null &&
    data.total_amount != null &&
    (sum > cents(data.total_amount) + 5n || sum < cents(data.total_amount) - 5n)
  return (
    <>
      <Link className="back-link" to="/receipts">
        <ArrowLeftIcon />К чекам
      </Link>
      <header className="page-header receipt-header">
        <div>
          <div className="heading-status">
            <h1>{data.store_name || 'Новый чек'}</h1>
            <StatusBadge status={data.status} />
          </div>
          <p>{dateTime(data.purchase_datetime || data.created_at)}</p>
        </div>
        <strong className="receipt-head-total">{money(data.total_amount)}</strong>
      </header>
      {processing && (
        <section className="processing-panel" role="status">
          <h2>{statusLabels[data.status]}</h2>
          <p>Можно оставить эту страницу открытой. Статус обновится автоматически.</p>
          <ol className="pipeline-steps">
            {['uploaded', 'preprocessing', 'ocr_processing', 'parsing'].map((step, index) => {
              const current = ['uploaded', 'preprocessing', 'ocr_processing', 'parsing'].indexOf(
                data.status,
              )
              return (
                <li
                  key={step}
                  className={index <= current ? 'reached' : ''}
                  aria-current={step === data.status ? 'step' : undefined}
                >
                  {statusLabels[step as keyof typeof statusLabels]}
                </li>
              )
            })}
          </ol>
        </section>
      )}
      {data.status === 'failed' && (
        <ErrorNotice
          error={
            data.processing_error_message ||
            'Не удалось обработать чек. Попробуйте распознать его ещё раз.'
          }
        />
      )}
      {data.status === 'completed' && data.confirmed_at && (
        <Callout.Root className="confirmation-note">
          <Callout.Icon>
            <CheckCircleIcon size={20} />
          </Callout.Icon>
          <Callout.Text>
            Подтверждён {dateTime(data.confirmed_at)}. Изменение данных потребует повторного
            подтверждения.
          </Callout.Text>
        </Callout.Root>
      )}
      {confirm.isError && <ErrorNotice error={confirm.error} />}
      {reprocess.isError && <ErrorNotice error={reprocess.error} />}
      <div className="receipt-detail-layout">
        <div className="receipt-image-column">
          <ReceiptImage id={id} />
          {data.raw_ocr_text && (
            <details className="surface ocr-details">
              <summary>
                Распознанный текст
                {data.ocr_confidence != null
                  ? ` · OCR ${Math.round(data.ocr_confidence * 100)}%`
                  : ''}
              </summary>
              <pre>{data.raw_ocr_text}</pre>
            </details>
          )}
        </div>
        <div className="receipt-data-column">
          {editable ? (
            <>
              <ReceiptMetadata receipt={data} refresh={refresh} onDirty={onDirty} />
              <ReceiptItems receipt={data} refresh={refresh} onDirty={onDirty} />
              <section className="review-footer surface">
                <div className="review-totals">
                  <span>
                    Сумма товаров{' '}
                    <strong>
                      {sum == null ? 'Не все суммы заполнены' : money(centsString(sum))}
                    </strong>
                  </span>
                  <span>
                    Итог чека <strong>{money(data.total_amount)}</strong>
                  </span>
                </div>
                {mismatch && (
                  <Callout.Root color="amber">
                    <Callout.Text>
                      Сумма товаров отличается от итога чека. Проверьте позиции, скидки и итог перед
                      подтверждением.
                    </Callout.Text>
                  </Callout.Root>
                )}
                {dirty.size > 0 && (
                  <p className="unsaved" role="status">
                    Есть несохранённые изменения. Сначала сохраните данные и товары.
                  </p>
                )}
                <div className="review-confirm">
                  <p>
                    Подтвердите чек, когда все данные верны. После этого расходы появятся в
                    аналитике.
                  </p>
                  <Button
                    size="3"
                    disabled={
                      data.status !== 'need_review' ||
                      dirty.size > 0 ||
                      !totalsComplete ||
                      confirm.isPending ||
                      reprocess.isPending
                    }
                    loading={confirm.isPending}
                    onClick={() => confirm.mutate()}
                  >
                    <CheckCircleIcon size={19} />
                    {data.status === 'completed' ? 'Чек подтверждён' : 'Подтвердить чек'}
                  </Button>
                </div>
              </section>
            </>
          ) : (
            <section className="surface waiting-panel">
              <h2>Готовим данные чека</h2>
              <p>Редактирование откроется после окончания обработки.</p>
            </section>
          )}
          {!processing && (
            <div className="reprocess-area">
              <AlertDialog.Root>
                <AlertDialog.Trigger>
                  <Button
                    variant="ghost"
                    color="gray"
                    disabled={dirty.size > 0 || reprocess.isPending || confirm.isPending}
                  >
                    <ArrowClockwiseIcon size={18} />
                    Распознать повторно
                  </Button>
                </AlertDialog.Trigger>
                <AlertDialog.Content maxWidth="490px">
                  <AlertDialog.Title>Повторить распознавание?</AlertDialog.Title>
                  <AlertDialog.Description>
                    Товарные позиции будут заменены новым результатом, включая ручные исправления
                    товаров. Подтверждение чека будет сброшено. Сохранённые ручные исправления
                    данных чека останутся.
                  </AlertDialog.Description>
                  <div className="dialog-actions">
                    <AlertDialog.Cancel>
                      <Button variant="soft" color="gray">
                        Отмена
                      </Button>
                    </AlertDialog.Cancel>
                    <AlertDialog.Action>
                      <Button onClick={() => reprocess.mutate(true)}>
                        Повторить распознавание
                      </Button>
                    </AlertDialog.Action>
                  </div>
                </AlertDialog.Content>
              </AlertDialog.Root>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
