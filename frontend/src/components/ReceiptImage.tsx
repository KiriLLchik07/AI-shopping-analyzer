import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Button } from '@radix-ui/themes'
import { ArrowsOutIcon } from '@phosphor-icons/react'
import { apiRequest } from '../api/client'
import { ErrorNotice, Loading } from './Feedback'

export function ReceiptImage({ id }: { id: string }) {
  const [failed, setFailed] = useState(false)
  const image = useQuery({
    queryKey: ['receipt-image', id],
    queryFn: ({ signal }) =>
      apiRequest<{ image_url: string }>('/api/receipts/' + id + '/image-url', { signal }),
    staleTime: 120_000,
    refetchInterval: 120_000,
  })
  return (
    <section className="surface receipt-photo">
      <div className="section-header">
        <h2>Оригинал чека</h2>
        {image.data && (
          <a
            href={image.data.image_url}
            target="_blank"
            rel="noreferrer"
            aria-label="Открыть оригинал чека"
          >
            <ArrowsOutIcon size={20} />
          </a>
        )}
      </div>
      {image.isPending ? (
        <Loading label="Загружаем фото" />
      ) : image.isError ? (
        <ErrorNotice error={image.error} retry={() => void image.refetch()} />
      ) : failed ? (
        <div className="image-error">
          <p>Не удалось загрузить фото.</p>
          <Button
            variant="soft"
            onClick={() => {
              setFailed(false)
              void image.refetch()
            }}
          >
            Обновить фото
          </Button>
        </div>
      ) : (
        <a
          href={image.data.image_url}
          target="_blank"
          rel="noreferrer"
          className="receipt-photo-link"
        >
          <img
            src={image.data.image_url}
            alt="Оригинальная фотография чека"
            onError={() => setFailed(true)}
          />
        </a>
      )}
    </section>
  )
}
