export function resolveApiOrigin(configured: string | undefined, browserOrigin?: string): URL {
  const url = new URL(
    configured === '' ? (browserOrigin ?? '') : (configured ?? 'http://localhost:8000'),
  )
  if (
    !['http:', 'https:'].includes(url.protocol) ||
    url.username ||
    url.password ||
    url.pathname !== '/' ||
    url.search ||
    url.hash
  ) {
    throw new Error('VITE_API_BASE_URL должен содержать только origin API')
  }
  return url
}

const baseUrl = resolveApiOrigin(
  import.meta.env.VITE_API_BASE_URL,
  typeof window === 'undefined' ? undefined : window.location.origin,
)
let sessionEpoch = 0

export function resetApiSession() {
  sessionEpoch += 1
}

export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly correlationId?: string
  readonly details?: Record<string, unknown>

  constructor(
    message: string,
    status: number,
    code?: string,
    correlationId?: string,
    details?: Record<string, unknown>,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.correlationId = correlationId
    this.details = details
  }
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const requestEpoch = sessionEpoch
  if (!path.startsWith('/api/') && !path.startsWith('/health/')) {
    throw new Error('Нужен путь API, начинающийся с /api/ или /health/')
  }
  const url = new URL(path, baseUrl)
  if (url.origin !== baseUrl.origin || !/^\/(api|health)\//.test(url.pathname)) {
    throw new Error('Запрос должен оставаться в пределах API')
  }

  const headers = new Headers(options.headers)
  if (!headers.has('Accept')) headers.set('Accept', 'application/json')

  const response = await fetch(url, {
    ...options,
    headers,
    credentials: 'include',
    cache: 'no-store',
  })

  if (!response.ok) {
    const data: unknown = await response.json().catch(() => null)
    const error = data && typeof data === 'object' ? (data as Record<string, unknown>) : {}
    const details =
      error.detail && typeof error.detail === 'object' && !Array.isArray(error.detail)
        ? (error.detail as Record<string, unknown>)
        : undefined
    const message =
      typeof error.detail === 'string'
        ? error.detail
        : typeof details?.message === 'string'
          ? details.message
          : 'Не удалось выполнить запрос. Попробуйте ещё раз.'
    if (
      response.status === 401 &&
      requestEpoch === sessionEpoch &&
      !options.signal?.aborted &&
      typeof window !== 'undefined' &&
      path !== '/api/auth_login'
    ) {
      window.dispatchEvent(new Event('session-expired'))
    }
    throw new ApiError(
      message,
      response.status,
      typeof error.code === 'string'
        ? error.code
        : typeof details?.code === 'string'
          ? details.code
          : undefined,
      response.headers.get('X-Correlation-ID') ?? undefined,
      details,
    )
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}

export function apiJson<T>(path: string, method: string, body?: unknown): Promise<T> {
  return apiRequest<T>(path, {
    method,
    ...(body === undefined
      ? {}
      : {
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(body),
        }),
  })
}

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 401) return 'Сессия завершилась. Войдите снова.'
    if (error.status === 422) return 'Проверьте заполненные поля и допустимый диапазон значений.'
    if (error.status === 429) return 'Слишком много попыток. Подождите немного и повторите.'
    return error.message
  }
  return 'Не удалось связаться с сервером. Проверьте подключение и повторите.'
}
