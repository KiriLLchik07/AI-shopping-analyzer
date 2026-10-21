import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { AlertDialog, Button, Dialog } from '@radix-ui/themes'
import { CalculatorIcon, CheckIcon, PlusIcon, TrashIcon } from '@phosphor-icons/react'
import { apiJson, apiRequest } from '../api/client'
import type { Category, ReceiptDetail, ReceiptItem } from '../api/types'
import { useQuery } from '@tanstack/react-query'
import { decimal, lineTotal, localDateTime, omskToIso } from '../lib/format'
import { ErrorNotice } from './Feedback'

type Shared = { refresh: () => Promise<void>; onDirty: (key: string, dirty: boolean) => void }
export function ReceiptMetadata({
  receipt,
  refresh,
  onDirty,
}: { receipt: ReceiptDetail } & Shared) {
  const [store, setStore] = useState(receipt.store_name ?? '')
  const [date, setDate] = useState(localDateTime(receipt.purchase_datetime))
  const [total, setTotal] = useState(receipt.total_amount ?? '')
  const [busy, setBusy] = useState(false)
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => {
    if (!dirty) {
      setStore(receipt.store_name ?? '')
      setDate(localDateTime(receipt.purchase_datetime))
      setTotal(receipt.total_amount ?? '')
    }
  }, [receipt.store_name, receipt.purchase_datetime, receipt.total_amount, dirty])
  const changed = () => {
    setDirty(true)
    onDirty('metadata', true)
    setError(null)
  }
  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    let amount: string
    try {
      amount = decimal(total, 2, true)
    } catch (e) {
      setError((e as Error).message)
      return
    }
    setBusy(true)
    try {
      const payload: Record<string, unknown> = {}
      if (store.trim() !== (receipt.store_name ?? '')) payload.store_name = store.trim()
      if (date !== localDateTime(receipt.purchase_datetime))
        payload.purchase_datetime = omskToIso(date)
      if (amount !== receipt.total_amount) payload.total_amount = amount
      if (Object.keys(payload).length)
        await apiJson(`/api/receipts/${receipt.receipt_id}`, 'PATCH', payload)
      await refresh()
      setDirty(false)
      onDirty('metadata', false)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <form onSubmit={save} className="surface metadata-form">
      <div className="section-header">
        <h2>Данные чека</h2>
        <span className="muted">Время Омска, UTC+6</span>
      </div>
      <fieldset disabled={busy} className="metadata-grid">
        <label>
          Магазин
          <input
            value={store}
            onChange={(e) => {
              setStore(e.target.value)
              changed()
            }}
            required
            maxLength={100}
          />
        </label>
        <label>
          Дата и время покупки
          <input
            type="datetime-local"
            value={date}
            onChange={(e) => {
              setDate(e.target.value)
              changed()
            }}
            required
          />
        </label>
        <label>
          Итог чека, ₽
          <input
            inputMode="decimal"
            value={total}
            onChange={(e) => {
              setTotal(e.target.value)
              changed()
            }}
            required
          />
        </label>
        <Button type="submit" variant="soft" disabled={!dirty} loading={busy}>
          <CheckIcon size={17} />
          Сохранить
        </Button>
      </fieldset>
      {error != null && <ErrorNotice error={error} />}
    </form>
  )
}

type ItemDraft = {
  name: string
  quantity: string
  unit: string
  price: string
  total: string
  category: string
}
function toDraft(item: ReceiptItem): ItemDraft {
  return {
    name: item.normalized_name || item.raw_name,
    quantity: item.quantity ?? '',
    unit: item.unit ?? '',
    price: item.unit_price ?? '',
    total: item.total_price ?? '',
    category: item.category_id ?? '',
  }
}
function ItemRow({
  item,
  receiptId,
  categories,
  refresh,
  onDirty,
}: { item: ReceiptItem; receiptId: string; categories: Category[] } & Shared) {
  const [draft, setDraft] = useState(() => toDraft(item))
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  useEffect(() => {
    if (!dirty) setDraft(toDraft(item))
  }, [item, dirty])
  const formId = `item-${item.receipt_item_id}`
  const change = (key: keyof ItemDraft, value: string) => {
    setDraft((previous) => ({ ...previous, [key]: value }))
    setDirty(true)
    onDirty(formId, true)
    setError(null)
  }
  async function save(event: FormEvent) {
    event.preventDefault()
    setError(null)
    let values: Record<string, unknown>
    try {
      values = {
        quantity: decimal(draft.quantity, 3, true),
        unit_price: decimal(draft.price),
        total_price: decimal(draft.total),
        unit: draft.unit.trim() || null,
      }
    } catch (e) {
      setError((e as Error).message)
      return
    }
    if (draft.name.trim() !== (item.normalized_name || item.raw_name))
      values.normalized_name = draft.name.trim()
    if (draft.category !== (item.category_id ?? '')) values.category_id = draft.category || null
    setBusy(true)
    try {
      await apiJson(`/api/receipts/${receiptId}/items/${item.receipt_item_id}`, 'PATCH', values)
      await refresh()
      setDirty(false)
      onDirty(formId, false)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  async function remove() {
    setBusy(true)
    setError(null)
    try {
      await apiJson(`/api/receipts/${receiptId}/items/${item.receipt_item_id}`, 'DELETE')
      onDirty(formId, false)
      await refresh()
    } catch (e) {
      setError(e)
      setBusy(false)
    }
  }
  const label = `товара ${item.raw_name}`
  return (
    <tr className={dirty ? 'dirty-row' : ''}>
      <td data-label="Товар">
        <input
          form={formId}
          aria-label={`Название ${label}`}
          value={draft.name}
          onChange={(e) => change('name', e.target.value)}
          maxLength={256}
          required
          disabled={busy}
        />
        <small className="ocr-name" title={item.raw_name}>
          На чеке: {item.raw_name}
        </small>
        {item.confidence != null && item.confidence < 0.8 && (
          <small className="low-confidence">
            Проверьте текст: OCR {Math.round(item.confidence * 100)}%
          </small>
        )}
      </td>
      <td data-label="Количество">
        <input
          form={formId}
          aria-label={`Количество ${label}`}
          inputMode="decimal"
          value={draft.quantity}
          required
          disabled={busy}
          onChange={(e) => change('quantity', e.target.value)}
        />
      </td>
      <td data-label="Единица">
        <input
          form={formId}
          aria-label={`Единица ${label}`}
          value={draft.unit}
          maxLength={100}
          disabled={busy}
          onChange={(e) => change('unit', e.target.value)}
        />
      </td>
      <td data-label="Цена, ₽">
        <input
          form={formId}
          aria-label={`Цена ${label}`}
          inputMode="decimal"
          value={draft.price}
          required
          disabled={busy}
          onChange={(e) => change('price', e.target.value)}
        />
      </td>
      <td data-label="Сумма, ₽">
        <div className="total-cell">
          <input
            form={formId}
            aria-label={`Сумма ${label}`}
            inputMode="decimal"
            value={draft.total}
            required
            disabled={busy}
            onChange={(e) => change('total', e.target.value)}
          />
          <button
            type="button"
            className="icon-button"
            aria-label={`Рассчитать сумму ${label}`}
            disabled={busy}
            onClick={() => {
              try {
                change('total', lineTotal(draft.quantity, draft.price))
              } catch (e) {
                setError((e as Error).message)
              }
            }}
          >
            <CalculatorIcon size={18} />
          </button>
        </div>
      </td>
      <td data-label="Категория">
        <select
          form={formId}
          aria-label={`Категория ${label}`}
          value={draft.category}
          disabled={busy}
          onChange={(e) => change('category', e.target.value)}
        >
          <option value="">Без категории</option>
          {categories.map((c) => (
            <option key={c.category_id} value={c.category_id}>
              {c.category_name}
            </option>
          ))}
        </select>
      </td>
      <td className="item-actions">
        <form id={formId} onSubmit={save}>
          <Button
            type="submit"
            variant="soft"
            size="1"
            disabled={!dirty}
            loading={busy}
            aria-label={`Сохранить товар ${item.raw_name}`}
            title="Сохранить товар"
          >
            <CheckIcon size={16} />
            <span>Сохранить</span>
          </Button>
        </form>
        <AlertDialog.Root>
          <AlertDialog.Trigger>
            <Button
              variant="ghost"
              color="gray"
              disabled={busy}
              aria-label={`Удалить товар ${item.raw_name}`}
              title="Удалить товар"
            >
              <TrashIcon size={18} />
            </Button>
          </AlertDialog.Trigger>
          <AlertDialog.Content maxWidth="430px">
            <AlertDialog.Title>Удалить товар?</AlertDialog.Title>
            <AlertDialog.Description>
              Позиция «{item.raw_name}» будет удалена из этого чека.
            </AlertDialog.Description>
            <div className="dialog-actions">
              <AlertDialog.Cancel>
                <Button variant="soft" color="gray">
                  Отмена
                </Button>
              </AlertDialog.Cancel>
              <AlertDialog.Action>
                <Button color="red" onClick={() => void remove()}>
                  Удалить
                </Button>
              </AlertDialog.Action>
            </div>
          </AlertDialog.Content>
        </AlertDialog.Root>
        {error != null && <ErrorNotice error={error} />}
      </td>
    </tr>
  )
}

function AddItem({
  receiptId,
  categories,
  refresh,
}: {
  receiptId: string
  categories: Category[]
  refresh: () => Promise<void>
}) {
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<unknown>(null)
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setError(null)
    const data = new FormData(event.currentTarget)
    let values: Record<string, unknown>
    try {
      values = {
        raw_name: String(data.get('name')).trim(),
        quantity: decimal(String(data.get('quantity')), 3, true),
        unit_price: decimal(String(data.get('price'))),
        total_price: decimal(String(data.get('total'))),
        unit: data.get('unit') || null,
      }
      if (data.get('category')) values.category_id = data.get('category')
    } catch (e) {
      setError((e as Error).message)
      return
    }
    setBusy(true)
    try {
      await apiJson(`/api/receipts/${receiptId}/items`, 'POST', values)
      await refresh()
      setOpen(false)
    } catch (e) {
      setError(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Dialog.Root
      open={open}
      onOpenChange={(next) => {
        if (!busy) {
          setOpen(next)
          setError(null)
        }
      }}
    >
      <Dialog.Trigger>
        <Button variant="soft">
          <PlusIcon />
          Добавить товар
        </Button>
      </Dialog.Trigger>
      <Dialog.Content maxWidth="520px">
        <Dialog.Title>Добавить товар</Dialog.Title>
        <Dialog.Description>Укажите конечную цену и сумму после скидок.</Dialog.Description>
        <form onSubmit={create} className="stack add-item-form">
          <fieldset disabled={busy} className="stack">
            <label>
              Название товара
              <input name="name" required maxLength={256} />
            </label>
            <div className="form-grid">
              <label>
                Количество
                <input name="quantity" inputMode="decimal" defaultValue="1" required />
              </label>
              <label>
                Единица
                <input name="unit" defaultValue="шт" maxLength={100} />
              </label>
              <label>
                Цена, ₽<input name="price" inputMode="decimal" required />
              </label>
              <label>
                Сумма, ₽<input name="total" inputMode="decimal" required />
              </label>
            </div>
            <label>
              Категория
              <select name="category">
                <option value="">Предложить автоматически</option>
                {categories.map((c) => (
                  <option key={c.category_id} value={c.category_id}>
                    {c.category_name}
                  </option>
                ))}
              </select>
            </label>
            {error != null && <ErrorNotice error={error} />}
            <div className="dialog-actions">
              <Dialog.Close>
                <Button type="button" variant="soft" color="gray">
                  Отмена
                </Button>
              </Dialog.Close>
              <Button type="submit" loading={busy}>
                Добавить товар
              </Button>
            </div>
          </fieldset>
        </form>
      </Dialog.Content>
    </Dialog.Root>
  )
}
export function ReceiptItems({ receipt, refresh, onDirty }: { receipt: ReceiptDetail } & Shared) {
  const categories = useQuery({
    queryKey: ['categories'],
    queryFn: ({ signal }) => apiRequest<Category[]>('/api/categories', { signal }),
    staleTime: 300_000,
  })
  return (
    <section className="surface items-surface">
      <div className="section-header">
        <div>
          <h2>
            Товары в чеке <span className="count-label">{receipt.items.length}</span>
          </h2>
          <p className="muted">Проверьте названия, количество и конечные цены.</p>
        </div>
        {categories.data && (
          <AddItem receiptId={receipt.receipt_id} categories={categories.data} refresh={refresh} />
        )}
      </div>
      {categories.isError && (
        <ErrorNotice error={categories.error} retry={() => void categories.refetch()} />
      )}
      {receipt.items.length === 0 ? (
        <p className="no-items">Товары пока не найдены. Добавьте их вручную.</p>
      ) : (
        <div className="items-scroll">
          <table className="items-table">
            <caption className="sr-only">Ручная проверка товаров</caption>
            <thead>
              <tr>
                <th>Товар</th>
                <th>Кол-во</th>
                <th>Ед.</th>
                <th>Цена, ₽</th>
                <th>Сумма, ₽</th>
                <th>Категория</th>
                <th>
                  <span className="sr-only">Действия</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {receipt.items.map((item) => (
                <ItemRow
                  key={item.receipt_item_id}
                  item={item}
                  receiptId={receipt.receipt_id}
                  categories={categories.data ?? []}
                  refresh={refresh}
                  onDirty={onDirty}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
