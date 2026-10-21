import { Button, Callout, Skeleton } from '@radix-ui/themes'
import { WarningCircleIcon, TrayIcon } from '@phosphor-icons/react'
import { errorMessage } from '../api/client'
import type { ReactNode } from 'react'

export function ErrorNotice({ error, retry }: { error: unknown; retry?: () => void }) {
  return (
    <Callout.Root color="red" role="alert" className="error-notice">
      <Callout.Icon>
        <WarningCircleIcon size={20} />
      </Callout.Icon>
      <Callout.Text>
        {typeof error === 'string' ? error : errorMessage(error)}
        {retry && (
          <Button type="button" variant="soft" color="red" onClick={retry}>
            Повторить
          </Button>
        )}
      </Callout.Text>
    </Callout.Root>
  )
}
export function Loading({ label = 'Загрузка данных' }: { label?: string }) {
  return (
    <div className="loading-state" role="status" aria-label={label}>
      <span className="muted">{label}</span>
      <Skeleton height="32px" width="50%" />
      <Skeleton height="64px" />
      <Skeleton height="64px" />
    </div>
  )
}
export function Empty({
  title,
  description,
  action,
}: {
  title: string
  description: string
  action?: ReactNode
}) {
  return (
    <div className="empty-state">
      <TrayIcon size={38} weight="light" aria-hidden="true" />
      <h2>{title}</h2>
      <p>{description}</p>
      {action}
    </div>
  )
}
