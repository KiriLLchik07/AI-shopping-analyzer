import { Badge } from '@radix-ui/themes'
import { statusLabels, isProcessing } from '../lib/format'
import type { ReceiptStatus } from '../api/types'

export function StatusBadge({ status }: { status: ReceiptStatus }) {
  return (
    <Badge
      color={
        status === 'failed'
          ? 'red'
          : status === 'need_review'
            ? 'amber'
            : status === 'completed'
              ? 'jade'
              : 'gray'
      }
      variant="soft"
      size="2"
    >
      {isProcessing(status) && <span className="processing-mark" aria-hidden="true" />}
      {statusLabels[status] ?? status}
    </Badge>
  )
}
