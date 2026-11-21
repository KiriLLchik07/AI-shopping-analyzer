import { useCallback, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertDialog, Button, Callout } from '@radix-ui/themes'
import { ArrowLeftIcon, CheckCircleIcon, ArrowClockwiseIcon } from '@phosphor-icons/react'
import { apiJson, apiRequest } from '../api/client'
import type { ReceiptDetail } from '../api/types'
import {
  cents,
  centsString,
  dateTime,
  isProcessing,
  money,
  processingStatusLabels,
} from '../lib/format'
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
      query.state.data && isProcessing(query.state.data.processing_status) ? 2500 : false,
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
  const reviewManually = useMutation({
    mutationFn: () => apiJson(`/api/receipts/${id}/review`, 'POST'),
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
  const processing = isProcessing(data.processing_status)
  const failedDraft = data.receipt_status === 'draft' && data.processing_status === 'failed'
  const confirmed = data.receipt_status === 'confirmed'
  const editable = !processing
  const actionPending = confirm.isPending || reprocess.isPending || reviewManually.isPending
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
            <StatusBadge
              receiptStatus={data.receipt_status}
              processingStatus={data.processing_status}
            />
          </div>
          <p>{dateTime(data.purchase_datetime || data.created_at)}</p>
        </div>
        <strong className="receipt-head-total">{money(data.total_amount)}</strong>
      </header>
      {processing && (
        <section className="processing-panel" role="status">
          <h2>{processingStatusLabels[data.processing_status]}</h2>
          <p>Чек сохранён. Статус обновится автоматически.</p>
        </section>
      )}
      {failedDraft && (
        <ErrorNotice
          error={
            data.processing_error_message ||
            'Не удалось распознать чек. Его можно заполнить вручную.'
          }
        />
      )}
      {confirmed && data.confirmed_at && (
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
      {reviewManually.isError && <ErrorNotice error={reviewManually.error} />}
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
                    {failedDraft
                      ? 'Заполните реквизиты и товары вручную, чтобы перейти к проверке.'
                      : 'Подтвердите чек, когда все данные верны. После этого расходы появятся в аналитике.'}
                  </p>
                  {data.receipt_status === 'needs_review' && !data.purchase_datetime && (
                    <p>Укажите дату покупки в реквизитах чека.</p>
                  )}
                  {failedDraft ? (
                    <Button
                      size="3"
                      disabled={dirty.size > 0 || actionPending}
                      loading={reviewManually.isPending}
                      onClick={() => reviewManually.mutate()}
                    >
                      Перейти к ручной проверке
                    </Button>
                  ) : (
                    <Button
                      size="3"
                      disabled={
                        data.receipt_status !== 'needs_review' ||
                        dirty.size > 0 ||
                        !data.purchase_datetime ||
                        !totalsComplete ||
                        actionPending
                      }
                      loading={confirm.isPending}
                      onClick={() => confirm.mutate()}
                    >
                      <CheckCircleIcon size={19} />
                      {confirmed ? 'Чек подтверждён' : 'Подтвердить чек'}
                    </Button>
                  )}
                </div>
              </section>
            </>
          ) : (
            <section className="surface waiting-panel">
              <h2>Готовим данные чека</h2>
              <p>Редактирование откроется после окончания обработки.</p>
            </section>
          )}
          {failedDraft && data.manual_ocr_attempts_remaining === 0 && (
            <p>Ручные попытки исчерпаны. Заполните чек и перейдите к проверке.</p>
          )}
          {failedDraft && data.manual_ocr_attempts_remaining > 0 && (
            <div className="reprocess-area">
              <AlertDialog.Root>
                <AlertDialog.Trigger>
                  <Button variant="ghost" color="gray" disabled={dirty.size > 0 || actionPending}>
                    <ArrowClockwiseIcon size={18} />
                    Распознать повторно
                  </Button>
                </AlertDialog.Trigger>
                <AlertDialog.Content maxWidth="490px">
                  <AlertDialog.Title>Повторить распознавание?</AlertDialog.Title>
                  <AlertDialog.Description>
                    Осталось ручных попыток: {data.manual_ocr_attempts_remaining}. Новый результат
                    заменит товарные позиции. Правки реквизитов чека сохранятся.
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
