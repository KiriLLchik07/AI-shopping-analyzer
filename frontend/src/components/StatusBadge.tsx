import { Badge } from '@radix-ui/themes'
import { isProcessing, processingStatusLabels, receiptStatusLabels } from '../lib/format'
import type { ProcessingStatus, ReceiptReviewStatus } from '../api/types'

export function StatusBadge({
  receiptStatus,
  processingStatus,
}: {
  receiptStatus: ReceiptReviewStatus
  processingStatus: ProcessingStatus
}) {
  const active = isProcessing(processingStatus)
  const draft = receiptStatus === 'draft'
  const color =
    receiptStatus === 'confirmed'
      ? 'jade'
      : receiptStatus === 'needs_review'
        ? 'amber'
        : processingStatus === 'failed'
          ? 'red'
          : 'gray'
  return (
    <Badge color={color} variant="soft" size="2">
      {active && <span className="processing-mark" aria-hidden="true" />}
      {draft ? processingStatusLabels[processingStatus] : receiptStatusLabels[receiptStatus]}
    </Badge>
  )
}
