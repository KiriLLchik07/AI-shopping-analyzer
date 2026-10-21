import { afterEach, describe, expect, it, vi } from 'vitest'
import { apiJson, apiRequest, resetApiSession, resolveApiOrigin } from './client'

afterEach(() => vi.unstubAllGlobals())

function mockResponse(response: Response) {
  const fetch = vi.fn().mockResolvedValue(response)
  vi.stubGlobal('fetch', fetch)
  return fetch
}

describe('apiRequest', () => {
  it('uses same-origin API requests for the Docker build', () => {
    expect(resolveApiOrigin('', 'http://localhost:5173').origin).toBe('http://localhost:5173')
    expect(resolveApiOrigin(undefined).origin).toBe('http://localhost:8000')
  })

  it.each([
    'https://user:pass@example.com',
    'https://example.com/api',
    'https://example.com?key=value',
    'https://example.com#hash',
    'ftp://example.com',
  ])('rejects invalid API origin %s', (origin) => {
    expect(() => resolveApiOrigin(origin)).toThrow()
  })
  it('sends cookies even if the caller specifies other credentials', async () => {
    const fetch = mockResponse(Response.json({ user_id: 'user' }))
    await expect(apiRequest('/api/auth/me', { credentials: 'omit' })).resolves.toEqual({
      user_id: 'user',
    })
    const [url, options] = fetch.mock.calls[0]
    expect(String(url)).toBe('http://localhost:8000/api/auth/me')
    expect(options.credentials).toBe('include')
    expect(options.cache).toBe('no-store')
    expect(options.headers.get('Accept')).toBe('application/json')
  })

  it('keeps JSON headers, body and abort signal', async () => {
    const fetch = mockResponse(Response.json({ ok: true }))
    const controller = new AbortController()
    const body = JSON.stringify({ user_mail: 'test@example.com' })
    await apiRequest('/api/auth_login', {
      method: 'POST',
      body,
      signal: controller.signal,
      headers: { 'Content-Type': 'application/json' },
    })
    const options = fetch.mock.calls[0][1]
    expect(options.method).toBe('POST')
    expect(options.body).toBe(body)
    expect(options.signal).toBe(controller.signal)
    expect(options.headers.get('Content-Type')).toBe('application/json')
  })

  it('leaves multipart Content-Type to the browser', async () => {
    const fetch = mockResponse(Response.json({ receipt_id: 'receipt' }))
    const body = new FormData()
    body.append('file', new Blob(['image'], { type: 'image/jpeg' }), 'receipt.jpg')
    await apiRequest('/api/receipts', { method: 'POST', body })
    expect(fetch.mock.calls[0][1].body).toBe(body)
    expect(fetch.mock.calls[0][1].headers.has('Content-Type')).toBe(false)
  })

  it('handles an empty logout response', async () => {
    mockResponse(new Response(null, { status: 204 }))
    await expect(apiRequest<void>('/api/logout', { method: 'POST' })).resolves.toBeUndefined()
  })

  it('preserves a safe provider error and correlation ID', async () => {
    mockResponse(
      Response.json(
        { detail: 'Модель недоступна', code: 'llm_unavailable' },
        {
          status: 503,
          headers: { 'X-Correlation-ID': 'test-id' },
        },
      ),
    )
    await expect(apiRequest('/api/llm/reports')).rejects.toMatchObject({
      name: 'ApiError',
      status: 503,
      code: 'llm_unavailable',
      message: 'Модель недоступна',
      correlationId: 'test-id',
    })
  })

  it.each([
    new Response('PRIVATE proxy error', { status: 502 }),
    Response.json({ detail: [{ msg: 'invalid' }] }, { status: 422 }),
  ])('uses a readable fallback for nonstandard error bodies', async (response) => {
    mockResponse(response)
    await expect(apiRequest('/api/auth_login')).rejects.toMatchObject({
      name: 'ApiError',
      message: 'Не удалось выполнить запрос. Попробуйте ещё раз.',
    })
  })

  it.each(['https://example.org/api/auth/me', '//example.org/api/auth/me', '/api/../../secret'])(
    'rejects paths outside this API: %s',
    async (path) => {
      const fetch = vi.fn()
      vi.stubGlobal('fetch', fetch)
      await expect(apiRequest(path)).rejects.toThrow()
      expect(fetch).not.toHaveBeenCalled()
    },
  )

  it('expires the current session on a protected endpoint 401', async () => {
    const target = new EventTarget()
    const expired = vi.fn()
    target.addEventListener('session-expired', expired)
    vi.stubGlobal('window', target)
    mockResponse(Response.json({ detail: 'Session expired' }, { status: 401 }))
    await expect(apiRequest('/api/receipts')).rejects.toMatchObject({ status: 401 })
    expect(expired).toHaveBeenCalledOnce()
  })

  it('ignores a late 401 belonging to an earlier session', async () => {
    const target = new EventTarget()
    const expired = vi.fn()
    target.addEventListener('session-expired', expired)
    vi.stubGlobal('window', target)
    let finish!: (response: Response) => void
    vi.stubGlobal(
      'fetch',
      vi.fn(
        () =>
          new Promise<Response>((resolve) => {
            finish = resolve
          }),
      ),
    )
    const pending = apiRequest('/api/llm/reports/monthly')
    const result = expect(pending).rejects.toMatchObject({ status: 401 })
    resetApiSession()
    finish(Response.json({ detail: 'Old session expired' }, { status: 401 }))
    await result
    expect(expired).not.toHaveBeenCalled()
  })

  it('preserves cancellation', async () => {
    const error = new DOMException('Aborted', 'AbortError')
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(error))
    await expect(apiRequest('/api/auth/me')).rejects.toBe(error)
  })

  it('preserves a saved receipt ID after an unconfirmed enqueue', async () => {
    mockResponse(
      Response.json(
        {
          detail: {
            code: 'receipt_enqueue_unconfirmed',
            message: 'Чек сохранён',
            receipt_id: 'receipt-id',
          },
        },
        { status: 503 },
      ),
    )
    await expect(apiRequest('/api/receipts/upload')).rejects.toMatchObject({
      message: 'Чек сохранён',
      code: 'receipt_enqueue_unconfirmed',
      details: { receipt_id: 'receipt-id' },
    })
  })

  it('serializes JSON and preserves decimal strings', async () => {
    const fetch = mockResponse(Response.json({}))
    await apiJson('/api/receipts/id', 'PATCH', { total_amount: '129.90' })
    expect(fetch.mock.calls[0][1].body).toBe('{"total_amount":"129.90"}')
    expect(fetch.mock.calls[0][1].headers.get('Content-Type')).toBe('application/json')
    expect(fetch.mock.calls[0][1].credentials).toBe('include')
  })
})
