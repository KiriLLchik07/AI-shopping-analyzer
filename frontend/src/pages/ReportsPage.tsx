import { useState } from 'react'
import { Link, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Button } from '@radix-ui/themes'
import {
  SparkleIcon,
  CalendarBlankIcon,
  ArrowUpRightIcon,
  ArrowLeftIcon,
} from '@phosphor-icons/react'
import { apiJson, apiRequest } from '../api/client'
import type { Page, Report, ReportSummary } from '../api/types'
import { TIMEZONE, dateTime, money, monthNow } from '../lib/format'
import { Empty, ErrorNotice, Loading } from '../components/Feedback'
import { Pagination } from '../components/Pagination'

const monthLabel = (date: string) =>
  new Intl.DateTimeFormat('ru-RU', { year: 'numeric', month: 'long', timeZone: 'UTC' }).format(
    new Date(date),
  )
export function ReportsPage() {
  const { reportId } = useParams()
  return reportId ? <ReportView key={reportId} id={reportId} /> : <ReportsList />
}
function ReportsList() {
  const navigate = useNavigate()
  const client = useQueryClient()
  const [month, setMonth] = useState(monthNow)
  const [params, setParams] = useSearchParams()
  const page = Math.max(1, Number(params.get('page')) || 1)
  const reports = useQuery({
    queryKey: ['reports', page],
    queryFn: ({ signal }) =>
      apiRequest<Page<ReportSummary>>(`/api/llm/reports?page=${page}&page_size=10`, { signal }),
  })
  const create = useMutation({
    mutationFn: () =>
      apiJson<Report>('/api/llm/reports/monthly', 'POST', {
        month: month + '-01',
        timezone: TIMEZONE,
      }),
    onSuccess: (report) => {
      client.setQueryData(['report', report.report_id], report)
      void client.invalidateQueries({ queryKey: ['reports'] })
    },
  })
  return (
    <>
      <header className="page-header">
        <div>
          <h1>Взгляд на месяц</h1>
          <p>Отчёты и рекомендации на основе подтверждённых расходов.</p>
        </div>
      </header>
      <section className="report-create surface">
        <div className="report-symbol">
          <SparkleIcon size={34} weight="duotone" />
        </div>
        <div>
          <h2>Что стоит заметить в покупках?</h2>
          <p>
            Выберите месяц. Модель получит суммы и категории расходов, без фотографий и текста
            чеков.
          </p>
        </div>
        <form
          onSubmit={(e) => {
            e.preventDefault()
            create.mutate(undefined, {
              onSuccess: (report) => navigate(`/reports/${report.report_id}`),
            })
          }}
        >
          <label>
            Месяц
            <input
              type="month"
              value={month}
              onChange={(e) => {
                setMonth(e.target.value)
                create.reset()
              }}
              required
              max={monthNow()}
              disabled={create.isPending}
            />
          </label>
          <Button type="submit" loading={create.isPending} disabled={!month}>
            <SparkleIcon size={18} />
            Создать отчёт
          </Button>
        </form>
      </section>
      {create.isPending && (
        <div className="generation-state" role="status">
          <Loading label="Модель анализирует расходы. Это может занять несколько минут." />
          <p className="muted">
            Отчёт появится здесь после сохранения. Не запускайте генерацию повторно.
          </p>
        </div>
      )}
      {create.isError && <ErrorNotice error={create.error} />}
      <section className="surface reports-list">
        <div className="section-header">
          <h2>Сохранённые отчёты</h2>
          <span className="muted">{reports.data?.total ?? ''}</span>
        </div>
        {reports.isPending ? (
          <Loading />
        ) : reports.isError ? (
          <ErrorNotice error={reports.error} retry={() => void reports.refetch()} />
        ) : (
          <>
            {reports.data.items.length === 0 ? (
              <Empty
                title="Первый отчёт ещё впереди"
                description="Подтвердите покупки за месяц и создайте отчёт выше."
              />
            ) : (
              reports.data.items.map((report) => (
                <Link
                  className="report-row"
                  key={report.report_id}
                  to={`/reports/${report.report_id}`}
                >
                  <span className="receipt-glyph">
                    <CalendarBlankIcon size={25} />
                  </span>
                  <div>
                    <strong>{monthLabel(report.period_start)}</strong>
                    <small>Создан {dateTime(report.created_at)}</small>
                  </div>
                  <ArrowUpRightIcon size={20} />
                </Link>
              ))
            )}
            <Pagination
              page={page}
              pages={reports.data.total_pages}
              onChange={(next) => setParams({ page: String(next) })}
            />
          </>
        )}
      </section>
    </>
  )
}
function ReportView({ id }: { id: string }) {
  const report = useQuery({
    queryKey: ['report', id],
    queryFn: ({ signal }) => apiRequest<Report>(`/api/llm/reports/${id}`, { signal }),
  })
  if (report.isPending) return <Loading label="Открываем отчёт" />
  if (report.isError)
    return <ErrorNotice error={report.error} retry={() => void report.refetch()} />
  const data = report.data
  return (
    <>
      <Link to="/reports" className="back-link">
        <ArrowLeftIcon />К отчётам
      </Link>
      <header className="page-header">
        <div>
          <h1>Отчёт: {monthLabel(data.period_start)}</h1>
          <p>Сохранён {dateTime(data.created_at)}</p>
        </div>
        <span className="model-label">{data.model_name}</span>
      </header>
      <div className="report-content">
        <section className="surface report-overview">
          <div className="section-header">
            <h2>Итоги месяца</h2>
            <SparkleIcon size={25} weight="duotone" />
          </div>
          <div className="report-numbers">
            <div>
              <span>Расходы</span>
              <strong>{money(data.input_data.current.total_amount)}</strong>
            </div>
            <div>
              <span>Покупок</span>
              <strong>{data.input_data.current.purchase_count}</strong>
            </div>
            <div>
              <span>Прошлый месяц</span>
              <strong>{money(data.input_data.previous.total_amount)}</strong>
            </div>
          </div>
          <p className="report-summary">{data.report_data.summary}</p>
        </section>
        <section className="recommendations">
          <h2>На что обратить внимание</h2>
          {data.report_data.recommendations.map((r, index) => (
            <article className="recommendation surface" key={index}>
              <div className="recommendation-heading">
                <SparkleIcon size={22} weight="duotone" />
                <h3>{r.title}</h3>
              </div>
              <p>{r.reason}</p>
              <div className="recommendation-action">
                <strong>Что можно сделать</strong>
                <p>{r.action}</p>
              </div>
            </article>
          ))}
        </section>
        <p className="footnote">
          Рекомендации модели могут быть неточными. Они не изменяют ваши чеки и категории. Отчёт
          отражает данные на момент создания.
        </p>
      </div>
    </>
  )
}
