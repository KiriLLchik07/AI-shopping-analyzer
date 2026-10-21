import { useEffect, useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { Button } from '@radix-ui/themes'
import { UploadSimpleIcon, ImageIcon, ArrowLeftIcon, XIcon } from '@phosphor-icons/react'
import { ApiError, apiRequest } from '../api/client'
import type { Receipt } from '../api/types'
import { ErrorNotice } from '../components/Feedback'

export function UploadPage() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState('')
  const [validation, setValidation] = useState('')
  const [imageFailed, setImageFailed] = useState(false)
  const [dragging, setDragging] = useState(false)
  useEffect(() => {
    if (!file) {
      setPreview('')
      return
    }
    const url = URL.createObjectURL(file)
    setPreview(url)
    setImageFailed(false)
    return () => URL.revokeObjectURL(url)
  }, [file])
  const upload = useMutation({
    mutationFn: () => {
      const data = new FormData()
      data.append('file', file!)
      return apiRequest<Receipt>('/api/receipts/upload', { method: 'POST', body: data })
    },
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: ['receipts'] })
    },
  })
  const savedId =
    upload.error instanceof ApiError &&
    upload.error.code === 'receipt_enqueue_unconfirmed' &&
    typeof upload.error.details?.receipt_id === 'string'
      ? upload.error.details.receipt_id
      : null
  function selectFile(next: File | undefined) {
    if (upload.isPending) return
    upload.reset()
    setValidation('')
    if (!next) return
    if (!['image/jpeg', 'image/png', 'image/webp'].includes(next.type)) {
      setValidation('Выберите JPEG, PNG или WebP. HEIC сначала преобразуйте в JPEG.')
      return
    }
    if (next.size > 10 * 1024 * 1024) {
      setValidation('Размер фотографии должен быть не больше 10 МБ.')
      return
    }
    setFile(next)
  }
  return (
    <>
      <Link className="back-link" to="/receipts">
        <ArrowLeftIcon />К чекам
      </Link>
      <header className="page-header">
        <div>
          <h1>Добавить чек</h1>
          <p>Загрузите фото. Товары можно будет исправить после распознавания.</p>
        </div>
      </header>
      <div className="upload-layout">
        <section className="surface upload-surface">
          <div
            className={`drop-zone${dragging ? ' dragging' : ''}`}
            onDragOver={(e) => {
              e.preventDefault()
              setDragging(true)
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault()
              setDragging(false)
              selectFile(e.dataTransfer.files[0])
            }}
          >
            {preview ? (
              <div className="local-preview">
                <img
                  src={preview}
                  alt="Предпросмотр выбранного чека"
                  onError={() => setImageFailed(true)}
                />
                <Button
                  type="button"
                  aria-label="Убрать фотографию"
                  variant="soft"
                  color="gray"
                  disabled={upload.isPending}
                  onClick={() => {
                    setFile(null)
                    upload.reset()
                  }}
                >
                  <XIcon />
                </Button>
              </div>
            ) : (
              <>
                <div className="upload-symbol">
                  <ImageIcon size={44} weight="light" />
                </div>
                <h2>Фото вашего чека</h2>
                <p>Перетащите файл сюда или выберите его на устройстве.</p>
              </>
            )}
            <label className={`file-picker${upload.isPending ? ' disabled' : ''}`}>
              <UploadSimpleIcon size={20} />
              {file ? 'Выбрать другое фото' : 'Выбрать фото'}
              <input
                type="file"
                accept="image/jpeg,image/png,image/webp"
                disabled={upload.isPending}
                onChange={(e) => {
                  selectFile(e.target.files?.[0])
                  e.target.value = ''
                }}
              />
            </label>
            <small>JPEG, PNG или WebP, до 10 МБ</small>
          </div>
          {file && (
            <div className="file-info">
              <span>{file.name}</span>
              <span>{(file.size / 1024 / 1024).toFixed(1)} МБ</span>
            </div>
          )}
          {validation && <ErrorNotice error={validation} />}
          {imageFailed && (
            <ErrorNotice error="Не удалось открыть изображение. Выберите другой файл." />
          )}
          {upload.isError && <ErrorNotice error={upload.error} />}
          {savedId ? (
            <Button asChild size="3">
              <Link to={`/receipts/${savedId}`}>Перейти к сохранённому чеку</Link>
            </Button>
          ) : (
            <Button
              size="3"
              className="upload-submit"
              disabled={!file || imageFailed}
              loading={upload.isPending}
              onClick={() =>
                upload.mutate(undefined, {
                  onSuccess: (receipt) =>
                    navigate(`/receipts/${receipt.receipt_id}`, { replace: true }),
                })
              }
            >
              Распознать чек
            </Button>
          )}
          {upload.isPending && (
            <p role="status" className="muted">
              Сохраняем фотографию. Не загружайте её повторно.
            </p>
          )}
        </section>
        <aside className="upload-advice">
          <h2>Чтобы текст читался лучше</h2>
          <p>Положите чек на ровную поверхность и снимите его при хорошем освещении.</p>
          <ul>
            <li>Все края чека видны в кадре.</li>
            <li>Текст в фокусе, без бликов и теней.</li>
            <li>Одна фотография на один чек.</li>
          </ul>
          <div className="privacy-note">
            <strong>Вы проверяете результат</strong>
            <p>
              После распознавания чек появится в списке. Он попадёт в расходы только после вашего
              подтверждения.
            </p>
          </div>
        </aside>
      </div>
    </>
  )
}
