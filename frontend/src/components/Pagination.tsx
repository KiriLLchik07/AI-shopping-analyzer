import { Button } from '@radix-ui/themes'
import { CaretLeftIcon, CaretRightIcon } from '@phosphor-icons/react'

export function Pagination({
  page,
  pages,
  onChange,
}: {
  page: number
  pages: number
  onChange: (page: number) => void
}) {
  if (pages <= 1 && page === 1) return null
  return (
    <nav className="pagination" aria-label="Страницы результатов">
      <Button variant="soft" color="gray" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        <CaretLeftIcon />
        Назад
      </Button>
      <span>
        Страница {page} из {Math.max(pages, page)}
      </span>
      <Button
        variant="soft"
        color="gray"
        disabled={page >= pages}
        onClick={() => onChange(page + 1)}
      >
        Далее
        <CaretRightIcon />
      </Button>
    </nav>
  )
}
