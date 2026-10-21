const baseUrl = new URL(import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000')

if (
  !['http:', 'https:'].includes(baseUrl.protocol) ||
  baseUrl.username || baseUrl.password || baseUrl.pathname !== '/' ||
  baseUrl.search || baseUrl.hash
) {
  throw new Error('VITE_API_BASE_URL должен содержать только origin API')
}

export class ApiError extends Error {
  readonly status: number
  readonly code?: string
  readonly correlationId?: string

  constructor(
    message: string,
    status: number,
    code?: string,
    correlationId?: string,
  ) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.correlationId = correlationId
  }
}

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
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
    const error = data && typeof data === 'object' ? data as Record<string, unknown> : {}
    const message = typeof error.detail === 'string'
      ? error.detail
      : 'Не удалось выполнить запрос. Попробуйте ещё раз.'
    throw new ApiError(
      message,
      response.status,
      typeof error.code === 'string' ? error.code : undefined,
      response.headers.get('X-Correlation-ID') ?? undefined,
    )
  }

  if (response.status === 204) return undefined as T
  return response.json() as Promise<T>
}
